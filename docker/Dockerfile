# ── AgentCI Dockerfile ────────────────────────────────────────────────
# Multi-stage build with two targets:
#   - api:    FastAPI server (uvicorn on :8000)
#   - worker: Temporal worker process
# Both share the same base image with all Python deps installed.

# ── Stage 1: Base ─────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# Prevent .pyc files, enable unbuffered stdout for Docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps required by asyncpg (libpq) and curl for healthchecks
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[dev]"

# ── Stage 2: API Server ──────────────────────────────────────────────
FROM base AS api

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "agentci.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]

# ── Stage 3: Temporal Worker ─────────────────────────────────────────
FROM base AS worker

CMD ["python", "-m", "agentci.workflows.worker"]
