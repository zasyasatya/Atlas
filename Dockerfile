# syntax=docker/dockerfile:1
# ============================================================================
#  ATLAS - AI Internship Operating System
#  Single-image monolith: Next.js static export served by FastAPI.
#  Build:  docker build -t atlas .
#  Run:    docker run -p 8000:8000 -v atlas_storage:/app/storage atlas
#  Coolify: point at this Dockerfile, expose port 8000, mount /app/storage.
# ============================================================================

# ---------- stage 1: build the frontend ----------
FROM node:20-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1 BUILD_EXPORT=1
RUN npm run build


# ---------- stage 2: python dependencies ----------
FROM python:3.11-slim AS deps

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


# ---------- stage 3: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    ATLAS_ENVIRONMENT=production \
    ATLAS_STORAGE_DIR=/app/storage \
    PORT=8000

WORKDIR /app

# curl for the healthcheck; git so learners can pull app bundles from a repo
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git tini \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 atlas

COPY --from=deps /opt/venv /opt/venv
COPY backend/ /app/backend/
COPY templates/ /app/templates/
COPY --from=frontend /build/out /app/backend/app/static

# NOTE: /bin/sh in slim images is dash, which has no brace expansion.
RUN for d in datasets decks notebooks deployments artifacts runs; do \
      mkdir -p "/app/storage/$d"; \
    done \
 && chown -R atlas:atlas /app

USER atlas
WORKDIR /app/backend

EXPOSE 8000
VOLUME ["/app/storage"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
