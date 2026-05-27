"""
Temporal worker startup.

Registers all workflows and activities, initialises the asyncpg pool
and Redis connection BEFORE starting the worker loop, then starts
a worker pointed at the configured task queue.

Handles SIGTERM/SIGINT for graceful shutdown in Docker/K8s environments.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from .eval_workflow import EvalRunWorkflow, ScenarioEvalWorkflow
from .activities import (
    update_eval_run_status,
    create_github_check_run,
    load_scenarios,
    run_agent_on_scenario,
    run_judge_panel,
    aggregate_and_analyze,
    store_results,
    report_to_github,
    publish_scenario_progress,
)

logger = logging.getLogger(__name__)

_shutdown_event: asyncio.Event | None = None


async def run_worker() -> None:
    """Connect to Temporal, init infrastructure, and start the eval worker."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "agentci-eval")

    logger.info(
        "AgentCI worker starting (pid=%d, queue=%s, temporal=%s/%s)",
        os.getpid(), task_queue, host, namespace,
    )

    # ── Init infrastructure BEFORE worker starts ─────────────────────
    from ..db.connection import create_pool, close_pool
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://agentci:agentci@localhost:5432/agentci",
    )
    await create_pool(dsn)
    logger.info("Database pool initialised for worker")

    # Redis (non-fatal if unavailable)
    try:
        from ..cache.redis_client import get_redis
        await get_redis()
        logger.info("Redis connected for worker")
    except Exception as e:
        logger.warning("Redis not available for worker (non-fatal): %s", e)

    # ── Connect to Temporal ──────────────────────────────────────────
    client = await Client.connect(host, namespace=namespace)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[EvalRunWorkflow, ScenarioEvalWorkflow],
        activities=[
            update_eval_run_status,
            create_github_check_run,
            load_scenarios,
            run_agent_on_scenario,
            run_judge_panel,
            aggregate_and_analyze,
            store_results,
            report_to_github,
            publish_scenario_progress,
        ],
    )

    # ── Register signal handlers for graceful shutdown ────────────────
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    logger.info("Worker started on queue '%s' — waiting for tasks", task_queue)

    try:
        # Run until shutdown signal
        shutdown_task = asyncio.create_task(_shutdown_event.wait())
        worker_task = asyncio.create_task(worker.run())

        done, pending = await asyncio.wait(
            [shutdown_task, worker_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    except asyncio.CancelledError:
        logger.info("Worker cancelled")
    finally:
        # ── Cleanup ──────────────────────────────────────────────────
        logger.info("Worker shutting down — draining connections")
        try:
            from ..cache.redis_client import close_redis
            await close_redis()
        except Exception:
            pass
        try:
            await close_pool()
        except Exception:
            pass
        logger.info("Worker shutdown complete")


def _handle_shutdown(sig: signal.Signals) -> None:
    """Signal handler — sets the shutdown event."""
    logger.info("Received signal %s — initiating graceful shutdown", sig.name)
    if _shutdown_event:
        _shutdown_event.set()


def main() -> None:
    """Entry point for the worker process."""
    # Configure logging
    try:
        from ..logging_config import configure_logging
        log_level = os.environ.get("LOG_LEVEL", "INFO")
        json_logs = os.environ.get("LOG_FORMAT", "json") == "json"
        configure_logging(level=log_level, json_output=json_logs)
    except ImportError:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

