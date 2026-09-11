# MaskGuard

Image sensitive-data detection and redaction pipeline. Detects personal data,
financial data, credentials, and business-confidential text in images via
local OCR + rule-based/local-AI classification, then masks/blurs/pixelates it
in place. See `Skill.md` for the full specification this implements.

## Setup

```bash
python -m pip install -e .
```

OCR requires the **Tesseract binary** to be installed and on `PATH` (this is
separate from — and in addition to — the `pytesseract` Python package, which
is just a thin subprocess wrapper around it).

### Windows

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

Installs to `C:\Program Files\Tesseract-OCR` and (after a new shell/session)
puts `tesseract.exe` on `PATH`. **Known gotcha, confirmed on this project:**
the winget/UB-Mannheim package's bundled `tessdata` only ships `eng` (+`osd`)
— `chi_tra` (Traditional Chinese) is **not** included and must be added
manually:

```powershell
# Download the language pack Tesseract's own project publishes:
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata" -OutFile "$env:LOCALAPPDATA\tessdata\chi_tra.traineddata"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$env:LOCALAPPDATA\tessdata\"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" "$env:LOCALAPPDATA\tessdata\"
# Point Tesseract at a language-data directory you can write to without admin rights:
$env:TESSDATA_PREFIX = "$env:LOCALAPPDATA\tessdata"
```

