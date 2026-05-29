"""
Async consensus panel with parallel judge execution and tiered evaluation.

Runs all judges concurrently using asyncio.gather(), computes consensus
via median aggregation, and supports two-tier evaluation for cost reduction.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import numpy as np

from ..models.scenario import JudgeResponse, ScoreBreakdown
from .async_judge import AsyncLLMJudge
from .llm_judge import JudgeModel

logger = logging.getLogger(__name__)

DEFAULT_PANEL = [JudgeModel.GPT_4O, JudgeModel.CLAUDE_SONNET, JudgeModel.GEMINI_PRO]


@dataclass
class ConsensusResult:
    """Result of the consensus panel evaluation."""
    consensus_scores: dict[str, float]
    weighted_score: float
    inter_judge_agreement: float
    individual_responses: list[JudgeResponse]
    tiebreaker_used: bool
    tier: int = 2


@dataclass
class TierStats:
    """Tracking statistics for tiered evaluation."""
    tier1_pass: int = 0
    tier1_fail: int = 0
    tier1_escalated: int = 0

    @property
    def total(self) -> int:
        return self.tier1_pass + self.tier1_fail + self.tier1_escalated

    def summary(self) -> str:
        return (
            f"Tier 1 screened: {self.tier1_pass} pass, "
            f"{self.tier1_fail} fail, "
            f"{self.tier1_escalated} escalated to Tier 2"
        )


class AsyncConsensusPanel:
    """
    Async consensus panel that runs judges in parallel.

    All judge API calls within a single scenario execute concurrently
    via asyncio.gather(), reducing latency from N*T to ~T.
    """

    def __init__(
        self,
        models: list[JudgeModel | str] | None = None,
        ija_threshold: float = 0.7,
        tiebreaker_model: JudgeModel | str = JudgeModel.GPT_4O,
    ):
        self.models = models or DEFAULT_PANEL
        self.judges = [AsyncLLMJudge(m) for m in self.models]
        self.ija_threshold = ija_threshold
        self.tiebreaker = AsyncLLMJudge(tiebreaker_model)

    async def evaluate(
        self,
        scenario_description: str,
        conversation_history: str,
        agent_output: str,
        rubric_criteria: list[dict],
        context: str | None = None,
    ) -> ConsensusResult:
        """Run all judges concurrently, compute consensus via median."""
        eval_kwargs = dict(
            scenario_description=scenario_description,
            conversation_history=conversation_history,
            agent_output=agent_output,
            rubric_criteria=rubric_criteria,
            context=context,
        )

        # Phase 1: Run all judges in parallel
        tasks = [judge.evaluate(**eval_kwargs) for judge in self.judges]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        responses: list[JudgeResponse] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                logger.error("Judge %s failed: %s", self.judges[i].model, result)
            else:
                responses.append(result)
                logger.info("Judge %s completed", self.judges[i].model)

        if not responses:
            raise RuntimeError("All judges failed — cannot produce consensus")

        # Phase 2: Compute per-criterion median scores
        criterion_names = [c["name"] for c in rubric_criteria]
        consensus_scores, overall_ija = self._compute_consensus(responses, criterion_names)

        # Phase 3: Tiebreaker if IJA is low
        tiebreaker_used = False
        if overall_ija < self.ija_threshold and len(responses) >= 2:
            logger.info("IJA %.2f < threshold — invoking tiebreaker", overall_ija)
            try:
                tb_resp = await self.tiebreaker.evaluate(**eval_kwargs)
                responses.append(tb_resp)
                tiebreaker_used = True
                consensus_scores, _ = self._compute_consensus(responses, criterion_names)
            except Exception as e:
                logger.error("Tiebreaker failed: %s", e)

        # Phase 4: Weighted final score
        weights = {c["name"]: c["weight"] for c in rubric_criteria}
        total_weight = sum(weights.values())
        weighted_score = sum(
            consensus_scores.get(n, 0.0) * weights.get(n, 1.0) for n in criterion_names
        ) / total_weight if total_weight > 0 else 0.0

        return ConsensusResult(
            consensus_scores=consensus_scores,
            weighted_score=weighted_score,
            inter_judge_agreement=overall_ija,
            individual_responses=responses,
            tiebreaker_used=tiebreaker_used,
        )

    async def close(self) -> None:
        """Close all judge HTTP clients."""
        for judge in self.judges:
            await judge.close()
        await self.tiebreaker.close()

    @staticmethod
    def _compute_consensus(
        responses: list[JudgeResponse],
        criterion_names: list[str],
    ) -> tuple[dict[str, float], float]:
        """Compute median scores and IJA from judge responses."""
        consensus: dict[str, float] = {}
        ija_values: list[float] = []

        for name in criterion_names:
            scores = [r.scores[name].score for r in responses if name in r.scores]
            if not scores:
                consensus[name] = 0.0
                continue
            consensus[name] = float(np.median(scores))
            if len(scores) >= 2:
                ija_values.append(1.0 - (max(scores) - min(scores)))

        overall_ija = float(np.mean(ija_values)) if ija_values else 1.0
        return consensus, overall_ija


class TieredJudgePanel:
    """
    Two-tier evaluation panel for cost reduction.

    Tier 1: Single cheap judge (e.g., GPT-4o-mini) for screening.
    Tier 2: Full consensus panel for ambiguous cases.
    """

    def __init__(
        self,
        tier1_model: JudgeModel | str = JudgeModel.GPT_4O_MINI,
        tier2_models: list[JudgeModel | str] | None = None,
        auto_pass_threshold: float = 0.95,
        auto_fail_threshold: float = 0.30,
        ija_threshold: float = 0.7,
    ):
        self.tier1 = AsyncLLMJudge(tier1_model)
        self.tier2 = AsyncConsensusPanel(models=tier2_models, ija_threshold=ija_threshold)
        self.auto_pass = auto_pass_threshold
        self.auto_fail = auto_fail_threshold
        self.stats = TierStats()

    async def evaluate(
        self,
        scenario_description: str,
        conversation_history: str,
        agent_output: str,
        rubric_criteria: list[dict],
        context: str | None = None,
    ) -> ConsensusResult:
        """Evaluate with tier-1 screening, escalating to tier-2 if ambiguous."""
        eval_kwargs = dict(
            scenario_description=scenario_description,
            conversation_history=conversation_history,
            agent_output=agent_output,
            rubric_criteria=rubric_criteria,
            context=context,
        )

        # Tier 1: Screening judge
        tier1_resp = await self.tier1.evaluate(**eval_kwargs)

        weights = {c["name"]: c["weight"] for c in rubric_criteria}
        total_weight = sum(weights.values())
        criterion_names = [c["name"] for c in rubric_criteria]
        tier1_score = sum(
            tier1_resp.scores.get(n, ScoreBreakdown(score=0.5, reasoning="")).score * weights.get(n, 1.0)
            for n in criterion_names
        ) / total_weight if total_weight > 0 else 0.0

        # Auto-pass
        if tier1_score >= self.auto_pass:
            self.stats.tier1_pass += 1
            logger.info("Tier 1 AUTO-PASS: %.3f >= %.3f", tier1_score, self.auto_pass)
            return ConsensusResult(
                consensus_scores={n: tier1_resp.scores[n].score for n in criterion_names if n in tier1_resp.scores},
                weighted_score=tier1_score,
                inter_judge_agreement=1.0,
                individual_responses=[tier1_resp],
                tiebreaker_used=False,
                tier=1,
            )

        # Auto-fail
        if tier1_score <= self.auto_fail:
            self.stats.tier1_fail += 1
            logger.info("Tier 1 AUTO-FAIL: %.3f <= %.3f", tier1_score, self.auto_fail)
            return ConsensusResult(
                consensus_scores={n: tier1_resp.scores[n].score for n in criterion_names if n in tier1_resp.scores},
                weighted_score=tier1_score,
                inter_judge_agreement=1.0,
                individual_responses=[tier1_resp],
                tiebreaker_used=False,
                tier=1,
            )

        # Escalate to Tier 2
        self.stats.tier1_escalated += 1
        logger.info("Tier 1 ESCALATE: %.3f (ambiguous range)", tier1_score)
        result = await self.tier2.evaluate(**eval_kwargs)
        result.tier = 2
        return result

    async def close(self) -> None:
        await self.tier1.close()
        await self.tier2.close()
