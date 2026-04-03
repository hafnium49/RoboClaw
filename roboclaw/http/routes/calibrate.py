"""Dashboard calibration API routes — thin HTTP shell over EmbodiedService."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class StartCalibrationRequest(BaseModel):
    arm_alias: str


def register_calibrate_routes(app: FastAPI, service: Any) -> None:
    """Register /api/dashboard/calibrate/* routes on the given app."""

    API = "/api/dashboard/calibrate"

    def _handle_calibration_error(exc: RuntimeError) -> None:
        raise HTTPException(409, str(exc)) from exc

    @app.post(f"{API}/start")
    async def calibrate_start(body: StartCalibrationRequest) -> dict:
        try:
            return await service.start_calibration(body.arm_alias)
        except RuntimeError as exc:
            _handle_calibration_error(exc)

    @app.get(f"{API}/status")
    async def calibrate_status() -> dict:
        return service.get_calibration_status()

    @app.post(f"{API}/set-homing")
    async def calibrate_set_homing() -> dict:
        try:
            return await service.set_calibration_homing()
        except RuntimeError as exc:
            _handle_calibration_error(exc)

    @app.get(f"{API}/positions")
    async def calibrate_positions() -> dict:
        try:
            return await service.read_calibration_positions()
        except RuntimeError as exc:
            _handle_calibration_error(exc)

    @app.post(f"{API}/finish")
    async def calibrate_finish() -> dict:
        try:
            return await service.finish_calibration()
        except RuntimeError as exc:
            _handle_calibration_error(exc)

    @app.post(f"{API}/cancel")
    async def calibrate_cancel() -> dict:
        await service.cancel_calibration()
        return {"state": "idle"}
