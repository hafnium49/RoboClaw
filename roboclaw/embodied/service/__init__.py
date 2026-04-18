"""Unified service layer for all embodied operations."""

from __future__ import annotations

import json
import threading
from typing import Any

from roboclaw.embodied.board import Board, Command, SessionState
from roboclaw.embodied.board.board import IDLE_STATE
from roboclaw.embodied.command import CommandBuilder, group_arms
from roboclaw.embodied.embodiment.hardware.monitor import (
    ArmStatus, CameraStatus, HardwareMonitor,
    check_arm_status, check_camera_status,
)
from roboclaw.embodied.embodiment.lock import EmbodimentBusyError, EmbodimentFileLock
from roboclaw.embodied.embodiment.manifest import Manifest
from roboclaw.embodied.embodiment.manifest.binding import Binding
from roboclaw.embodied.service.hub import HubService
from roboclaw.embodied.service.session import (
    InferSession, RecordSession, ReplaySession, Session,
    TeleopSession, TrainSession,
)
from roboclaw.embodied.service.session.calibrate import CalibrationSession
from roboclaw.embodied.embodiment.doctor import DoctorService
from roboclaw.embodied.service.session.setup import SetupSession


def _compute_readiness(
    arms: list[Binding],
    arm_statuses: list[ArmStatus],
    camera_statuses: list[CameraStatus],
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    grouped = group_arms(arms)
    if not grouped["followers"]:
        missing.append("No follower arm configured")
    if not grouped["leaders"]:
        missing.append("No leader arm configured")
    for status in arm_statuses:
        if not status.connected:
            missing.append(f"Arm '{status.alias}' is disconnected")
        elif not status.calibrated:
            missing.append(f"Arm '{status.alias}' is not calibrated")
    for status in camera_statuses:
        if not status.connected:
            missing.append(f"Camera '{status.alias}' is disconnected")
    followers = grouped["followers"]
    leaders = grouped["leaders"]
    if followers and leaders and len(followers) != len(leaders):
        missing.append(f"Follower/leader count mismatch: {len(followers)} vs {len(leaders)}")
    return len(missing) == 0, missing


class EmbodiedService:
    """Single point of control for ALL embodied operations.

    Two-layer mutex:
    - Layer 1: Embodiment lock — physical robot is one resource.
    - Layer 2: Active session — only one operation at a time.
    """

    def __init__(
        self,
        hardware_monitor: HardwareMonitor | None = None,
        board: Board | None = None,
        manifest: Manifest | None = None,
    ) -> None:
        self._monitor = hardware_monitor
        self.board = board or Board()
        self.manifest = manifest or Manifest(board=self.board)
        self.manifest.ensure()
        self._lock = threading.Lock()
        self._file_lock = EmbodimentFileLock()
        self._embodiment_owner: str = ""
        self._active_session: Session | None = None
        self._recording_started = False

        # Sub-services
        self.calibration = CalibrationSession(self)
        self.setup = SetupSession(self)
        self.teleop = TeleopSession(self)
        self.record = RecordSession(self)
        self.replay = ReplaySession(self)
        self.train = TrainSession(self)
        self.infer = InferSession(self)
        self.hub = HubService(self)
        self.doctor = DoctorService(self)

        for session in (self.teleop, self.record, self.replay, self.infer):
            session._exit_callback = self._on_session_exit

    # -- Embodiment lock --

    @property
    def embodiment_busy(self) -> bool:
        with self._lock:
            return self._embodiment_owner != ""

    @property
    def busy(self) -> bool:
        with self._lock:
            busy, _ = self._busy_state_unlocked()
            return busy

    @property
    def busy_reason(self) -> str:
        with self._lock:
            _, reason = self._busy_state_unlocked(default_reason="unknown")
            return reason

    def _busy_state_unlocked(self, default_reason: str = "") -> tuple[bool, str]:
        """Return (busy, reason) using the active session's state or the owner string."""
        if self._active_session is not None and self._active_session.busy:
            return True, self.board.state.get("state", default_reason)
        if self._embodiment_owner:
            return True, self._embodiment_owner
        return False, ""

    def acquire_embodiment(self, owner: str) -> None:
        with self._lock:
            busy, reason = self._busy_state_unlocked()
            if busy:
                raise EmbodimentBusyError(f"Embodiment busy: {reason}")
            self._file_lock.acquire_exclusive(owner)  # cross-process
            self._embodiment_owner = owner
            self.board.set_field("embodiment_owner", owner)

    def release_embodiment(self, owner: str = "") -> None:
        with self._lock:
            if owner and self._embodiment_owner != owner:
                return
            self._file_lock.release_exclusive()  # cross-process
            self._embodiment_owner = ""
            self.board.set_field("embodiment_owner", "")

    # -- Status --

    def get_status(self) -> dict[str, Any]:
        status = self.board.state
        # Merge cross-process owner info for REST callers
        if not status.get("embodiment_owner"):
            status["embodiment_owner"] = self._embodiment_owner or self._file_lock.owner()
        return status

    def get_logs(self) -> list[str]:
        return self.board.all_logs()

    def clear_logs(self) -> None:
        self.board.clear_logs()

    def _clear_recording_tracking(self, session: Session | None) -> None:
        if session is self.record or (session is None and self._recording_started):
            self._recording_started = False
            if self._monitor is not None:
                self._monitor.set_recording_active(False)

    def _finish_managed_session(self, session: Session | None, owner: str = "") -> None:
        """Clear service session bookkeeping and release embodiment ownership."""
        with self._lock:
            if session is None or self._active_session is session:
                self._active_session = None
        self._clear_recording_tracking(session)
        self.release_embodiment(owner)

    def _on_session_exit(self, session: Session) -> None:
        """Called when a subprocess exits naturally (not via stop())."""
        self._finish_managed_session(session)

    async def _start_managed_session(
        self,
        session: Session,
        *,
        owner: str,
        argv: list[str],
    ) -> None:
        self.acquire_embodiment(owner)
        self._active_session = session
        try:
            await session.start(argv)
        except Exception:
            self._finish_managed_session(session, owner)
            raise

    async def _run_managed_session(
        self,
        session: Session,
        *,
        owner: str,
        argv: list[str],
        tty_handoff: Any | None = None,
    ) -> str:
        await self._start_managed_session(session, owner=owner, argv=argv)
        if tty_handoff:
            from roboclaw.embodied.toolkit.tty import TtySession

            try:
                return await TtySession(tty_handoff).run(session)
            finally:
                self._finish_managed_session(session, owner)
        try:
            await session.wait()
            return session.result()
        finally:
            self._finish_managed_session(session, owner)

    # -- Operations (Web entry points) --

    async def start_teleop(self, *, fps: int = 30, arms: str = "") -> None:
        argv = CommandBuilder.teleop(self.manifest, fps=fps, arms=arms)
        await self._start_managed_session(self.teleop, owner="teleop", argv=argv)

    async def start_recording(
        self,
        task: str,
        num_episodes: int = 10,
        fps: int = 30,
        episode_time_s: int = 300,
        reset_time_s: int = 10,
        dataset_name: str = "",
        use_cameras: bool = True,
        arms: str = "",
    ) -> str:
        argv, dataset_name = CommandBuilder.record(
            self.manifest,
            task=task,
            dataset_name=dataset_name,
            num_episodes=num_episodes,
            fps=fps,
            episode_time_s=episode_time_s,
            reset_time_s=reset_time_s,
            use_cameras=use_cameras,
            arms=arms,
        )
        await self._start_managed_session(self.record, owner="recording", argv=argv)
        await self.board.update(target_episodes=num_episodes, dataset=dataset_name)
        self._recording_started = True
        if self._monitor is not None:
            self._monitor.set_recording_active(True)
        return dataset_name

    async def start_replay(
        self,
        *,
        dataset_name: str = "default",
        episode: int = 0,
        fps: int = 30,
        arms: str = "",
    ) -> None:
        argv = CommandBuilder.replay(
            self.manifest, dataset_name=dataset_name, episode=episode, fps=fps, arms=arms,
        )
        await self._start_managed_session(self.replay, owner="replaying", argv=argv)

    async def start_inference(
        self,
        *,
        checkpoint_path: str = "",
        source_dataset: str = "",
        dataset_name: str = "",
        task: str = "eval",
        num_episodes: int = 1,
        episode_time_s: int = 60,
        arms: str = "",
        use_cameras: bool = True,
    ) -> None:
        argv = CommandBuilder.infer(
            self.manifest,
            checkpoint_path=checkpoint_path,
            source_dataset=source_dataset,
            dataset_name=dataset_name,
            task=task,
            num_episodes=num_episodes,
            episode_time_s=episode_time_s,
            arms=arms,
            use_cameras=use_cameras,
        )
        await self._start_managed_session(self.infer, owner="inferring", argv=argv)

    async def run_replay(
        self,
        *,
        dataset_name: str = "default",
        episode: int = 0,
        fps: int = 30,
        arms: str = "",
        tty_handoff: Any | None = None,
    ) -> str:
        argv = CommandBuilder.replay(
            self.manifest, dataset_name=dataset_name, episode=episode, fps=fps, arms=arms,
        )
        return await self._run_managed_session(
            self.replay, owner="replaying", argv=argv, tty_handoff=tty_handoff,
        )

    async def run_inference(
        self,
        *,
        checkpoint_path: str = "",
        source_dataset: str = "",
        dataset_name: str = "",
        task: str = "eval",
        num_episodes: int = 1,
        episode_time_s: int = 60,
        arms: str = "",
        use_cameras: bool = True,
        tty_handoff: Any | None = None,
    ) -> str:
        argv = CommandBuilder.infer(
            self.manifest,
            checkpoint_path=checkpoint_path,
            source_dataset=source_dataset,
            dataset_name=dataset_name,
            task=task,
            num_episodes=num_episodes,
            episode_time_s=episode_time_s,
            arms=arms,
            use_cameras=use_cameras,
        )
        return await self._run_managed_session(
            self.infer, owner="inferring", argv=argv, tty_handoff=tty_handoff,
        )

    async def dismiss_error(self) -> None:
        """Clear error state and release embodiment lock so user can retry."""
        self._finish_managed_session(self._active_session)
        await self.board.update(**IDLE_STATE)

    async def stop(self) -> None:
        session = self._active_session
        if session:
            await session.stop()
            self._finish_managed_session(session)

    async def save_episode(self) -> None:
        if self._active_session:
            self.board.post_command(Command.SAVE_EPISODE)

    async def discard_episode(self) -> None:
        if self._active_session:
            self.board.post_command(Command.DISCARD_EPISODE)

    async def skip_reset(self) -> None:
        if self._active_session:
            self.board.post_command(Command.SKIP_RESET)

    # -- Calibration (web) --

    async def start_calibration(self, arm_alias: str) -> dict[str, Any]:
        """Start calibration subprocess for a single arm (web path)."""
        arm = self.manifest.find_arm(arm_alias)
        if arm is None:
            raise RuntimeError(f"Arm '{arm_alias}' not found in manifest.")
        self.acquire_embodiment("calibrating")
        try:
            await self.calibration.start_calibration(arm, self.manifest)
        except Exception:
            self.release_embodiment()
            raise
        return {"state": "calibrating", "arm_alias": arm_alias}

    async def stop_calibration(self) -> None:
        """Properly terminate calibration subprocess (ESC → SIGINT → kill)."""
        await self.calibration.stop()
        self.release_embodiment()

    def post_calibration_command(self, command: str) -> None:
        """Forward a calibration command to the Board."""
        self.board.post_command(command)

    # -- Manifest mutations (kept identical) --

    def _require_not_busy(self) -> None:
        busy, reason = self._busy_state_unlocked()
        if busy:
            raise EmbodimentBusyError(f"Cannot modify config while busy: {reason}")

    def bind_arm(self, alias: str, arm_type: str, interface: Any) -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.set_arm(alias, arm_type, interface)

    def unbind_arm(self, alias: str) -> None:
        with self._lock:
            self._require_not_busy()
            self.manifest.remove_arm(alias)

    def rename_arm(self, alias: str, new_alias: str) -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.rename_arm(alias, new_alias)

    def bind_camera(self, alias: str, interface: Any, side: str = "") -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.set_camera(alias, interface, side)

    def unbind_camera(self, alias: str) -> None:
        with self._lock:
            self._require_not_busy()
            self.manifest.remove_camera(alias)

    def rename_camera(self, old_alias: str, new_alias: str) -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.rename_camera(old_alias, new_alias)

    def bind_hand(self, alias: str, hand_type: str, interface: Any, slave_id: int) -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.set_hand(alias, hand_type, interface, slave_id)

    def unbind_hand(self, alias: str) -> None:
        with self._lock:
            self._require_not_busy()
            self.manifest.remove_hand(alias)

    def rename_hand(self, old_alias: str, new_alias: str) -> Binding:
        with self._lock:
            self._require_not_busy()
            return self.manifest.rename_hand(old_alias, new_alias)

    # -- Queries --

    def get_manifest_summary(self) -> str:
        snapshot = self.manifest.snapshot
        snapshot["status"] = self.get_hardware_status(self.manifest)
        return json.dumps(snapshot, indent=2, ensure_ascii=False)

    def get_hardware_status(self, manifest: Manifest | None = None) -> dict[str, Any]:
        if manifest is None:
            manifest = self.manifest
        arms = manifest.arms
        cameras = manifest.cameras
        arm_statuses = [check_arm_status(arm) for arm in arms]
        camera_statuses = [check_camera_status(camera) for camera in cameras]
        ready, missing = _compute_readiness(arms, arm_statuses, camera_statuses)
        active = self._active_session is not None and self._active_session.busy
        return {
            "ready": ready,
            "missing": missing,
            "arms": [status.to_dict() for status in arm_statuses],
            "cameras": [status.to_dict() for status in camera_statuses],
            "session_busy": active,
        }

    def read_servo_positions(self) -> dict[str, Any]:
        if not self._file_lock.try_shared():
            return {"error": "busy", "arms": {}}
        try:
            from roboclaw.embodied.embodiment.hardware.motors import read_servo_positions
            return read_servo_positions(self.manifest.arms)
        finally:
            self._file_lock.release_shared()

    # -- Shutdown --

    async def shutdown(self) -> None:
        if self._active_session and self._active_session.busy:
            await self.stop()
        if self.setup.motion_active:
            self.setup.stop_motion_detection()
        if self._monitor is not None:
            self._monitor.set_recording_active(False)
        self.release_embodiment()
