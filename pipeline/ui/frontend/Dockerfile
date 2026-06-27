# ── Stage 1: Build ────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# URL prefix — must match gateway routing (e.g. /app).
# Read from deploy-config.yaml by deploy.sh and passed as --build-arg.
ARG BASE_PATH=/app
ENV VITE_BASE_PATH=$BASE_PATH \
    VITE_API_BASE_PREFIX=$BASE_PATH \
    VITE_WS_BASE_PREFIX=$BASE_PATH

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:alpine

ARG BASE_PATH=/app
# Optional prefix prepended to internal ACA hostnames (kg-backend, etc.).
# Default empty for backwards compatibility; set to e.g. "p2k-packs-"
# when multiple Policy to Knowledge stacks share an ACA managed environment.
ARG APP_PREFIX=""

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/nginx.conf.template

# Substitute ${BASE_PATH} and ${APP_PREFIX} in nginx template; leave all
# other $vars untouched. When BASE_PATH is empty (root deployment), strip
# the IF_BASE_PATH blocks (otherwise they collide with `location ${BASE_PATH}/`
# which becomes `location /`).
RUN if [ -z "$BASE_PATH" ]; then \
      sed -i '/# IF_BASE_PATH_BEGIN/,/# IF_BASE_PATH_END/d' /etc/nginx/conf.d/nginx.conf.template; \
    fi \
 && BASE_PATH="$BASE_PATH" APP_PREFIX="$APP_PREFIX" \
      envsubst '${BASE_PATH} ${APP_PREFIX}' \
      < /etc/nginx/conf.d/nginx.conf.template \
      > /etc/nginx/conf.d/default.conf \
 && rm /etc/nginx/conf.d/nginx.conf.template

EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:5173/ || exit 1
