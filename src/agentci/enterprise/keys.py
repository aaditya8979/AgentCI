"""
BYOK key management for AgentCI.

Handles API key validation, storage, and resolution across
multiple sources: env vars → .env file → ~/.agentci/config.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}

_PROVIDER_VALIDATION_URLS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
}


@dataclass
class KeyStatus:
    """Status of a single provider's API key."""
    provider: str
    env_var: str
    found: bool
    source: str  # "env", "dotenv", "config", "none"
    valid: bool | None = None  # None = not tested
    error: str = ""


def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into key-value pairs."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            result[key] = value
    return result


def resolve_key(provider: str, project_dir: str | Path = ".") -> tuple[str, str]:
    """
    Resolve an API key for a provider using the resolution chain:
    1. Environment variables
    2. .env file in project directory
    3. ~/.agentci/config

    Returns (key_value, source) where source is "env", "dotenv", "config", or "".
    """
    env_var = _PROVIDER_ENV_VARS.get(provider, "")
    if not env_var:
        return "", ""

    # 1. Environment variable
    val = os.environ.get(env_var, "").strip()
    if val:
        return val, "env"

    # 2. .env file
    dotenv_path = Path(project_dir) / ".env"
    dotenv = _load_dotenv(dotenv_path)
    if env_var in dotenv and dotenv[env_var]:
        return dotenv[env_var], "dotenv"

    # 3. Global config
    config_path = Path.home() / ".agentci" / "config"
    global_cfg = _load_dotenv(config_path)
    if env_var in global_cfg and global_cfg[env_var]:
        return global_cfg[env_var], "config"

    return "", ""


def check_all_keys(project_dir: str | Path = ".") -> list[KeyStatus]:
    """Check all provider keys and return their status."""
    statuses: list[KeyStatus] = []
    for provider, env_var in _PROVIDER_ENV_VARS.items():
        key, source = resolve_key(provider, project_dir)
        statuses.append(KeyStatus(
            provider=provider,
            env_var=env_var,
            found=bool(key),
            source=source if key else "none",
        ))
    return statuses


def validate_key(provider: str, key: str) -> tuple[bool, str]:
    """
    Validate an API key by making a minimal test call.
    Returns (is_valid, error_message).
    """
    url = _PROVIDER_VALIDATION_URLS.get(provider)
    if not url:
        return False, f"Unknown provider: {provider}"

    try:
        if provider == "openai":
            resp = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=10)
        elif provider == "anthropic":
            resp = httpx.get(url, headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            }, timeout=10)
        elif provider == "google":
            resp = httpx.get(f"{url}?key={key}", timeout=10)
        else:
            return False, "Unsupported provider"

        if resp.status_code in (200, 201):
            return True, ""
        elif resp.status_code == 401:
            return False, "Invalid API key (401 Unauthorized)"
        elif resp.status_code == 403:
            return False, "Forbidden — key may lack permissions (403)"
        else:
            return False, f"Unexpected status: {resp.status_code}"
    except httpx.TimeoutException:
        return False, "Connection timed out"
    except Exception as e:
        return False, str(e)


def save_key_to_dotenv(provider: str, key: str, project_dir: str | Path = ".") -> None:
    """Save a key to the .env file and ensure .gitignore covers it."""
    env_var = _PROVIDER_ENV_VARS.get(provider, "")
    if not env_var:
        raise ValueError(f"Unknown provider: {provider}")

    project = Path(project_dir)
    dotenv_path = project / ".env"

    # Read existing
    existing = _load_dotenv(dotenv_path) if dotenv_path.exists() else {}
    existing[env_var] = key

    # Write back
    lines = [f"{k}={v}" for k, v in existing.items()]
    dotenv_path.write_text("\n".join(lines) + "\n")

    # Ensure .gitignore contains .env
    gitignore = project / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".env" not in content.splitlines():
            with gitignore.open("a") as f:
                f.write("\n.env\n")
    else:
        gitignore.write_text(".env\n")


def detect_ollama(host: str = "http://localhost:11434") -> bool:
    """Check if Ollama is running locally."""
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False
