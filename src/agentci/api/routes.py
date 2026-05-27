"""
REST API routes for the AgentCI dashboard.

Provides endpoints for eval runs, scenario results, and trend data.
All queries go through the typed query layer in db/queries.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter()


def _pool(request: Request):
    """Get the DB pool from the module-level singleton."""
    from ..db.connection import get_pool
    try:
        return get_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")


# ── Eval Runs ────────────────────────────────────────────────────────────


@router.get("/runs")
async def list_runs(
    request: Request,
    repo: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List eval runs, optionally filtered by repository."""
    from ..db import queries

    pool = _pool(request)
    rows = await queries.list_eval_runs(pool, repo_full_name=repo, limit=limit, offset=offset)

    runs = []
    for r in rows:
        runs.append({
            "id": str(r["id"]),
            "repo": r["repo_full_name"],
            "pr": r.get("pr_number"),
            "commit": r["commit_sha"][:7],
            "commit_full": r["commit_sha"],
            "suite": r["eval_suite"],
            "status": r["status"],
            "score": r.get("final_score"),
            "baseline": r.get("baseline_score"),
            "delta": (
                round(r["final_score"] - r["baseline_score"], 4)
                if r.get("final_score") is not None and r.get("baseline_score") is not None
                else None
            ),
            "passed": r.get("overall_passed"),
            "severity": r.get("severity"),
            "p_value": r.get("p_value"),
            "scenarios_total": r.get("scenarios_total", 0),
            "scenarios_passed": r.get("scenarios_passed", 0),
            "duration_ms": r.get("duration_ms"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
        })

    return {"runs": runs, "total": len(runs), "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> dict[str, Any]:
    """Get full detail for a single eval run including all scenario results."""
    from ..db import queries

    pool = _pool(request)
    run = await queries.get_eval_run(pool, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    scenario_rows = await queries.get_scenario_results(pool, run_id)
    scenarios = []
    for s in scenario_rows:
        scenarios.append({
            "id": str(s["id"]),
            "scenario_id": s["scenario_id"],
            "category": s.get("category"),
            "difficulty": s.get("difficulty"),
            "consensus_score": s.get("consensus_score"),
            "passed": s.get("passed"),
            "ija": s.get("ija"),
            "tiebreaker_used": s.get("tiebreaker_used", False),
            "tier": s.get("tier"),
            "duration_ms": s.get("duration_ms"),
            "cost_usd": s.get("cost_usd"),
            "agent_output": s.get("agent_output", "")[:500],
            "agent_error": s.get("agent_error"),
            "judge_scores": s.get("judge_scores"),
        })

    return {
        "id": str(run["id"]),
        "repo": run["repo_full_name"],
        "pr": run.get("pr_number"),
        "commit": run["commit_sha"],
        "suite": run["eval_suite"],
        "status": run["status"],
        "score": run.get("final_score"),
        "baseline": run.get("baseline_score"),
        "p_value": run.get("p_value"),
        "cohens_d": run.get("cohens_d"),
        "severity": run.get("severity"),
        "passed": run.get("overall_passed"),
        "scenarios_total": run.get("scenarios_total", 0),
        "scenarios_passed": run.get("scenarios_passed", 0),
        "duration_ms": run.get("duration_ms"),
        "created_at": run["created_at"].isoformat() if run.get("created_at") else None,
        "completed_at": run["completed_at"].isoformat() if run.get("completed_at") else None,
        "scenarios": scenarios,
    }


@router.get("/runs/{run_id}/scenarios/{scenario_id}")
async def get_scenario_detail(
    request: Request, run_id: str, scenario_id: str,
) -> dict[str, Any]:
    """Get full scenario result including trace data and judge reasoning."""
    from ..db import queries

    pool = _pool(request)
    rows = await queries.get_scenario_results(pool, run_id)

    for s in rows:
        if s["scenario_id"] == scenario_id:
            return {
                "id": str(s["id"]),
                "scenario_id": s["scenario_id"],
                "category": s.get("category"),
                "difficulty": s.get("difficulty"),
                "consensus_score": s.get("consensus_score"),
                "passed": s.get("passed"),
                "ija": s.get("ija"),
                "tiebreaker_used": s.get("tiebreaker_used", False),
                "tier": s.get("tier"),
                "duration_ms": s.get("duration_ms"),
                "cost_usd": s.get("cost_usd"),
                "agent_output": s.get("agent_output"),
                "agent_error": s.get("agent_error"),
                "judge_scores": s.get("judge_scores"),
                "judge_responses": s.get("judge_responses"),
                "trace_data": s.get("trace_data"),
                "regression": s.get("regression"),
            }

    raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found in run {run_id}")


@router.get("/trends")
async def get_trends(
    request: Request,
    repo: str | None = None,
    suite: str = "full",
    limit: int = Query(default=30, le=100),
) -> dict[str, Any]:
    """
    Get rolling score data per scenario for trend charts.

    Returns the most recent N eval runs and their per-scenario scores,
    suitable for time-series visualisation.
    """
    from ..db import queries

    pool = _pool(request)
    runs = await queries.list_eval_runs(pool, repo_full_name=repo, limit=limit)

    trend_data: list[dict] = []
    for run in runs:
        if run["status"] != "completed" or run.get("final_score") is None:
            continue
        trend_data.append({
            "run_id": str(run["id"]),
            "score": run["final_score"],
            "baseline": run.get("baseline_score"),
            "severity": run.get("severity"),
            "passed": run.get("overall_passed"),
            "scenarios_total": run.get("scenarios_total", 0),
            "scenarios_passed": run.get("scenarios_passed", 0),
            "created_at": run["created_at"].isoformat() if run.get("created_at") else None,
            "commit": run["commit_sha"][:7],
            "pr": run.get("pr_number"),
        })

    return {"trends": trend_data, "repo": repo, "suite": suite}


@router.get("/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    """Aggregate statistics across all repos."""
    from ..db import queries

    pool = _pool(request)
    runs = await queries.list_eval_runs(pool, limit=200)

    total = len(runs)
    completed = [r for r in runs if r["status"] == "completed"]
    passed = [r for r in completed if r.get("overall_passed")]
    scores = [r["final_score"] for r in completed if r.get("final_score") is not None]
    regressions = [r for r in completed if r.get("severity") and r["severity"] != "negligible"]

    repos = set(r["repo_full_name"] for r in runs)

    return {
        "total_runs": total,
        "completed_runs": len(completed),
        "pass_rate": round(len(passed) / len(completed), 3) if completed else 0,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
        "regressions": len(regressions),
        "repos": len(repos),
    }
