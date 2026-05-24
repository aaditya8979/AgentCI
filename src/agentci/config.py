"""
Configuration model for AgentCI.

Parses .agentci.yml files that define how evaluations run for a project.
Supports scenario paths, judge configuration, baseline strategy, and
trigger conditions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class JudgeConfig(BaseModel):
    """Configuration for the judge panel."""
    models: list[str] = Field(
        default=["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.5-pro"],
        description="Judge model identifiers for the consensus panel",
    )
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    ija_threshold: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description="Inter-Judge Agreement threshold below which tiebreaker is invoked",
    )
    tiebreaker_model: str = Field(default="gpt-4o")


class BaselineConfig(BaseModel):
    """Configuration for baseline comparison strategy."""
    min_score: float = Field(default=0.85, ge=0.0, le=1.0)
    comparison: str = Field(
        default="last_5_runs",
        description="Baseline comparison strategy: last_N_runs or fixed",
    )
    statistical_test: str = Field(default="welch_t_test")
    significance_level: float = Field(default=0.05, ge=0.001, le=0.5)
    min_samples: int = Field(
        default=3, ge=2,
        description="Minimum baseline samples required before statistical testing activates",
    )


class TriggerConfig(BaseModel):
    """Configuration for which file changes trigger evals."""
    paths: list[str] = Field(
        default=["**/*.py"],
        description="Glob patterns for files that trigger evaluation when changed",
    )
    eval_suite: str = Field(
        default="full",
        description="Which scenario suite to run: 'full' or a category name",
    )


class AgentCIConfig(BaseModel):
    """Root configuration model parsed from .agentci.yml."""
    version: str = Field(default="1")
    scenarios_path: str = Field(
        default="./eval/scenarios",
        description="Directory containing scenario JSON files",
    )
    agent_entry: str = Field(
        default="./agent.py",
        description="Path to the agent script or module",
    )
    agent_function: str = Field(
        default="run",
        description="Function name inside the agent module to call",
    )
    judges: JudgeConfig = Field(default_factory=JudgeConfig)
    baselines: BaselineConfig = Field(default_factory=BaselineConfig)
    triggers: TriggerConfig = Field(default_factory=TriggerConfig)
    num_runs: int = Field(
        default=3, ge=1, le=20,
        description="Number of times to run each scenario for statistical stability",
    )
    parallel: bool = Field(
        default=True,
        description="Whether to run scenarios in parallel",
    )
    max_workers: int = Field(default=4, ge=1, le=32)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentCIConfig":
        """Load configuration from a YAML file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")

        with p.open("r") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        return cls(**data)

    @classmethod
    def default(cls) -> "AgentCIConfig":
        """Return default configuration."""
        return cls()

    def to_yaml(self, path: str | Path) -> None:
        """Write configuration to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            yaml.dump(
                self.model_dump(mode="json"),
                f,
                default_flow_style=False,
                sort_keys=False,
            )
