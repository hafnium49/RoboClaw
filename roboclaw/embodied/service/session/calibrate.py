"""Calibration — runs lerobot-calibrate subprocess per arm.

CalibrationSession drives a subprocess for each target arm,
then syncs the resulting calibration to motor EEPROM.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from roboclaw.embodied.command import CommandBuilder, resolve_action_arms
from roboclaw.embodied.embodiment.arm.registry import get_model, get_role
from roboclaw.embodied.embodiment.manifest.binding import Binding
from roboclaw.embodied.executor import SubprocessExecutor

if TYPE_CHECKING:
    from roboclaw.embodied.embodiment.manifest import Manifest
    from roboclaw.embodied.service import EmbodiedService

# Minimal spec data needed for motor bus operations.
_MOTOR_SPECS: dict[str, dict[str, Any]] = {
    "so101": {
        "motor_bus_module": "lerobot.motors.feetech",
        "motor_bus_class": "FeetechMotorsBus",
        "motor_names": ("shoulder_pan", "shoulder_lift", "elbow_flex",
                        "wrist_flex", "wrist_roll", "gripper"),
        "full_turn_motors": ("wrist_roll",),
        "default_motor": "sts3215",
    },
    "koch": {
        "motor_bus_module": "lerobot.motors.dynamixel",
        "motor_bus_class": "DynamixelMotorsBus",
        "motor_names": ("shoulder_pan", "shoulder_lift", "elbow_flex",
                        "wrist_flex", "wrist_roll", "gripper"),
        "full_turn_motors": ("wrist_roll",),
        "default_motor": "xl330-m288",
    },
}


def _get_spec(arm_type: str) -> dict[str, Any]:
    """Look up motor spec by arm type name."""
    model = get_model(arm_type)
    if model not in _MOTOR_SPECS:
        raise ValueError(f"No motor spec for model '{model}'")
    return _MOTOR_SPECS[model]


class CalibrationSession:
    """Runs lerobot-calibrate subprocess for each arm.

    Iterates over uncalibrated arms, launches a PassthroughSpec subprocess
    per arm, and syncs EEPROM on success.
    """

    def __init__(self, parent: EmbodiedService) -> None:
        self._parent = parent

    async def calibrate(
        self,
        manifest: Manifest,
        kwargs: dict[str, Any],
        tty_handoff: Any,
    ) -> str:
        """Run calibration for each uncalibrated arm."""
        if not tty_handoff:
            return "This action requires a local terminal."

        configured = manifest.arms
        if not configured:
            return "No arms configured."

        targets = _resolve_targets(manifest, kwargs)
        if not targets:
            return "All arms are already calibrated."

        runner = SubprocessExecutor()
        results: list[str] = []

        for arm in targets:
            result = await self._calibrate_one(arm, manifest, runner, tty_handoff)
            if result == "interrupted":
                return "interrupted"
            results.append(result)

        self._parent.manifest.reload()
        ok = sum(1 for r in results if r.endswith(": OK"))
        fail = len(results) - ok
        return f"{ok} succeeded, {fail} failed.\n" + "\n".join(results)

    async def _calibrate_one(
        self,
        arm: Binding,
        manifest: Manifest,
        runner: SubprocessExecutor,
        tty_handoff: Any,
    ) -> str:
        """Calibrate a single arm. Returns result string or "interrupted"."""
        display = arm.alias
        argv = CommandBuilder.calibrate(arm)
        await tty_handoff(start=True, label=f"Calibrating: {display}")
        try:
            rc, stderr_text = await runner.run_interactive(argv)
        finally:
            await tty_handoff(start=False, label=f"Calibrating: {display}")

        if rc in (130, -2):
            return "interrupted"
        if rc == 0:
            manifest.mark_arm_calibrated(arm.alias)
            _sync_calibration_to_motors(arm)
            return f"{display}: OK"
        return _format_failure(display, rc, stderr_text)


def _format_failure(display: str, rc: int, stderr_text: str) -> str:
    msg = f"{display}: FAILED (exit {rc})"
    if stderr_text.strip():
        msg += f"\nstderr: {stderr_text.strip()}"
    return msg


def _resolve_targets(manifest: Manifest, kwargs: dict[str, Any]) -> list[Binding]:
    """Select calibration targets -- all uncalibrated arms, or explicit selection."""
    selected = resolve_action_arms(manifest, kwargs.get("arms", ""))
    if kwargs.get("arms", ""):
        return selected
    return [arm for arm in selected if not arm.calibrated]


def _sync_calibration_to_motors(arm: Binding) -> None:
    """Sync calibration data to motor EEPROM after successful CLI calibration."""
    cal_dir = arm.calibration_dir
    serial = Path(cal_dir).name
    cal_path = Path(cal_dir) / f"{serial}.json"
    if not cal_path.exists():
        return

    from lerobot.motors.motors_bus import Motor, MotorCalibration, MotorNormMode

    spec = _get_spec(arm.type_name)
    default_motor = spec["default_motor"]
    cal = json.loads(cal_path.read_text())

    motors = {}
    calibration = {}
    for name, cfg in cal.items():
        motors[name] = Motor(id=cfg["id"], model=default_motor, norm_mode=MotorNormMode.DEGREES)
        calibration[name] = MotorCalibration(
            id=cfg["id"],
            drive_mode=cfg["drive_mode"],
            homing_offset=cfg["homing_offset"],
            range_min=cfg["range_min"],
            range_max=cfg["range_max"],
        )

    mod = importlib.import_module(spec["motor_bus_module"])
    bus_class = getattr(mod, spec["motor_bus_class"])
    bus = bus_class(port=arm.port, motors=motors, calibration=calibration)
    try:
        bus.connect()
        for name, cfg in cal.items():
            bus.write("Homing_Offset", name, cfg["homing_offset"], normalize=False)
            bus.write("Min_Position_Limit", name, cfg["range_min"], normalize=False)
            bus.write("Max_Position_Limit", name, cfg["range_max"], normalize=False)
    except (OSError, ConnectionError):
        logger.warning("Motor EEPROM sync failed for {}", arm.alias)
    finally:
        bus.disconnect()
