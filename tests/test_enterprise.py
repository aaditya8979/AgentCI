"""
Tests for the enterprise severity classifier and agent adapters.
"""
import pytest

from agentci.enterprise.severity import (
    SeverityTier,
    RecommendedAction,
    classify_severity,
)
from agentci.runner.adapter import (
    AgentInput,
    AgentOutput,
    PythonFunctionAdapter,
)


class TestSeverityClassifier:
    """Tests for the 5-tier severity classifier."""

    def test_cosmetic_regression(self):
        result = classify_severity(
            criterion_scores={"tone": 0.70},
            baseline_scores={"tone": 0.85},
            criterion_metadata={"tone": {"dimension": "tone", "reversibility": "immediate"}},
        )
        assert result.tier == SeverityTier.COSMETIC
        assert result.action == RecommendedAction.WARN
        assert "author" in result.routing

    def test_safety_regression_escalates(self):
        result = classify_severity(
            criterion_scores={"harmful_content": 0.30},
            baseline_scores={"harmful_content": 0.95},
            criterion_metadata={
                "harmful_content": {
                    "dimension": "safety",
                    "reversibility": "critical",
                    "blast_radius": "cross_domain",
                }
            },
        )
        assert result.tier == SeverityTier.SAFETY
        assert result.action == RecommendedAction.BLOCK_AND_ESCALATE
        assert "security_team" in result.routing
        assert "on_call" in result.routing

    def test_compliance_regression(self):
        result = classify_severity(
            criterion_scores={"legal_accuracy": 0.42},
            baseline_scores={"legal_accuracy": 0.94},
            criterion_metadata={
                "legal_accuracy": {
                    "dimension": "compliance",
                    "reversibility": "critical",
                }
            },
        )
        assert result.tier == SeverityTier.COMPLIANCE
        assert result.action == RecommendedAction.BLOCK_AND_ESCALATE
        assert "legal_team" in result.routing

    def test_no_regression_stays_cosmetic(self):
        result = classify_severity(
            criterion_scores={"tone": 0.92},
            baseline_scores={"tone": 0.90},
        )
        # No significant delta → stays at default COSMETIC
        assert result.tier == SeverityTier.COSMETIC
        assert result.worst_score_delta == 0.0

    def test_large_delta_escalates_to_functional(self):
        result = classify_severity(
            criterion_scores={"accuracy": 0.40},
            baseline_scores={"accuracy": 0.90},
            criterion_metadata={"accuracy": {"dimension": "accuracy"}},
        )
        # 0.50 delta > 0.30 threshold → escalated to FUNCTIONAL
        assert result.tier.value >= SeverityTier.FUNCTIONAL.value

    def test_critical_reversibility_escalates(self):
        result = classify_severity(
            criterion_scores={"tool_use": 0.50},
            baseline_scores={"tool_use": 0.85},
            criterion_metadata={
                "tool_use": {
                    "dimension": "tool_use",
                    "reversibility": "critical",
                }
            },
        )
        assert result.tier.value >= SeverityTier.SAFETY.value

    def test_explanation_contains_details(self):
        result = classify_severity(
            criterion_scores={"quality": 0.60},
            baseline_scores={"quality": 0.90},
            criterion_metadata={"quality": {"dimension": "accuracy"}},
        )
        assert "quality" in result.explanation
        assert "dropped by" in result.explanation

    def test_multi_dimension_regression(self):
        result = classify_severity(
            criterion_scores={"tone": 0.60, "safety": 0.40},
            baseline_scores={"tone": 0.90, "safety": 0.95},
            criterion_metadata={
                "tone": {"dimension": "tone"},
                "safety": {"dimension": "safety", "reversibility": "critical"},
            },
        )
        # Safety dimension should dominate
        assert result.tier.value >= SeverityTier.SAFETY.value
        assert len(result.affected_dimensions) == 2


class TestPythonFunctionAdapter:
    """Tests for the PythonFunction adapter."""

    def test_basic_function(self):
        def my_agent(input_data):
            return f"Response: {input_data['messages'][-1]['content']}"

        adapter = PythonFunctionAdapter(my_agent)
        inp = AgentInput(conversation=[{"role": "user", "content": "Hello"}])
        out = adapter.run(inp)
        assert isinstance(out, AgentOutput)
        assert "Hello" in out.content

    def test_health_check(self):
        adapter = PythonFunctionAdapter(lambda x: "ok")
        assert adapter.health_check() is True

    def test_reset_is_noop(self):
        adapter = PythonFunctionAdapter(lambda x: "ok")
        adapter.reset()  # should not raise

    def test_stream_raises_not_implemented(self):
        adapter = PythonFunctionAdapter(lambda x: "streamed")
        inp = AgentInput(conversation=[{"role": "user", "content": "test"}])
        with pytest.raises(NotImplementedError, match="does not support streaming"):
            list(adapter.stream(inp))
