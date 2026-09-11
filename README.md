# MaskGuard

**[English](README.md) | [繁體中文](README.zh-TW.md)**

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
puts `tesseract.exe` on `PATH`. The winget/UB-Mannheim package's bundled
`tessdata` only ships `eng` (+`osd`) — `chi_tra` (Traditional Chinese) must be
added manually:

```powershell
# Download the language pack Tesseract's own project publishes:
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata" -OutFile "$env:LOCALAPPDATA\tessdata\chi_tra.traineddata"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$env:LOCALAPPDATA\tessdata\"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" "$env:LOCALAPPDATA\tessdata\"
# Point Tesseract at a language-data directory you can write to without admin rights:
$env:TESSDATA_PREFIX = "$env:LOCALAPPDATA\tessdata"
```

Verify with `tesseract --list-langs` — it should print `chi_tra`, `eng`,
`osd`. If `tesseract` isn't on `PATH` at all, open a new terminal (winget
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

### Verifying the environment

```bash
python tests/e2e/_environment.py
```

Prints Python version, whether `pytesseract` imports, the resolved
`tesseract` binary path, `tesseract --version` output, and which of
`eng`/`chi_tra` are actually available.

## CLI Usage

```bash
imgmask input.png --output ./output
imgmask input.png --output ./output --mode strict --verify
imgmask ./input_folder --output ./output --recursive
```

Output layout:

```
output/
├── processed/<name>_masked.png
├── report/<name>_masked.json      # processing_report.json — no raw sensitive text
└── audit.log                      # append-only, type/confidence/region only
```

`--mode strict` enables local-only OCR/AI, no cloud upload, requires
verification, and blocks output entirely if verification fails (no image is
written).

## HTTP API

An optional FastAPI layer (`maskguard/api/`) exposes the same MaskGuard
pipeline over HTTP.

### Install and start the server

```bash
python -m pip install -e ".[api]"   # installs fastapi/uvicorn/pydantic/python-multipart on top of Core
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000
# or:
python -m maskguard.api
```

Binds to `127.0.0.1` (localhost only) by default. **Do not** pass
`--host 0.0.0.0` (or set `MASKGUARD_API_HOST=0.0.0.0`) unless you've put a
reverse proxy, authentication, and TLS in front of it — the API ships no
authentication of its own.

### Endpoints

All under `/api/v1/`. Interactive docs at `http://127.0.0.1:8000/docs` once
the server is running.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness check. Never runs OCR. |
| POST | `/api/v1/analyze` | Full pipeline; returns findings as JSON (no image). |
| POST | `/api/v1/process` | Same as `/analyze` — an explicit alias. |
| POST | `/api/v1/redact` | Full pipeline; returns the redacted image (`image/png`). |
| POST | `/api/v1/verify` | Independent whole-image sanity check — no prior detection context needed. |
| POST | `/api/v1/review` | Submit Human Review decisions for a prior `/analyze`'s `review_token`; returns the reviewed redacted image (`image/png`). |

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

`status` combines the verification status with `needs_human_review`/
`blocked` into one field: `PASSED` / `FAILED` / `SKIPPED` / `NEEDS_REVIEW` /
`BLOCKED`. This is a MaskGuard processing status, not an HTTP error — even a
`NEEDS_REVIEW` or `BLOCKED` result is returned as HTTP `200`.

Detection responses carry only `type` / `risk_level` / `action` /
`confidence` / `needs_review` / `bbox` — never the matched raw text.

### Configuration

