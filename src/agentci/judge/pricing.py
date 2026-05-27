"""
LLM pricing tables and cost computation.

Computes per-call cost in USD based on provider, model, and token counts.
Prices are per million tokens. Updated 2025-05.

Usage:
    cost = compute_cost("openai", "gpt-4o", input_tokens=1200, output_tokens=350)
    # Returns 0.01125 (USD)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Prices in USD per million tokens
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    },
    "anthropic": {
        "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    },
    "google": {
        "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    },
    "ollama": {},  # Local models — zero cost
}

# Fallback: if exact model not found, try prefix match
_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "gpt-4o": ("openai", "gpt-4o"),
    "gpt-4": ("openai", "gpt-4"),
    "claude-3": ("anthropic", "claude-sonnet-4-20250514"),
    "gemini": ("google", "gemini-2.0-flash"),
}

_warned: set[str] = set()


def compute_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Compute cost in USD for an LLM call.

    Returns 0.0 for:
      - Local models (Ollama)
      - Unknown provider/model combinations (logs warning once)

    Args:
        provider: "openai", "anthropic", "google", "ollama"
        model: Full model name, e.g. "gpt-4o", "claude-sonnet-4-20250514"
        input_tokens: Number of prompt/input tokens
        output_tokens: Number of completion/output tokens

    Returns:
        Cost in USD (float, 6 decimal precision)
    """
    if provider == "ollama":
        return 0.0

    provider_prices = PRICING.get(provider, {})
    model_prices = provider_prices.get(model)

    # Try prefix matching if exact match fails
    if model_prices is None:
        for known_model in provider_prices:
            if model.startswith(known_model) or known_model.startswith(model):
                model_prices = provider_prices[known_model]
                break

    if model_prices is None:
        key = f"{provider}/{model}"
        if key not in _warned:
            logger.warning(
                "Unknown pricing for %s/%s — cost will be reported as $0.00. "
                "Add pricing to agentci.judge.pricing.PRICING.",
                provider, model,
            )
            _warned.add(key)
        return 0.0

    input_cost = (input_tokens / 1_000_000) * model_prices["input"]
    output_cost = (output_tokens / 1_000_000) * model_prices["output"]
    return round(input_cost + output_cost, 6)


def format_cost(cost_usd: float) -> str:
    """Format cost for display: $0.0043 or <$0.001 for very small amounts."""
    if cost_usd < 0.001:
        return "<$0.001"
    if cost_usd < 1.0:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.2f}"


def estimate_run_cost(
    provider: str,
    model: str,
    scenario_count: int,
    avg_input_tokens: int = 800,
    avg_output_tokens: int = 400,
    judge_count: int = 3,
) -> float:
    """
    Estimate total cost for an eval run before execution.

    Useful for rate limiting and cost alerts.
    """
    per_call = compute_cost(provider, model, avg_input_tokens, avg_output_tokens)
    return round(per_call * scenario_count * judge_count, 4)
