"""Setup management — single source of truth for the user's embodied configuration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SETUP_PATH = Path("~/.roboclaw/workspace/embodied/setup.json").expanduser()

_DEFAULT_SETUP: dict[str, Any] = {
    "version": 2,
    "arms": {},
    "cameras": {},
    "datasets": {
        "root": str(Path("~/.roboclaw/workspace/embodied/datasets").expanduser()),
    },
    "policies": {
        "root": str(Path("~/.roboclaw/workspace/embodied/policies").expanduser()),
    },
    "scanned_ports": [],
    "scanned_cameras": [],
}


def load_setup(path: Path = SETUP_PATH) -> dict[str, Any]:
    """Load setup.json, return defaults if not found."""
    if not path.exists():
        return copy.deepcopy(_DEFAULT_SETUP)
    return json.loads(path.read_text(encoding="utf-8"))


def save_setup(setup: dict[str, Any], path: Path = SETUP_PATH) -> None:
    """Write setup.json, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(setup, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def create_setup_with_scan(path: Path = SETUP_PATH) -> dict[str, Any]:
    """Create setup.json with auto-detected hardware. Called during onboard."""
    from roboclaw.embodied.scan import scan_cameras, scan_serial_ports

    setup = copy.deepcopy(_DEFAULT_SETUP)
    setup["scanned_ports"] = scan_serial_ports()
    setup["scanned_cameras"] = scan_cameras()
    save_setup(setup, path)
    return setup


def ensure_setup(path: Path = SETUP_PATH) -> dict[str, Any]:
    """Load setup.json if exists, otherwise create with defaults (no scan) and return."""
    if path.exists():
        return load_setup(path)
    defaults = copy.deepcopy(_DEFAULT_SETUP)
    save_setup(defaults, path)
    return defaults


def update_setup(updates: dict[str, Any], path: Path = SETUP_PATH) -> dict[str, Any]:
    """Merge updates into existing setup and save. Returns the merged result."""
    setup = load_setup(path)
    _deep_merge(setup, updates)
    save_setup(setup, path)
    return setup


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base, mutating base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
