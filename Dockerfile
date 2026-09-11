# MaskGuard API image (Phase 9 §2/§4/§21/§22).
#
# Multi-stage: a "builder" stage installs Python dependencies into an
# isolated venv (needs no OS build tools beyond what pip itself requires
# for these packages, which ship manylinux wheels); the final "runtime"
# stage starts fresh from the SAME pinned base, installs ONLY what's
# needed to actually RUN MaskGuard (Tesseract + language data, plus the
# runtime shared libraries opencv-python-headless/Pillow need), copies the
# built venv in, and drops root. No compiler, no pip cache, no build
# tooling ships in the final image.
#
# Base image pinned by tag AND digest (§21 — "no `latest`, document how
# images are updated": bump both together, after testing, in one commit).
# Phase 9.1 §3-5: base OS changed from bookworm to trixie SPECIFICALLY for
# Tesseract version parity — Debian bookworm only packages tesseract-ocr
# 5.3.0 (confirmed via `apt-cache madison`, including bookworm-backports,
# which does not carry a newer build); trixie packages 5.5.0. The exact
# Windows dev build (5.4.0.20240606, a UB Mannheim Windows-installer label
# for upstream tesseract 5.4.0) is not available as a Debian package on
# EITHER release and was not built from source here (see
# docs/ocr-parity-findings.md for the full decision record) — trixie's
# 5.5.0 was chosen as the canonical production version: it is Debian's own
# actively-maintained package (reproducible via apt, no from-source build
# fragility) and its leptonica dependency (1.84.1) happens to exactly
# match the Windows dev install's leptonica version. This is a newer
# release than Windows dev's 5.4.0, not an older one — a deliberate,
# disclosed choice, not silent drift.
FROM python:3.11-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder

WORKDIR /build

# Only what pip itself needs to resolve/build the pinned dependency set —
# never present in the final runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml requirements.lock ./
COPY maskguard ./maskguard
COPY README.md ./

# Phase 9.1 §7-10: install from the LOCKED, transitively-pinned dependency
# set (requirements.lock — generated via pip-compile INSIDE a container
# matching this exact base image, see that file's header) instead of
# resolving `.[api]`'s loose `>=` constraints fresh at every build. Same
# Git commit + this lock file = the same installed versions, every time —
# this is what closes the reproducibility gap that previously let the
# container resolve dependency versions the Windows dev environment had
# never actually tested against (and once caused a real `tests/api/`
# collection failure from an unpinned Starlette pulling in a testclient
# dependency the dev environment didn't have). `--no-deps` on the second
# install: `maskguard` itself is installed via `pip install .` AFTER the
# lock so pip doesn't re-resolve/override the already-pinned versions
# above it while still registering the package (console script, metadata).
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.lock \
 && pip install --no-cache-dir --no-deps .


FROM python:3.11-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS runtime

# Tesseract + the exact language data MaskGuard requires (Skill.md's own
# stated requirement, verified — Phase 9 §22, re-verified Phase 9.1 §4-5):
# eng, chi_tra, osd. `tesseract-ocr` pulls in `eng` + `osd` by default on
# Debian; `chi_tra` is a separate language-data package. trixie's package
# is tesseract 5.5.0 (leptonica 1.84.1) — see the builder stage's comment
# above for why trixie was chosen over bookworm's 5.3.0. No other apt
# packages, no recommends.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-tra \
        libjpeg62-turbo \
        zlib1g \
        libpng16-16 \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user (§12). Tesseract, temp-file creation, and uvicorn
# all run as this user — verified in CI/deployment testing (see
# docs/deployment.md), not merely asserted.
RUN groupadd --gid 10001 maskguard \
 && useradd --uid 10001 --gid maskguard --no-create-home --shell /usr/sbin/nologin maskguard

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MASKGUARD_ENV=production

WORKDIR /app
COPY maskguard ./maskguard
COPY config.default.yaml ./config.default.yaml

# The venv, app code, and working directory are all owned by the runtime
# user — nothing here needs write access except the OS temp directory
# (already root-owned but world-writable+sticky-bit, `/tmp`'s standard
# mode, which `tempfile.TemporaryDirectory()` relies on — see §13).
RUN chown -R maskguard:maskguard /app

# Phase 10.4 §24/§52/§119: durable audit storage mount point — created
# here (not left for a volume driver to guess ownership) and owned by the
# non-root runtime user, so the mounted volume inherits correct
# permissions on first use. Not world-readable (§52).
RUN mkdir -p /var/lib/maskguard-audit \
 && chown maskguard:maskguard /var/lib/maskguard-audit \
 && chmod 700 /var/lib/maskguard-audit

USER maskguard

# Phase 9.1 §26: build metadata, queryable via `docker inspect
# --format '{{json .Config.Labels}}' maskguard-api:9.1.0` — no secrets, no
# filesystem paths, nothing beyond version identifiers. `MASKGUARD_VERSION`
# defaults here but is meant to be overridden per release via
# `docker build --build-arg MASKGUARD_VERSION=9.1.0` (see
# docs/release-hardening.md "Image tagging").
ARG MASKGUARD_VERSION=10.7.0
LABEL org.opencontainers.image.title="maskguard-api" \
      org.opencontainers.image.version="${MASKGUARD_VERSION}" \
      org.opencontainers.image.base.name="python:3.11-slim-trixie"

EXPOSE 8000

# §29: lightweight liveness/readiness only — never runs OCR (see
# maskguard/api/routes/health.py). `curl` isn't installed in this minimal
# image; Python's own stdlib does the HTTP GET instead, so no extra
# package is needed just for the healthcheck.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"]

# Production start command (§47): explicit host/port, no --reload, ONE
# worker process. See docs/deployment.md "Why a single worker" — the
# in-memory review-token issuer and ConcurrencyLimiter (Phase 8.3/8.4) are
# per-process state; multiple uvicorn workers would each get their OWN
# independent secret/limiter, silently breaking review-token verification
# and concurrency bounding across workers. Scale this service by running
# more CONTAINERS behind a load balancer only once a shared token/limiter
# store exists (Phase 10+) — not by adding `--workers N` here.
CMD ["uvicorn", "maskguard.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
