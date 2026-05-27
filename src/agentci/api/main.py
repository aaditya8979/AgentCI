"""
FastAPI application for AgentCI.

Provides the webhook endpoint for GitHub PR events, REST API for eval runs,
and real-time WebSocket for live eval progress.

Initialises asyncpg pool, Redis, and Temporal client once at startup
via the module-level singletons in db.connection and cache.redis_client.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .webhook import router as webhook_router
from .routes import router as api_router
from .ws import router as ws_router

logger = logging.getLogger(__name__)

# ── Version ──────────────────────────────────────────────────────────────────
__version__ = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # ── Startup ──────────────────────────────────────────────────────
    logger.info("AgentCI API v%s starting up (pid=%d)", __version__, os.getpid())

    # Configure structlog if available
    try:
        from ..logging_config import configure_logging
        log_level = os.environ.get("LOG_LEVEL", "INFO")
        json_logs = os.environ.get("LOG_FORMAT", "json") == "json"
        configure_logging(level=log_level, json_output=json_logs)
        logger.info("Structured logging configured: level=%s json=%s", log_level, json_logs)
    except ImportError:
        pass  # structlog not installed — stdlib logging works fine

    # 1. Database pool — sets the module-level singleton
    from ..db.connection import create_pool, close_pool
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://agentci:agentci@localhost:5432/agentci",
    )
    try:
        pool = await create_pool(dsn)
        app.state.db_pool = pool  # kept for backward compat; prefer get_pool()
        logger.info("Database pool ready (min=2, max=20)")
    except Exception as e:
        logger.error("Database connection failed: %s — API will return 503", e)
        app.state.db_pool = None

    # 2. Redis
    try:
        from ..cache.redis_client import get_redis, close_redis
        app.state.redis = await get_redis()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available (non-fatal): %s", e)
        app.state.redis = None

    # 3. Temporal client
    try:
        from temporalio.client import Client as TemporalClient
        temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
        temporal_ns = os.environ.get("TEMPORAL_NAMESPACE", "default")
        app.state.temporal = await TemporalClient.connect(
            temporal_host, namespace=temporal_ns,
        )
        logger.info("Temporal client connected: %s/%s", temporal_host, temporal_ns)
    except Exception as e:
        logger.warning("Temporal not available (non-fatal): %s", e)
        app.state.temporal = None

    logger.info("AgentCI API startup complete")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("AgentCI API shutting down — draining connections")

    # Close in reverse order of creation
    try:
        from ..cache.redis_client import close_redis
        await close_redis()
        logger.info("Redis connection closed")
    except Exception:
        pass

    try:
        await close_pool()
        logger.info("Database pool closed")
    except Exception:
        pass

    logger.info("AgentCI API shutdown complete")


app = FastAPI(
    title="AgentCI",
    description="Enterprise-Grade CI/CD Quality Gate for LLM Agents",
    version=__version__,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin for origin in [
            "http://localhost:3000",
            "http://dashboard:3000",
            os.environ.get("DASHBOARD_ORIGIN", ""),
        ] if origin
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# ── Correlation ID + Request Logging Middleware ──────────────────────────────
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Inject a unique request ID into every request/response pair."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.perf_counter()

    response = await call_next(request)

    latency_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = request_id

    # Log all non-health requests
    if request.url.path != "/health":
        logger.info(
            "request_completed method=%s path=%s status=%d latency_ms=%d request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            request_id,
        )

    return response


# ── API Key Authentication Middleware ────────────────────────────────────────
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Enforce API key authentication on /api/* endpoints."""
    path = request.url.path
    # Exempt paths: health check, webhooks, WebSocket, docs
    if (
        path == "/health"
        or path.startswith("/webhook/")
        or path.startswith("/ws/")
        or path == "/docs"
        or path == "/openapi.json"
        or path == "/redoc"
        or path.startswith("/static/")
    ):
        return await call_next(request)

    if path.startswith("/api/"):
        api_keys_str = os.environ.get("AGENTCI_API_KEYS", "")
        if api_keys_str:
            valid_keys = {k.strip() for k in api_keys_str.split(",") if k.strip()}
            api_key = request.headers.get("X-API-Key", "")
            if api_key not in valid_keys:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "message": "Valid API key required in X-API-Key header.",
                    },
                )

    return await call_next(request)


# ── Routes ───────────────────────────────────────────────────────────────────
app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])
app.include_router(api_router, prefix="/api", tags=["api"])
app.include_router(ws_router, tags=["websocket"])


# ── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """
    Health check endpoint.

    Returns 200 with status "ok" when all required dependencies are healthy.
    Returns 200 with status "degraded" when optional dependencies are down.
    Returns 503 when the database (required dependency) is down.
    """
    checks: dict[str, str] = {"api": "ok", "version": __version__}

    # Check DB via the singleton — not app.state
    db_ok = False
    try:
        from ..db.connection import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = "ok"
        db_ok = True
    except RuntimeError:
        checks["database"] = "not initialised"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    # Check Redis (optional)
    try:
        redis = getattr(app.state, "redis", None)
        if redis:
            await redis.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not configured"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"

    # Check Temporal (optional)
    temporal = getattr(app.state, "temporal", None)
    checks["temporal"] = "ok" if temporal else "not configured"

    if db_ok:
        status_label = "ok"
        status_code = 200
    elif checks["database"] == "not initialised":
        status_label = "degraded"
        status_code = 503
    else:
        status_label = "unhealthy"
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content={"status": status_label, "checks": checks},
    )
