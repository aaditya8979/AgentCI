"""
Tests for the baseline storage system.
"""
import json

import pytest
from agentci.stats.baseline import BaselineStore


@pytest.fixture
def store(tmp_path):
    """Create a BaselineStore with a temporary directory."""
    return BaselineStore(baseline_dir=tmp_path / "baselines")


class TestBaselineStore:

    def test_empty_baseline_returns_empty_list(self, store):
        """A scenario with no history should return an empty list."""
        scores = store.get_baseline_scores("nonexistent_scenario")
        assert scores == []

    def test_append_and_retrieve(self, store):
        """Appended scores should be retrievable."""
        store.append_score("test_001", 0.92)
        store.append_score("test_001", 0.89)
        store.append_score("test_001", 0.91)

        scores = store.get_baseline_scores("test_001", window=5)
        assert scores == [0.92, 0.89, 0.91]

    def test_window_limits_results(self, store):
        """Window parameter should limit to most recent N scores."""
        for i in range(10):
            store.append_score("test_002", 0.80 + i * 0.01)

        scores = store.get_baseline_scores("test_002", window=3)
        assert len(scores) == 3
        assert scores == pytest.approx([0.87, 0.88, 0.89])

    def test_has_baseline_true(self, store):
        """has_baseline should return True when sufficient samples exist."""
        for _ in range(5):
            store.append_score("test_003", 0.90)
        assert store.has_baseline("test_003", min_samples=3) is True

    def test_has_baseline_false(self, store):
        """has_baseline should return False when insufficient samples."""
        store.append_score("test_004", 0.90)
        assert store.has_baseline("test_004", min_samples=3) is False

    def test_clear_specific_scenario(self, store):
        """Clearing a specific scenario should not affect others."""
        store.append_score("keep_me", 0.95)
        store.append_score("delete_me", 0.50)

        store.clear("delete_me")

        assert store.get_baseline_scores("keep_me") == [0.95]
        assert store.get_baseline_scores("delete_me") == []

    def test_clear_all(self, store):
        """Clearing all should remove everything."""
        store.append_score("a", 0.90)
        store.append_score("b", 0.80)
        store.clear()
        assert store.get_baseline_scores("a") == []
        assert store.get_baseline_scores("b") == []

    def test_metadata_stored(self, store):
        """Metadata should be preserved in the stored entries."""
        store.append_score("test_005", 0.88, metadata={"commit": "abc123"})

        path = store._scenario_path("test_005")
        with path.open() as f:
            data = json.load(f)

        assert data["entries"][0]["metadata"]["commit"] == "abc123"

    def test_bounded_storage(self, store):
        """Storage should cap at 100 entries to prevent unbounded growth."""
        for i in range(150):
            store.append_score("bounded", 0.50 + (i * 0.001))

        path = store._scenario_path("bounded")
        with path.open() as f:
            data = json.load(f)

        assert len(data["entries"]) == 100
