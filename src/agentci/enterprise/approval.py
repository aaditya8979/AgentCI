"""
Approval workflow engine for severity-stratified regressions.

Enforces configurable approval policies per severity tier,
supporting auto-block, notification routing, and comment-based
approval via /agentci approve on GitHub PRs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .severity import SeverityTier

logger = logging.getLogger(__name__)


class ApprovalAction(str, Enum):
    WARN = "warn"
    BLOCK = "block"
    BLOCK_AND_REQUIRE_APPROVAL = "block_and_require_approval"


@dataclass
class ApprovalPolicy:
    """Policy for a single severity tier."""
    tier: SeverityTier
    action: ApprovalAction
    notify: list[str] = field(default_factory=list)
    approval_required_from: list[str] = field(default_factory=list)


@dataclass
class ApprovalRecord:
    """Record of an approval decision."""
    pr_number: int
    run_id: str
    severity_tier: SeverityTier
    approved_by: str
    approved_at: str
    comment: str = ""


# Default policy per tier
DEFAULT_POLICIES: dict[SeverityTier, ApprovalPolicy] = {
    SeverityTier.COSMETIC: ApprovalPolicy(
        tier=SeverityTier.COSMETIC,
        action=ApprovalAction.WARN,
        notify=[],
    ),
    SeverityTier.QUALITY: ApprovalPolicy(
        tier=SeverityTier.QUALITY,
        action=ApprovalAction.BLOCK,
        notify=["author"],
    ),
    SeverityTier.FUNCTIONAL: ApprovalPolicy(
        tier=SeverityTier.FUNCTIONAL,
        action=ApprovalAction.BLOCK,
        notify=["author", "team_lead"],
    ),
    SeverityTier.SAFETY: ApprovalPolicy(
        tier=SeverityTier.SAFETY,
        action=ApprovalAction.BLOCK_AND_REQUIRE_APPROVAL,
        notify=["author", "security_team"],
        approval_required_from=["security_team"],
    ),
    SeverityTier.COMPLIANCE: ApprovalPolicy(
        tier=SeverityTier.COMPLIANCE,
        action=ApprovalAction.BLOCK_AND_REQUIRE_APPROVAL,
        notify=["author", "legal_team", "cto"],
        approval_required_from=["legal_team"],
    ),
}


def load_policies_from_config(config: dict[str, Any]) -> dict[SeverityTier, ApprovalPolicy]:
    """Load approval policies from .agentci.yml approval_workflow section."""
    policies = dict(DEFAULT_POLICIES)
    workflow = config.get("approval_workflow", {})

    tier_map = {
        "cosmetic": SeverityTier.COSMETIC,
        "quality": SeverityTier.QUALITY,
        "functional": SeverityTier.FUNCTIONAL,
        "safety": SeverityTier.SAFETY,
        "compliance": SeverityTier.COMPLIANCE,
    }

    for tier_name, settings in workflow.items():
        tier = tier_map.get(tier_name)
        if not tier:
            continue
        policies[tier] = ApprovalPolicy(
            tier=tier,
            action=ApprovalAction(settings.get("action", "block")),
            notify=settings.get("notify", []),
            approval_required_from=settings.get("approval_required_from", []),
        )

    return policies


def evaluate_policy(
    severity_tier: SeverityTier,
    policies: dict[SeverityTier, ApprovalPolicy] | None = None,
) -> ApprovalPolicy:
    """Get the approval policy for a given severity tier."""
    p = (policies or DEFAULT_POLICIES)
    return p.get(severity_tier, DEFAULT_POLICIES.get(severity_tier, DEFAULT_POLICIES[SeverityTier.QUALITY]))


def is_approval_comment(comment_body: str) -> bool:
    """Check if a PR comment is an approval command."""
    stripped = comment_body.strip().lower()
    return stripped in ("/agentci approve", "/agentci-approve")


def create_approval_record(
    pr_number: int,
    run_id: str,
    severity_tier: SeverityTier,
    approver_username: str,
    comment: str = "",
) -> ApprovalRecord:
    """Create an approval record for audit logging."""
    return ApprovalRecord(
        pr_number=pr_number,
        run_id=run_id,
        severity_tier=severity_tier,
        approved_by=approver_username,
        approved_at=datetime.now(timezone.utc).isoformat(),
        comment=comment,
    )


def check_approver_authorized(
    approver: str,
    policy: ApprovalPolicy,
    team_memberships: dict[str, list[str]] | None = None,
) -> bool:
    """
    Check if an approver is authorized per the policy.

    Args:
        approver: GitHub username of the approver.
        policy: The approval policy to check against.
        team_memberships: Mapping of team names to member usernames.
    """
    if not policy.approval_required_from:
        return True  # No specific approvers required

    memberships = team_memberships or {}

    for required_team in policy.approval_required_from:
        # Check if approver is in the required team
        team_members = memberships.get(required_team, [])
        if approver in team_members:
            return True
        # Also accept if the approver's name matches the team (single person)
        if approver == required_team:
            return True

    return False
