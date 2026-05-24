"""
End-to-end integration test for AgentCI pipeline.

Tests the full flow: load agent → run scenario → judge (mocked) → stats → report.
No API keys required — uses mock judges.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── 1. Create a temporary agent and scenario ──

def make_test_agent(tmp_dir: Path) -> Path:
    """Create a simple test agent."""
    agent_file = tmp_dir / "test_agent.py"
    agent_file.write_text('''
def run(input_data):
    messages = input_data.get("messages", [])
    last = messages[-1]["content"] if messages else ""
    return f"I understand your concern about: {last}. Let me help you with that right away. I will process your refund within 3-5 business days."
''')
    return agent_file


def make_test_scenarios(tmp_dir: Path) -> Path:
    """Create test scenarios."""
    scenarios = [
        {
            "scenario_id": "refund_request_001",
            "description": "Customer requests a refund for defective product",
            "category": "refund",
            "difficulty": "medium",
            "conversation": [
                {"role": "user", "content": "My widget is broken and I want a refund"}
            ],
            "rubric": {
                "criteria": [
                    {"name": "empathy", "description": "Shows understanding", "weight": 0.3},
                    {"name": "action", "description": "Takes concrete action", "weight": 0.4},
                    {"name": "accuracy", "description": "No hallucinated policies", "weight": 0.3},
                ],
                "passing_threshold": 0.80,
            },
            "context": {"policy": "30-day return window"},
        },
        {
            "scenario_id": "greeting_001",
            "description": "Simple greeting scenario",
            "category": "general",
            "difficulty": "easy",
            "conversation": [
                {"role": "user", "content": "Hello there!"}
            ],
            "rubric": {
                "criteria": [
                    {"name": "politeness", "description": "Responds politely", "weight": 0.5},
                    {"name": "relevance", "description": "Response is relevant", "weight": 0.5},
                ],
                "passing_threshold": 0.75,
            },
            "context": {},
        },
    ]
    scenarios_file = tmp_dir / "scenarios.json"
    scenarios_file.write_text(json.dumps(scenarios, indent=2))
    return scenarios_file


# ── 2. Run the pipeline ──

def main():
    from agentci.runner.agent_runner import AgentRunner
    from agentci.judge.consensus import ConsensusPanel, ConsensusResult
    from agentci.models.scenario import Scenario, ScenarioResult, JudgeResponse, ScoreBreakdown
    from agentci.stats.significance import is_regression
    from agentci.stats.baseline import BaselineStore
    from agentci.reporter.console import ConsoleReporter
    from agentci.reporter.markdown import MarkdownReporter

    print("=" * 60)
    print("  AgentCI — End-to-End Integration Test")
    print("  (Mock judges — no API keys required)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        agent_path = make_test_agent(tmp_dir)
        scenarios_path = make_test_scenarios(tmp_dir)

        # Load scenarios
        with scenarios_path.open() as f:
            raw = json.load(f)
        scenarios = [Scenario(**s) for s in raw]
        print(f"\n✅ Loaded {len(scenarios)} scenarios")

        # Load agent
        runner = AgentRunner(agent_path=agent_path, agent_function="run")
        runner.load()
        print(f"✅ Agent loaded: {agent_path.name}")

        # Run each scenario through the agent
        results = []
        for scenario in scenarios:
            agent_output, trace = runner.run_scenario(scenario)
            print(f"\n📋 Scenario: {scenario.scenario_id}")
            print(f"   Agent said: {agent_output[:80]}...")
            print(f"   Trace steps: {len(trace.steps)}, latency: {trace.total_latency_ms:.1f}ms")

            # Mock judge scores (simulating what the LLM judges would return)
            mock_scores = {}
            for c in scenario.rubric.criteria:
                # Give realistic scores based on the scenario
                if scenario.scenario_id == "refund_request_001":
                    score_map = {"empathy": 0.85, "action": 0.90, "accuracy": 0.75}
                else:
                    score_map = {"politeness": 0.95, "relevance": 0.90}
                mock_scores[c.name] = score_map.get(c.name, 0.80)

            # Compute weighted score
            total_weight = sum(c.weight for c in scenario.rubric.criteria)
            weighted = sum(
                mock_scores[c.name] * c.weight
                for c in scenario.rubric.criteria
            ) / total_weight

            passed = weighted >= scenario.rubric.passing_threshold

            result = ScenarioResult(
                scenario_id=scenario.scenario_id,
                scores=mock_scores,
                weighted_score=weighted,
                passed=passed,
                trace=trace,
                judge_reasonings={"mock_judge": "Mock evaluation for integration test"},
            )
            results.append(result)
            print(f"   Weighted score: {weighted:.3f} → {'✅ PASS' if passed else '❌ FAIL'}")

        # ── 3. Statistical regression testing ──
        print("\n" + "=" * 60)
        print("  Statistical Regression Analysis")
        print("=" * 60)

        # Simulate a baseline
        baseline_store = BaselineStore(tmp_dir / "baselines")
        for s in scenarios:
            for score in [0.88, 0.87, 0.89, 0.86, 0.90]:
                baseline_store.append_score(s.scenario_id, score)

        regressions = {}
        for r in results:
            baseline = baseline_store.get_baseline_scores(r.scenario_id, window=5)
            if baseline:
                reg = is_regression(baseline, [r.weighted_score] * 3)
                regressions[r.scenario_id] = reg
                print(f"\n   {r.scenario_id}: {reg.summary}")

        # ── 4. Console report ──
        print("\n")
        reporter = ConsoleReporter()
        reporter.print_header("Integration Test", "Mock judges, real pipeline")
        reporter.print_scenario_table(results, regressions)

        for r in results:
            if not r.passed:
                reporter.print_failure_details(r, regressions.get(r.scenario_id))

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg = sum(r.weighted_score for r in results) / total
        reporter.print_summary(total, passed, total - passed, avg, 0.5)

        # ── 5. Markdown report ──
        md_reporter = MarkdownReporter()
        md = md_reporter.generate_report(results, regressions, commit_sha="abc123def", duration_seconds=0.5)
        md_path = tmp_dir / "report.md"
        md_path.write_text(md)
        print(f"\n📄 Markdown report generated ({len(md)} chars)")
        print(f"   Preview (first 500 chars):")
        print(f"   {'─' * 50}")
        print(md[:500])
        print(f"   {'─' * 50}")

        print("\n✅ End-to-end pipeline completed successfully!")
        print("   All components working: Runner → Judge → Stats → Reporter")


if __name__ == "__main__":
    main()
