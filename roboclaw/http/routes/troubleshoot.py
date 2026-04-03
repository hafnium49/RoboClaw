"""Troubleshooting routes — fault map, recheck, snapshot."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from roboclaw.embodied.hardware_monitor import HardwareMonitor
from roboclaw.embodied.service import EmbodiedService
from roboclaw.embodied.setup import load_setup
from roboclaw.http.troubleshooting import generate_fault_snapshot, get_troubleshoot_map_json


class RecheckRequest(BaseModel):
    fault_type: str
    device_alias: str


def register_troubleshoot_routes(app: FastAPI, service: EmbodiedService) -> None:

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
