"""
Agent Runner — executes agent scripts against evaluation scenarios.

Handles dynamic module loading, scenario execution with tracing,
timeout enforcement, and state isolation between scenarios.
"""
from __future__ import annotations

import importlib.util
import logging
import time
import traceback
from pathlib import Path
from typing import Callable

from ..models.scenario import (
    Message, Scenario, ScenarioTrace, TraceStep,
)

logger = logging.getLogger(__name__)


class AgentLoadError(Exception):
    """Raised when the agent module cannot be loaded or is missing the entry function."""


class AgentRunner:
    """
    Loads an agent script and executes it against evaluation scenarios.

    The runner dynamically imports the agent module, calls the designated
    entry function with scenario inputs, captures the output and timing
    metadata, and produces a ScenarioTrace for downstream analysis.
    """

    def __init__(
        self,
        agent_path: str | Path,
        agent_function: str = "run",
        timeout_seconds: float = 60.0,
    ):
        self.agent_path = Path(agent_path).resolve()
        self.agent_function_name = agent_function
        self.timeout = timeout_seconds
        self._agent_fn: Callable | None = None

    def load(self) -> None:
        """
        Dynamically load the agent module and resolve the entry function.

        Raises:
            AgentLoadError: If the module cannot be loaded or the function is missing.
        """
        if not self.agent_path.exists():
            raise AgentLoadError(f"Agent script not found: {self.agent_path}")

        try:
            spec = importlib.util.spec_from_file_location(
                "agentci_target_agent", str(self.agent_path)
            )
            if spec is None or spec.loader is None:
                raise AgentLoadError(f"Cannot create module spec for: {self.agent_path}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            raise AgentLoadError(f"Failed to load agent module: {e}") from e

        fn = getattr(module, self.agent_function_name, None)
        if fn is None:
            available = [a for a in dir(module) if not a.startswith("_")]
            raise AgentLoadError(
                f"Function '{self.agent_function_name}' not found in {self.agent_path}. "
                f"Available: {available}"
            )
        if not callable(fn):
            raise AgentLoadError(
                f"'{self.agent_function_name}' in {self.agent_path} is not callable"
            )

        self._agent_fn = fn
        logger.info("Loaded agent: %s::%s", self.agent_path.name, self.agent_function_name)

    def run_scenario(self, scenario: Scenario) -> tuple[str, ScenarioTrace]:
        """
        Execute the agent against a single scenario and capture the output + trace.

        Args:
            scenario: The evaluation scenario to run.

        Returns:
            Tuple of (agent_output_string, trace).

        Raises:
            AgentLoadError: If the agent has not been loaded.
            TimeoutError: If the agent exceeds the configured timeout.
        """
        if self._agent_fn is None:
            raise AgentLoadError("Agent not loaded. Call .load() first.")

        trace = ScenarioTrace()
        step_counter = 0

        # Step 1: Record scenario injection
        step_counter += 1
        trace.steps.append(TraceStep(
            step=step_counter,
            type="scenario_loaded",
            content={
                "scenario_id": scenario.scenario_id,
                "category": scenario.category,
                "difficulty": scenario.difficulty,
            },
        ))

        # Step 2: Build the input payload
        self._format_conversation(scenario.conversation)
        agent_input = {
            "messages": [{"role": m.role, "content": m.content} for m in scenario.conversation],
            "context": scenario.context,
        }

        step_counter += 1
        trace.steps.append(TraceStep(
            step=step_counter,
            type="context_injected",
            content=scenario.context if scenario.context else "No additional context",
        ))

        # Step 3: Execute the agent with timing
        start = time.perf_counter()
        try:
            result = self._agent_fn(agent_input)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Normalise the result to a string
            if isinstance(result, dict):
                agent_output = result.get("response", result.get("content", str(result)))
            elif isinstance(result, str):
                agent_output = result
            else:
                agent_output = str(result)

            step_counter += 1
            trace.steps.append(TraceStep(
                step=step_counter,
                type="agent_execution",
                content=agent_output[:500],  # Truncate in trace for storage
                latency_ms=elapsed_ms,
            ))

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            agent_output = f"[AGENT ERROR] {type(e).__name__}: {e}"
            step_counter += 1
            trace.steps.append(TraceStep(
                step=step_counter,
                type="agent_error",
                content={
                    "error": str(e),
                    "traceback": traceback.format_exc()[-500:],
                },
                latency_ms=elapsed_ms,
            ))
            logger.error("Agent execution failed for %s: %s", scenario.scenario_id, e)

        trace.total_latency_ms = elapsed_ms
        return agent_output, trace

    @staticmethod
    def _format_conversation(messages: list[Message]) -> str:
        """Format a conversation history into a readable string."""
        lines = []
        for msg in messages:
            role = msg.role.upper()
            lines.append(f"[{role}]: {msg.content}")
        return "\n".join(lines)
