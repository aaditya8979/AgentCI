"""
Judge calibration and bias measurement.

Compares judge model scores against a human-labeled golden set
to compute reliability metrics, detect systematic bias, and
generate correction coefficients.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GoldenEntry:
    """A single golden-set labeled example."""
    scenario_id: str
    agent_output_hash: str
    human_scores: dict[str, float]  # criterion → score
    reviewer: str = ""
    timestamp: str = ""


@dataclass
class CalibrationMetrics:
    """Calibration metrics for a single judge model."""
    model: str
    spearman_correlation: float = 0.0
    mean_score_delta: float = 0.0  # judge - human (positive = lenient)
    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0
    sample_size: int = 0
    drift_warning: bool = False

    @property
    def healthy(self) -> bool:
        return self.spearman_correlation >= 0.8 and not self.drift_warning


@dataclass
class CalibrationProfile:
    """Full calibration profile with correction coefficients."""
    models: dict[str, CalibrationMetrics] = field(default_factory=dict)
    systematic_bias_offset: float = 0.0
    generated_at: str = ""

    def correction_for(self, model: str, raw_score: float) -> float:
        """Apply bias correction to a raw score."""
        metrics = self.models.get(model)
        if not metrics:
            return raw_score
        corrected = raw_score - metrics.mean_score_delta
        return max(0.0, min(1.0, corrected))


def _rank_data(values: list[float]) -> list[float]:
    """Compute ranks for Spearman correlation (handles ties with average rank)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def compute_spearman(x: list[float], y: list[float]) -> float:
    """Compute Spearman rank correlation coefficient."""
    if len(x) != len(y) or len(x) < 3:
        return 0.0

    n = len(x)
    rx = _rank_data(x)
    ry = _rank_data(y)

    d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d_sq) / (n * (n * n - 1))


def compute_calibration(
    golden_set: list[GoldenEntry],
    judge_scores: dict[str, dict[str, float]],
    model: str,
    pass_threshold: float = 0.85,
) -> CalibrationMetrics:
    """
    Compute calibration metrics for a judge model.

    Args:
        golden_set: Human-labeled golden entries.
        judge_scores: {scenario_id: {criterion: score}} from the judge.
        model: Model identifier.
        pass_threshold: Threshold for pass/fail FPR/FNR computation.
    """
    human_vals: list[float] = []
    judge_vals: list[float] = []
    fp = 0
    fn = 0
    total_pass = 0
    total_fail = 0

    for entry in golden_set:
        if entry.scenario_id not in judge_scores:
            continue

        h_scores = entry.human_scores
        j_scores = judge_scores[entry.scenario_id]

        for criterion in h_scores:
            if criterion in j_scores:
                human_vals.append(h_scores[criterion])
                judge_vals.append(j_scores[criterion])

        # Overall pass/fail
        h_avg = sum(h_scores.values()) / len(h_scores) if h_scores else 0
        j_avg = sum(j_scores.get(c, 0.5) for c in h_scores) / len(h_scores) if h_scores else 0

        h_pass = h_avg >= pass_threshold
        j_pass = j_avg >= pass_threshold

        if h_pass:
            total_pass += 1
            if not j_pass:
                fn += 1
        else:
            total_fail += 1
            if j_pass:
                fp += 1

    spearman = compute_spearman(human_vals, judge_vals) if len(human_vals) >= 3 else 0.0
    mean_delta = (sum(j - h for j, h in zip(judge_vals, human_vals)) / len(human_vals)) if human_vals else 0.0

    return CalibrationMetrics(
        model=model,
        spearman_correlation=round(spearman, 4),
        mean_score_delta=round(mean_delta, 4),
        false_positive_rate=round(fp / total_fail, 4) if total_fail > 0 else 0.0,
        false_negative_rate=round(fn / total_pass, 4) if total_pass > 0 else 0.0,
        sample_size=len(human_vals),
        drift_warning=spearman < 0.8,
    )


def load_golden_set(path: str | Path) -> list[GoldenEntry]:
    """Load golden set from JSON file."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open() as f:
        data = json.load(f)
    return [GoldenEntry(**entry) for entry in data]


def save_calibration_profile(profile: CalibrationProfile, path: str | Path) -> None:
    """Save calibration profile to JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": profile.generated_at,
        "systematic_bias_offset": profile.systematic_bias_offset,
        "models": {
            name: {
                "spearman_correlation": m.spearman_correlation,
                "mean_score_delta": m.mean_score_delta,
                "false_positive_rate": m.false_positive_rate,
                "false_negative_rate": m.false_negative_rate,
                "sample_size": m.sample_size,
                "drift_warning": m.drift_warning,
            }
            for name, m in profile.models.items()
        },
    }
    with p.open("w") as f:
        json.dump(data, f, indent=2)
