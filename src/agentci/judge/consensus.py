"""
Multi-judge consensus panel with median aggregation and tiebreaker logic.

Implements the three-judge panel described in the blueprint:
- Cross-family composition to reduce self-enhancement bias
- Median aggregation (not mean) to resist outliers
- Inter-Judge Agreement (IJA) check with optional tiebreaker
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ..models.scenario import JudgeResponse
from .llm_judge import LLMJudge, JudgeModel

logger = logging.getLogger(__name__)

# Default panel: one judge from each major provider family
DEFAULT_PANEL = [
    JudgeModel.GPT_4O,
    JudgeModel.CLAUDE_SONNET,
    JudgeModel.GEMINI_PRO,
]


@dataclass
class ConsensusResult:
    """Result of the consensus panel evaluation."""
    consensus_scores: dict[str, float]
    weighted_score: float
    inter_judge_agreement: float
    individual_responses: list[JudgeResponse]
    tiebreaker_used: bool


class ConsensusPanel:
    """
    A panel of LLM judges that evaluates agent outputs via consensus.

    Runs multiple judges independently, then aggregates via median.
    If inter-judge agreement drops below threshold, a tiebreaker judge
    is invoked with visibility into the disagreement.
    """

    def __init__(
        self,
        models: list[JudgeModel | str] | None = None,
        ija_threshold: float = 0.7,
        tiebreaker_model: JudgeModel | str = JudgeModel.GPT_4O,
    ):
        self.models = models or DEFAULT_PANEL
        self.judges = [LLMJudge(m) for m in self.models]
        self.ija_threshold = ija_threshold
        self.tiebreaker = LLMJudge(tiebreaker_model)

    def evaluate(
        self,
        scenario_description: str,
        conversation_history: str,
        agent_output: str,
        rubric_criteria: list[dict],
        context: str | None = None,
    ) -> ConsensusResult:
        """
        Run all judges, compute consensus via median, and trigger
        tiebreaker if inter-judge agreement is below threshold.
        """
        # Phase 1: Collect independent judgments
        responses: list[JudgeResponse] = []
        for judge in self.judges:
            try:
                resp = judge.evaluate(
                    scenario_description=scenario_description,
                    conversation_history=conversation_history,
                    agent_output=agent_output,
                    rubric_criteria=rubric_criteria,
                    context=context,
                )
                responses.append(resp)
                logger.info("Judge %s completed evaluation", judge.model)
            except Exception as e:
                logger.error("Judge %s failed: %s", judge.model, e)

        if not responses:
            raise RuntimeError("All judges failed — cannot produce consensus")

        # Phase 2: Compute per-criterion median scores
        criterion_names = [c["name"] for c in rubric_criteria]
        consensus_scores: dict[str, float] = {}
        ija_values: list[float] = []

        for name in criterion_names:
            scores = [
                r.scores[name].score
                for r in responses
                if name in r.scores
            ]
            if not scores:
                consensus_scores[name] = 0.0
                continue

            consensus_scores[name] = float(np.median(scores))

            # Inter-Judge Agreement for this criterion
            if len(scores) >= 2:
                ija = 1.0 - (max(scores) - min(scores))
                ija_values.append(ija)

        overall_ija = float(np.mean(ija_values)) if ija_values else 1.0

        # Phase 3: Tiebreaker if agreement is low
        tiebreaker_used = False
        if overall_ija < self.ija_threshold and len(responses) >= 2:
            logger.info(
                "IJA %.2f < threshold %.2f — invoking tiebreaker judge",
                overall_ija, self.ija_threshold,
            )
            try:
                tb_resp = self.tiebreaker.evaluate(
                    scenario_description=scenario_description,
                    conversation_history=conversation_history,
                    agent_output=agent_output,
                    rubric_criteria=rubric_criteria,
                    context=context,
                )
                responses.append(tb_resp)
                tiebreaker_used = True

                # Recompute consensus with the tiebreaker included
                for name in criterion_names:
                    scores = [
                        r.scores[name].score
                        for r in responses
                        if name in r.scores
                    ]
                    if scores:
                        consensus_scores[name] = float(np.median(scores))

            except Exception as e:
                logger.error("Tiebreaker judge failed: %s", e)

        # Phase 4: Compute weighted final score
        weights = {c["name"]: c["weight"] for c in rubric_criteria}
        total_weight = sum(weights.values())
        weighted_score = sum(
            consensus_scores.get(name, 0.0) * weights.get(name, 1.0)
            for name in criterion_names
        ) / total_weight if total_weight > 0 else 0.0

        return ConsensusResult(
            consensus_scores=consensus_scores,
            weighted_score=weighted_score,
            inter_judge_agreement=overall_ija,
            individual_responses=responses,
            tiebreaker_used=tiebreaker_used,
        )
