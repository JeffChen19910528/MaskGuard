# Shared between nginx.dev.conf.template and nginx.prod.conf.template
# (included via `include` so the two topologies can't drift apart on the
# things that matter for security regardless of TLS/HTTP). Phase 9 §36/§38/
# §39/§41.

# --- Request size (§38): defense in depth alongside the ASGI streaming
# limit (MaskGuard.MaxRequestBodySizeMiddleware) and the application's own
# MASKGUARD_MAX_UPLOAD_SIZE_BYTES validation — this is the FIRST layer, at
# the edge, before the request body is even proxied to the API container.
# Kept slightly above MASKGUARD_MAX_REQUEST_BODY_BYTES (12 MiB default) so
# the proxy never rejects a request the application would have accepted;
# the ASGI layer remains the authoritative limit.
client_max_body_size ${NGINX_MAX_BODY_SIZE};

# --- Security headers (§36) — applied to every response this server block
# serves, static or proxied. `add_header` here does NOT remove headers the
# proxied FastAPI response already set (Phase 8.4's own security-headers
# middleware) — Nginx merges by name, so the API's own headers still apply
# to /api/ responses; these are the frontend/edge-level equivalents for the
# static assets and as a fallback.
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'" always;

# --- Access logging (§34/§35): method/path/status/duration only — never
# the query string (a GET on this app never legitimately carries sensitive
# data in one, but this format omits it defensively anyway) and never
# request bodies (Nginx's default access log never includes bodies). The
# `maskguard` format itself is defined in log_format.conf (http-context,
# auto-included by nginx.conf's own conf.d/*.conf wildcard) since
# `log_format` is only valid at http-context, not here inside a server{}.
access_log /var/log/nginx/access.log maskguard;

# --- Static frontend (§41): ONLY the built output directory is ever
# served — no source, no .env, no backend files, nothing outside this root
# is reachable via any path (Nginx's root/alias model can't traverse above
# root through a plain `location /` block; no `alias` with user input is
# used anywhere in this config).
root /usr/share/nginx/html;
index index.html;

location /healthz {
    # §29-equivalent for the proxy container itself — never proxied to the
    # API, never triggers OCR, used by Docker HEALTHCHECK and (in Compose)
    # `depends_on: condition: service_healthy` for anything that waits on
    # the proxy specifically.
    default_type text/plain;
    return 200 "ok\n";
}

location = /favicon.ico {
    access_log off;
    try_files /favicon.ico =204;
}

# React Router / SPA fallback — every non-API, non-asset path serves
# index.html; the app itself renders the right view client-side. This can
# never expose a file outside the build output because $uri is always
# resolved relative to `root` above.
location / {
    try_files $uri $uri/ /index.html;
}

# --- Reverse proxy to the API (§1/§37): the ONLY way a browser ever
# reaches FastAPI. The API container's port 8000 is never published to the
# host/Internet (see docker-compose*.yml) — this proxy_pass over the
# internal Docker network is the sole path in.
location /api/ {
    # Phase 10.6 §59/§60/§117: `maskguard_api_upstream` is an `upstream{}`
    # block rendered by entrypoint.sh at container start (http-context,
    # /etc/nginx/conf.d/01-maskguard-upstream.conf) — ONE server
    # (API_UPSTREAM) for the single-instance topology (docker-compose.yml/
    # .prod.yml, unchanged behavior — an upstream block with a single
    # server behaves identically to a direct proxy_pass) or TWO
    # (API_UPSTREAM + API_UPSTREAM_B, docker-compose.multi.yml) for the
    # multi-instance profile. Default round-robin — NO `ip_hash`/sticky
    # directive anywhere in this config, deliberately: distributed shared
    # state (Phase 10.6) is the actual solution, not session affinity.
    proxy_pass http://maskguard_api_upstream/api/;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # --- Timeout (§39): consistent with MASKGUARD_PROCESSING_TIMEOUT_SECONDS
    # (60s default) but slightly ABOVE it, so the application's own timeout
    # response (504 JSON from FastAPI) is what a slow request actually
    # produces, not the proxy cutting the connection first and masking it.
    proxy_read_timeout ${NGINX_PROXY_TIMEOUT}s;
    proxy_send_timeout ${NGINX_PROXY_TIMEOUT}s;
    proxy_connect_timeout 10s;

    # Analyze/redact/review responses can be a redacted image (binary) —
    # buffering off keeps latency down and avoids Nginx spooling large
    # image bodies to disk unnecessarily.
    proxy_buffering off;
    client_max_body_size ${NGINX_MAX_BODY_SIZE};
}
