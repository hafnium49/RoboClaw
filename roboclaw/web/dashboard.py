"""Data Collection Dashboard — consolidated REST API routes.

All dashboard endpoints live under ``/api/dashboard/``.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

from roboclaw.embodied.hardware_monitor import HardwareMonitor
from roboclaw.embodied.setup import load_setup
from roboclaw.web.dashboard_datasets import delete_dataset, get_dataset_info, list_datasets
from roboclaw.web.dashboard_session import DashboardSession
from roboclaw.web.troubleshooting import generate_fault_snapshot, get_troubleshoot_map_json


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RecordStartRequest(BaseModel):
    task: str
    num_episodes: int = 10
    fps: int = 30
    episode_time_s: int = 300
    reset_time_s: int = 10


class TeleopStartRequest(BaseModel):
    fps: int = 30


class RecheckRequest(BaseModel):
    fault_type: str
    device_alias: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        logger.warning("Failed to detect LAN IP, falling back to 127.0.0.1")
        return "127.0.0.1"


def _check_arm_status(arm: dict[str, Any]) -> dict[str, Any]:
    alias = arm.get("alias", "unknown")
    port = arm.get("port", "")
    connected = bool(port and Path(port).exists())
    calibrated = bool(arm.get("calibrated", False))
    arm_type = arm.get("type", "")
    role = "follower" if "follower" in arm_type else "leader" if "leader" in arm_type else ""
    return {
        "alias": alias, "type": arm_type, "role": role,
        "connected": connected, "calibrated": calibrated,
    }


def _check_camera_status(cam: dict[str, Any]) -> dict[str, Any]:
    alias = cam.get("alias", "unknown")
    port = cam.get("port", "")
    connected = bool(port and Path(port).exists())
    return {"alias": alias, "connected": connected,
            "width": cam.get("width", 640), "height": cam.get("height", 480)}


def _compute_readiness(
    arms: list[dict[str, Any]],
    arm_statuses: list[dict[str, Any]],
    camera_statuses: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    from roboclaw.embodied.ops.helpers import _group_arms

    missing: list[str] = []
    grouped = _group_arms(arms)
    if not grouped["followers"]:
        missing.append("No follower arm configured")
    if not grouped["leaders"]:
        missing.append("No leader arm configured")
    for s in arm_statuses:
        if not s["connected"]:
            missing.append(f"Arm '{s['alias']}' is disconnected")
        elif not s["calibrated"]:
            missing.append(f"Arm '{s['alias']}' is not calibrated")
    for s in camera_statuses:
        if not s["connected"]:
            missing.append(f"Camera '{s['alias']}' is disconnected")
    f, l = grouped["followers"], grouped["leaders"]
    if f and l and len(f) != len(l):
        missing.append(f"Follower/leader count mismatch: {len(f)} vs {len(l)}")
    return len(missing) == 0, missing


def _datasets_root() -> Path:
    from roboclaw.embodied.ops.helpers import _dataset_root
    return _dataset_root(load_setup())


# ---------------------------------------------------------------------------
# Servo position reading (blocking — run in thread)
# ---------------------------------------------------------------------------

_MOTOR_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def _read_one_arm(arm: dict[str, Any]) -> dict[str, Any]:
    """Read servo positions for a single follower arm. Blocking — run in thread."""
    port = arm.get("port", "")
    try:
        from lerobot.motors.feetech import FeetechMotorsBus
        from lerobot.motors.motors_bus import Motor, MotorNormMode

        motors = {
            name: Motor(id=i + 1, model="sts3215", norm_mode=MotorNormMode.RANGE_M100_100)
            for i, name in enumerate(_MOTOR_NAMES)
        }
        bus = FeetechMotorsBus(port=port, motors=motors)
        bus.connect()
        positions = {}
        for name in _MOTOR_NAMES:
            try:
                positions[name] = int(bus.read("Present_Position", name, normalize=False))
            except Exception:
                positions[name] = None
        bus.disconnect()
        return positions
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_dashboard_routes(
    app: FastAPI,
    web_channel: Any,
    get_config: Callable[[], tuple[str, int]],
) -> None:
    """Register all dashboard API endpoints on the FastAPI app."""

    async def _on_state_change(status: dict[str, Any]) -> None:
        await web_channel.broadcast_dashboard_event({
            "type": "dashboard.session.state_changed", **status,
        })

    session = DashboardSession(on_state_change=_on_state_change)
    app.state.dashboard_session = session

    # -- Hardware status ---------------------------------------------------

    @app.get("/api/dashboard/hardware-status")
    async def hardware_status() -> dict[str, Any]:
        setup = load_setup()
        arms = setup.get("arms", [])
        cameras = setup.get("cameras", [])
        arm_statuses = [_check_arm_status(a) for a in arms]
        camera_statuses = [_check_camera_status(c) for c in cameras]
        ready, missing = _compute_readiness(arms, arm_statuses, camera_statuses)
        return {
            "ready": ready, "missing": missing,
            "arms": arm_statuses, "cameras": camera_statuses,
            "session_busy": session.busy,
        }

    # -- Session lifecycle -------------------------------------------------

    @app.get("/api/dashboard/session/status")
    async def session_status() -> dict[str, Any]:
        return session.get_status()

    @app.post("/api/dashboard/session/teleop/start")
    async def teleop_start(body: TeleopStartRequest | None = None) -> dict[str, str]:
        await session.start_teleop()
        return {"status": "teleoperating"}

    @app.post("/api/dashboard/session/teleop/stop")
    async def teleop_stop() -> dict[str, str]:
        await session.stop()
        return {"status": "idle"}

    @app.post("/api/dashboard/session/record/start")
    async def record_start(body: RecordStartRequest) -> dict[str, Any]:
        dataset_name = await session.start_recording(
            task=body.task,
            num_episodes=body.num_episodes,
            fps=body.fps,
            episode_time_s=body.episode_time_s,
            reset_time_s=body.reset_time_s,
        )
        app.state.hardware_monitor.set_recording_active(True)
        return {"status": "recording", "dataset_name": dataset_name}

    @app.post("/api/dashboard/session/record/stop")
    async def record_stop() -> dict[str, str]:
        try:
            await session.stop()
        finally:
            app.state.hardware_monitor.set_recording_active(False)
        return {"status": "idle"}

    # -- Episode control ---------------------------------------------------

    @app.post("/api/dashboard/session/episode/save")
    async def episode_save() -> dict[str, str]:
        await session.save_episode()
        return {"status": "episode_saved"}

    @app.post("/api/dashboard/session/episode/discard")
    async def episode_discard() -> dict[str, str]:
        await session.discard_episode()
        return {"status": "episode_discarded"}

    @app.post("/api/dashboard/session/episode/skip-reset")
    async def episode_skip_reset() -> dict[str, str]:
        await session.skip_reset()
        return {"status": "reset_skipped"}

    # -- Datasets ----------------------------------------------------------

    @app.get("/api/dashboard/datasets")
    async def datasets_list_route() -> list[dict]:
        return await asyncio.to_thread(list_datasets, _datasets_root())

    @app.get("/api/dashboard/datasets/{name}")
    async def dataset_detail(name: str) -> dict:
        info = await asyncio.to_thread(get_dataset_info, _datasets_root(), name)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
        return info

    @app.delete("/api/dashboard/datasets/{name}")
    async def dataset_delete(name: str) -> dict[str, str]:
        await asyncio.to_thread(delete_dataset, _datasets_root(), name)
        return {"status": "deleted", "name": name}

    # -- Servo positions ---------------------------------------------------

    @app.get("/api/dashboard/servo-positions")
    async def servo_positions() -> dict[str, Any]:
        if session.busy:
            return {"error": "busy", "arms": {}}
        from roboclaw.embodied.port_lock import port_locks
        setup = load_setup()
        result: dict[str, Any] = {"error": None, "arms": {}}
        for arm in setup.get("arms", []):
            if "follower" not in arm.get("type", ""):
                continue
            port = arm.get("port", "")
            alias = arm.get("alias", "")
            if not port:
                continue
            async with port_locks.acquire(port):
                positions = await asyncio.to_thread(_read_one_arm, arm)
            result["arms"][alias] = positions
        return result

    # -- Troubleshooting ---------------------------------------------------

    @app.get("/api/dashboard/troubleshoot-map")
    async def troubleshoot_map() -> dict[str, Any]:
        return get_troubleshoot_map_json()

    @app.post("/api/dashboard/troubleshoot/recheck")
    async def troubleshoot_recheck(body: RecheckRequest) -> dict[str, Any]:
        monitor: HardwareMonitor = app.state.hardware_monitor
        faults = monitor.check_hardware()
        return {"faults": [f.to_dict() for f in faults]}

    @app.post("/api/dashboard/troubleshoot/snapshot")
    async def troubleshoot_snapshot() -> dict[str, Any]:
        setup = load_setup()
        monitor: HardwareMonitor = app.state.hardware_monitor
        faults = monitor.active_faults
        return generate_fault_snapshot(setup, faults, "")

    # -- Network info ------------------------------------------------------

    @app.get("/api/dashboard/network-info")
    async def network_info() -> dict[str, Any]:
        host, port = get_config()
        return {"host": host, "port": port, "lan_ip": _get_lan_ip()}

    # -- Setup wizard routes -----------------------------------------------

    from roboclaw.web.dashboard_setup import register_setup_routes
    register_setup_routes(app)
