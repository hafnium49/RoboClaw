"""Unified service layer for all embodied operations.

Every interface (Dashboard, CLI, Agent Tool) calls EmbodiedService.
This is the single coordination point for busy state, hardware monitor
integration, and operation lifecycle.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from loguru import logger

from roboclaw.embodied.engine import (
    CalibrationSession,
    HardwareScanner,
    OperationEngine,
    StatusCallback,
)
from roboclaw.embodied.hardware_monitor import (
    ArmStatus,
    CameraStatus,
    HardwareMonitor,
    check_arm_status,
    check_camera_status,
)
from roboclaw.embodied.ops.helpers import group_arms
from roboclaw.embodied.port_lock import port_locks
from roboclaw.embodied.setup import load_setup, mark_arm_calibrated


def _compute_readiness(
    arms: list[dict[str, Any]],
    arm_statuses: list[ArmStatus],
    camera_statuses: list[CameraStatus],
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    grouped = group_arms(arms)
    if not grouped["followers"]:
        missing.append("No follower arm configured")
    if not grouped["leaders"]:
        missing.append("No leader arm configured")
    for s in arm_statuses:
        if not s.connected:
            missing.append(f"Arm '{s.alias}' is disconnected")
        elif not s.calibrated:
            missing.append(f"Arm '{s.alias}' is not calibrated")
    for s in camera_statuses:
        if not s.connected:
            missing.append(f"Camera '{s.alias}' is disconnected")
    f, l = grouped["followers"], grouped["leaders"]
    if f and l and len(f) != len(l):
        missing.append(f"Follower/leader count mismatch: {len(f)} vs {len(l)}")
    return len(missing) == 0, missing


class EmbodiedService:
    """Single point of control for ALL embodied operations.

    Responsibilities:
    1. Busy mutex — only one operation at a time
    2. HardwareMonitor coordination (recording_active lifecycle)
    3. Teleop / recording via OperationEngine
    4. Calibration via CalibrationSession
    5. Scanning / motion detection via HardwareScanner
    6. Hardware status and servo reads
    """

    def __init__(
        self,
        hardware_monitor: HardwareMonitor | None = None,
        on_state_change: StatusCallback | None = None,
    ) -> None:
        self._monitor = hardware_monitor
        self._session = OperationEngine(on_state_change=self._on_session_state_change)
        self._external_callback = on_state_change
        self._recording_started = False
        self._hw_lock_holder: str = ""
        # Calibration
        self._cal_session: CalibrationSession | None = None
        self._cal_arm_alias: str = ""
        self._cal_port_cm: Any = None
        # Scanner
        self._scanner = HardwareScanner()

    # -- Busy state -----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._session.busy or self._hw_lock_holder != ""

    @property
    def busy_reason(self) -> str:
        if self._session.busy:
            return self._session.state
        return self._hw_lock_holder

    def acquire_hardware(self, reason: str) -> None:
        if self.busy:
            raise RuntimeError(f"Hardware busy: {self.busy_reason}")
        self._hw_lock_holder = reason

    def release_hardware(self) -> None:
        self._hw_lock_holder = ""

    def get_status(self) -> dict[str, Any]:
        return self._session.get_status()

    # -- Teleop ---------------------------------------------------------------

    async def start_teleop(self, *, fps: int = 30) -> None:
        await self._session.start_teleop(fps=fps)

    # -- Recording ------------------------------------------------------------

    async def start_recording(
        self,
        task: str,
        num_episodes: int = 10,
        fps: int = 30,
        episode_time_s: int = 300,
        reset_time_s: int = 10,
    ) -> str:
        """Start recording. Returns dataset_name."""
        dataset_name = await self._session.start_recording(
            task=task,
            num_episodes=num_episodes,
            fps=fps,
            episode_time_s=episode_time_s,
            reset_time_s=reset_time_s,
        )
        self._recording_started = True
        if self._monitor is not None:
            self._monitor.set_recording_active(True)
        return dataset_name

    async def stop(self) -> None:
        await self._session.stop()

    # -- Episode control ------------------------------------------------------

    async def save_episode(self) -> None:
        await self._session.save_episode()

    async def discard_episode(self) -> None:
        await self._session.discard_episode()

    async def skip_reset(self) -> None:
        await self._session.skip_reset()

    # -- Calibration ----------------------------------------------------------

    async def start_calibration(self, arm_alias: str) -> dict[str, Any]:
        """Start calibrating an arm. Acquires hardware lock + port lock."""
        self.acquire_hardware("calibrating")
        setup = load_setup()
        arm = _find_arm(setup, arm_alias)
        port = arm.get("port", "")
        if port:
            self._cal_port_cm = port_locks.acquire(port)
            await self._cal_port_cm.__aenter__()

        session = CalibrationSession(arm)
        try:
            await asyncio.to_thread(session.connect)
        except Exception:
            await self._cleanup_calibration()
            raise

        self._cal_session = session
        self._cal_arm_alias = arm_alias
        return {"state": session.state, "arm_alias": arm_alias}

    def get_calibration_status(self) -> dict[str, Any]:
        if self._cal_session is None:
            return {"state": "idle", "arm_alias": ""}
        return {"state": self._cal_session.state, "arm_alias": self._cal_arm_alias}

    async def set_calibration_homing(self) -> dict[str, Any]:
        self._require_calibration()
        offsets = await asyncio.to_thread(self._cal_session.set_homing)
        return {"state": self._cal_session.state, "homing_offsets": offsets}

    async def read_calibration_positions(self) -> dict[str, Any]:
        self._require_calibration()
        if self._cal_session.state != "recording":
            raise RuntimeError(f"Not recording (state={self._cal_session.state})")
        snapshot = await asyncio.to_thread(self._cal_session.read_range_positions)
        return {
            "positions": snapshot.positions,
            "mins": snapshot.mins,
            "maxes": snapshot.maxes,
        }

    async def finish_calibration(self) -> dict[str, Any]:
        self._require_calibration()
        calibration = await asyncio.to_thread(self._cal_session.finish)
        mark_arm_calibrated(self._cal_arm_alias)
        await self._cleanup_calibration()
        return {"state": "done", "calibration": calibration}

    async def cancel_calibration(self) -> None:
        if self._cal_session is not None:
            await asyncio.to_thread(self._cal_session.cancel)
        await self._cleanup_calibration()

    def _require_calibration(self) -> None:
        if self._cal_session is None:
            raise RuntimeError("No calibration session active.")

    async def _cleanup_calibration(self) -> None:
        if self._cal_port_cm is not None:
            await self._cal_port_cm.__aexit__(None, None, None)
            self._cal_port_cm = None
        if self._cal_session is not None:
            await asyncio.to_thread(self._cal_session.disconnect)
            self._cal_session = None
        self._cal_arm_alias = ""
        self.release_hardware()

    # -- Scanning / motion detection ------------------------------------------

    def scan_ports(self) -> list[dict]:
        return self._scanner.scan_ports()

    def scan_cameras(self) -> list[dict]:
        return self._scanner.scan_cameras_list()

    def capture_camera_previews(self, output_dir: str) -> list[dict]:
        return self._scanner.capture_camera_previews(output_dir)

    def start_motion_detection(self) -> int:
        return self._scanner.start_motion_detection()

    def poll_motion(self) -> list[dict]:
        return self._scanner.poll_motion()

    def stop_motion_detection(self) -> None:
        self._scanner.stop_motion_detection()

    # -- Hardware status / servo ----------------------------------------------

    def get_hardware_status(self) -> dict[str, Any]:
        setup = load_setup()
        arms = setup.get("arms", [])
        cameras = setup.get("cameras", [])
        arm_statuses = [check_arm_status(a) for a in arms]
        camera_statuses = [check_camera_status(c) for c in cameras]
        ready, missing = _compute_readiness(arms, arm_statuses, camera_statuses)
        return {
            "ready": ready,
            "missing": missing,
            "arms": [s.to_dict() for s in arm_statuses],
            "cameras": [s.to_dict() for s in camera_statuses],
            "session_busy": self._session.busy,
        }

    def read_servo_positions(self) -> dict[str, Any]:
        """Read servo positions. Returns busy error if operation in progress."""
        if self.busy:
            return {"error": "busy", "arms": {}}
        from roboclaw.embodied.motors import read_servo_positions
        return read_servo_positions()

    # -- Shutdown -------------------------------------------------------------

    async def shutdown(self) -> None:
        if self._session.busy:
            await self._session.stop()
        if self._cal_session is not None:
            await self.cancel_calibration()
        if self._monitor is not None:
            self._monitor.set_recording_active(False)

    # -- Internal: state change routing ---------------------------------------

    async def _on_session_state_change(self, status: dict[str, Any]) -> None:
        """Called by OperationEngine on every state transition."""
        new_state = status.get("state", "idle")
        if new_state == "idle" and self._recording_started:
            self._recording_started = False
            if self._monitor is not None:
                self._monitor.set_recording_active(False)

        if self._external_callback is not None:
            result = self._external_callback(status)
            if inspect.isawaitable(result):
                await result


def _find_arm(setup: dict, alias: str) -> dict:
    for arm in setup.get("arms", []):
        if arm.get("alias") == alias:
            return arm
    raise RuntimeError(f"Arm '{alias}' not found in setup.")
