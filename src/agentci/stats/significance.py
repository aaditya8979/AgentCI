"""
Statistical significance testing for AgentCI regression detection.

Implements Welch's t-test for determining whether score changes between
baseline and current runs are statistically significant, plus Cohen's d
for effect-size classification.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy import stats


class Severity(str, Enum):
    """Regression severity based on Cohen's d effect size."""
    NEGLIGIBLE = "negligible"  # d < 0.2
    SMALL = "small"            # 0.2 <= d < 0.5
    MEDIUM = "medium"          # 0.5 <= d < 0.8
    LARGE = "large"            # d >= 0.8


@dataclass(frozen=True)
class RegressionResult:
    """Complete result of a regression analysis between baseline and current scores."""
    is_regression: bool
    p_value: float
    effect_size: float
    severity: Severity
    baseline_mean: float
    baseline_std: float
    current_mean: float
    current_std: float
    delta: float

    @property
    def summary(self) -> str:
        direction = "▼" if self.delta < 0 else "▲"
        status = "REGRESSION" if self.is_regression else "OK"
        return (
            f"[{status}] {direction} Δ={self.delta:+.4f} "
            f"(p={self.p_value:.4f}, d={self.effect_size:.3f}, "
            f"severity={self.severity.value})"
        )


def cohens_d(baseline: list[float], current: list[float]) -> float:
    """
    Compute Cohen's d effect size between two independent samples.

    Uses pooled standard deviation. Positive values indicate that
    baseline > current (i.e., a regression).
    """
    b = np.asarray(baseline, dtype=np.float64)
    c = np.asarray(current, dtype=np.float64)

    n_b, n_c = len(b), len(c)
    if n_b < 2 or n_c < 2:
        return 0.0

    var_b = np.var(b, ddof=1)
    var_c = np.var(c, ddof=1)

    pooled_var = ((n_b - 1) * var_b + (n_c - 1) * var_c) / (n_b + n_c - 2)
    pooled_std = np.sqrt(pooled_var)

    if pooled_std == 0:
        return 0.0

    return float((np.mean(b) - np.mean(c)) / pooled_std)


def _classify_severity(d: float) -> Severity:
    """Classify Cohen's d into a severity tier."""
    d_abs = abs(d)
    if d_abs < 0.2:
        return Severity.NEGLIGIBLE
    elif d_abs < 0.5:
        return Severity.SMALL
    elif d_abs < 0.8:
        return Severity.MEDIUM
    else:
        return Severity.LARGE


def is_regression(
    baseline_scores: list[float],
    current_scores: list[float],
    significance: float = 0.05,
) -> RegressionResult:
    """
    Determine whether current scores represent a statistically significant
    regression from baseline scores.

    Uses a one-sided Welch's t-test (tests if baseline > current, i.e.,
    quality dropped). Welch's variant does not assume equal variances
    between the two groups.

    Args:
        baseline_scores: Historical scores from previous runs.
        current_scores: Scores from the current evaluation run.
        significance: Alpha level for statistical significance (default 0.05).

    Returns:
        RegressionResult with full statistical breakdown.
    """
    b = np.asarray(baseline_scores, dtype=np.float64)
    c = np.asarray(current_scores, dtype=np.float64)

    b_mean, b_std = float(np.mean(b)), float(np.std(b, ddof=1))
    c_mean, c_std = float(np.mean(c)), float(np.std(c, ddof=1))
    delta = c_mean - b_mean

    # One-sided Welch's t-test: H_a is baseline > current (regression)
    t_stat, two_sided_p = stats.ttest_ind(b, c, equal_var=False)

    # Convert to one-sided p-value (we only care if current < baseline)
    if t_stat > 0:
        p_value = float(two_sided_p / 2)
    else:
        p_value = float(1.0 - two_sided_p / 2)

    d = cohens_d(baseline_scores, current_scores)
    severity = _classify_severity(d)

    return RegressionResult(
        is_regression=p_value < significance and d > 0,
        p_value=p_value,
        effect_size=d,
        severity=severity,
        baseline_mean=b_mean,
        baseline_std=b_std,
        current_mean=c_mean,
        current_std=c_std,
        delta=delta,
    )
