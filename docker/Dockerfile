FROM python:3.11-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY pyproject.toml .
COPY README.md .
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[server]"

FROM deps AS app
RUN pip install --no-cache-dir -e . --no-deps

# Non-root user for production
RUN addgroup --system --gid 1001 agentci && \
    adduser --system --uid 1001 --gid 1001 agentci

# ── API Server ───────────────────────────────────────────────────────────────
FROM app AS api
USER agentci
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "agentci.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]

# ── Temporal Worker ──────────────────────────────────────────────────────────
FROM app AS worker
USER agentci
CMD ["python", "-m", "agentci.workflows.worker"]
