"""
Temporal activity implementations.

Each activity is a single side-effecting operation: DB write, API call,
agent execution, or judge invocation. Activities are retried independently.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn
async def update_eval_run_status(
    run_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    """Update an eval run's status in the database."""
    from ..db.connection import get_pool
    from ..db import queries

    pool = await get_pool()
    await queries.update_eval_run_status(pool, run_id, status, **kwargs)
    logger.info("Updated run %s → %s", run_id, status)


@activity.defn
async def create_github_check_run(
    repo: str,
    sha: str,
    run_id: str,
) -> str:
    """Create a GitHub Check Run and store its ID."""
    from ..reporter.github import GitHubClient
    from ..db.connection import get_pool
    from ..db import queries

    gh = GitHubClient()
    try:
        check_run_id = await gh.create_check_run(repo, sha, f"AgentCI Eval ({run_id[:8]})")
        pool = await get_pool()
        await queries.update_eval_run_status(
            pool, run_id, "running", github_check_run_id=check_run_id,
        )
        return check_run_id
    finally:
        await gh.close()


@activity.defn
async def load_scenarios(scenarios_path: str) -> list[str]:
    """Load scenario JSON files from a path. Returns list of JSON strings."""
    from pathlib import Path
    from ..models.scenario import Scenario

    p = Path(scenarios_path)
    results: list[str] = []

    if p.is_file():
        with p.open() as f:
            data = json.load(f)
        items = data if isinstance(data, list) else [data]
        for item in items:
            Scenario(**item)  # validate
            results.append(json.dumps(item))
    elif p.is_dir():
        for json_file in sorted(p.glob("*.json")):
            with json_file.open() as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for item in items:
                Scenario(**item)
                results.append(json.dumps(item))

    logger.info("Loaded %d scenarios from %s", len(results), scenarios_path)
    return results


@activity.defn
async def run_agent_on_scenario(
    scenario_json: str,
    agent_entry: str,
    agent_function: str,
) -> dict[str, Any]:
    """Execute the agent against a single scenario."""
    from ..models.scenario import Scenario
    from ..runner.agent_runner import AgentRunner

    scenario = Scenario(**json.loads(scenario_json))
    runner = AgentRunner(agent_path=agent_entry, agent_function=agent_function)
    runner.load()

    start = time.perf_counter()
    output, trace = runner.run_scenario(scenario)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "scenario_id": scenario.scenario_id,
        "output": output,
        "trace": trace.model_dump() if hasattr(trace, "model_dump") else {},
        "duration_ms": elapsed_ms,
    }


@activity.defn
async def run_judge_panel(
    scenario_json: str,
    agent_output: str,
    judge_models: list[str],
) -> dict[str, Any]:
    """Run the async judge panel on an agent's output."""
    from ..models.scenario import Scenario
    from ..judge.async_consensus import AsyncConsensusPanel

    scenario = Scenario(**json.loads(scenario_json))
    panel = AsyncConsensusPanel(models=judge_models)

    try:
        conv_text = "\n".join(
            f"[{m.role.upper()}]: {m.content}" for m in scenario.conversation
        )
        rubric_dicts = [
            {"name": c.name, "description": c.description, "weight": c.weight}
            for c in scenario.rubric.criteria
        ]
        context_str = json.dumps(scenario.context) if scenario.context else None

        result = await panel.evaluate(
            scenario_description=scenario.description,
            conversation_history=conv_text,
            agent_output=agent_output,
            rubric_criteria=rubric_dicts,
            context=context_str,
        )

        threshold = scenario.rubric.passing_threshold or 0.85
        return {
            "scenario_id": scenario.scenario_id,
            "consensus_score": result.weighted_score,
            "passed": result.weighted_score >= threshold,
            "ija": result.inter_judge_agreement,
            "tiebreaker_used": result.tiebreaker_used,
            "tier": result.tier,
            "scores": result.consensus_scores,
        }
    finally:
        await panel.close()


