"""
Baseline storage and rolling baseline computation.

Manages historical eval scores on disk (JSON) for statistical comparison.
Provides rolling window baselines and Bayesian prior estimation for
cold-start scenarios (Gap 1 from the theoretical analysis).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BASELINE_DIR = ".agentci/baselines"


class BaselineStore:
    """
    Stores and retrieves historical evaluation scores for baseline comparison.

    Each scenario's scores are stored as a JSON file in the baseline directory.
    The store supports rolling window retrieval (e.g., last N runs) and
    appending new results after each evaluation.
    """

    def __init__(self, baseline_dir: str | Path = DEFAULT_BASELINE_DIR):
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)

    def _scenario_path(self, scenario_id: str) -> Path:
        """Get the storage path for a scenario's baseline data."""
        safe_id = scenario_id.replace("/", "_").replace(" ", "_")
        return self.baseline_dir / f"{safe_id}.json"

    def get_baseline_scores(
        self,
        scenario_id: str,
        window: int = 5,
    ) -> list[float]:
        """
        Retrieve the most recent `window` scores for a scenario.

        Args:
            scenario_id: The scenario identifier.
            window: Number of most recent scores to return.

        Returns:
            List of historical weighted scores (most recent last).
            Empty list if no baseline data exists.
        """
        path = self._scenario_path(scenario_id)
        if not path.exists():
            return []

        try:
            with path.open() as f:
                data = json.load(f)
            entries = data.get("entries", [])
            scores = [e["weighted_score"] for e in entries]
            return scores[-window:]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to read baseline for %s: %s", scenario_id, e)
            return []

    def append_score(
        self,
        scenario_id: str,
        weighted_score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Append a new score to a scenario's baseline history.

        Args:
            scenario_id: The scenario identifier.
            weighted_score: The weighted score from this evaluation run.
            metadata: Optional metadata (commit SHA, judge panel, etc.).
        """
        path = self._scenario_path(scenario_id)

        if path.exists():
            with path.open() as f:
                data = json.load(f)
        else:
            data = {"scenario_id": scenario_id, "entries": []}

        entry = {
            "weighted_score": weighted_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            entry["metadata"] = metadata

        data["entries"].append(entry)

        # Keep at most 100 entries to prevent unbounded growth
        if len(data["entries"]) > 100:
            data["entries"] = data["entries"][-100:]

        with path.open("w") as f:
            json.dump(data, f, indent=2)

    def has_baseline(self, scenario_id: str, min_samples: int = 3) -> bool:
        """Check if sufficient baseline data exists for statistical testing."""
        scores = self.get_baseline_scores(scenario_id, window=min_samples)
        return len(scores) >= min_samples

    def clear(self, scenario_id: str | None = None) -> None:
        """
        Clear baseline data.

        Args:
            scenario_id: If provided, clear only this scenario's baseline.
                         If None, clear all baselines.
        """
        if scenario_id:
            path = self._scenario_path(scenario_id)
            if path.exists():
                path.unlink()
                logger.info("Cleared baseline for %s", scenario_id)
        else:
            for path in self.baseline_dir.glob("*.json"):
                path.unlink()
            logger.info("Cleared all baselines")
