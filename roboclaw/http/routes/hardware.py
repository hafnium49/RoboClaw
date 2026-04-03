"""Hardware status and servo position routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from roboclaw.embodied.service import EmbodiedService


def register_hardware_routes(app: FastAPI, service: EmbodiedService) -> None:

    @app.get("/api/dashboard/hardware-status")
    async def hardware_status() -> dict[str, Any]:
        return service.get_hardware_status()

    @app.get("/api/dashboard/servo-positions")
    async def servo_positions() -> dict[str, Any]:
        return await asyncio.to_thread(service.read_servo_positions)
