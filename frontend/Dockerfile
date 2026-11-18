# [D1] Dockerfile — two stages: Node builds the static bundle, nginx serves it
# Final image has no Node and no source code — just nginx + the built files
#
# Build:  docker build -t retail-frontend ./frontend
# Run:    docker run --rm -p 8080:80 retail-frontend      → http://localhost:8080
# Mocks:  docker build --build-arg VITE_USE_MOCKS=true -t retail-frontend ./frontend


# ═══════════════════════════════════════════════════════════════════
# 1. Build stage — npm ci + vite build → /app/dist
# ═══════════════════════════════════════════════════════════════════
FROM node:24-alpine AS build
WORKDIR /app

# Dependencies first → this layer is cached until package*.json changes
COPY package.json package-lock.json ./
RUN npm ci

# VITE_* values are baked into the JS at build time (Vite replaces import.meta.env.*)
# VITE_API_URL empty → same-origin requests (/auth, /agent, /domain) that the
# API Gateway routes to each service — no CORS.
# Process env beats .env files in Vite; .env is also excluded by .dockerignore
ARG VITE_API_URL=
ARG VITE_USE_MOCKS=false
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_USE_MOCKS=$VITE_USE_MOCKS

COPY . .
RUN npm run build


# ═══════════════════════════════════════════════════════════════════
# 2. Serve stage — nginx with our config
# ═══════════════════════════════════════════════════════════════════
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
