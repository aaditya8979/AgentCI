"""
WebSocket endpoint for live eval run progress.

Subscribes to Redis pub/sub on the channel for a specific eval run
and forwards progress events to the connected browser client in real-time.

Gracefully handles: Redis unavailable, client disconnect, malformed messages.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/runs/{run_id}")
async def eval_run_progress(websocket: WebSocket, run_id: str):
    """
    Stream live eval progress for a specific run.

    Protocol:
      - Client connects to /ws/runs/{run_id}
      - Server subscribes to Redis channel agentci:progress:{run_id}
      - Each Redis message is forwarded as a WebSocket text frame
      - Connection closes when the run completes or client disconnects

    Message format (JSON):
      {
        "type": "scenario_started" | "scenario_completed" | "run_completed",
        "scenario_id": "...",
        "progress": 0.0-1.0,
        "score": 0.85,
        ...
      }
    """
    await websocket.accept()

    # Check Redis availability
    try:
        from ..cache.redis_client import get_redis
        redis = await get_redis()
    except Exception as e:
        logger.warning("WebSocket: Redis unavailable for run %s: %s", run_id, e)
        await websocket.close(code=1011, reason="Live updates unavailable — Redis not connected")
        return

    pubsub = redis.pubsub()
    channel = f"agentci:progress:{run_id}"

    try:
        await pubsub.subscribe(channel)
        logger.info("WebSocket: subscribed to %s", channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                await websocket.send_text(data if isinstance(data, str) else data.decode())

                # Auto-close on run completion
                try:
                    parsed = json.loads(data)
                    if parsed.get("type") in ("run_completed", "run_failed"):
                        logger.info("WebSocket: run %s finished, closing", run_id)
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

    except WebSocketDisconnect:
        logger.info("WebSocket: client disconnected for run %s", run_id)
    except Exception as e:
        logger.error("WebSocket: error for run %s: %s", run_id, e)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        logger.debug("WebSocket: cleaned up subscription for %s", channel)
