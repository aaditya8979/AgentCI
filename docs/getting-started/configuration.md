# Configuration

AgentCI is configured via a `.agentci.yml` file in your repository root.

## Full Configuration Reference

```yaml
# .agentci.yml
version: "1"

# ── Agent ────────────────────────────────────────────
agent_entry: src/agent.py       # Path to agent module
agent_function: run              # Function name to call
scenarios_path: eval/scenarios   # Directory or single JSON file

# ── Execution ────────────────────────────────────────
num_runs: 3                      # Runs per scenario (for stability)
parallel: true                   # Run scenarios concurrently
max_workers: 4                   # Max parallel scenarios

# ── Judge Panel ──────────────────────────────────────
judges:
  models:                        # One from each LLM family
    - gpt-4o                     # OpenAI
    - claude-sonnet-4-20250514   # Anthropic
    - gemini-2.5-pro             # Google
  temperature: 0.1               # Low temp for consistency
  ija_threshold: 0.7             # Inter-Judge Agreement threshold
  tiebreaker_model: gpt-4o       # Used when IJA < threshold

# ── Baselines ────────────────────────────────────────
baselines:
  min_score: 0.85                # Minimum acceptable score
  comparison: last_5_runs        # Compare against recent runs
  statistical_test: welch_t_test # Regression detection method
  significance_level: 0.05       # p-value threshold
  min_samples: 3                 # Min baseline runs before testing

# ── Triggers ─────────────────────────────────────────
triggers:
  paths:                         # Glob patterns that trigger eval
    - "**/*.py"
    - ".agentci.yml"
  eval_suite: full               # Which suite to run
```

## Scenario Schema

Each scenario in your JSON file follows this schema:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario_id` | string | ✅ | Unique identifier |
| `description` | string | ✅ | What this scenario tests |
| `category` | string | ❌ | Grouping (accuracy, safety, compliance) |
| `difficulty` | string | ❌ | easy / medium / hard |
| `conversation` | array | ✅ | List of `{role, content}` messages |
| `rubric.criteria` | array | ✅ | Grading criteria with weights |
| `rubric.passing_threshold` | float | ❌ | Override default threshold (0.85) |
| `context` | object | ❌ | Additional context for judges |

## Rubric Criteria

Each criterion has:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Criterion identifier (e.g., "accuracy") |
| `description` | string | What the judge should evaluate |
| `weight` | float | Relative weight (all weights are normalized) |

## Environment Variables

See [Environment Variables Reference](../self-hosting/environment.md) for all configuration options.
