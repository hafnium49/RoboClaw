"""Camera helpers for embodied actions."""

from __future__ import annotations

from typing import Any

from roboclaw.embodied.manifest.binding import Binding
from roboclaw.embodied.sensor.registry import OPENCV_CAMERA


def resolve_cameras(cameras: list[Binding]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cam in cameras:
        alias = cam.alias
        port = cam.port
        if not alias or not port:
            continue
        config: dict[str, Any] = {
            "type": OPENCV_CAMERA.name,
            "index_or_path": port,
            "width": cam.interface.width,
            "height": cam.interface.height,
            "fps": cam.interface.fps or OPENCV_CAMERA.default_fps,
        }
        fourcc = cam.interface.fourcc
        if fourcc:
            config["fourcc"] = fourcc
        result[alias] = config
    return result
