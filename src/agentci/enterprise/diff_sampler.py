"""
Diff-aware scenario sampling.

Analyzes PR diffs to determine which scenarios are most likely
to be affected, enabling targeted evaluation that reduces cost
and runtime while maintaining regression detection accuracy.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FileCategory(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    FEW_SHOT = "few_shot_examples"
    RAG_CONFIG = "rag_config"
    TOOL_DEFINITIONS = "tool_definitions"
    AGENT_LOGIC = "agent_logic"
    INFRASTRUCTURE = "infrastructure"
    TEST = "test"
    OTHER = "other"


@dataclass
class DiffFile:
    """A single changed file from a PR diff."""
    path: str
    additions: int = 0
    deletions: int = 0
    category: FileCategory = FileCategory.OTHER
    content_snippet: str = ""


@dataclass
class SamplingResult:
    """Result of diff-aware scenario sampling."""
    recommended_scenarios: list[str]  # scenario IDs to run
    skipped_scenarios: list[str]  # scenario IDs safe to skip
    reasoning: dict[str, str]  # scenario_id → why it was included/excluded
    diff_categories: list[FileCategory]
    confidence: float = 0.8


# File path patterns → category
_CATEGORY_PATTERNS: list[tuple[str, FileCategory]] = [
    (r"(system[_-]?prompt|instructions|persona)", FileCategory.SYSTEM_PROMPT),
    (r"(few[_-]?shot|examples|shots)", FileCategory.FEW_SHOT),
    (r"(rag|retriev|vector|embed|index)", FileCategory.RAG_CONFIG),
    (r"(tool|function[_-]?call|action)", FileCategory.TOOL_DEFINITIONS),
    (r"(agent|chain|pipeline|handler|bot)", FileCategory.AGENT_LOGIC),
    (r"(docker|k8s|helm|deploy|infra|ci|cd)", FileCategory.INFRASTRUCTURE),
    (r"(test_|_test\.py|spec\.)", FileCategory.TEST),
]

# Category → which scenario dimensions are affected
_CATEGORY_TO_DIMENSIONS: dict[FileCategory, list[str]] = {
    FileCategory.SYSTEM_PROMPT: ["safety", "compliance", "accuracy", "tone"],
    FileCategory.FEW_SHOT: ["accuracy", "tone"],
    FileCategory.RAG_CONFIG: ["accuracy", "hallucination"],
    FileCategory.TOOL_DEFINITIONS: ["tool_use", "accuracy"],
    FileCategory.AGENT_LOGIC: ["accuracy", "safety", "tool_use", "compliance"],
    FileCategory.INFRASTRUCTURE: [],
    FileCategory.TEST: [],
    FileCategory.OTHER: [],
}


def categorize_file(path: str) -> FileCategory:
    """Categorize a changed file based on its path."""
    path_lower = path.lower()
    for pattern, category in _CATEGORY_PATTERNS:
        if re.search(pattern, path_lower):
            return category
    if path_lower.endswith(".py"):
        return FileCategory.AGENT_LOGIC
    return FileCategory.OTHER


def parse_diff(diff_text: str) -> list[DiffFile]:
    """Parse a unified diff into DiffFile objects."""
    files: list[DiffFile] = []
    current_file: str = ""
    adds = 0
    dels = 0
    snippet_lines: list[str] = []

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            if current_file:
                files.append(DiffFile(
                    path=current_file,
                    additions=adds,
                    deletions=dels,
                    category=categorize_file(current_file),
                    content_snippet="\n".join(snippet_lines[:10]),
                ))
            # Extract file path
            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else ""
            adds = 0
            dels = 0
            snippet_lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            adds += 1
            snippet_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1

    if current_file:
        files.append(DiffFile(
            path=current_file,
            additions=adds,
            deletions=dels,
            category=categorize_file(current_file),
            content_snippet="\n".join(snippet_lines[:10]),
        ))

    return files


def sample_scenarios(
    diff_files: list[DiffFile],
    all_scenario_ids: list[str],
    scenario_metadata: dict[str, dict] | None = None,
    min_scenarios: int = 10,
    confidence_threshold: float = 0.92,
) -> SamplingResult:
    """
    Select which scenarios to run based on diff analysis.

    Args:
        diff_files: Parsed diff files with categories.
        all_scenario_ids: All available scenario IDs.
        scenario_metadata: Optional {scenario_id: {category, dimension, difficulty}}.
        min_scenarios: Always run at least this many.
        confidence_threshold: Skip remainder if top-K all pass above this.
    """
    metadata = scenario_metadata or {}

    # Determine affected dimensions
    affected_dims: set[str] = set()
    diff_cats: list[FileCategory] = []
    for f in diff_files:
        diff_cats.append(f.category)
        affected_dims.update(_CATEGORY_TO_DIMENSIONS.get(f.category, []))

    if not affected_dims:
        # Infrastructure-only or test-only change — run minimum set
        selected = all_scenario_ids[:min_scenarios]
        skipped = all_scenario_ids[min_scenarios:]
        return SamplingResult(
            recommended_scenarios=selected,
            skipped_scenarios=skipped,
            reasoning={s: "included in minimum set" for s in selected},
            diff_categories=diff_cats,
            confidence=0.95,
        )

    # Score each scenario by relevance to the diff
    scored: list[tuple[str, float, str]] = []  # (id, score, reason)
    for sid in all_scenario_ids:
        meta = metadata.get(sid, {})
        dim = meta.get("dimension", "accuracy")
        cat = meta.get("category", "general")
        diff_str = meta.get("difficulty", "medium")

        relevance = 0.0
        reason_parts: list[str] = []

        if dim in affected_dims:
            relevance += 0.6
            reason_parts.append(f"dimension '{dim}' affected by diff")
        if any(cat in str(fc.value) for fc in diff_cats):
            relevance += 0.3
            reason_parts.append("category matches diff area")
        if diff_str == "hard":
            relevance += 0.1
            reason_parts.append("high difficulty")

        # If no metadata, give moderate relevance
        if not meta:
            relevance = 0.4
            reason_parts = ["no metadata — included by default"]

        scored.append((sid, relevance, "; ".join(reason_parts) if reason_parts else "low relevance"))

    # Sort by relevance
    scored.sort(key=lambda x: x[1], reverse=True)

    # Select: all with relevance > 0.3, minimum min_scenarios
    selected_ids: list[str] = []
    skipped_ids: list[str] = []
    reasoning: dict[str, str] = {}

    for sid, score, reason in scored:
        if score > 0.3 or len(selected_ids) < min_scenarios:
            selected_ids.append(sid)
            reasoning[sid] = f"selected (relevance={score:.2f}): {reason}"
        else:
            skipped_ids.append(sid)
            reasoning[sid] = f"skipped (relevance={score:.2f}): {reason}"

    return SamplingResult(
        recommended_scenarios=selected_ids,
        skipped_scenarios=skipped_ids,
        reasoning=reasoning,
        diff_categories=diff_cats,
        confidence=confidence_threshold,
    )
