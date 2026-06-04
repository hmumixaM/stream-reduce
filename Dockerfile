# syntax=docker/dockerfile:1

# --- Stage 1: build the React SPA ---
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: resolve Python dependencies into a venv ---
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# --- Stage 3: minimal runtime image ---
# Static ffmpeg/ffprobe binaries (~80MB) instead of the ~420MB apt package.
FROM mwader/static-ffmpeg:8.1.1 AS ffmpeg

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=deps /app/.venv /app/.venv
COPY app ./app
COPY worker ./worker
COPY alembic ./alembic
COPY alembic.ini ./
COPY --from=frontend /fe/dist ./frontend/dist

# App code stays root-owned (read-only at runtime); only the data dir is writable.
RUN useradd -m -u 1000 appuser && mkdir -p /data && chown appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
