"""
FastAPI application for AgentCI.

Provides the webhook endpoint for GitHub PR events, REST API for eval runs,
and real-time WebSocket for live eval progress.

Initialises asyncpg pool, Redis, and Temporal client once at startup
and stores them on app.state for reuse across requests.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .webhook import router as webhook_router
from .routes import router as api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # ── Startup ──────────────────────────────────────────────────────
    logger.info("AgentCI API starting up")

    # 1. Database pool
    from ..db.connection import create_pool, close_pool
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://agentci:agentci@localhost:5432/agentci",
    )
    pool = await create_pool(dsn)
    app.state.db_pool = pool
    logger.info("Database pool ready")

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
        logger.info("Temporal client connected: %s", temporal_host)
    except Exception as e:
        logger.warning("Temporal not available (non-fatal): %s", e)
        app.state.temporal = None

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("AgentCI API shutting down")
    await close_pool()
    try:
        from ..cache.redis_client import close_redis
        await close_redis()
    except Exception:
        pass


app = FastAPI(
    title="AgentCI",
    description="Enterprise-Grade CI/CD Quality Gate for LLM Agents",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://dashboard:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])
app.include_router(api_router, prefix="/api", tags=["api"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    checks = {"api": "ok"}

    # Check DB
    try:
        pool = getattr(app.state, "db_pool", None)
        if pool:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["database"] = "ok"
        else:
            checks["database"] = "not configured"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Check Redis
    try:
        redis = getattr(app.state, "redis", None)
        if redis:
            await redis.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not configured"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Check Temporal
    checks["temporal"] = "ok" if getattr(app.state, "temporal", None) else "not configured"

    overall = all(v == "ok" for v in checks.values() if v != "not configured")
    return {"status": "ok" if overall else "degraded", "checks": checks}

