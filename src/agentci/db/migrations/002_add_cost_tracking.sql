-- 002_add_cost_tracking.sql
-- Adds cost tracking columns to eval_runs and scenario_results.

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS total_cost_usd FLOAT DEFAULT 0.0;
ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS cost_usd FLOAT DEFAULT 0.0;
