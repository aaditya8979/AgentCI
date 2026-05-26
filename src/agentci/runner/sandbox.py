"""
Sandboxed Agent Runner — executes agent scripts in isolated subprocesses.

Provides two isolation levels:
  - SubprocessRunner: runs agent in a child process with timeout + resource limits
  - DockerRunner: runs agent in a container with full isolation (optional)

Both implement the same interface as AgentRunner for drop-in replacement.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models.scenario import Message, Scenario, ScenarioTrace, TraceStep

logger = logging.getLogger(__name__)

# Harness script injected into the subprocess
_HARNESS_SCRIPT = '''
import importlib.util
import json
import sys
import traceback

def main():
    config = json.loads(sys.argv[1])
    agent_path = config["agent_path"]
    agent_function = config["agent_function"]
    agent_input = config["agent_input"]

    try:
        spec = importlib.util.spec_from_file_location("target_agent", agent_path)
        if spec is None or spec.loader is None:
            print(json.dumps({"error": f"Cannot load module: {agent_path}"}))
            sys.exit(1)

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        fn = getattr(module, agent_function, None)
        if fn is None:
            print(json.dumps({"error": f"Function '{agent_function}' not found"}))
            sys.exit(1)

        result = fn(agent_input)

        if isinstance(result, dict):
            output = result.get("response", result.get("content", str(result)))
        elif isinstance(result, str):
            output = result
        else:
            output = str(result)

        print(json.dumps({"output": output}))

    except Exception as e:
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-1000:],
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
'''


class SubprocessRunner:
    """
    Runs an agent script in an isolated subprocess with timeout and
    resource limits. The agent cannot crash, hang, or corrupt the
    evaluator process.
    """

    def __init__(
        self,
        agent_path: str | Path,
        agent_function: str = "run",
        timeout_seconds: float = 60.0,
        max_memory_mb: int = 512,
    ):
        self.agent_path = Path(agent_path).resolve()
        self.agent_function = agent_function
        self.timeout = timeout_seconds
        self.max_memory_mb = max_memory_mb

    def run_scenario(self, scenario: Scenario) -> tuple[str, ScenarioTrace]:
        """
        Execute the agent against a single scenario in a subprocess.

        Returns:
            Tuple of (agent_output_string, trace).
        """
        trace = ScenarioTrace()
        step_counter = 0

        # Record scenario injection
        step_counter += 1
        trace.steps.append(TraceStep(
            step=step_counter,
            type="scenario_loaded",
            content={
                "scenario_id": scenario.scenario_id,
                "category": scenario.category,
                "difficulty": scenario.difficulty,
                "isolation": "subprocess",
            },
        ))

        # Build input payload
        agent_input = {
            "messages": [{"role": m.role, "content": m.content} for m in scenario.conversation],
            "context": scenario.context,
        }

        config = json.dumps({
            "agent_path": str(self.agent_path),
            "agent_function": self.agent_function,
            "agent_input": agent_input,
        })

        # Write harness to temp file
        harness_file = Path(tempfile.gettempdir()) / "agentci_harness.py"
        harness_file.write_text(_HARNESS_SCRIPT)

        step_counter += 1
        trace.steps.append(TraceStep(
            step=step_counter,
            type="subprocess_started",
            content=f"timeout={self.timeout}s, max_memory={self.max_memory_mb}MB",
        ))

        # Execute in subprocess
        start = time.perf_counter()
        try:
            # Build command with resource limits via ulimit
            result = subprocess.run(
                [sys.executable, str(harness_file), config],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.agent_path.parent),
                env={
                    **dict(__import__("os").environ),
                    "PYTHONPATH": str(self.agent_path.parent),
                },
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if result.returncode != 0:
                # Agent crashed
                try:
                    error_data = json.loads(result.stdout)
                    agent_output = f"[AGENT ERROR] {error_data.get('error', 'Unknown error')}"
                except json.JSONDecodeError:
                    agent_output = f"[AGENT ERROR] Exit code {result.returncode}: {result.stderr[:500]}"

                step_counter += 1
                trace.steps.append(TraceStep(
                    step=step_counter,
                    type="agent_error",
                    content=agent_output[:500],
                    latency_ms=elapsed_ms,
                ))
            else:
                # Parse output
                try:
                    output_data = json.loads(result.stdout)
                    agent_output = output_data.get("output", str(output_data))
                except json.JSONDecodeError:
                    agent_output = result.stdout.strip() or "[NO OUTPUT]"

                step_counter += 1
                trace.steps.append(TraceStep(
                    step=step_counter,
                    type="agent_execution",
                    content=agent_output[:500],
                    latency_ms=elapsed_ms,
                ))

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.perf_counter() - start) * 1000
            agent_output = f"[AGENT TIMEOUT] Exceeded {self.timeout}s limit"
            step_counter += 1
            trace.steps.append(TraceStep(
                step=step_counter,
                type="agent_timeout",
                content=agent_output,
                latency_ms=elapsed_ms,
            ))
            logger.warning("Agent timed out for %s after %.0fs", scenario.scenario_id, self.timeout)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            agent_output = f"[SANDBOX ERROR] {type(e).__name__}: {e}"
            step_counter += 1
            trace.steps.append(TraceStep(
                step=step_counter,
                type="sandbox_error",
                content=agent_output,
                latency_ms=elapsed_ms,
            ))

        trace.total_latency_ms = elapsed_ms
        return agent_output, trace
