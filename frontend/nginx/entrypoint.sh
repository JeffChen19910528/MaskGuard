#!/bin/sh
# Renders the Nginx config from the templates in this image at CONTAINER
# START (not build time) — Phase 9 §10/§62-64: the same built image serves
# either dev (HTTP) or prod (HTTPS) depending on env vars supplied by
# docker-compose.yml / docker-compose.prod.yml, and the actual cert/key
# paths are never baked into the image.
#
# Installed as /docker-entrypoint.d/60-maskguard-render-config.sh, which the
# base nginx:alpine image's own entrypoint (`docker-entrypoint.sh`) runs
# automatically for every *.sh file in that directory, before starting
# nginx — no custom ENTRYPOINT/CMD override needed.
set -eu

# `export` is required here, not just the `:=` default-assignment — envsubst
# runs as a separate child process and only sees exported variables; without
# `export` these defaults are invisible to it and silently substitute as
# empty strings (caught during Phase 9 container testing: an empty
# client_max_body_size value is an Nginx config syntax error at startup).
: "${MASKGUARD_NGINX_MODE:=dev}"
: "${API_UPSTREAM:=api:8000}"
# Phase 10.6 §58/§59/§116-117: optional SECOND API node — set only by
# docker-compose.multi.yml. Empty (the default) means the rendered
# upstream block has exactly one server, identical behavior to every
# prior single-instance phase.
: "${API_UPSTREAM_B:=}"
: "${NGINX_MAX_BODY_SIZE:=13m}"
: "${NGINX_PROXY_TIMEOUT:=65}"
export MASKGUARD_NGINX_MODE API_UPSTREAM API_UPSTREAM_B NGINX_MAX_BODY_SIZE NGINX_PROXY_TIMEOUT

# Phase 10.6: http-context `upstream{}` block — rendered directly (not via
# envsubst, since it needs conditional logic envsubst can't express) into
# conf.d/ so the existing wildcard include picks it up automatically.
# Round-robin only (§59/§60/§117): no ip_hash/sticky directive — shared
# Redis state (Phase 10.6) is the actual cross-node consistency mechanism.
{
    echo "upstream maskguard_api_upstream {"
    echo "    server ${API_UPSTREAM};"
    if [ -n "${API_UPSTREAM_B}" ]; then
        echo "    server ${API_UPSTREAM_B};"
    fi
    echo "}"
} > /etc/nginx/conf.d/01-maskguard-upstream.conf

# Explicit substitution list (Phase 9 note): envsubst by default replaces
# EVERY $VARNAME it finds, which would also mangle Nginx's own runtime
# variables ($uri, $status, $host, $remote_addr, ...) used throughout
# common.conf.inc. Restricting to exactly these four keeps everything else
# in the templates untouched.
SUBST_VARS='${API_UPSTREAM} ${NGINX_MAX_BODY_SIZE} ${NGINX_PROXY_TIMEOUT} ${TLS_CERT_PATH} ${TLS_KEY_PATH}'

# Rendered OUTSIDE /etc/nginx/conf.d/ on purpose: nginx.conf's own
# `include /etc/nginx/conf.d/*.conf;` (http-context, wildcard) would pick
# this file up a SECOND time if it lived there too, alongside our deliberate
# `include` of it from inside the server{} block below — and a `location`/
# `root` directive is invalid at http-context, so nginx would refuse to
# start. Keeping it under a directory the wildcard never scans avoids that.
mkdir -p /etc/nginx/maskguard-conf
envsubst "$SUBST_VARS" < /etc/nginx/maskguard-templates/common.conf.inc > /etc/nginx/maskguard-conf/common.conf

# Static (no substitution needed) — copied at runtime, not build time, so it
# survives a tmpfs mount over /etc/nginx/conf.d (see Dockerfile comment).
cp /etc/nginx/maskguard-templates/00-log-format.conf /etc/nginx/conf.d/00-log-format.conf

case "$MASKGUARD_NGINX_MODE" in
  prod|production)
    if [ -z "${TLS_CERT_PATH:-}" ] || [ -z "${TLS_KEY_PATH:-}" ]; then
      echo "FATAL: MASKGUARD_NGINX_MODE=prod requires TLS_CERT_PATH and TLS_KEY_PATH to be set." >&2
      exit 1
    fi
    envsubst "$SUBST_VARS" < /etc/nginx/maskguard-templates/nginx.prod.conf.template > /etc/nginx/conf.d/default.conf
    ;;
  *)
    envsubst "$SUBST_VARS" < /etc/nginx/maskguard-templates/nginx.dev.conf.template > /etc/nginx/conf.d/default.conf
    ;;
esac
