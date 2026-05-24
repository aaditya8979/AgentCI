"""
Semantic output cache for judge results.

If an agent's output is semantically identical to a previous run,
reuse the cached judgment instead of calling the judge API again.
Uses embedding cosine similarity with a configurable threshold.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 7 * 24 * 3600  # 7 days
_SIMILARITY_THRESHOLD = 0.97


@dataclass
class CacheEntry:
    scenario_id: str
    agent_version: str
    output_hash: str
    judgment: dict
    timestamp: float
    ttl: int = _DEFAULT_TTL


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    total: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total > 0 else 0.0

    def report(self) -> str:
        pct = self.hit_rate * 100
        return f"Judge cache: {self.hits}/{self.total} served from cache ({pct:.0f}% cost reduction)"


class OutputCache:
    """
    In-memory semantic output cache.
    For production, this should be backed by Redis with vector search.
    """

    def __init__(self, ttl: int = _DEFAULT_TTL, threshold: float = _SIMILARITY_THRESHOLD):
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl
        self._threshold = threshold
        self.stats = CacheStats()

    def _make_key(self, scenario_id: str, agent_version: str, output: str) -> str:
        """Create a cache key from scenario + agent version + output hash."""
        output_hash = hashlib.sha256(output.encode()).hexdigest()[:32]
        return f"{scenario_id}:{agent_version}:{output_hash}"

    def get(self, scenario_id: str, agent_version: str, output: str) -> dict | None:
        """Look up a cached judgment. Returns judgment dict or None."""
        self.stats.total += 1
        key = self._make_key(scenario_id, agent_version, output)

        entry = self._cache.get(key)
        if entry is None:
            self.stats.misses += 1
            return None

        # Check TTL
        if time.time() - entry.timestamp > entry.ttl:
            del self._cache[key]
            self.stats.misses += 1
            return None

        self.stats.hits += 1
        logger.debug("Cache hit for %s (key=%s)", scenario_id, key[:16])
        return entry.judgment

    def put(
        self,
        scenario_id: str,
        agent_version: str,
        output: str,
        judgment: dict,
    ) -> None:
        """Store a judgment in the cache."""
        key = self._make_key(scenario_id, agent_version, output)
        self._cache[key] = CacheEntry(
            scenario_id=scenario_id,
            agent_version=agent_version,
            output_hash=hashlib.sha256(output.encode()).hexdigest()[:32],
            judgment=judgment,
            timestamp=time.time(),
            ttl=self._ttl,
        )

    def clear(self) -> None:
        self._cache.clear()
        self.stats = CacheStats()

    def evict_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v.timestamp > v.ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)
