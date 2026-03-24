"""Setup management — single source of truth for the user's embodied configuration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SETUP_PATH = Path("~/.roboclaw/workspace/embodied/setup.json").expanduser()

_ARM_TYPES = ("so101_follower", "so101_leader")
_ARM_ROLES = ("follower", "leader")
_ARM_FIELDS = {"type", "port", "calibration_dir", "calibrated", "alias"}
_CAMERA_FIELDS = {"by_path", "by_id", "dev", "width", "height"}
_VALID_TOP_KEYS = {"version", "arms", "cameras", "datasets", "policies", "scanned_ports", "scanned_cameras"}

_CALIBRATION_ROOT = Path("~/.roboclaw/workspace/embodied/calibration").expanduser()

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
    _validate_setup(setup)
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
    """Merge updates into existing setup and save. Returns the merged result.

    Internal helper for programmatic updates (e.g. calibrate marking arms done).
    Not exposed as an agent action — use set_arm / set_camera instead.
    """
    setup = load_setup(path)
    _deep_merge(setup, updates)
    save_setup(setup, path)
    return setup


def _resolve_port(port: str, scanned_ports: list[dict]) -> str:
    """Resolve a volatile port (e.g. /dev/ttyACM0) to a stable by_id path.

    If port already starts with /dev/serial/by-id/ or /dev/serial/by-path/, keep as-is.
    Otherwise look up in scanned_ports and prefer by_id > by_path > original.
    """
    if port.startswith("/dev/serial/"):
        return port
    for entry in scanned_ports:
        if entry.get("dev") != port:
            continue
        by_id = entry.get("by_id", "")
        if by_id:
            return by_id
        return port
    return port


# ── Structured mutators (exposed as agent actions) ──────────────────


def set_arm(
    role: str, arm_type: str, port: str, *, alias: str | None = None, path: Path = SETUP_PATH,
) -> dict[str, Any]:
    """Add or update an arm. Auto-fills calibration_dir, sets calibrated=False."""
    if role not in _ARM_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {_ARM_ROLES}.")
    if arm_type not in _ARM_TYPES:
        raise ValueError(f"Invalid arm_type '{arm_type}'. Must be one of {_ARM_TYPES}.")
    if not port:
        raise ValueError("Arm port is required.")
    from roboclaw.embodied.scan import scan_serial_ports
    setup = load_setup(path)
    port = _resolve_port(port, scan_serial_ports())
    entry: dict[str, Any] = {
        "type": arm_type,
        "port": port,
        "calibration_dir": str(_CALIBRATION_ROOT / role),
        "calibrated": False,
    }
    if alias:
        entry["alias"] = alias
    setup.setdefault("arms", {})[role] = entry
    save_setup(setup, path)
    return setup


def arm_display_name(role: str, arm: dict) -> str:
    """Return user-friendly display name: 'alias (role)' if alias exists, else role."""
    alias = arm.get("alias")
    if alias:
        return f"{alias} ({role})"
    return role


def remove_arm(role: str, path: Path = SETUP_PATH) -> dict[str, Any]:
    """Remove an arm by role."""
    setup = load_setup(path)
    arms = setup.get("arms", {})
    if role not in arms:
        raise ValueError(f"No arm with role '{role}' in setup.")
    del arms[role]
    save_setup(setup, path)
    return setup


def set_camera(name: str, camera_index: int, path: Path = SETUP_PATH) -> dict[str, Any]:
    """Add or update a camera by picking from scanned_cameras by index."""
    setup = load_setup(path)
    scanned = setup.get("scanned_cameras", [])
    if camera_index < 0 or camera_index >= len(scanned):
        raise ValueError(
            f"camera_index {camera_index} out of range. "
            f"scanned_cameras has {len(scanned)} entries."
        )
    source = scanned[camera_index]
    entry = {field: source[field] for field in _CAMERA_FIELDS if field in source}
    setup.setdefault("cameras", {})[name] = entry
    save_setup(setup, path)
    return setup


def remove_camera(name: str, path: Path = SETUP_PATH) -> dict[str, Any]:
    """Remove a camera by name."""
    setup = load_setup(path)
    cameras = setup.get("cameras", {})
    if name not in cameras:
        raise ValueError(f"No camera named '{name}' in setup.")
    del cameras[name]
    save_setup(setup, path)
    return setup


# ── Validation ───────────────────────────────────────────────────────


def _validate_setup(setup: dict[str, Any]) -> None:
    """Validate setup against schema. Raises ValueError on invalid data."""
    invalid_top = set(setup.keys()) - _VALID_TOP_KEYS
    if invalid_top:
        raise ValueError(f"Unknown top-level keys: {invalid_top}")
    _validate_arms(setup.get("arms", {}))
    _validate_cameras(setup.get("cameras", {}))


def _validate_arms(arms: Any) -> None:
    """Validate all arm entries."""
    if not isinstance(arms, dict):
        raise ValueError("'arms' must be a dict.")
    for role, arm in arms.items():
        if not isinstance(arm, dict):
            raise ValueError(f"Arm '{role}' must be a dict.")
        bad_fields = set(arm.keys()) - _ARM_FIELDS
        if bad_fields:
            raise ValueError(f"Arm '{role}' has unknown fields: {bad_fields}")
        arm_type = arm.get("type")
        if arm_type is not None and arm_type not in _ARM_TYPES:
            raise ValueError(f"Arm '{role}' has invalid type '{arm_type}'.")


def _validate_cameras(cameras: Any) -> None:
    """Validate all camera entries."""
    if not isinstance(cameras, dict):
        raise ValueError("'cameras' must be a dict.")
    for name, cam in cameras.items():
        if not isinstance(cam, dict):
            raise ValueError(f"Camera '{name}' must be a dict.")
        bad_fields = set(cam.keys()) - _CAMERA_FIELDS
        if bad_fields:
            raise ValueError(f"Camera '{name}' has unknown fields: {bad_fields}")


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base, mutating base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