(Writing directly into `C:\Program Files\Tesseract-OCR\tessdata\` requires an
elevated/admin shell — the `TESSDATA_PREFIX` env var pointing at a
user-writable copy avoids that.) Verify with `tesseract --list-langs` — it
should print `chi_tra`, `eng`, `osd`.

If `tesseract` isn't on `PATH` at all, either open a new terminal (winget
updates the registry `PATH`, not your current shell) or pass the binary path
explicitly: `LocalOcrEngine(tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe")`.

### Linux (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng
```

Other distros: `dnf install tesseract tesseract-langpack-chi_tra` (Fedora) or
build from https://github.com/tesseract-ocr/tesseract. Verify with
`tesseract --list-langs`.

### macOS

```bash
brew install tesseract tesseract-lang   # tesseract-lang bundles all language packs, incl. chi_tra
```

Verify with `tesseract --list-langs`.

### Verifying the environment yourself

```bash
python tests/e2e/_environment.py
```

Prints Python version, whether `pytesseract` imports, the resolved
`tesseract` binary path, `tesseract --version` output, and which of
`eng`/`chi_tra` are actually available — this is the same check the E2E test
suite (`pytest -m e2e`) runs before every test, via the `ocr_env` fixture in
`tests/e2e/conftest.py`. If the environment isn't ready, E2E tests report
**SKIPPED** (never a false PASS) with the specific missing piece named.

## Usage

```bash
imgmask input.png --output ./output
imgmask input.png --output ./output --mode strict --verify
imgmask ./input_folder --output ./output --recursive
```

Output layout (Skill.md §24):

```
output/
├── processed/<name>_masked.png
├── report/<name>_masked.json      # processing_report.json — no raw sensitive text
└── audit.log                      # append-only, type/confidence/region only
```

`--mode strict` enables Skill.md §40 Strict Mode: local-only OCR/AI, no cloud
upload, verification required, and a failed verification blocks output
entirely (no image is written).

## HTTP API (Phase 8.1)

An optional FastAPI layer (`maskguard/api/`) exposes the same MaskGuard Core
pipeline over HTTP, for a browser/client that isn't a terminal. It is a thin
wrapper only — every request calls straight into `Pipeline`/
`WholeImageSanityScanner`, the exact same classes the `imgmask` CLI uses;
Detection/Risk/Policy/Redaction/Verification/OCR logic lives in Core, not in
any API route. The CLI is unaffected and keeps working exactly as before —
CLI and API are two independent front ends over one Core.

### Install and start the server

```bash
python -m pip install -e ".[api]"   # installs fastapi/uvicorn/pydantic/python-multipart on top of Core
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000
# or:
python -m maskguard.api
```

Binds to `127.0.0.1` (localhost only) by default. **Do not** pass
`--host 0.0.0.0` (or set `MASKGUARD_API_HOST=0.0.0.0`) unless you've put a
reverse proxy, authentication, and TLS in front of it — Phase 8.1 ships no
authentication of its own (that's a later phase's scope).

### Endpoints

All under `/api/v1/`. Interactive docs at `http://127.0.0.1:8000/docs` once
the server is running.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness check. Never runs OCR. |
| POST | `/api/v1/analyze` | Full Core pipeline; returns findings as JSON (no image). |
| POST | `/api/v1/process` | Same as `/analyze` — an explicit alias for a unified-pipeline call. |
| POST | `/api/v1/redact` | Full Core pipeline; returns the redacted image (`image/png`). |
| POST | `/api/v1/verify` | Independent whole-image sanity check (`WholeImageSanityScanner`) — no prior detection context needed. |
| POST | `/api/v1/review` | Phase 8.3: submit Human Review decisions for a prior `/analyze`'s `review_token`; returns the reviewed redacted image (`image/png`) with `X-Review-*` result headers. |

```bash
curl http://127.0.0.1:8000/api/v1/health

curl -X POST http://127.0.0.1:8000/api/v1/analyze -F "file=@example.png"

curl -X POST http://127.0.0.1:8000/api/v1/redact -F "file=@example.png" --output redacted.png

curl -X POST http://127.0.0.1:8000/api/v1/verify -F "file=@redacted.png"
```

(`example.png` above should be your own test image — never upload real
personal/financial data to a local dev server casually.)

Example `/api/v1/analyze` response (illustrative, not real data):

```json
{
  "status": "PASSED",
  "needs_human_review": false,
  "blocked": false,
  "detections": [
    {"type": "TaiwanID", "risk_level": "CRITICAL", "action": "FULL_MASK",
     "confidence": 0.85, "needs_review": false,
     "bbox": {"x": 144, "y": 160, "width": 175, "height": 25}}
  ],
  "verification": {"status": "PASSED", "attempts": 1, "residual_count": 0, "needs_human_review": false},
  "summary": {"total_detections": 1, "critical_count": 1, "needs_review_count": 0, "blocked": false}
}
```

`status` combines Core's verification status with `needs_human_review`/
`blocked` into one field: `PASSED` / `FAILED` / `SKIPPED` / `NEEDS_REVIEW` /
`BLOCKED`. **This is a MaskGuard security-processing status, not an HTTP
error** — a `NEEDS_REVIEW` or even `BLOCKED` result is still returned as
HTTP `200`; HTTP status codes (`400`/`413`/`415`/`422`/`500`/`504`) only
describe whether the *API call itself* succeeded.

### What the API never returns or logs

Detection responses carry only `type` / `risk_level` / `action` /
`confidence` / `needs_review` / `bbox` — never the matched raw text (no
password, API key, credit card number, Taiwan ID, bank account number, or
any other sensitive value). Application logs are equally restricted to
request id, duration, file size, and detection counts — never OCR text,
filenames, or detection values, not even at DEBUG level. See
`tests/api/test_security_logging.py` for the tests enforcing this across
Email/TaiwanID/CreditCard/BankAccount/APIKey/Password fixtures.

### File limits and configuration

All HTTP-layer limits live in `maskguard/api/config.py` (`ApiSettings`), set
via environment variables — never hardcoded in a route:

| Variable | Default | Meaning |
|---|---|---|
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760` (10 MB) | Rejected with `413` above this. |
| `MASKGUARD_MAX_IMAGE_WIDTH` | `8000` | Rejected with `422` above this. |
| `MASKGUARD_MAX_IMAGE_HEIGHT` | `8000` | Rejected with `422` above this. |
| `MASKGUARD_MAX_IMAGE_PIXELS` | `40000000` | Rejected with `422` above this (decompression-bomb guard). |
| `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` | `60` | Request-level soft timeout; `504` if exceeded (Known limitations below). |
| `MASKGUARD_CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated allowed origins. Empty means no cross-origin access — never `*` by default. |
| `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS` | `600` | Phase 8.3: how long a `/analyze` review token stays valid. |
| `MASKGUARD_MAX_REVIEW_REASON_LENGTH` | `200` | Phase 8.3: max length of a REJECTED item's `reason` text. |
| `MASKGUARD_MIN_REVIEW_BBOX_WIDTH` / `_HEIGHT` | `4` | Phase 8.3: minimum manual-detection box size. |
| `MASKGUARD_MAX_REVIEW_BBOX_AREA_RATIO` | `0.9` | Phase 8.3: max fraction of image area a manual box may cover. |

Uploads are validated by actually decoding them with Pillow (never trusting
the client's `Content-Type` header), and are written to a securely-created
temporary directory under a fixed filename — **never** the client-supplied
filename — which is removed on every exit path (success or exception).

### No persistent storage

Phase 8.1 is a stateless processing API: no database, no user accounts, no
saved images, no download/job history. Every request's temp files are gone
before the response is returned.

### Known limitations

- Single synchronous call per request, offloaded to a worker thread — there
  is no job queue, so a request whose processing exceeds
  `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` returns `504` to the client, but the
  underlying worker thread is not force-killed (Tesseract/OpenCV calls can't
  be safely interrupted mid-call); it finishes in the background and its temp
  directory is still cleaned up.
- No authentication/authorization — put this behind a trusted network
  boundary or a reverse proxy that adds one before exposing it beyond
  localhost.

## Web Frontend (Phase 8.2)

A React + TypeScript + Vite browser UI (`frontend/`) — a thin client over
the HTTP API above. It displays backend detection/redaction results only;
no OCR/Detection/Risk/Policy/Redaction/Verification logic exists in the
frontend. End users only need a browser; Node.js is a development-time
dependency only (the production build is static HTML/CSS/JS).

### Run it locally

```bash
# Terminal 1 — backend (see "HTTP API" above)
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000

# Terminal 2 — frontend dev server
cd frontend
npm install
npm run dev   # opens on http://127.0.0.1:5173 by default, proxies to VITE_API_BASE_URL
```

`frontend/.env.development` sets `VITE_API_BASE_URL=http://127.0.0.1:8000`.
Change it (or set the env var at build time) to point at a different
backend — never hardcode a production server address into the source.

### Production build

```bash
cd frontend
npm run build     # tsc -b && vite build -> frontend/dist/ (static assets)
```

Serving `frontend/dist/` in production (nginx, a CDN, etc.) is out of scope
for this phase — see "Do not implement" below.

### What it does and does not do

- Uploads an image, calls `POST /api/v1/analyze`, and draws the returned
  bounding boxes over the original image using an SVG overlay — the
  backend's `(x, y, width, height)` values are authoritative; the frontend
  only rescales them to match however large the `<img>` is rendered on
  screen, never recomputes them.
- Displays `type` / `risk_level` / `action` / `confidence` / `needs_review`
  per detection — **never** a raw matched value (no ID number, card number,
  password, or API key ever reaches the DOM or the browser console).
- "執行遮罩" calls `POST /api/v1/redact` (using the real Core pipeline again,
  not a client-side mask) and shows the returned image side-by-side with
  the original — the original is never overwritten.
- A `BLOCKED` redact response (Strict Mode) is shown as a blocked notice,
  never rendered as if it were a successful image.
- No `localStorage`/`sessionStorage`/IndexedDB persistence of image data;
  object URLs (`URL.createObjectURL`) are revoked when replaced or on
  unmount.
- Human Review (accept/reject a finding, add a manual detection) is
  Phase 8.3 — see the section below. Does **not** implement deployment
  (Docker/nginx/HTTPS/auth) — later phases.

### Frontend tests

```bash
cd frontend
npm test                                   # Vitest — component/unit tests, no backend required
VITE_TEST_REAL_BACKEND=1 npm test          # also runs the real-backend integration test — start the backend first
```

## Human Review (Phase 8.3)

Human Review is an ADDITIONAL security control layered on top of the
automatic pipeline — it can never bypass RiskEngine/PolicyEngine/
RedactionEngine/VerificationEngine. The browser only ever submits *review
intent* (accept/reject an existing finding by its `detection_id`, or a new
finding's *type* and *bbox*); every actual security decision — risk level,
redaction action, whether a value is really gone — is still made by Core,
server-side, exactly as it already was:

```
Automatic Detection (Core)
        |
        v
Human Review (browser: accept / reject / add manual bbox+type)
        |
        v
Backend Validation (signed review token, bbox/type checks)
        |
        v
Policy (existing PolicyEngine — re-run ONLY for new manual detections)
        |
        v
Redaction (existing RedactionEngine)
        |
        v
Verification (existing VerificationEngine + Whole-Image Sanity Scan)
        |
        v
Final result
```

### Why the browser can't be trusted with risk/action/type

`POST /api/v1/analyze`'s response now also includes a `review_token` — an
HMAC-signed, short-lived, opaque blob recording exactly what Core found
(`detection_id`, type, risk_level, action, confidence, bbox) for THIS
image. `POST /api/v1/review` decodes and verifies that token server-side
and resolves every accept/reject decision against ITS contents — never
against anything the request body claims. Concretely: `ReviewItemRequest`
(the request schema) has no field for risk_level/action/confidence at all,
so there is nothing to smuggle even if a client tried; a manual detection's
`type` must be on a server-side allowlist and its `bbox` is fully
re-validated (bounds, minimum/maximum size) against the real image
dimensions. See `maskguard/api/review_token.py` and
`maskguard/api/review_service.py`.

### Accept / Reject

- **Accept**: no effect on redaction (the finding was already going to be
  masked) — clears a "needs review" flag once a human has confirmed it.
- **Reject**: for a non-critical type (Email, Phone, PersonalName, Address,
  …), the finding is dropped from redaction — a legitimate false-positive
  correction. For an intrinsically critical type (TaiwanID, Passport,
  BankAccount, CreditCard, SecretKeyValue, BearerToken, JWT), rejecting it
  **never removes the mask** — the region is still redacted, and the result
  is flagged `needs_human_review` (surfaced as status `NEEDS_REVIEW`) so a
  human supervisor sees it again. "The user rejected it" is never treated
  as "therefore it's safe."

### Manual detection

A reviewer picks a type from a server-defined dropdown and draws a
rectangle on the ORIGINAL image; the frontend converts the on-screen
rectangle to the image's own pixel coordinates before sending it (purely a
visual transform — the backend independently re-validates the result
against the real image). The backend then runs the real `RiskEngine`/
`PolicyEngine` on it (confidence = 1.0, since a human visually confirmed
both the region and the type) — exactly the same engines the automatic
pipeline uses, never a client-supplied risk/action.

### Expiration and replay

A review token expires after `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS` (default
600s) and can only be submitted once — a second submission of the same
token is refused with `REVIEW_CONFLICT` (409), and an expired one with
`REVIEW_EXPIRED` (409). Both the signing key and the one-time-use guard
live only in server process memory (no database — Phase 8.3 stays
stateless); a server restart invalidates in-flight reviews, which simply
means re-analyzing the image.

### No persistent storage

Exactly like Phase 8.1: no database, no stored review history, no audit
table. `POST /api/v1/review` re-sends the original image alongside the
review decisions in one request — there is nothing to fetch back later.

## API Security Hardening (Phase 8.4)

Phase 8.4 attacked the existing HTTP/API layer and closed the abuse cases
it found. No Core module (OCR/Detection/Risk/Policy/Redaction/
Verification) changed — every control below lives in `maskguard/api/`.

**This version is not intended for direct Internet exposure without
authentication and production deployment controls** (reverse proxy, TLS,
rate limiting at the edge, auth — all later phases). It is hardened against
abusive/malformed *input*, not against having no access control at all.

### Limits (all in `ApiSettings`, environment-overridable)

| Variable | Default | Purpose |
|---|---|---|
| `MASKGUARD_MAX_REQUEST_BODY_BYTES` | `12582912` (12 MB) | Outer ASGI-level cap on the whole request body — enforced while the body STREAMS IN, not after it's fully buffered (see below). |
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760` (10 MB) | The precise, authoritative per-file limit (unchanged from Phase 8.1). |
| `MASKGUARD_MAX_REVIEW_ITEMS` | `200` | Total accept/reject/manual items one `/review` submission may contain. |
| `MASKGUARD_MAX_MANUAL_DETECTIONS` | `50` | Of those, how many may be brand-new MANUAL detections (the subset that triggers real RiskEngine/PolicyEngine work). |
| `MASKGUARD_MAX_REVIEW_PAYLOAD_BYTES` | `262144` (256 KB) | Raw byte size of the `review` JSON form field, checked BEFORE it's parsed. |
| `MASKGUARD_MAX_REVIEW_TOKEN_BYTES` | `65536` (64 KB) | An incoming `review_token` longer than this is rejected before any base64/HMAC work. |
| `MASKGUARD_MAX_CONCURRENT_JOBS` | `4` | Bounded concurrent Core (OCR/Detection/.../Verification) jobs — see below. |

(Image dimension/pixel limits, review bbox/reason limits, and the review
token TTL are unchanged from Phase 8.1/8.3 — see those sections above.)

### Upload size: streaming enforcement, not just a post-hoc check

FastAPI resolves `UploadFile` parameters by fully parsing the multipart
body before a route function runs at all — meaning a naive "check
`len(data)` after reading it" limit (Phase 8.1's original design) only
rejects an oversized upload AFTER the server already received and spooled
the whole thing. `maskguard/api/middleware.py`'s `MaxRequestBodySizeMiddleware`
closes this at the raw ASGI level, in front of everything else:

1. A `Content-Length` fast path rejects an honestly-oversized declared
   body instantly, with a clean `413`, before reading a single byte.
2. A streaming byte-counter backstop bounds actual bytes consumed
   regardless of what — or whether — `Content-Length` was sent (an
   attacker who omits/falsifies it cannot bypass this). Verified directly:
   a 200MB streamed body against a 12MB cap was cut off after exactly
   12MB, in under 20ms.

Known, tested limitation of the streaming backstop: interrupting
Starlette's multipart parser mid-stream this way is caught by its own
internal error handling and surfaces as a generic `400` (via the existing
`StarletteHTTPException` handler) rather than a precisely-coded `413`. The
security property that matters — bounded resource consumption, no crash,
no leak — holds either way; only the exact status code differs from the
`Content-Length`-fast-path case.

### Concurrency: bounded, not unlimited

At most `MASKGUARD_MAX_CONCURRENT_JOBS` Core-processing calls
(analyze/redact/verify/review) run at once, using the SAME single
`Pipeline`/OCR-engine instance the whole process already shares (Phase 8.1
§20 — never a second engine). A request arriving when all slots are busy
is refused immediately with `429` — it is never queued. Verified directly:
10 concurrent `/analyze` requests against a limit of 4 produced exactly 4
successful responses and 6 immediate (~20ms) `429`s, with total wall time
matching a single processing pass, not 10x it.

**Timeout/concurrency interaction — read this before assuming a timeout
"cancels" anything.** Python cannot force-kill a running worker thread.
When a request's processing exceeds `MASKGUARD_PROCESSING_TIMEOUT_SECONDS`,
the HTTP call returns `504 PROCESSING_TIMEOUT` — but the underlying OCR/
Core work keeps running to completion in the background regardless (this
was already true and documented in Phase 8.1). What Phase 8.4 adds: that
phantom worker's concurrency slot is **not** released just because the
HTTP response gave up waiting — it stays held until the worker genuinely
finishes. This is what actually bounds worst-case concurrent CPU usage
under a flood of timeout-inducing requests: at most
`MAX_CONCURRENT_JOBS` phantom workers can ever be alive at once, never
more, even though each individual call already returned. Verified directly
in `tests/api/test_security_hardening.py`.

### Temporary files

Unchanged design from Phase 8.1: one `tempfile.TemporaryDirectory()` per
request, a fixed server-generated filename (never the client's), cleaned
up on every exit path (success, validation failure, exception, or
timeout — since cleanup is a context-manager `__exit__`, it fires
regardless of how the `with` block was left). Verified under repeated
failure conditions: no directories accumulate.

Platform note (§26): `tempfile` creates directories with mode `0o700`
(owner-only) on POSIX by default; on Windows, the temp directory inherits
the ACLs of the user's own `%TEMP%` profile directory. MaskGuard does not
additionally harden permissions beyond what the stdlib already provides —
documented here rather than reimplemented, since this is a single-user,
single-process local service in this phase (no multi-tenant isolation
requirement yet).

### HTTP security headers

Applied to `/api/v1/*` responses only — never to `/docs`/`/openapi.json`/
`/redoc`, which would otherwise break Swagger UI's own asset loading:

- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store` — every `/api/v1` response can carry
  business-sensitive content (detection findings, the redacted image
  itself), so none of it is ever cacheable by a browser, proxy, or CDN.
- `X-Frame-Options: DENY` — this API is never meant to be framed/embedded.

A strict `Content-Security-Policy` was deliberately NOT added — this is an
API, not a page that renders untrusted HTML, and a CSP would only risk
breaking the dev-mode `/docs` UI for no real benefit here.

### CORS (unchanged default, reconfirmed under attack)

Still empty-by-default (Phase 8.1 §19) — never `*`. Verified directly: an
`Origin: https://evil.example` request (including a CORS preflight)
receives no `Access-Control-Allow-Origin` header at all, so a browser
cannot read the response cross-origin regardless of what the response body
contains.

### Error leakage

Unchanged contract (Phase 8.1 §17): every error is `{"error": {"code",
"message", "request_id"}}`, never a traceback/filesystem path/module
name/environment variable. Verified directly by forcing an internal
exception containing a fake secret/path string — none of it appeared in
the client-facing response.

### Log injection

`X-Request-ID` was already regex-validated (`^[A-Za-z0-9._-]{1,128}$`,
Phase 8.1 §16) — this charset cannot contain `\r`/`\n`/control characters
by construction, so a forged log line was never structurally possible;
Phase 8.4 adds direct tests proving it (including bypassing client-library
header validation to hit the server's own check). Review reasons and
filenames are never logged at all (Phase 8.1/8.3 — logging is whitelisted-
field-only: route, request id, duration, file size, detection count,
status).

### Review payload/token abuse

A `/review` submission is bounded on every axis an attacker could inflate:
raw `review` field byte size (checked before JSON parsing), total item
count, manual-detection count (the subset that does real Risk/Policy
work), and incoming `review_token` byte size (checked before any base64/
HMAC work). None of this changes what Phase 8.3 already guarantees: the
browser still cannot set a detection's risk/action/confidence/type — see
the Human Review section above.

## Docker / Production Deployment (Phase 9)

### Architecture

```
Browser --HTTPS--> [frontend container: Nginx]
                       - serves the built React app (static files)
                       - reverse-proxies /api/ --> [api container: FastAPI/Uvicorn]
                                                       - Core pipeline, Tesseract
```

Two containers, one dedicated Docker network (`maskguard_net`), no
`network_mode: host`. The API container's port 8000 is **never** published
to the host or the Internet — the frontend/proxy container is the only
public entry point, and only over HTTPS in production.

### Prerequisites

- **Windows 11**: Docker Desktop (WSL2 backend recommended), `docker compose` v2 (bundled with Docker Desktop). PowerShell or Git Bash both work for the commands below.
- **Linux**: Docker Engine 24+, the `docker compose` v2 plugin. No privileged containers, no `docker.sock` mounts, no `network_mode: host` are required anywhere in this setup.

### Dev deployment (plain HTTP, local only)

```bash
docker compose up --build -d
docker compose ps                 # wait for both services "healthy"
curl http://localhost:8080/api/v1/health
```
PowerShell: identical command — `docker compose` behaves the same from either shell.

This uses `docker-compose.yml`: `MASKGUARD_ENV=development` (an ephemeral,
auto-generated review-token secret — fine for local testing, **never**
reused across restarts), plain HTTP on `localhost:8080`, no TLS.

### Production deployment (HTTPS, externalized secret)

1. Generate a real review-token secret (32+ random characters) and a real
   TLS certificate/key for your deployment's hostname:
   ```bash
   mkdir -p secrets certs
   openssl rand -base64 48 > secrets/review_token_secret.txt
   # certs/cert.pem + certs/key.pem: supplied by your CA / enterprise PKI —
   # this repo never ships or generates a "production" cert for you.
   ```
   Neither `secrets/` nor `certs/` is ever committed (see `.gitignore`).
2. ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
3. The API container **fails closed** at startup
   (`InsecureProductionConfigError`) if the secret file is missing, empty,
   an obvious placeholder (`changeme`, etc.), or under 32 characters — it
   will not silently fall back to an insecure default. Check
   `docker compose -f docker-compose.prod.yml logs api` if the stack
   doesn't come up healthy.
4. ```bash
   curl -k https://localhost/api/v1/health   # -k only needed for a self-signed test cert
   ```

### Configuration

All API-layer limits (upload size, image dimensions, concurrency, timeout,
review-token TTL, CORS, the environment/secret settings) are centralized in
`maskguard/api/config.py` and overridable via the `MASKGUARD_*` environment
variables listed in `.env.example`. Nginx-layer settings (upstream,
request-size ceiling, proxy timeout, TLS paths) are set via the
`docker-compose*.yml` `environment:` blocks and rendered into the actual
Nginx config at container start (`frontend/nginx/entrypoint.sh`) — never
hardcoded in the image.

### Secrets

- **Review-token secret** (`MASKGUARD_REVIEW_TOKEN_SECRET` /
  `MASKGUARD_REVIEW_TOKEN_SECRET_FILE`): signs the Phase 8.3 human-review
  tokens. In production, sourced from a Docker secret file
  (`./secrets/review_token_secret.txt`, mounted at
  `/run/secrets/review_token_secret`) — never a plain env var, never
  committed, never sent to the frontend. **Changing this secret invalidates
  all outstanding review tokens** (by design — acceptable, documented).
  **This secret and the review-token state are process-local**: this
  container topology supports exactly **one** API instance (see "Backend
  startup" below); running multiple replicas behind a load balancer would
  need a shared secret + shared token/limiter store, which does not exist
  yet (future phase).
- **TLS certificate/key**: operator-supplied, bind-mounted read-only from
  `./certs/`. Never committed. Rotate by replacing the files and restarting
  the `frontend` container (`docker compose -f docker-compose.prod.yml
  restart frontend`) — no rebuild needed.

### TLS

`docker-compose.prod.yml`'s `frontend` service listens on 443 with
`nginx.prod.conf.template` (HTTP on 80 redirects to HTTPS only — it never
serves the app or proxies `/api/` in plaintext). `TLS_CERT_PATH`/
`TLS_KEY_PATH` point at the mounted files; this repo ships no certificate
of its own.

### Resource limits

Measured empirically (see `docs/deployment.md` "Resource limits" for the
methodology), not chosen arbitrarily: the API container idles around
~51 MiB and peaked at ~2.82 GiB RSS under 4 concurrent requests each
analyzing a 36-megapixel image (the worst case `MASKGUARD_MAX_CONCURRENT_JOBS=4`
allows near the 40 MP cap). Both compose files set `deploy.resources.limits`
(api: 2 CPU / 4 GiB / 200 PIDs; frontend: 1 CPU / 256 MiB / 50 PIDs) well
above those measured peaks. A verified OOM-kill under a deliberately tight
limit produced **no response at all** (connection reset, no partial/unsafe
output) — see `docs/deployment.md`.

### Health checks / startup order

Both containers ship a `HEALTHCHECK`; `frontend` only starts once `api`
reports healthy (`depends_on: condition: service_healthy` — never an
arbitrary `sleep`). `GET /api/v1/health` never runs OCR.

### Logs

Container logs never contain OCR text, detection values, image bytes, or
the review-token secret (Phase 8.4's logging whitelist is unchanged).
Configure Docker's log rotation at the daemon level
(`/etc/docker/daemon.json`: `{"log-driver": "json-file", "log-opts":
{"max-size": "10m", "max-file": "3"}}`) since this project's compose files
intentionally don't hardcode a log driver (keeps them portable across
hosts with different logging setups). Nginx access logs record
method/path/status/duration only — never query strings or bodies.

### Upgrade / Rollback

```bash
docker compose -f docker-compose.prod.yml pull            # if using a registry
docker compose -f docker-compose.prod.yml up -d --build    # or rebuild locally
docker compose -f docker-compose.prod.yml ps               # confirm healthy
curl -k https://localhost/api/v1/health                    # smoke test
```
Tag images with a version (`maskguard-api:9.x.x`), never rely on `latest`,
so a rollback is `docker compose ... up -d` after re-tagging the previous
image back to what the compose file references. Do not delete the previous
image until the new one is confirmed healthy and smoke-tested.

### Backup

Nothing is persisted by this deployment (§9/§14 below) — there is no image
store to back up. Back up: `docker-compose*.yml`, `.env.example`/your real
`.env`, `certs/`, `secrets/` (per your organization's secret-management
policy — never into Git), and the `docs/` runbooks.

### Troubleshooting

See `docs/deployment.md` "Troubleshooting" for the full list; most common:
container unhealthy at startup in production almost always means the
review-token secret is missing/weak (`docker compose -f
docker-compose.prod.yml logs api`).

### Security limitations of the base Phase 9 deployment (historical)

The items below described the deployment BEFORE Phase 10's Enterprise
Security work. They are **superseded** — see "Enterprise Security" below
for what actually closes each one — but kept here for historical
accuracy about what Phase 9 itself shipped:

- ~~Single-instance only~~ → multi-instance is now supported with shared
  Redis-backed state (Phase 10.6).
- **No persistent image storage** — still true and unchanged: original
  images, redacted images, OCR text, and detection values are never
  written to disk outside the request's own temp lifecycle (`/tmp`,
  cleaned up per-request), in every deployment profile.
- ~~No authentication/authorization layer~~ → OIDC authentication +
  permission-based RBAC now exist (Phase 10.2/10.3), opt-in via
  `OIDC_ENABLED`/`AUTHZ_ROLE_MAPPING_FILE`.
- ~~No built-in rate-limiting~~ → server-side rate limiting now exists
  (Phase 10.5), shared across instances via Redis in multi-instance
  deployments (Phase 10.6).

### Backend startup — why a single Uvicorn worker per container

`Dockerfile`'s `CMD` runs `uvicorn ... --workers 1` deliberately — Core
processing state (`ConcurrencyLimiter`) is per-process. Scale by running
more **containers** (see "Enterprise Security" → "Multi-instance
deployment" below), not by adding `--workers N` to one container.
Session/review-replay/rate-limit state is shared correctly across
containers once `REDIS_ENABLED=true`; `ConcurrencyLimiter` itself remains
per-container by design (documented, not a bug — aggregate Core
concurrency across N containers is `MASKGUARD_MAX_CONCURRENT_JOBS × N`).

## Enterprise Security (Phase 10)

Everything below is **opt-in** — a deployment that sets none of these
environment variables behaves exactly like the base Phase 9 deployment
described above. Enabling them is a deliberate choice for organizations
that need enterprise identity, accountability, and multi-instance
scaling; MaskGuard Core (OCR → Detection → Risk → Policy → Redaction →
Verification) is completely unaffected by any of it either way.

### Authentication (OIDC)

`OIDC_ENABLED=true` turns on standards-based OIDC login (Authorization
Code + PKCE — never the implicit flow, never a token accepted directly
from the browser). The server validates ID token signature/issuer/
audience/expiry itself; the browser only ever holds an opaque,
`HttpOnly`/`Secure`/`SameSite=Lax` session cookie — no access/ID/refresh
token is ever exposed to JavaScript or stored in `localStorage`.
Configure via `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET_FILE`/
`OIDC_REDIRECT_URI` (see `.env.example`).

### Authorization (RBAC)

Once authentication is on, `AUTHZ_ROLE_MAPPING_FILE` maps `issuer +
subject` to roles (Operator, Reviewer, SecurityAdministrator, Auditor,
Administrator), each carrying a fixed, least-privilege permission bundle
— checked server-side on every request, never inferred from a
client-supplied header. An identity with no mapping entry gets zero
permissions (default-deny). No role, including Administrator, can bypass
PolicyEngine or force-unmask anything — there is no admin-bypass code
path anywhere in the codebase.

### Audit

`AUDIT_ENABLED=true` records a durable, append-only trail of security-
relevant events (login, authorization decisions, analyze/redact/verify/
review actions) to a local SQLite database, chained with a keyed
HMAC-SHA256 hash so tampering (modifying, deleting, or reordering a
record) is detectable via `GET /api/v1/audit/integrity`. Audit records
never contain OCR text, detection values, tokens, or secrets — only
metadata about WHO did WHAT and WHEN. Reading the audit trail requires
the `audit.read` permission (the Auditor role).

### Rate Limiting

`RATE_LIMIT_ENABLED=true` bounds request rate per endpoint class
(authentication, analyze/redact/verify, review, audit query), keyed by
the trusted authenticated identity or the network client address — never
a spoofable header. Independent of, and in addition to, the existing
`MASKGUARD_MAX_CONCURRENT_JOBS` concurrency bound (rate limiting answers
"how many requests over time," concurrency limiting answers "how many
run at once" — not the same control).

### Multi-instance deployment

`REDIS_ENABLED=true` shares session, review-replay, and rate-limit state
across multiple API containers via Redis, so a load balancer can
round-robin traffic across nodes with no sticky sessions and no
per-node security-decision drift (the same authenticated identity, the
same review-token replay guard, and the same rate-limit counter are
observed identically regardless of which node handles a given request).
Redis is *state*, never *authority* — it never makes an authentication,
authorization, or policy decision, only stores what those decisions
already produced. A Redis outage fails every dependent operation
*closed* (a clear error), never open. See `docker-compose.multi.yml` for
a ready-to-run two-node + Redis + Nginx topology.

### Production deployment profiles

Three profiles, selectable via `MASKGUARD_DEPLOYMENT_PROFILE`:

| Profile | Compose file | Requires |
|---|---|---|
| `development` (default) | `docker-compose.yml` | nothing — every control above stays off |
| `single-instance-enterprise` | `docker-compose.prod.yml` | OIDC + authorization + audit + rate limiting all enabled together |
| `multi-instance-enterprise` | `docker-compose.multi.yml` | the above, plus Redis |

Declaring an enterprise profile makes the application **refuse to
start** if its required controls aren't all consistently enabled — a
partially-configured "enterprise" deployment is a hard startup failure,
never a silent downgrade to weaker security.

### Health & readiness

`GET /api/v1/health` — liveness (is the process alive; never checks
Redis). `GET /api/v1/ready` — readiness (are dependencies required for
secure operation available; reports Redis availability when
`REDIS_ENABLED=true`). Neither ever returns a secret, connection string,
or internal exception detail.

## Tests

```bash
python -m pytest              # unit tests only — no Tesseract required
python -m pytest -m e2e       # real-OCR end-to-end tests — requires Tesseract (see above)
python -m pytest -m benchmark # OCR benchmark suite — requires Tesseract; see benchmarks/README.md
python -m pytest -m api       # HTTP API tests — requires the `api` extra; most also require Tesseract
```

`-m api` includes the Phase 10.x enterprise suites (`tests/api/auth/`,
`tests/api/authorization/`, `tests/api/audit/`, `tests/api/ratelimit/`,
`tests/api/distributed/`). Authentication/authorization tests run
against a fully in-process mock OIDC provider (real RSA keys, real JWT
signing — no external IdP needed). The distributed-state and Redis-backed
unit tests (`tests/api/distributed/`, `tests/test_redis_*.py`) need a
real Redis reachable at `TEST_REDIS_URL`, or a local Docker daemon to
spin up an ephemeral one automatically (`tests/redis_env.py`) — they
**skip** (never fail) if neither is available.

Unit tests exercise detection/risk/policy/redaction logic directly against
synthetic OCR tokens and a fake OCR engine, so they never touch the Tesseract
binary. `-m e2e` selects the separate real-OCR suite under `tests/e2e/`,
which drives the full `Image -> Preprocess -> Real OCR -> Detection -> Risk
-> Policy -> Redaction -> Verification -> Output` pipeline against generated
test images. Plain `pytest` (no `-m`) excludes `e2e` automatically via
`pyproject.toml`'s `addopts`, so CI/local unit runs stay fast and don't need
Tesseract installed.

E2E tests never silently pass without a real OCR environment: if Tesseract
or the `chi_tra` language data is missing, every E2E test **SKIPS** (not
passes) with a message naming exactly what's missing.

### Generating E2E test fixtures

```bash
python scripts/generate_test_images.py
```

Regenerates `tests/fixtures/*.png` + `manifest.json`. All fixture text is
synthetic (fabricated formats, plus the standard Luhn-valid *test* credit
card number `4111 1111 1111 1111` that every payment processor's own docs
use) and every image carries a visible "TEST DATA (SYNTHETIC)" banner. Rerun
this if you change the fixture content in `scripts/generate_test_images.py`.
