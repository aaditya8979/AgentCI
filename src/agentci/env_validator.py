"""
Environment validation for AgentCI.

Checks that all required environment variables are present at startup.
Fails fast with a clear, actionable error message listing every missing
variable grouped by component.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS: dict[str, list[str]] = {
    "Database": ["DATABASE_URL"],
    "Redis": ["REDIS_URL"],
    "Temporal": ["TEMPORAL_HOST"],
}

# These are only required when running as the API server with webhooks enabled
WEBHOOK_ENV_VARS: dict[str, list[str]] = {
    "GitHub App": [
        "GITHUB_WEBHOOK_SECRET",
    ],
    "Authentication": ["AGENTCI_API_KEYS"],
}

OPTIONAL_ENV_VARS: dict[str, dict[str, str]] = {
    "LLM Judges": {
        "OPENAI_API_KEY": "Required for OpenAI judges (gpt-4o, gpt-4o-mini)",
        "ANTHROPIC_API_KEY": "Required for Anthropic judges (claude-sonnet, claude-opus)",
        "GOOGLE_API_KEY": "Required for Google judges (gemini-2.5-pro, gemini-2.0-flash)",
        "OLLAMA_HOST": "Required for local judge models (default: localhost:11434)",
    },
    "Dashboard": {
        "AGENTCI_SESSION_SECRET": "Required for dashboard session signing",
        "DASHBOARD_ORIGIN": "CORS origin for the dashboard (default: http://localhost:3000)",
    },
}

_DESCRIPTIONS: dict[str, str] = {
    "DATABASE_URL": "PostgreSQL connection string (e.g., postgresql://user:pass@host:5432/db)",
    "REDIS_URL": "Redis connection string (e.g., redis://localhost:6379)",
    "TEMPORAL_HOST": "Temporal server address (e.g., localhost:7233)",
    "GITHUB_WEBHOOK_SECRET": "Secret used to verify webhook signatures from GitHub",
    "AGENTCI_API_KEYS": "Comma-separated list of valid API keys for /api/* endpoints",
    "AGENTCI_SESSION_SECRET": "Secret for signing dashboard session JWTs",
}


def validate_environment(include_webhook: bool = True) -> None:
    """
    Validate that all required environment variables are set.

    Raises EnvironmentError with a formatted list of missing variables
    if any required variable is missing.

    Args:
        include_webhook: If True, also validate webhook-specific vars.
    """
    missing: dict[str, list[str]] = {}
    all_required = dict(REQUIRED_ENV_VARS)
    if include_webhook:
        all_required.update(WEBHOOK_ENV_VARS)

    for component, vars_list in all_required.items():
        for var in vars_list:
            if not os.environ.get(var):
                missing.setdefault(component, []).append(var)

    if missing:
        lines = [
            "AgentCI startup failed. The following required environment variables are not set:\n"
        ]
        for component, vars_list in missing.items():
            lines.append(f"  [{component}]")
            for var in vars_list:
                desc = _DESCRIPTIONS.get(var, "")
                lines.append(f"    {var} — {desc}" if desc else f"    {var}")
            lines.append("")

        lines.append("Set these variables in your .env file or environment and restart.")
        lines.append("See .env.example for a complete reference.")
        raise EnvironmentError("\n".join(lines))

    # Log optional variable status
    for component, vars_dict in OPTIONAL_ENV_VARS.items():
        for var, description in vars_dict.items():
            if os.environ.get(var):
                logger.info("Optional env var set: %s (%s)", var, description)
            else:
                logger.debug("Optional env var not set: %s (%s)", var, description)
