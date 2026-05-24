"""
Five-tier severity classifier for regression analysis.

Maps rubric criteria tagged with behavioral dimensions and reversibility
to actionable severity tiers with routing recommendations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class BehavioralDimension(str, Enum):
    TONE = "tone"
    ACCURACY = "accuracy"
    SAFETY = "safety"
    COMPLIANCE = "compliance"
    TOOL_USE = "tool_use"
    HALLUCINATION = "hallucination"


class Reversibility(str, Enum):
    IMMEDIATE = "immediate"    # tone — fix and redeploy
    DELAYED = "delayed"        # accuracy — may have caused harm
    CRITICAL = "critical"      # safety — escalate immediately


class BlastRadius(str, Enum):
    NARROW = "narrow"          # single category
    MODERATE = "moderate"      # multiple related categories
    CROSS_DOMAIN = "cross_domain"  # affects all interactions


class SeverityTier(int, Enum):
    COSMETIC = 1       # Tone, style, formatting
    QUALITY = 2        # Minor accuracy, relevance
    FUNCTIONAL = 3     # Core functionality degraded
    SAFETY = 4         # Safety / harmful content
    COMPLIANCE = 5     # Legal / regulatory / policy


class RecommendedAction(str, Enum):
    WARN = "warn"
    BLOCK = "block"
    BLOCK_AND_ESCALATE = "block_and_escalate"


@dataclass
class SeverityClassification:
    """Result of the severity classification for a regression."""
    tier: SeverityTier
    action: RecommendedAction
    routing: list[str]
    explanation: str
    affected_dimensions: list[BehavioralDimension]
    worst_criterion: str
    worst_score_delta: float


# Dimension → tier mapping
_DIMENSION_TO_TIER: dict[BehavioralDimension, SeverityTier] = {
    BehavioralDimension.TONE: SeverityTier.COSMETIC,
    BehavioralDimension.ACCURACY: SeverityTier.QUALITY,
    BehavioralDimension.TOOL_USE: SeverityTier.FUNCTIONAL,
    BehavioralDimension.HALLUCINATION: SeverityTier.FUNCTIONAL,
    BehavioralDimension.SAFETY: SeverityTier.SAFETY,
    BehavioralDimension.COMPLIANCE: SeverityTier.COMPLIANCE,
}

# Tier → action mapping
_TIER_TO_ACTION: dict[SeverityTier, RecommendedAction] = {
    SeverityTier.COSMETIC: RecommendedAction.WARN,
    SeverityTier.QUALITY: RecommendedAction.WARN,
    SeverityTier.FUNCTIONAL: RecommendedAction.BLOCK,
    SeverityTier.SAFETY: RecommendedAction.BLOCK_AND_ESCALATE,
    SeverityTier.COMPLIANCE: RecommendedAction.BLOCK_AND_ESCALATE,
}

# Tier → routing targets
_TIER_TO_ROUTING: dict[SeverityTier, list[str]] = {
    SeverityTier.COSMETIC: ["author"],
    SeverityTier.QUALITY: ["author", "reviewer"],
    SeverityTier.FUNCTIONAL: ["author", "tech_lead"],
    SeverityTier.SAFETY: ["author", "security_team", "on_call"],
    SeverityTier.COMPLIANCE: ["author", "legal_team", "security_team"],
}


def classify_severity(
    criterion_scores: dict[str, float],
    baseline_scores: dict[str, float],
    criterion_metadata: dict[str, dict] | None = None,
) -> SeverityClassification:
    """
    Classify the severity of a regression based on per-criterion deltas
    and their behavioral dimension tags.

    Args:
        criterion_scores: Current scores per criterion name.
        baseline_scores: Baseline scores per criterion name.
        criterion_metadata: Optional metadata with 'dimension', 'reversibility',
                           'blast_radius' keys per criterion.

    Returns:
        SeverityClassification with tier, action, routing, and explanation.
    """
    metadata = criterion_metadata or {}
    affected_dims: list[BehavioralDimension] = []
    worst_criterion = ""
    worst_delta = 0.0
    max_tier = SeverityTier.COSMETIC

    for name, current in criterion_scores.items():
        baseline = baseline_scores.get(name, current)
        delta = baseline - current  # positive = regression

        if delta <= 0.02:  # negligible change
            continue

        meta = metadata.get(name, {})
        dim_str = meta.get("dimension", "accuracy")
        rev_str = meta.get("reversibility", "immediate")
        blast_str = meta.get("blast_radius", "narrow")

        try:
            dim = BehavioralDimension(dim_str)
        except ValueError:
            dim = BehavioralDimension.ACCURACY

        try:
            rev = Reversibility(rev_str)
        except ValueError:
            rev = Reversibility.IMMEDIATE

        try:
            blast = BlastRadius(blast_str)
        except ValueError:
            blast = BlastRadius.NARROW

        affected_dims.append(dim)

        # Determine tier from dimension
        tier = _DIMENSION_TO_TIER.get(dim, SeverityTier.QUALITY)

        # Escalate based on reversibility
        if rev == Reversibility.CRITICAL and tier.value < SeverityTier.SAFETY.value:
            tier = SeverityTier.SAFETY

        # Escalate based on blast radius
        if blast == BlastRadius.CROSS_DOMAIN and tier.value < SeverityTier.FUNCTIONAL.value:
            tier = SeverityTier.FUNCTIONAL

        # Escalate based on magnitude
        if delta > 0.30 and tier.value < SeverityTier.FUNCTIONAL.value:
            tier = SeverityTier.FUNCTIONAL

        if tier.value > max_tier.value:
            max_tier = tier

        if delta > worst_delta:
            worst_delta = delta
            worst_criterion = name

    # Build explanation
    action = _TIER_TO_ACTION.get(max_tier, RecommendedAction.WARN)
    routing = _TIER_TO_ROUTING.get(max_tier, ["author"])

    dim_names = ", ".join(sorted(set(d.value for d in affected_dims))) if affected_dims else "none"

    explanation = (
        f"Regression detected in {len(affected_dims)} criterion/criteria "
        f"across dimensions: [{dim_names}]. "
        f"Worst: '{worst_criterion}' dropped by {worst_delta:.2f}. "
        f"Severity: {max_tier.name} (tier {max_tier.value}). "
        f"Action: {action.value}."
    )

    if max_tier.value >= SeverityTier.SAFETY.value:
        explanation += (
            f" Escalation required — {', '.join(routing)} must review "
            f"before this PR can proceed."
        )

    return SeverityClassification(
        tier=max_tier,
        action=action,
        routing=routing,
        explanation=explanation,
        affected_dimensions=affected_dims,
        worst_criterion=worst_criterion,
        worst_score_delta=worst_delta,
    )
