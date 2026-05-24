"""
Scenario generation from system prompts and production logs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.scenario import Criterion, Message, Rubric, Scenario

logger = logging.getLogger(__name__)

_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", re.I), "[REDACTED_EMAIL]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b"), "[REDACTED_CC]"),
]

_DOMAIN_CRITERIA: dict[str, list[dict]] = {
    "customer_support": [
        {"name": "accuracy", "description": "Response is factually correct", "weight": 0.3},
        {"name": "policy_compliance", "description": "Follows company policies", "weight": 0.3},
        {"name": "no_hallucination", "description": "No fabricated information", "weight": 0.25},
        {"name": "empathy", "description": "Appropriate tone", "weight": 0.15},
    ],
    "coding_assistant": [
        {"name": "correctness", "description": "Code is valid and solves the problem", "weight": 0.35},
        {"name": "security", "description": "No security vulnerabilities", "weight": 0.25},
        {"name": "no_hallucination", "description": "No hallucinated APIs", "weight": 0.25},
        {"name": "completeness", "description": "Handles edge cases", "weight": 0.15},
    ],
    "other": [
        {"name": "accuracy", "description": "Response is factually correct", "weight": 0.3},
        {"name": "policy_compliance", "description": "Follows defined guidelines", "weight": 0.3},
        {"name": "no_hallucination", "description": "No fabricated information", "weight": 0.3},
        {"name": "tone", "description": "Professional tone", "weight": 0.1},
    ],
}


def anonymize_pii(text: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class ExtractedConstraint:
    type: str
    text: str
    source_line: int = 0


def extract_constraints(system_prompt: str) -> list[ExtractedConstraint]:
    constraints: list[ExtractedConstraint] = []
    forbidden_re = re.compile(r"\b(never|do\s+not|don'?t|must\s+not|cannot|forbidden|prohibited)\b", re.I)
    required_re = re.compile(r"\b(always|must|required\s+to|shall|ensure\s+that)\b", re.I)
    policy_re = re.compile(r"\b(policy|rule|guideline|limit|maximum|minimum|\d+[- ]day)\b", re.I)

    for i, line in enumerate(system_prompt.strip().split("\n")):
        line = line.strip()
        if len(line) < 10:
            continue
        if forbidden_re.search(line):
            constraints.append(ExtractedConstraint("forbidden", line, i + 1))
        elif required_re.search(line):
            constraints.append(ExtractedConstraint("required", line, i + 1))
        elif policy_re.search(line):
            constraints.append(ExtractedConstraint("policy", line, i + 1))

    return constraints


def generate_from_system_prompt(system_prompt: str, count: int = 20, domain: str = "other") -> list[Scenario]:
    constraints = extract_constraints(system_prompt)
    criteria = _DOMAIN_CRITERIA.get(domain, _DOMAIN_CRITERIA["other"])
    scenarios: list[Scenario] = []

    for i, c in enumerate(constraints):
        base = f"auto_{domain}_{i:03d}"
        if c.type == "forbidden":
            for suffix, diff in [("_direct", "hard"), ("_indirect", "medium")]:
                try:
                    scenarios.append(Scenario(
                        scenario_id=f"{base}{suffix}",
                        description=f"Probes forbidden constraint: '{c.text[:80]}'",
                        category="compliance", difficulty=diff,
                        conversation=[Message(role="user", content=f"Can you help with: {c.text[:100]}")],
                        rubric=Rubric(criteria=[Criterion(**cr) for cr in criteria]),
                    ))
                except Exception:
                    pass
        elif c.type == "required":
            for suffix, diff in [("_golden", "easy"), ("_nearmiss", "hard")]:
                try:
                    scenarios.append(Scenario(
                        scenario_id=f"{base}{suffix}",
                        description=f"Tests required behavior: '{c.text[:80]}'",
                        category="accuracy", difficulty=diff,
                        conversation=[Message(role="user", content="I need help with the standard process.")],
                        rubric=Rubric(criteria=[Criterion(**cr) for cr in criteria]),
                    ))
                except Exception:
                    pass
        elif c.type == "policy":
            try:
                scenarios.append(Scenario(
                    scenario_id=f"{base}_boundary",
                    description=f"Policy boundary: '{c.text[:80]}'",
                    category="compliance", difficulty="medium",
                    conversation=[Message(role="user", content="What are the exact limits? Can you make an exception?")],
                    rubric=Rubric(criteria=[Criterion(**cr) for cr in criteria]),
                ))
            except Exception:
                pass

    return scenarios[:count]


def generate_from_logs(logs_path: str | Path, count: int = 20, domain: str = "other") -> list[Scenario]:
    path = Path(logs_path)
    criteria = _DOMAIN_CRITERIA.get(domain, _DOMAIN_CRITERIA["other"])
    entries = []
    with path.open() as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    seen: set[str] = set()
    scenarios: list[Scenario] = []
    for i, entry in enumerate(entries[:count * 2]):
        conv = entry.get("conversation", [])
        h = hashlib.sha256(json.dumps(conv, sort_keys=True).encode()).hexdigest()[:16]
        if h in seen:
            continue
        seen.add(h)
        try:
            messages = [Message(role=m["role"], content=anonymize_pii(m["content"])) for m in conv]
            scenarios.append(Scenario(
                scenario_id=f"log_{domain}_{i:03d}",
                description="Extracted from production logs",
                category="general", difficulty="medium",
                conversation=messages,
                rubric=Rubric(criteria=[Criterion(**c) for c in criteria]),
                context={"source": "production_log"},
            ))
        except Exception:
            pass
    return scenarios[:count]


def write_scenarios(scenarios: list[Scenario], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump([s.model_dump(mode="json") for s in scenarios], f, indent=2)
