"""
Temporal worker startup.

Registers all workflows and activities, then starts a worker
pointed at the configured task queue.
"""
from __future__ import annotations

import asyncio
import logging
import os

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


async def run_worker() -> None:
    """Connect to Temporal and start the eval worker."""
    host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "agentci-eval")

    logger.info("Connecting to Temporal at %s (namespace=%s)", host, namespace)
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

    logger.info("Worker started on queue '%s'", task_queue)
    await worker.run()


def main() -> None:
    """Entry point for the worker process."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
