"""
Typed database queries for AgentCI.

Every SQL query in the system lives here. No raw SQL outside this file.
All functions take a pool parameter for testability.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


# ── Eval Runs ────────────────────────────────────────────────────────────────

async def create_eval_run(
    pool: asyncpg.Pool,
    repo_full_name: str,
    commit_sha: str,
    pr_number: int | None = None,
    eval_suite: str = "full",
    triggered_by: str = "webhook",
    metadata: dict | None = None,
) -> str:
    """Insert a new eval run and return its UUID."""
    row = await pool.fetchrow(
        """
        INSERT INTO eval_runs (repo_full_name, commit_sha, pr_number, eval_suite, triggered_by, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        RETURNING id
        """,
        repo_full_name, commit_sha, pr_number, eval_suite, triggered_by,
        _to_json(metadata or {}),
    )
    run_id = str(row["id"])
    logger.info("Created eval run %s for %s@%s", run_id, repo_full_name, commit_sha[:7])
    return run_id


async def update_eval_run_status(
    pool: asyncpg.Pool,
    run_id: str,
    status: str,
    final_score: float | None = None,
    baseline_score: float | None = None,
    p_value: float | None = None,
    cohens_d: float | None = None,
    severity: str | None = None,
    overall_passed: bool | None = None,
    scenarios_total: int | None = None,
    scenarios_passed: int | None = None,
    duration_ms: int | None = None,
    github_check_run_id: str | None = None,
    github_comment_id: str | None = None,
) -> None:
    """Update an eval run's status and results."""
    completed_at = datetime.now(timezone.utc) if status in ("completed", "failed") else None
    await pool.execute(
        """
        UPDATE eval_runs SET
            status = $2,
            final_score = COALESCE($3, final_score),
            baseline_score = COALESCE($4, baseline_score),
            p_value = COALESCE($5, p_value),
            cohens_d = COALESCE($6, cohens_d),
            severity = COALESCE($7, severity),
            overall_passed = COALESCE($8, overall_passed),
            scenarios_total = COALESCE($9, scenarios_total),
            scenarios_passed = COALESCE($10, scenarios_passed),
            duration_ms = COALESCE($11, duration_ms),
            github_check_run_id = COALESCE($12, github_check_run_id),
            github_comment_id = COALESCE($13, github_comment_id),
            completed_at = COALESCE($14, completed_at)
        WHERE id = $1::uuid
        """,
        run_id, status, final_score, baseline_score, p_value, cohens_d,
        severity, overall_passed, scenarios_total, scenarios_passed,
        duration_ms, github_check_run_id, github_comment_id, completed_at,
    )


async def get_eval_run(pool: asyncpg.Pool, run_id: str) -> dict | None:
    """Fetch a single eval run by ID."""
    row = await pool.fetchrow("SELECT * FROM eval_runs WHERE id = $1::uuid", run_id)
    return dict(row) if row else None


async def list_eval_runs(
    pool: asyncpg.Pool,
    repo_full_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List eval runs, optionally filtered by repo."""
    if repo_full_name:
        rows = await pool.fetch(
            "SELECT * FROM eval_runs WHERE repo_full_name = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            repo_full_name, limit, offset,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
    return [dict(r) for r in rows]


# ── Scenario Results ─────────────────────────────────────────────────────────

async def insert_scenario_result(
    pool: asyncpg.Pool,
    eval_run_id: str,
    scenario_id: str,
    consensus_score: float,
    passed: bool,
    category: str | None = None,
    difficulty: str | None = None,
    agent_output: str | None = None,
    agent_error: str | None = None,
    judge_responses: list | None = None,
    judge_scores: dict | None = None,
    ija: float | None = None,
    tiebreaker_used: bool = False,
    regression: dict | None = None,
    trace_data: dict | None = None,
    tier: int = 2,
    duration_ms: int | None = None,
    cost_usd: float | None = None,
) -> str:
    """Insert a scenario result and return its UUID."""
    row = await pool.fetchrow(
        """
        INSERT INTO scenario_results (
            eval_run_id, scenario_id, category, difficulty,
            agent_output, agent_error, judge_responses, judge_scores,
            consensus_score, ija, tiebreaker_used, regression,
            trace_data, passed, tier, duration_ms, cost_usd
        ) VALUES (
            $1::uuid, $2, $3, $4, $5, $6,
            $7::jsonb, $8::jsonb, $9, $10, $11,
            $12::jsonb, $13::jsonb, $14, $15, $16, $17
        ) RETURNING id
        """,
        eval_run_id, scenario_id, category, difficulty,
        agent_output, agent_error,
        _to_json(judge_responses or []),
        _to_json(judge_scores or {}),
        consensus_score, ija, tiebreaker_used,
        _to_json(regression) if regression else None,
        _to_json(trace_data) if trace_data else None,
        passed, tier, duration_ms, cost_usd,
    )
    return str(row["id"])


async def get_scenario_results(pool: asyncpg.Pool, eval_run_id: str) -> list[dict]:
    """Fetch all scenario results for an eval run."""
    rows = await pool.fetch(
        "SELECT * FROM scenario_results WHERE eval_run_id = $1::uuid ORDER BY created_at",
        eval_run_id,
    )
    return [dict(r) for r in rows]


# ── Baselines ────────────────────────────────────────────────────────────────

async def upsert_baseline_score(
    pool: asyncpg.Pool,
    repo_full_name: str,
    scenario_id: str,
    score: float,
    eval_suite: str = "full",
    max_scores: int = 100,
) -> None:
    """Append a score to a scenario's baseline, creating if needed."""
    await pool.execute(
        """
        INSERT INTO baselines (repo_full_name, eval_suite, scenario_id, scores, rolling_mean, rolling_stddev, sample_count)
        VALUES ($1, $2, $3, ARRAY[$4::float], $4, 0, 1)
        ON CONFLICT (repo_full_name, eval_suite, scenario_id) DO UPDATE SET
            scores = (
                CASE WHEN array_length(baselines.scores, 1) >= $5
                THEN baselines.scores[2:] || ARRAY[$4::float]
                ELSE baselines.scores || ARRAY[$4::float]
                END
            ),
            sample_count = LEAST(baselines.sample_count + 1, $5),
            last_updated = NOW()
        """,
        repo_full_name, eval_suite, scenario_id, score, max_scores,
    )
    # Update rolling stats
    await pool.execute(
        """
        UPDATE baselines SET
            rolling_mean = (SELECT AVG(s) FROM UNNEST(scores) s),
            rolling_stddev = (SELECT COALESCE(STDDEV(s), 0) FROM UNNEST(scores) s)
        WHERE repo_full_name = $1 AND eval_suite = $2 AND scenario_id = $3
        """,
        repo_full_name, eval_suite, scenario_id,
    )


async def get_baseline_scores(
    pool: asyncpg.Pool,
    repo_full_name: str,
    scenario_id: str,
    eval_suite: str = "full",
    window: int = 10,
) -> list[float]:
    """Get the most recent N baseline scores for a scenario."""
    row = await pool.fetchrow(
        "SELECT scores FROM baselines WHERE repo_full_name = $1 AND eval_suite = $2 AND scenario_id = $3",
        repo_full_name, eval_suite, scenario_id,
    )
    if not row or not row["scores"]:
        return []
    return list(row["scores"][-window:])


# ── Audit Log ────────────────────────────────────────────────────────────────

async def write_audit_log(
    pool: asyncpg.Pool,
    event_type: str,
    payload: dict,
    repo_full_name: str | None = None,
    eval_run_id: str | None = None,
    actor: str | None = None,
) -> None:
    """Write an immutable audit log entry."""
    await pool.execute(
        """
        INSERT INTO audit_log (event_type, repo_full_name, eval_run_id, actor, payload)
        VALUES ($1, $2, $3::uuid, $4, $5::jsonb)
        """,
        event_type, repo_full_name, eval_run_id, actor, _to_json(payload),
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_json(obj: Any) -> str:
    """Serialize to JSON string for asyncpg JSONB parameters."""
    import json
    return json.dumps(obj, default=str)
