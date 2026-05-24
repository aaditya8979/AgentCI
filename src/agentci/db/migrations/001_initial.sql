-- AgentCI Database Schema
-- Migration 001: Initial schema
-- PostgreSQL 16+

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- EVAL RUNS: one per PR webhook event that triggers evaluation
-- ============================================================================
CREATE TABLE eval_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_full_name  TEXT NOT NULL,
    pr_number       INTEGER,
    commit_sha      TEXT NOT NULL,
    eval_suite      TEXT NOT NULL DEFAULT 'full',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','cancelled')),
    triggered_by    TEXT NOT NULL DEFAULT 'webhook'
                    CHECK (triggered_by IN ('webhook','cli','api')),
    github_check_run_id TEXT,
    github_comment_id   TEXT,
    baseline_score  FLOAT,
    final_score     FLOAT,
    p_value         FLOAT,
    cohens_d        FLOAT,
    severity        TEXT CHECK (severity IN ('negligible','small','medium','large')),
    overall_passed  BOOLEAN,
    scenarios_total INTEGER DEFAULT 0,
    scenarios_passed INTEGER DEFAULT 0,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'
);

-- ============================================================================
-- SCENARIO RESULTS: one per scenario per eval run
-- ============================================================================
CREATE TABLE scenario_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id     UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    scenario_id     TEXT NOT NULL,
    category        TEXT,
    difficulty      TEXT,
    agent_output    TEXT,
    agent_error     TEXT,
    judge_responses JSONB NOT NULL DEFAULT '[]',
    judge_scores    JSONB NOT NULL DEFAULT '{}',
    consensus_score FLOAT,
    ija             FLOAT,
    tiebreaker_used BOOLEAN DEFAULT FALSE,
    regression      JSONB,
    trace_data      JSONB,
    passed          BOOLEAN,
    tier            INTEGER DEFAULT 2,
    duration_ms     INTEGER,
    cost_usd        FLOAT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- BASELINES: rolling statistics per repo per scenario
-- ============================================================================
CREATE TABLE baselines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_full_name  TEXT NOT NULL,
    eval_suite      TEXT NOT NULL DEFAULT 'full',
    scenario_id     TEXT NOT NULL,
    scores          FLOAT[] NOT NULL DEFAULT '{}',
    rolling_mean    FLOAT,
    rolling_stddev  FLOAT,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(repo_full_name, eval_suite, scenario_id)
);

-- ============================================================================
-- AUDIT LOG: immutable append-only event stream
-- ============================================================================
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    repo_full_name  TEXT,
    eval_run_id     UUID REFERENCES eval_runs(id),
    actor           TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce immutability
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- ============================================================================
-- INDEXES
-- ============================================================================
CREATE INDEX idx_eval_runs_repo ON eval_runs(repo_full_name, created_at DESC);
CREATE INDEX idx_eval_runs_pr ON eval_runs(repo_full_name, pr_number);
CREATE INDEX idx_scenario_results_run ON scenario_results(eval_run_id);
CREATE INDEX idx_scenario_results_scenario ON scenario_results(scenario_id);
CREATE INDEX idx_baselines_lookup ON baselines(repo_full_name, eval_suite, scenario_id);
CREATE INDEX idx_audit_log_run ON audit_log(eval_run_id);
CREATE INDEX idx_audit_log_repo ON audit_log(repo_full_name, created_at DESC);
