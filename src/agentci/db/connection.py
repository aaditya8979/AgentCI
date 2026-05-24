"""
asyncpg connection pool management.

Provides a singleton pool with lazy initialization and graceful shutdown.
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
    """Create and return a new connection pool."""
    dsn = dsn or os.environ.get(
        "DATABASE_URL",
        "postgresql://agentci:agentci_dev@localhost:5432/agentci",
    )
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
    )
    logger.info("Database pool created (min=%d, max=%d)", min_size, max_size)
    return pool


async def get_pool() -> asyncpg.Pool:
    """Get or create the singleton connection pool."""
    global _pool
    if _pool is None:
        _pool = await create_pool()
    return _pool


async def close_pool() -> None:
    """Close the singleton pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
