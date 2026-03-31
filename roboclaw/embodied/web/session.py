"""Web-based robot session — delegates to existing embodied infrastructure."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from typing import Any

from loguru import logger

from roboclaw.embodied.ops.helpers import (
    _arm_id,
    _bimanual_cal_dirs,
    _dataset_path,
    _group_arms,
    _resolve_action_arms,
    _validate_pairing,
)
from roboclaw.embodied.sensor.camera import resolve_cameras
from roboclaw.embodied.setup import load_setup


class RobotSession:
    """Manages robot lifecycle via subprocess delegation to LeRobot CLI."""

    _STATES = ("disconnected", "connected", "teleoperating", "recording")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "disconnected"
        self._setup: dict[str, Any] = {}
        self._grouped: dict[str, list[dict]] = {}
        self._cameras: dict[str, dict] = {}
        self._process_pid: int | None = None
        self._recording_dataset: str = ""

    @property
    def state(self) -> str:
        return self._state

    def _require_state(self, *allowed: str) -> None:
        if self._state not in allowed:
            raise RuntimeError(f"Requires state {allowed}, current is '{self._state}'")

    def connect(self, setup: dict | None = None) -> None:
        with self._lock:
            self._require_state("disconnected")
            setup = setup or load_setup()
            self._setup = setup

            arms = _resolve_action_arms(setup, {})
            grouped = _group_arms(arms)
            error = _validate_pairing(grouped["followers"], grouped["leaders"])
            if error:
                raise RuntimeError(error)

            self._grouped = grouped
            self._cameras = resolve_cameras(setup)
            self._state = "connected"
            logger.info("Robot session connected: {} follower(s), {} leader(s), {} camera(s)",
                        len(grouped["followers"]), len(grouped["leaders"]), len(self._cameras))

    def disconnect(self) -> None:
        with self._lock:
            if self._state == "disconnected":
                return
            self._kill_subprocess()
            self._state = "disconnected"
            logger.info("Robot session disconnected")

    def start_teleop(self, fps: int = 30) -> None:
        with self._lock:
            self._require_state("connected")
            argv = self._build_teleop_argv()
            self._launch_subprocess(argv)
            self._state = "teleoperating"
            logger.info("Teleoperation started")

    def stop_teleop(self) -> None:
        with self._lock:
            self._require_state("teleoperating")
            self._kill_subprocess()
            self._state = "connected"
            logger.info("Teleoperation stopped")

    def start_recording(
        self,
        dataset_name: str,
        task: str,
        fps: int = 30,
        num_episodes: int = 10,
    ) -> None:
        with self._lock:
            self._require_state("connected", "teleoperating")
            if self._state == "teleoperating":
                self._kill_subprocess()

            argv = self._build_record_argv(dataset_name, task, fps, num_episodes)
            self._recording_dataset = dataset_name
            self._launch_subprocess(argv)
            self._state = "recording"
            logger.info("Recording started: dataset={}, episodes={}", dataset_name, num_episodes)

    def stop_recording(self) -> None:
        with self._lock:
            self._require_state("recording")
            self._kill_subprocess()
            self._state = "connected"
            logger.info("Recording stopped")

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "episode_count": 0,
            "frame_count": 0,
            "target_episodes": 0,
            "recording_fps": 30,
            "teleop_fps": 30,
            "task": "",
            "dataset": self._recording_dataset if self._state == "recording" else None,
        }

    # -- Command building (reuses SO101Controller) ---------------------

    def _build_teleop_argv(self) -> list[str]:
        from roboclaw.embodied.embodiment.arm.so101 import SO101Controller

        controller = SO101Controller()
        followers = self._grouped["followers"]
        leaders = self._grouped["leaders"]

        if len(followers) == 1:
            return controller.teleoperate(
                robot_type=followers[0]["type"],
                robot_port=followers[0]["port"],
                robot_cal_dir=followers[0]["calibration_dir"],
                robot_id=_arm_id(followers[0]),
                teleop_type=leaders[0]["type"],
                teleop_port=leaders[0]["port"],
                teleop_cal_dir=leaders[0]["calibration_dir"],
                teleop_id=_arm_id(leaders[0]),
                cameras=self._cameras,
            )

        with _bimanual_cal_dirs(followers, leaders) as (robot_dir, teleop_dir):
            return controller.teleoperate_bimanual(
                robot_id="bimanual",
                robot_cal_dir=robot_dir,
                left_robot=followers[0],
                right_robot=followers[1],
                teleop_id="bimanual",
                teleop_cal_dir=teleop_dir,
                left_teleop=leaders[0],
                right_teleop=leaders[1],
                cameras=self._cameras,
            )

    def _build_record_argv(
        self, dataset_name: str, task: str, fps: int, num_episodes: int,
    ) -> list[str]:
        from roboclaw.embodied.embodiment.arm.so101 import SO101Controller

        controller = SO101Controller()
        followers = self._grouped["followers"]
        leaders = self._grouped["leaders"]
        ds_path = _dataset_path(self._setup, dataset_name)
        record_kwargs: dict[str, Any] = {
            "cameras": self._cameras,
            "repo_id": dataset_name,
            "dataset_root": str(ds_path.parent),
            "task": task,
            "fps": fps,
            "num_episodes": num_episodes,
        }

        if len(followers) == 1:
            return controller.record(
                robot_type=followers[0]["type"],
                robot_port=followers[0]["port"],
                robot_cal_dir=followers[0]["calibration_dir"],
                robot_id=_arm_id(followers[0]),
                teleop_type=leaders[0]["type"],
                teleop_port=leaders[0]["port"],
                teleop_cal_dir=leaders[0]["calibration_dir"],
                teleop_id=_arm_id(leaders[0]),
                **record_kwargs,
            )

        with _bimanual_cal_dirs(followers, leaders) as (robot_dir, teleop_dir):
            return controller.record_bimanual(
                robot_id="bimanual",
                robot_cal_dir=robot_dir,
                left_robot=followers[0],
                right_robot=followers[1],
                teleop_id="bimanual",
                teleop_cal_dir=teleop_dir,
                left_teleop=leaders[0],
                right_teleop=leaders[1],
                **record_kwargs,
            )

    # -- Subprocess management -----------------------------------------

    def _launch_subprocess(self, argv: list[str]) -> None:
        import subprocess

        proc = subprocess.Popen(argv, start_new_session=True)
        self._process_pid = proc.pid
        logger.info("Launched subprocess pid={}: {}", proc.pid, " ".join(argv[:4]))

    def _kill_subprocess(self) -> None:
        pid = self._process_pid
        if pid is None:
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGINT)
            logger.info("Sent SIGINT to process group pid={}", pid)
        except (ProcessLookupError, PermissionError):
            pass
        self._process_pid = None
