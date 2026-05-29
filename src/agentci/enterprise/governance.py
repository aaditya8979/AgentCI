"""
Signed eval attestations and governance artifacts.

Generates cryptographically verifiable attestation documents
that prove an evaluation occurred with specific parameters
and produced specific results. For legal teams and auditors.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ATTESTATION_VERSION = "1.0"


@dataclass
class JudgePanelMember:
    provider: str
    model: str
    version: str = ""


@dataclass
class EvalAttestation:
    """Machine-readable eval attestation document."""
    version: str = ATTESTATION_VERSION
    attestation_id: str = ""
    run_id: str = ""
    repo: str = ""
    pr_number: int | None = None
    commit_sha: str = ""
    timestamp_utc: str = ""
    eval_suite: str = ""
    judge_panel: list[JudgePanelMember] = field(default_factory=list)
    scenarios_evaluated: int = 0
    scenarios_passed: int = 0
    overall_score: float = 0.0
    statistical_method: str = "welch_t_test"
    significance_level: float = 0.05
    outcome: str = "pass"  # pass or fail
    severity: str | None = None
    routing_recommendation: list[str] = field(default_factory=list)
    signature: str = ""  # SHA-256 of payload

    def compute_signature(self) -> str:
        """Compute SHA-256 hash of the attestation payload (excluding signature)."""
        data = asdict(self)
        data.pop("signature", None)
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def sign(self) -> None:
        """Sign the attestation by computing and storing the hash."""
        self.signature = self.compute_signature()

    def verify(self) -> bool:
        """Verify the attestation signature."""
        expected = self.compute_signature()
        return self.signature == expected


def create_attestation(
    run_id: str,
    repo: str = "",
    pr_number: int | None = None,
    commit_sha: str = "",
    eval_suite: str = "full",
    judge_models: list[str] | None = None,
    scenarios_evaluated: int = 0,
    scenarios_passed: int = 0,
    overall_score: float = 0.0,
    outcome: str = "pass",
    severity: str | None = None,
    routing: list[str] | None = None,
) -> EvalAttestation:
    """Create and sign a new attestation."""
    panel = []
    for model in (judge_models or []):
        if model.startswith("gpt"):
            panel.append(JudgePanelMember(provider="openai", model=model))
        elif model.startswith("claude"):
            panel.append(JudgePanelMember(provider="anthropic", model=model))
        elif model.startswith("gemini"):
            panel.append(JudgePanelMember(provider="google", model=model))
        elif model.startswith("ollama/"):
            panel.append(JudgePanelMember(provider="ollama", model=model))
        else:
            panel.append(JudgePanelMember(provider="unknown", model=model))

    attestation = EvalAttestation(
        attestation_id=str(uuid.uuid4()),
        run_id=run_id,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        eval_suite=eval_suite,
        judge_panel=panel,
        scenarios_evaluated=scenarios_evaluated,
        scenarios_passed=scenarios_passed,
        overall_score=round(overall_score, 4),
        outcome=outcome,
        severity=severity,
        routing_recommendation=routing or [],
    )
    attestation.sign()
    return attestation


def save_attestation(attestation: EvalAttestation, output_path: str | Path) -> None:
    """Save attestation to JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(asdict(attestation), f, indent=2, default=str)
    logger.info("Attestation saved to %s", path)


def load_and_verify(attestation_path: str | Path) -> tuple[EvalAttestation, bool]:
    """Load an attestation from file and verify its signature."""
    path = Path(attestation_path)
    with path.open() as f:
        data = json.load(f)

    # Reconstruct panel members
    panel = [JudgePanelMember(**p) for p in data.pop("judge_panel", [])]
    attestation = EvalAttestation(**data, judge_panel=panel)
    is_valid = attestation.verify()
    return attestation, is_valid
