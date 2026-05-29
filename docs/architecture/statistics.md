# Statistical Analysis

AgentCI uses rigorous statistical methods to determine if a code change caused a real regression — not just random noise.

## Regression Detection

### Welch's t-test

AgentCI uses **Welch's t-test** (not Student's t-test) because:

- It does **not** assume equal variances between baseline and current samples
- Eval scores from different runs are independent (not paired)
- It's more conservative, reducing false positives

A regression is flagged when:
- **p-value < 0.05** (statistically significant difference)
- **Current scores < baseline scores** (direction matters)

### Cohen's d Effect Size

Statistical significance alone isn't enough. A tiny score drop can be "significant" with enough samples. AgentCI also computes **Cohen's d** to measure practical significance:

| Cohen's d | Interpretation | Action |
|-----------|---------------|--------|
| < 0.2 | Negligible | No action |
| 0.2–0.5 | Small | Warning |
| 0.5–0.8 | Medium | Review recommended |
| > 0.8 | Large | Likely regression |

### Combined Decision

```python
is_regression = (p_value < 0.05) and (cohens_d > 0.5) and (current_mean < baseline_mean)
```

Both statistical significance AND practical significance must be present.

## Baseline Management

Baselines are maintained per-scenario, per-repository:

- **Rolling window** — Last N scores (configurable, default 10)
- **Automatic updates** — Every passing eval adds to the baseline
- **Per-criterion tracking** — Not just overall score, but each rubric dimension

### Minimum Samples

Statistical tests require sufficient data. AgentCI enforces a minimum of 3 baseline samples before activating regression detection. Before that threshold, only the absolute score is checked against `min_score`.

## Severity Classification

When a regression is detected, AgentCI classifies its severity:

| Severity | Criteria | Example |
|----------|----------|---------|
| **Critical** | Cohen's d > 1.5, p < 0.01 | Safety score dropped from 0.95 to 0.30 |
| **Major** | Cohen's d > 0.8, p < 0.05 | Accuracy dropped from 0.90 to 0.65 |
| **Minor** | Cohen's d > 0.5, p < 0.05 | Tone score dropped from 0.88 to 0.78 |
| **None** | Not significant | Normal variance |
