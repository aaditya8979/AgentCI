"""
Community marketplace for scenario packs.

Enables teams to install, rate, and share evaluation scenario packs.
Local pack management with future support for a community registry.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default local pack registry
_REGISTRY_DIR = Path.home() / ".agentci" / "marketplace"
_PACK_INDEX = _REGISTRY_DIR / "index.json"


@dataclass
class PackMetadata:
    """Metadata for a scenario pack."""
    name: str
    domain: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    scenario_count: int = 0
    rating: float = 0.0
    install_count: int = 0


@dataclass
class PackIndex:
    """Local index of installed packs."""
    packs: dict[str, PackMetadata] = field(default_factory=dict)


def _load_index() -> PackIndex:
    """Load the local pack index."""
    if not _PACK_INDEX.exists():
        return PackIndex()
    try:
        data = json.loads(_PACK_INDEX.read_text())
        packs = {
            name: PackMetadata(**meta) for name, meta in data.get("packs", {}).items()
        }
        return PackIndex(packs=packs)
    except Exception:
        return PackIndex()


def _save_index(index: PackIndex) -> None:
    """Save the pack index to disk."""
    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "packs": {
            name: {
                "name": m.name,
                "domain": m.domain,
                "description": m.description,
                "version": m.version,
                "author": m.author,
                "scenario_count": m.scenario_count,
                "rating": m.rating,
                "install_count": m.install_count,
            }
            for name, m in index.packs.items()
        }
    }
    _PACK_INDEX.write_text(json.dumps(data, indent=2))


def install_pack(pack_path: str | Path, name: str | None = None) -> PackMetadata:
    """
    Install a scenario pack from a local path.

    Args:
        pack_path: Path to the scenario JSON file.
        name: Optional name override.
    """
    path = Path(pack_path)
    if not path.exists():
        raise FileNotFoundError(f"Pack file not found: {path}")

    data = json.loads(path.read_text())
    scenario_count = len(data) if isinstance(data, list) else 1
    pack_name = name or path.stem

    # Copy to registry
    dest = _REGISTRY_DIR / "packs" / f"{pack_name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)

    # Update index
    index = _load_index()
    meta = PackMetadata(
        name=pack_name,
        domain=pack_name.split("_")[0] if "_" in pack_name else "general",
        description=f"Installed from {path.name}",
        scenario_count=scenario_count,
    )
    index.packs[pack_name] = meta
    _save_index(index)

    logger.info("Installed pack '%s' with %d scenarios", pack_name, scenario_count)
    return meta


def list_installed() -> list[PackMetadata]:
    """List all installed packs."""
    index = _load_index()
    return list(index.packs.values())


def rate_pack(pack_name: str, helpful: bool) -> None:
    """Rate a pack based on whether it caught a real regression."""
    index = _load_index()
    if pack_name not in index.packs:
        raise ValueError(f"Pack not found: {pack_name}")

    meta = index.packs[pack_name]
    # Simple exponential moving average
    delta = 1.0 if helpful else -0.5
    meta.rating = max(0.0, min(5.0, meta.rating + delta))
    _save_index(index)


def get_pack_scenarios(pack_name: str) -> Path:
    """Get the path to a pack's scenario file."""
    path = _REGISTRY_DIR / "packs" / f"{pack_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Pack not installed: {pack_name}")
    return path
