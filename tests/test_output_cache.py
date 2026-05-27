"""
Tests for the judge output cache.

Verifies:
- Exact hash matching works
- Semantic matching with mocked embeddings works
- Dissimilar embeddings produce cache misses
- Fallback hash mode when no embedding provider
- Hit rate calculation
"""
import pytest
from unittest.mock import patch, MagicMock

from agentci.cache.output_cache import OutputCache, CacheStats


class TestHashMode:

    def test_exact_match_returns_cached(self):
        cache = OutputCache(enable_semantic=False)
        judgment = {"score": 0.95, "reasoning": "Good"}
        cache.put("scenario_001", "v1", "Agent response text", judgment)
        result = cache.get("scenario_001", "v1", "Agent response text")
        assert result == judgment
        assert cache.stats.hits == 1

    def test_different_output_is_miss(self):
        cache = OutputCache(enable_semantic=False)
        cache.put("scenario_001", "v1", "Agent response text", {"score": 0.95})
        result = cache.get("scenario_001", "v1", "Different response")
        assert result is None
        assert cache.stats.misses == 1

    def test_different_version_is_miss(self):
        cache = OutputCache(enable_semantic=False)
        cache.put("scenario_001", "v1", "Agent response text", {"score": 0.95})
        result = cache.get("scenario_001", "v2", "Agent response text")
        assert result is None

    def test_expired_entry_is_miss(self):
        cache = OutputCache(ttl=0, enable_semantic=False)
        cache.put("scenario_001", "v1", "text", {"score": 0.9})
        import time; time.sleep(0.01)
        result = cache.get("scenario_001", "v1", "text")
        assert result is None


class TestSemanticMode:

    def test_identical_embeddings_cache_hit(self):
        cache = OutputCache(enable_semantic=True, threshold=0.97)

        # Mock embedding to return identical vectors
        identical_embedding = [1.0, 0.0, 0.0] * 100
        with patch.object(cache, '_compute_embedding', return_value=identical_embedding):
            cache.put("s1", "v1", "I'll process your refund", {"score": 0.9})
            result = cache.get("s1", "v1", "Let me initiate that refund for you")

        assert result is not None
        assert result == {"score": 0.9}
        assert cache.stats.semantic_hits == 1

    def test_dissimilar_embeddings_cache_miss(self):
        cache = OutputCache(enable_semantic=True, threshold=0.97)

        call_count = [0]
        def fake_embed(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return [1.0, 0.0, 0.0]  # first put
            else:
                return [0.0, 1.0, 0.0]  # orthogonal = similarity 0.0

        with patch.object(cache, '_compute_embedding', side_effect=fake_embed):
            cache.put("s1", "v1", "Hello", {"score": 0.9})
            result = cache.get("s1", "v1", "Completely different topic")

        assert result is None
        assert cache.stats.misses == 1

    def test_embedding_failure_falls_back_to_hash(self):
        cache = OutputCache(enable_semantic=True)

        with patch.object(cache, '_compute_embedding', return_value=None):
            cache.put("s1", "v1", "Same text", {"score": 0.9})
            # Exact hash match should still work
            result = cache.get("s1", "v1", "Same text")

        assert result is not None
        assert cache.stats.hits == 1
        assert cache.stats.semantic_hits == 0


class TestCacheStats:

    def test_hit_rate_calculation(self):
        stats = CacheStats(hits=3, misses=7, total=10, semantic_hits=1)
        assert stats.hit_rate == 0.3

    def test_empty_hit_rate(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_report_format(self):
        stats = CacheStats(hits=12, misses=38, total=50, semantic_hits=4)
        report = stats.report()
        assert "12/50" in report
        assert "24%" in report
        assert "semantic" in report


class TestCacheMaintenance:

    def test_clear(self):
        cache = OutputCache(enable_semantic=False)
        cache.put("s1", "v1", "text", {"score": 0.9})
        cache.clear()
        assert cache.get("s1", "v1", "text") is None

    def test_evict_expired(self):
        cache = OutputCache(ttl=0, enable_semantic=False)
        cache.put("s1", "v1", "text1", {"score": 0.9})
        cache.put("s2", "v1", "text2", {"score": 0.8})
        import time; time.sleep(0.01)
        evicted = cache.evict_expired()
        assert evicted == 2


class TestCosineSimEdgeCases:

    def test_zero_vector(self):
        assert OutputCache._cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    def test_identical_vectors(self):
        v = [0.5, 0.3, 0.8]
        sim = OutputCache._cosine_similarity(v, v)
        assert sim == pytest.approx(1.0, abs=1e-6)
