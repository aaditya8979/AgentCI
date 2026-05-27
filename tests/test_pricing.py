"""
Tests for the LLM pricing module.

Verifies:
- Known model strings return correct cost
- Unknown model strings return 0.0 without raising
- Cost computation is mathematically correct
"""
import pytest

from agentci.judge.pricing import compute_cost, format_cost, estimate_run_cost


class TestComputeCost:

    def test_gpt4o_known_cost(self):
        # gpt-4o: input=$2.50/M, output=$10.00/M
        # 1000 input + 500 output = (1000/1M * 2.50) + (500/1M * 10.00)
        # = 0.0025 + 0.005 = 0.0075
        cost = compute_cost("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.0075, abs=1e-6)

    def test_gpt4o_mini_known_cost(self):
        # gpt-4o-mini: input=$0.15/M, output=$0.60/M
        cost = compute_cost("openai", "gpt-4o-mini", input_tokens=10000, output_tokens=5000)
        expected = (10000 / 1e6 * 0.15) + (5000 / 1e6 * 0.60)
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_claude_sonnet_known_cost(self):
        # claude-sonnet-4-20250514: input=$3.00/M, output=$15.00/M
        cost = compute_cost("anthropic", "claude-sonnet-4-20250514", input_tokens=2000, output_tokens=1000)
        expected = (2000 / 1e6 * 3.00) + (1000 / 1e6 * 15.00)
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_unknown_model_returns_zero(self):
        cost = compute_cost("openai", "gpt-99-ultra-turbo", input_tokens=5000, output_tokens=2000)
        assert cost == 0.0

    def test_unknown_provider_returns_zero(self):
        cost = compute_cost("deepseek", "deepseek-v3", input_tokens=5000, output_tokens=2000)
        assert cost == 0.0

    def test_ollama_always_zero(self):
        cost = compute_cost("ollama", "llama3", input_tokens=100000, output_tokens=50000)
        assert cost == 0.0

    def test_zero_tokens(self):
        cost = compute_cost("openai", "gpt-4o", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_prefix_matching(self):
        # gpt-4o should match models that start with gpt-4o
        cost = compute_cost("openai", "gpt-4o-2024-05-13", input_tokens=1000, output_tokens=500)
        assert cost > 0.0


class TestFormatCost:

    def test_tiny_cost(self):
        assert format_cost(0.0001) == "<$0.001"

    def test_small_cost(self):
        assert format_cost(0.0075) == "$0.0075"

    def test_large_cost(self):
        assert format_cost(1.50) == "$1.50"


class TestEstimateRunCost:

    def test_estimate(self):
        cost = estimate_run_cost("openai", "gpt-4o", scenario_count=10, judge_count=3)
        assert cost > 0.0

    def test_estimate_ollama_free(self):
        cost = estimate_run_cost("ollama", "llama3", scenario_count=50, judge_count=3)
        assert cost == 0.0
