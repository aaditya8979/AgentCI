"""
asyncpg connection pool management.

Provides a process-wide singleton pool that is initialised once at
application startup (FastAPI lifespan or Temporal worker boot) and
shared across all request handlers, activities, and background tasks.

The pool is never created lazily. If get_pool() is called before
create_pool(), it raises RuntimeError immediately rather than
returning None and causing a confusing AttributeError downstream.
"""
from __future__ import annotations

import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool(
    dsn: str | None = None,
    min_size: int = 2,
    max_size: int = 10,
) -> asyncpg.Pool:
    """
    Create the process-wide connection pool and store it as the singleton.

    Must be called exactly once during application startup:
    - In the FastAPI lifespan (for the API process)
    - In the Temporal worker boot (for the worker process)

    Returns the pool so callers can also store a local reference.
    """
    global _pool
    if _pool is not None:
        logger.warning("create_pool() called but pool already exists — reusing")
        return _pool

    dsn = dsn or os.environ.get(
        "DATABASE_URL",
        "postgresql://agentci:agentci@localhost:5432/agentci",
    )
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
    )
    logger.info(
        "Database pool created (min=%d, max=%d, dsn=%s)",
        min_size, max_size, dsn.split("@")[-1] if "@" in dsn else dsn,
    )
    return _pool


def get_pool() -> asyncpg.Pool:
    """
    Return the singleton connection pool.

    Raises RuntimeError if the pool has not been initialised.
    This is intentionally synchronous — pool creation is async,
    but pool retrieval must never trigger lazy initialisation.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialised. "
            "Call create_pool() during application startup "
            "(FastAPI lifespan or Temporal worker boot)."
        )
    return _pool


async def close_pool() -> None:
    """Close the singleton pool. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
