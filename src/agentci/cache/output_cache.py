"""
Judge output cache for AgentCI.

Uses SHA-256 hash matching to detect identical agent outputs and
reuse cached judgments without re-calling the judge API.

When an embedding provider is configured (OPENAI_API_KEY), upgrades
to semantic similarity matching using cosine distance against stored
embeddings. This catches cases where the agent produces slightly
different phrasing with semantically identical content.

Fallback: exact hash matching (zero additional API cost).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field

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
    embedding: list[float] | None = None


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    total: int = 0
    semantic_hits: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total > 0 else 0.0

    def report(self) -> str:
        pct = self.hit_rate * 100
        parts = [f"Judge cache: {self.hits}/{self.total} served from cache ({pct:.0f}% cost reduction)"]
        if self.semantic_hits:
            parts.append(f" ({self.semantic_hits} semantic matches)")
        return "".join(parts)


class OutputCache:
    """
    Judge output cache with optional semantic similarity matching.

    Cache modes:
      - Hash mode (default): exact SHA-256 match of output text.
        Zero additional cost. No API calls.
      - Semantic mode (when embedding provider available):
        cosine similarity of text embeddings. Catches near-identical
        outputs that differ in whitespace, punctuation, or minor rewording.

    Usage:
        cache = OutputCache()
        cached = cache.get("scenario_001", "v1.2", agent_output)
        if cached is not None:
            return cached  # skip judge API call
        judgment = await judge.evaluate(...)
        cache.put("scenario_001", "v1.2", agent_output, judgment)
    """

    def __init__(
        self,
        ttl: int = _DEFAULT_TTL,
        threshold: float = _SIMILARITY_THRESHOLD,
        enable_semantic: bool | None = None,
    ):
        self._cache: dict[str, CacheEntry] = {}
        self._semantic_index: dict[str, list[CacheEntry]] = {}
        self._ttl = ttl
        self._threshold = threshold
        self.stats = CacheStats()

        # Auto-detect semantic mode
        if enable_semantic is None:
            self._semantic = bool(os.environ.get("OPENAI_API_KEY"))
        else:
            self._semantic = enable_semantic

        if self._semantic:
            logger.info(
                "Output cache: semantic mode enabled (threshold=%.2f)", threshold,
            )
        else:
            logger.info("Output cache: hash mode (exact matching)")

    def _make_key(self, scenario_id: str, agent_version: str, output: str) -> str:
        """Create a cache key from scenario + agent version + output hash."""
        output_hash = hashlib.sha256(output.encode()).hexdigest()[:32]
        return f"{scenario_id}:{agent_version}:{output_hash}"

    def _group_key(self, scenario_id: str, agent_version: str) -> str:
        return f"{scenario_id}:{agent_version}"

    def get(self, scenario_id: str, agent_version: str, output: str) -> dict | None:
        """Look up a cached judgment. Returns judgment dict or None."""
        self.stats.total += 1

        # 1. Try exact hash match (always)
        key = self._make_key(scenario_id, agent_version, output)
        entry = self._cache.get(key)
        if entry is not None:
            if time.time() - entry.timestamp > entry.ttl:
                del self._cache[key]
            else:
                self.stats.hits += 1
                logger.debug("Cache hit (exact) for %s", scenario_id)
                return entry.judgment

        # 2. Try semantic match if enabled
        if self._semantic:
            group = self._group_key(scenario_id, agent_version)
            entries = self._semantic_index.get(group, [])
            if entries:
                embedding = self._compute_embedding(output)
                if embedding:
                    for e in entries:
                        if time.time() - e.timestamp > e.ttl:
                            continue
                        if e.embedding and self._cosine_similarity(embedding, e.embedding) >= self._threshold:
                            self.stats.hits += 1
                            self.stats.semantic_hits += 1
                            logger.debug("Cache hit (semantic, sim>=%.2f) for %s", self._threshold, scenario_id)
                            return e.judgment

        self.stats.misses += 1
        return None

    def put(
        self,
        scenario_id: str,
        agent_version: str,
        output: str,
        judgment: dict,
    ) -> None:
        """Store a judgment in the cache."""
        key = self._make_key(scenario_id, agent_version, output)
        embedding = self._compute_embedding(output) if self._semantic else None

        entry = CacheEntry(
            scenario_id=scenario_id,
            agent_version=agent_version,
            output_hash=hashlib.sha256(output.encode()).hexdigest()[:32],
            judgment=judgment,
            timestamp=time.time(),
            ttl=self._ttl,
            embedding=embedding,
        )
        self._cache[key] = entry

        if self._semantic and embedding:
            group = self._group_key(scenario_id, agent_version)
            if group not in self._semantic_index:
                self._semantic_index[group] = []
            self._semantic_index[group].append(entry)

    def _compute_embedding(self, text: str) -> list[float] | None:
        """
        Compute text embedding using OpenAI text-embedding-3-small.

        Returns None if the API is unavailable — caller falls back to hash matching.
        """
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            import httpx
            resp = httpx.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "text-embedding-3-small", "input": text[:8000]},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception as e:
            logger.debug("Embedding computation failed: %s", e)
            return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x ** 2 for x in a) ** 0.5
        mag_b = sum(x ** 2 for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def clear(self) -> None:
        self._cache.clear()
        self._semantic_index.clear()
        self.stats = CacheStats()

    def evict_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v.timestamp > v.ttl]
        for k in expired:
            del self._cache[k]

        # Clean semantic index
        for group in list(self._semantic_index.keys()):
            self._semantic_index[group] = [
                e for e in self._semantic_index[group]
                if now - e.timestamp <= e.ttl
            ]
            if not self._semantic_index[group]:
                del self._semantic_index[group]

        return len(expired)
