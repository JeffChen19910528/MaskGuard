# MaskGuard frontend image (Phase 9 §2/§4/§6).
#
# Multi-stage: a "build" stage runs the REAL production build
# (`npm run build` -> `tsc -b && vite build`, never `npm run dev`/the Vite
# dev server) and produces static assets only; the final "runtime" stage is
# plain Nginx serving those static files plus reverse-proxying `/api/` to
# the FastAPI container. No Node, no npm, no source files, no dev
# dependencies ship in the final image — only compiled JS/CSS/HTML.
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build

WORKDIR /build

# Installed separately from `COPY . .` so `npm ci` (which needs
# package-lock.json to be reproducible, §46) is cached independently of
# source-code changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
COPY public ./public

# frontend/.env.production (committed, no secrets — see that file) supplies
# VITE_API_BASE_URL="" so the build emits same-origin `/api/v1/...` calls;
# Vite reads it automatically for a `production` mode build, no extra flag
# needed. This is the REAL production build the task requires — never the
# dev server.
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 AS runtime

# Nginx's stock image already runs its master process as root (required to
# bind port 80/443 and read TLS key files) but its WORKER processes already
# drop to the unprivileged `nginx` user by default — this is the image's
# normal, supported non-root worker model; no code changes needed. Static
# assets are owned by that same user so the worker can read them.
COPY --from=build /build/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html

# Config is rendered from these templates via envsubst at CONTAINER START
# (see nginx/entrypoint.sh), not baked in at build time, so the same image
# serves both dev (HTTP-only) and prod (HTTPS, cert paths from the
# deployment's secret configuration) topologies depending on env vars
# supplied by docker-compose.yml / docker-compose.prod.yml.
# Deliberately NOT /etc/nginx/templates/ — the base image's own
# /docker-entrypoint.d/20-envsubst-on-templates.sh auto-renders every
# *.template file in that directory with UNRESTRICTED envsubst (mangling
# Nginx's own $uri/$status/etc. runtime variables) and drops the output
# straight into /etc/nginx/conf.d/*.conf, which is auto-`include`d — a
# second, uncontrolled render our own entrypoint script doesn't manage.
# Using a separate directory keeps that built-in mechanism out of this.
COPY nginx/common.conf.inc nginx/nginx.dev.conf.template nginx/nginx.prod.conf.template /etc/nginx/maskguard-templates/
# http-context log_format. NOT copied straight into /etc/nginx/conf.d/ here
# — Compose's production hardening mounts conf.d as tmpfs (read-only root
# filesystem, §12/§37), which would shadow a build-time file placed there.
# entrypoint.sh copies this into conf.d at CONTAINER START instead, next to
# the config it renders, so it survives the tmpfs mount either way.
COPY nginx/00-log-format.conf /etc/nginx/maskguard-templates/00-log-format.conf
COPY nginx/entrypoint.sh /docker-entrypoint.d/60-maskguard-render-config.sh
RUN chmod +x /docker-entrypoint.d/60-maskguard-render-config.sh \
 && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80 443

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1/healthz"]
