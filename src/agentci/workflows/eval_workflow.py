"""
Temporal workflow definition for eval runs.

Orchestrates the complete evaluation pipeline as a durable workflow:
scenario loading → agent execution → judging → aggregation → reporting.

All side-effects (API calls, Docker, DB writes) are Activities.
The workflow itself is pure orchestration logic.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

logger = logging.getLogger(__name__)

# Default retry policy for activities
DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["AuthenticationError", "ConfigurationError"],
)


@dataclass
class EvalRunInput:
    """Input to the eval run workflow."""
    run_id: str
    repo_full_name: str
    commit_sha: str
    pr_number: int | None = None
    eval_suite: str = "full"
    scenarios_path: str = "./eval/scenarios"
    agent_entry: str = "./agent.py"
    agent_function: str = "run"
    judge_models: list[str] | None = None
    triggered_by: str = "webhook"


@dataclass
class EvalRunOutput:
    """Output of the eval run workflow."""
    run_id: str
    overall_passed: bool
    final_score: float
    baseline_score: float | None
    p_value: float | None
    severity: str | None
    scenarios_total: int
    scenarios_passed: int
    duration_ms: int


@dataclass
class ScenarioEvalInput:
    """Input for a single scenario evaluation."""
    run_id: str
    scenario_json: str
    agent_entry: str
    agent_function: str
    judge_models: list[str]


@dataclass
class ScenarioEvalOutput:
    """Output of a single scenario evaluation."""
    scenario_id: str
    consensus_score: float
    passed: bool
    ija: float
    tiebreaker_used: bool
    tier: int
    scores: dict[str, float]
    agent_output: str
    duration_ms: int


@workflow.defn
class EvalRunWorkflow:
    """
    Top-level workflow that orchestrates a complete eval run.

    Executes all scenarios in parallel via child workflows,
    aggregates results, runs statistical analysis, and reports.
    """

    @workflow.run
    async def run(self, input: EvalRunInput) -> EvalRunOutput:
        import time
        start = time.monotonic()

        # 1. Update status to running
        await workflow.execute_activity(
            "update_eval_run_status",
            args=[input.run_id, "running"],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=DEFAULT_RETRY,
        )

        # 2. Create GitHub Check Run (if PR)
        if input.pr_number:
            await workflow.execute_activity(
                "create_github_check_run",
                args=[input.repo_full_name, input.commit_sha, input.run_id],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=DEFAULT_RETRY,
            )

        # 3. Load scenarios
        scenario_jsons: list[str] = await workflow.execute_activity(
            "load_scenarios",
            args=[input.scenarios_path],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        judge_models = input.judge_models or ["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.5-pro"]

        # 4. Execute all scenarios in parallel via child workflows
        child_tasks = []
        for scenario_json in scenario_jsons:
            child_input = ScenarioEvalInput(
                run_id=input.run_id,
                scenario_json=scenario_json,
                agent_entry=input.agent_entry,
                agent_function=input.agent_function,
                judge_models=judge_models,
            )
            child_tasks.append(
                workflow.execute_child_workflow(
                    ScenarioEvalWorkflow,
                    child_input,
                    id=f"{input.run_id}-scenario-{len(child_tasks)}",
                )
            )

        results: list[ScenarioEvalOutput] = await asyncio.gather(
            *child_tasks, return_exceptions=True
        )

        # Filter out failures
        valid_results = [r for r in results if isinstance(r, ScenarioEvalOutput)]
        failed_count = len(results) - len(valid_results)

        # 5. Aggregate scores and run statistical analysis
        agg: dict = await workflow.execute_activity(
            "aggregate_and_analyze",
            args=[input.run_id, input.repo_full_name, input.eval_suite, valid_results],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        # 6. Store results in DB
        await workflow.execute_activity(
            "store_results",
            args=[input.run_id, valid_results],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        # 7. Report to GitHub
        if input.pr_number:
            await workflow.execute_activity(
                "report_to_github",
                args=[input.run_id, input.repo_full_name, input.pr_number, input.commit_sha],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=DEFAULT_RETRY,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 8. Update final status
        overall_passed = agg.get("overall_passed", False)
        final_score = agg.get("final_score", 0.0)
        status = "completed"

        await workflow.execute_activity(
            "update_eval_run_status",
            args=[input.run_id, status],
            kwargs={
                "final_score": final_score,
                "overall_passed": overall_passed,
                "scenarios_total": len(valid_results) + failed_count,
                "scenarios_passed": agg.get("scenarios_passed", 0),
                "duration_ms": elapsed_ms,
                "p_value": agg.get("p_value"),
                "cohens_d": agg.get("cohens_d"),
                "severity": agg.get("severity"),
            },
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=DEFAULT_RETRY,
        )

        return EvalRunOutput(
            run_id=input.run_id,
            overall_passed=overall_passed,
            final_score=final_score,
            baseline_score=agg.get("baseline_score"),
            p_value=agg.get("p_value"),
            severity=agg.get("severity"),
            scenarios_total=len(valid_results) + failed_count,
            scenarios_passed=agg.get("scenarios_passed", 0),
            duration_ms=elapsed_ms,
        )


@workflow.defn
class ScenarioEvalWorkflow:
    """
    Child workflow for evaluating a single scenario.

    Runs agent → judge panel → returns structured result.
    Each scenario is isolated in its own workflow for fault tolerance.
    """

    @workflow.run
    async def run(self, input: ScenarioEvalInput) -> ScenarioEvalOutput:
        # 1. Execute agent against scenario
        agent_result: dict = await workflow.execute_activity(
            "run_agent_on_scenario",
            args=[input.scenario_json, input.agent_entry, input.agent_function],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY,
        )

        # 2. Run judge panel
        judge_result: dict = await workflow.execute_activity(
            "run_judge_panel",
            args=[input.scenario_json, agent_result["output"], input.judge_models],
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=DEFAULT_RETRY,
        )

        # 3. Publish progress
        await workflow.execute_activity(
            "publish_scenario_progress",
            args=[input.run_id, judge_result["scenario_id"], judge_result["consensus_score"]],
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=DEFAULT_RETRY,
        )

        return ScenarioEvalOutput(
            scenario_id=judge_result["scenario_id"],
            consensus_score=judge_result["consensus_score"],
            passed=judge_result["passed"],
            ija=judge_result.get("ija", 1.0),
            tiebreaker_used=judge_result.get("tiebreaker_used", False),
            tier=judge_result.get("tier", 2),
            scores=judge_result.get("scores", {}),
            agent_output=agent_result["output"][:500],
            duration_ms=agent_result.get("duration_ms", 0),
        )
