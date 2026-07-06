# syntax=docker/dockerfile:1
#
# Runtime image for the AI Agent Platform.
# Supports every transport (api | telegram | cli) — the mode is chosen at run
# time via the command, not baked in. Secrets are injected via env at run time
# (never copied into the image; see .dockerignore excluding .env).

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first for better layer caching. The optional runtime
# extras (litellm for real models, aiogram for Telegram) are installed here so
# one image can serve every mode.
COPY requirements.txt ./
RUN pip install -r requirements.txt \
    "litellm>=1.35,<2.0" \
    "aiogram>=3.4,<4.0"

# Application code.
COPY app ./app

# Run as a non-root user; ensure the SQLite data dir is writable.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default mode is the REST API (needs no secrets). Override for Telegram, e.g.
#   docker run ... python -m app.main telegram
CMD ["python", "-m", "app.main", "api"]
