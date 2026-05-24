"""
Redis client for AgentCI.

Provides connection management, pub/sub for real-time eval progress,
rate limiting per repository, and eval run summary caching.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create the singleton Redis connection."""
    global _redis
    if _redis is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis = redis.from_url(url, decode_responses=True)
        logger.info("Redis connected: %s", url)
    return _redis


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed")


# ── Eval Progress Pub/Sub ────────────────────────────────────────────────────

async def publish_progress(run_id: str, event: dict[str, Any]) -> None:
    """Publish an eval progress event to the run's channel."""
    r = await get_redis()
    channel = f"agentci:progress:{run_id}"
    await r.publish(channel, json.dumps(event, default=str))


async def subscribe_progress(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to eval progress events for a run."""
    r = await get_redis()
    pubsub = r.pubsub()
    channel = f"agentci:progress:{run_id}"
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


# ── Rate Limiting ────────────────────────────────────────────────────────────

async def check_rate_limit(
    repo: str,
    limit: int = 10,
    window_seconds: int = 3600,
) -> bool:
    """
    Check if a repo is within its rate limit.

    Returns True if the request is allowed, False if rate limited.
    Uses a sliding window counter pattern.
    """
    r = await get_redis()
    key = f"agentci:ratelimit:{repo}"

    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()

    current_count = results[0]
    allowed = current_count <= limit

    if not allowed:
        logger.warning("Rate limit exceeded for %s: %d/%d", repo, current_count, limit)

    return allowed


# ── Caching ──────────────────────────────────────────────────────────────────

async def cache_run_summary(
    run_id: str,
    summary: dict[str, Any],
    ttl: int = 300,
) -> None:
    """Cache an eval run summary with TTL."""
    r = await get_redis()
    key = f"agentci:run:{run_id}"
    await r.set(key, json.dumps(summary, default=str), ex=ttl)


async def get_run_summary(run_id: str) -> dict[str, Any] | None:
    """Get a cached eval run summary."""
    r = await get_redis()
    key = f"agentci:run:{run_id}"
    data = await r.get(key)
    if data:
        return json.loads(data)
    return None
