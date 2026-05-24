"""
GitHub Actions workflow generator.

Generates .github/workflows/agentci.yml for teams that want
evals running on GitHub's own runners with zero server infrastructure.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def generate_actions_workflow(
    trigger_paths: list[str] | None = None,
    python_version: str = "3.12",
    judge_provider: str = "openai",
    scenarios_path: str = ".agentci/scenarios.json",
    agent_path: str = "./agent.py",
    agent_function: str = "run",
    threshold: float = 0.85,
) -> str:
    """Generate a GitHub Actions workflow YAML string."""
    paths = trigger_paths or ["**/*.py"]

    workflow = {
        "name": "AgentCI Eval",
        "on": {
            "pull_request": {
                "branches": ["main", "master"],
                "paths": paths,
            },
        },
        "permissions": {
            "checks": "write",
            "pull-requests": "write",
            "contents": "read",
        },
        "jobs": {
            "eval": {
                "runs-on": "ubuntu-latest",
                "timeout-minutes": 15,
                "steps": [
                    {"name": "Checkout", "uses": "actions/checkout@v4"},
                    {
                        "name": "Setup Python",
                        "uses": "actions/setup-python@v5",
                        "with": {"python-version": python_version},
                    },
                    {
                        "name": "Install AgentCI",
                        "run": "pip install agentci",
                    },
                    {
                        "name": "Validate Config",
                        "run": "agentci validate",
                    },
                    {
                        "name": "Run Evaluation",
                        "run": (
                            f"agentci eval "
                            f"--agent {agent_path} "
                            f"--scenarios {scenarios_path} "
                            f"--function {agent_function} "
                            f"--judges 3 "
                            f"--threshold {threshold} "
                            f"--format json"
                        ),
                        "env": _env_block(judge_provider),
                    },
                ],
            },
        },
    }

    return yaml.dump(workflow, default_flow_style=False, sort_keys=False)


def _env_block(provider: str) -> dict[str, str]:
    """Generate the env block mapping secrets to env vars."""
    env: dict[str, str] = {}
    if provider in ("openai", "all"):
        env["OPENAI_API_KEY"] = "${{ secrets.OPENAI_API_KEY }}"
    if provider in ("anthropic", "all"):
        env["ANTHROPIC_API_KEY"] = "${{ secrets.ANTHROPIC_API_KEY }}"
    if provider in ("google", "all"):
        env["GOOGLE_API_KEY"] = "${{ secrets.GOOGLE_API_KEY }}"
    if not env:
        env["OPENAI_API_KEY"] = "${{ secrets.OPENAI_API_KEY }}"
    return env


def write_actions_workflow(
    output_dir: str | Path = ".",
    **kwargs,
) -> Path:
    """Generate and write the workflow file."""
    root = Path(output_dir)
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    path = workflow_dir / "agentci.yml"

    content = generate_actions_workflow(**kwargs)
    path.write_text(content)
    logger.info("GitHub Actions workflow written to %s", path)
    return path
