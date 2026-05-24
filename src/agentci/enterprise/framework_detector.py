"""
Framework detection for agent projects.

Scans Python files in a project directory to identify:
- Which LLM/agent framework is in use
- The likely agent entry point
- Recommended configuration defaults
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Import patterns → framework ID
_IMPORT_PATTERNS: list[tuple[str, str]] = [
    (r"from\s+langchain", "langchain"),
    (r"import\s+langchain", "langchain"),
    (r"from\s+llama_index", "llama_index"),
    (r"import\s+llama_index", "llama_index"),
    (r"from\s+crewai", "crewai"),
    (r"import\s+crewai", "crewai"),
    (r"from\s+autogen", "autogen"),
    (r"import\s+autogen", "autogen"),
    (r"from\s+openai", "openai"),
    (r"import\s+openai", "openai"),
    (r"from\s+anthropic", "anthropic"),
    (r"import\s+anthropic", "anthropic"),
    (r"from\s+google\.genai", "google"),
    (r"import\s+google\.genai", "google"),
    (r"import\s+requests", "raw_http"),
    (r"import\s+httpx", "raw_http"),
]

# Framework → recommended config
_FRAMEWORK_DEFAULTS: dict[str, dict] = {
    "langchain": {
        "agent_function": "invoke",
        "description": "LangChain agent detected",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.5-pro"],
    },
    "llama_index": {
        "agent_function": "query",
        "description": "LlamaIndex agent detected",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514"],
    },
    "crewai": {
        "agent_function": "kickoff",
        "description": "CrewAI agent detected",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514"],
    },
    "autogen": {
        "agent_function": "run",
        "description": "AutoGen agent detected",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514"],
    },
    "openai": {
        "agent_function": "run",
        "description": "OpenAI SDK agent detected",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514"],
    },
    "anthropic": {
        "agent_function": "run",
        "description": "Anthropic SDK agent detected",
        "recommended_judges": ["claude-sonnet-4-20250514", "gpt-4o"],
    },
    "google": {
        "agent_function": "run",
        "description": "Google GenAI agent detected",
        "recommended_judges": ["gemini-2.5-pro", "gpt-4o"],
    },
    "raw_http": {
        "agent_function": "run",
        "description": "HTTP-based agent detected (requests/httpx)",
        "recommended_judges": ["gpt-4o", "claude-sonnet-4-20250514"],
    },
}

# Priority order — first match with higher specificity wins
_FRAMEWORK_PRIORITY = [
    "langchain", "llama_index", "crewai", "autogen",
    "openai", "anthropic", "google", "raw_http",
]


@dataclass
class DetectionResult:
    """Result of framework detection."""
    frameworks: dict[str, int] = field(default_factory=dict)  # framework → file count
    primary_framework: str = "unknown"
    agent_candidates: list[str] = field(default_factory=list)
    recommended_entry: str = "./agent.py"
    recommended_function: str = "run"
    description: str = "No framework detected"

    @property
    def detected(self) -> bool:
        return self.primary_framework != "unknown"


def detect_framework(project_dir: str | Path, max_files: int = 200) -> DetectionResult:
    """
    Scan a project directory for agent framework usage.

    Args:
        project_dir: Root directory to scan.
        max_files: Maximum Python files to scan (performance guard).

    Returns:
        DetectionResult with identified frameworks and recommendations.
    """
    root = Path(project_dir)
    result = DetectionResult()
    framework_counts: dict[str, int] = {}
    agent_files: list[str] = []

    # Collect Python files, skip venv/node_modules/hidden dirs
    py_files: list[Path] = []
    for p in root.rglob("*.py"):
        rel = str(p.relative_to(root))
        if any(skip in rel for skip in [
            "venv/", "env/", ".venv/", "node_modules/", "__pycache__/",
            ".git/", ".agentci/", "test_", "tests/", "setup.py",
        ]):
            continue
        py_files.append(p)
        if len(py_files) >= max_files:
            break

    compiled = [(re.compile(pat), fw) for pat, fw in _IMPORT_PATTERNS]

    for py_file in py_files:
        try:
            content = py_file.read_text(errors="ignore")
        except Exception:
            continue

        file_frameworks: set[str] = set()
        for regex, fw in compiled:
            if regex.search(content):
                file_frameworks.add(fw)

        for fw in file_frameworks:
            framework_counts[fw] = framework_counts.get(fw, 0) + 1

        # Heuristic: files with "agent" in the name are likely entry points
        name_lower = py_file.stem.lower()
        if any(kw in name_lower for kw in ["agent", "bot", "assistant", "chat"]):
            agent_files.append(str(py_file.relative_to(root)))

        # Also check for if __name__ == "__main__" or def run/main
        if file_frameworks and (
            'if __name__' in content
            or re.search(r'def\s+(run|main|invoke|chat)\s*\(', content)
        ):
            rel_path = str(py_file.relative_to(root))
            if rel_path not in agent_files:
                agent_files.append(rel_path)

    result.frameworks = framework_counts
    result.agent_candidates = sorted(set(agent_files))[:5]  # top 5

    # Determine primary framework by priority
    for fw in _FRAMEWORK_PRIORITY:
        if fw in framework_counts:
            result.primary_framework = fw
            defaults = _FRAMEWORK_DEFAULTS[fw]
            result.recommended_function = defaults["agent_function"]
            result.description = defaults["description"]
            break

    # Pick best entry point
    if agent_files:
        # Prefer files with "agent" in the name
        agent_named = [f for f in agent_files if "agent" in f.lower()]
        result.recommended_entry = f"./{agent_named[0]}" if agent_named else f"./{agent_files[0]}"
    else:
        result.recommended_entry = "./agent.py"

    return result


def get_framework_defaults(framework: str) -> dict:
    """Get recommended configuration defaults for a framework."""
    return _FRAMEWORK_DEFAULTS.get(framework, _FRAMEWORK_DEFAULTS["openai"])