@activity.defn
async def aggregate_and_analyze(
    run_id: str,
    repo_full_name: str,
    eval_suite: str,
    results: list[Any],
) -> dict[str, Any]:
    """Aggregate scenario results and run statistical analysis."""
    from ..stats.significance import is_regression as check_regression
    from ..db.connection import get_pool
    from ..db import queries

    if not results:
        return {"overall_passed": False, "final_score": 0.0, "scenarios_passed": 0}

    scores = [r.consensus_score for r in results]
    passed = [r for r in results if r.passed]
    final_score = sum(scores) / len(scores)

    # Compare against baseline
    pool = await get_pool()
    baseline_scores = await queries.get_baseline_scores(
        pool, repo_full_name, results[0].scenario_id, eval_suite,
    )

    analysis: dict[str, Any] = {
        "overall_passed": len(passed) == len(results),
        "final_score": final_score,
        "scenarios_passed": len(passed),
    }

    if len(baseline_scores) >= 3:
        reg = check_regression(baseline_scores, scores)
        analysis["p_value"] = reg.p_value
        analysis["cohens_d"] = reg.effect_size
        analysis["severity"] = reg.severity.value if reg.is_regression else None
        analysis["baseline_score"] = reg.baseline_mean

    # Store new scores as baselines
    for r in results:
        await queries.upsert_baseline_score(
            pool, repo_full_name, r.scenario_id, r.consensus_score, eval_suite,
        )

    return analysis


@activity.defn
async def store_results(run_id: str, results: list[Any]) -> None:
    """Store all scenario results in the database."""
    from ..db.connection import get_pool
    from ..db import queries

    pool = await get_pool()
    for r in results:
        await queries.insert_scenario_result(
            pool,
            eval_run_id=run_id,
            scenario_id=r.scenario_id,
            consensus_score=r.consensus_score,
            passed=r.passed,
            agent_output=r.agent_output,
            judge_scores=r.scores,
            ija=r.ija,
            tiebreaker_used=r.tiebreaker_used,
            tier=r.tier,
            duration_ms=r.duration_ms,
        )

    # Write audit log
    await queries.write_audit_log(
        pool,
        event_type="eval_run_completed",
        payload={
            "run_id": run_id,
            "scenarios": len(results),
            "passed": sum(1 for r in results if r.passed),
        },
        eval_run_id=run_id,
    )


@activity.defn
async def report_to_github(
    run_id: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
) -> None:
    """Post eval results to GitHub as a Check Run and PR comment."""
    from ..db.connection import get_pool
    from ..db import queries
    from ..reporter.github import GitHubClient
    from ..reporter.markdown import MarkdownReporter
    from ..models.scenario import ScenarioResult

    pool = await get_pool()
    run = await queries.get_eval_run(pool, run_id)
    if not run:
        logger.error("Run %s not found for GitHub reporting", run_id)
        return

    scenario_rows = await queries.get_scenario_results(pool, run_id)

    # Build ScenarioResult objects for the reporter
    results = []
    for row in scenario_rows:
        results.append(ScenarioResult(
            scenario_id=row["scenario_id"],
            scores=row["judge_scores"] or {},
            weighted_score=row["consensus_score"] or 0.0,
            passed=row["passed"] or False,
        ))

    md = MarkdownReporter.generate_report(
        results=results,
        commit_sha=commit_sha,
        duration_seconds=(run.get("duration_ms") or 0) / 1000,
    )

    gh = GitHubClient()
    try:
        # Update check run
        check_id = run.get("github_check_run_id")
        if check_id:
            conclusion = "success" if run.get("overall_passed") else "failure"
            await gh.update_check_run(
                repo, check_id,
                status="completed",
                conclusion=conclusion,
                title=f"AgentCI: {'Passed' if run.get('overall_passed') else 'Failed'}",
                summary=md[:65000],
            )

        # Upsert PR comment (delete old one first to avoid spam)
        comment_id = await gh.upsert_pr_comment(repo, pr_number, md)
        await queries.update_eval_run_status(
            pool, run_id, "completed", github_comment_id=comment_id,
        )
    finally:
        await gh.close()


@activity.defn
async def publish_scenario_progress(
    run_id: str,
    scenario_id: str,
    score: float,
) -> None:
    """Publish scenario completion event to Redis for live dashboard."""
    try:
        from ..cache.redis_client import publish_progress
        await publish_progress(run_id, {
            "event": "scenario_completed",
            "scenario_id": scenario_id,
            "score": score,
        })
    except Exception as e:
        # Non-critical — don't fail the workflow if Redis is down
        logger.warning("Failed to publish progress for %s: %s", run_id, e)