All HTTP-layer limits live in `maskguard/api/config.py` (`ApiSettings`), set
via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760` (10 MB) | Rejected with `413` above this. |
| `MASKGUARD_MAX_IMAGE_WIDTH` | `8000` | Rejected with `422` above this. |
| `MASKGUARD_MAX_IMAGE_HEIGHT` | `8000` | Rejected with `422` above this. |
| `MASKGUARD_MAX_IMAGE_PIXELS` | `40000000` | Rejected with `422` above this. |
| `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` | `60` | Request-level soft timeout; `504` if exceeded. |
| `MASKGUARD_CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated allowed origins. Empty means no cross-origin access. |
| `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS` | `600` | How long a `/analyze` review token stays valid. |
| `MASKGUARD_MAX_REVIEW_REASON_LENGTH` | `200` | Max length of a REJECTED item's `reason` text. |
| `MASKGUARD_MIN_REVIEW_BBOX_WIDTH` / `_HEIGHT` | `4` | Minimum manual-detection box size. |
| `MASKGUARD_MAX_REVIEW_BBOX_AREA_RATIO` | `0.9` | Max fraction of image area a manual box may cover. |
| `MASKGUARD_MAX_REQUEST_BODY_BYTES` | `12582912` (12 MB) | Outer ASGI-level cap on the whole request body. |
| `MASKGUARD_MAX_REVIEW_ITEMS` | `200` | Total accept/reject/manual items one `/review` submission may contain. |
| `MASKGUARD_MAX_MANUAL_DETECTIONS` | `50` | How many of those may be brand-new manual detections. |
| `MASKGUARD_MAX_REVIEW_PAYLOAD_BYTES` | `262144` (256 KB) | Raw byte size of the `review` JSON form field. |
| `MASKGUARD_MAX_REVIEW_TOKEN_BYTES` | `65536` (64 KB) | Max size of an incoming `review_token`. |
| `MASKGUARD_MAX_CONCURRENT_JOBS` | `4` | Bounded concurrent processing jobs; excess requests get `429`. |

Uploads are validated by decoding them with Pillow (the client's
`Content-Type` header is never trusted), and no client-supplied filename or
image data is persisted beyond the request.

## Web Frontend

A React + TypeScript + Vite browser UI (`frontend/`) — a thin client over the
HTTP API above. End users only need a browser; Node.js is a development-time
dependency only.

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
Change it (or set the env var at build time) to point at a different backend.

### Production build

```bash
cd frontend
npm run build     # tsc -b && vite build -> frontend/dist/ (static assets)
```

### What it does

- Uploads an image, calls `POST /api/v1/analyze`, and draws the returned
  bounding boxes over the original image.
- Displays `type` / `risk_level` / `action` / `confidence` / `needs_review`
  per detection — never a raw matched value.
- The mask button calls `POST /api/v1/redact` and shows the returned image
  side-by-side with the original.
- Supports Human Review: accept/reject an existing finding, or add a manual
  detection by drawing a box on the image and picking a type.

### Frontend tests

```bash
cd frontend
npm test                                   # Vitest — component/unit tests, no backend required
VITE_TEST_REAL_BACKEND=1 npm test          # also runs the real-backend integration test — start the backend first
```

## Docker / Production Deployment

### Architecture

```
Browser --HTTPS--> [frontend container: Nginx]
                       - serves the built React app (static files)
                       - reverse-proxies /api/ --> [api container: FastAPI/Uvicorn]
                                                       - Core pipeline, Tesseract
```

The API container's port 8000 is never published to the host — the
frontend/proxy container is the only public entry point.

### Prerequisites

- **Windows 11**: Docker Desktop (WSL2 backend recommended), `docker compose` v2.
- **Linux**: Docker Engine 24+, the `docker compose` v2 plugin.

### Dev deployment (plain HTTP, local only)

```bash
docker compose up --build -d
docker compose ps                 # wait for both services "healthy"
curl http://localhost:8080/api/v1/health
```

Uses `docker-compose.yml` with an ephemeral auto-generated review-token
secret (fine for local testing only), plain HTTP on `localhost:8080`.

### Production deployment (HTTPS, externalized secret)

1. Generate a real review-token secret and a real TLS certificate/key for
   your deployment's hostname:
   ```bash
   mkdir -p secrets certs
   openssl rand -base64 48 > secrets/review_token_secret.txt
   # certs/cert.pem + certs/key.pem: supplied by your CA / enterprise PKI
   ```
   Neither `secrets/` nor `certs/` is ever committed (see `.gitignore`).
2. ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
3. If the secret file is missing, empty, or under 32 characters, the API
   container refuses to start (`InsecureProductionConfigError`). Check
   `docker compose -f docker-compose.prod.yml logs api` if the stack doesn't
   come up healthy.
4. ```bash
   curl -k https://localhost/api/v1/health   # -k only needed for a self-signed test cert
   ```

### Configuration

API-layer limits are set via the `MASKGUARD_*` environment variables listed
in `.env.example`. Nginx-layer settings (upstream, request-size ceiling,
proxy timeout, TLS paths) are set via the `docker-compose*.yml`
`environment:` blocks.

### Secrets

- **Review-token secret** (`MASKGUARD_REVIEW_TOKEN_SECRET` /
  `MASKGUARD_REVIEW_TOKEN_SECRET_FILE`): sourced from a Docker secret file in
  production (`./secrets/review_token_secret.txt`). Changing this secret
  invalidates all outstanding review tokens.
- **TLS certificate/key**: operator-supplied, bind-mounted read-only from
  `./certs/`. Rotate by replacing the files and restarting the `frontend`
  container (`docker compose -f docker-compose.prod.yml restart frontend`).

### Upgrade / Rollback

```bash
docker compose -f docker-compose.prod.yml pull            # if using a registry
docker compose -f docker-compose.prod.yml up -d --build    # or rebuild locally
docker compose -f docker-compose.prod.yml ps               # confirm healthy
curl -k https://localhost/api/v1/health                    # smoke test
```

Tag images with a version (`maskguard-api:9.x.x`) rather than relying on
`latest`, so a rollback is re-tagging the previous image and running
`docker compose ... up -d` again.

### Troubleshooting

See `docs/deployment.md` "Troubleshooting" for the full list; the most
common issue is a missing/weak review-token secret in production
(`docker compose -f docker-compose.prod.yml logs api`).

## Enterprise Security

The following is opt-in via environment variables — a deployment that sets
none of them behaves like the base deployment above.

- **Authentication (OIDC)**: `OIDC_ENABLED=true`, configured via
  `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET_FILE`/
  `OIDC_REDIRECT_URI` (see `.env.example`).
- **Authorization (RBAC)**: `AUTHZ_ROLE_MAPPING_FILE` maps identities to
  roles (Operator, Reviewer, SecurityAdministrator, Auditor, Administrator).
- **Audit**: `AUDIT_ENABLED=true` records security events to a local
  tamper-evident SQLite database. Reading it requires the `audit.read`
  permission.
- **Rate limiting**: `RATE_LIMIT_ENABLED=true` bounds request rate per
  endpoint class.
- **Multi-instance deployment**: `REDIS_ENABLED=true` shares session,
  review-replay, and rate-limit state across API containers.

Three deployment profiles, selectable via `MASKGUARD_DEPLOYMENT_PROFILE`:

| Profile | Compose file | Requires |
|---|---|---|
| `development` (default) | `docker-compose.yml` | nothing |
| `single-instance-enterprise` | `docker-compose.prod.yml` | OIDC + authorization + audit + rate limiting all enabled together |
| `multi-instance-enterprise` | `docker-compose.multi.yml` | the above, plus Redis |

Declaring an enterprise profile makes the app refuse to start if its
required controls aren't all consistently enabled.

`GET /api/v1/health` (liveness) and `GET /api/v1/ready` (readiness, reports
Redis availability when enabled) are always available.

## Tests

```bash
python -m pytest              # unit tests only — no Tesseract required
python -m pytest -m e2e       # real-OCR end-to-end tests — requires Tesseract (see above)
python -m pytest -m benchmark # OCR benchmark suite — requires Tesseract; see benchmarks/README.md
python -m pytest -m api       # HTTP API tests — requires the `api` extra; most also require Tesseract
```

E2E tests **SKIP** (never falsely pass) if Tesseract or the `chi_tra`
language data is missing, naming exactly what's missing.

### Generating E2E test fixtures

```bash
python scripts/generate_test_images.py
```

Regenerates `tests/fixtures/*.png` + `manifest.json` with synthetic test
data. Rerun this if you change the fixture content in
`scripts/generate_test_images.py`.
