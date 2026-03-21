"""Runtime execution helpers for embodied procedures."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roboclaw.agent.tools.registry import ToolRegistry
from roboclaw.embodied.localization import localize_text
from roboclaw.embodied.definition.components.robots.model import RobotManifest
from roboclaw.embodied.definition.systems.assemblies.model import AssemblyManifest
from roboclaw.embodied.definition.systems.deployments.model import DeploymentProfile
from roboclaw.embodied.execution.integration.adapters.loader import AdapterLoader
from roboclaw.embodied.execution.integration.carriers.model import ExecutionTarget
from roboclaw.embodied.execution.orchestration.procedures.model import ProcedureKind
from roboclaw.embodied.execution.orchestration.runtime.manager import RuntimeManager
from roboclaw.embodied.execution.orchestration.runtime.model import CalibrationPhase, RuntimeSession, RuntimeStatus


@dataclass(frozen=True)
class ExecutionContext:
    """Resolved embodied execution state for one setup and runtime session."""

    setup_id: str
    assembly: AssemblyManifest
    deployment: DeploymentProfile
    target: ExecutionTarget
    robot: RobotManifest
    adapter_binding: Any
    profile: Any
    runtime: RuntimeSession
    preferred_language: str = "en"


@dataclass(frozen=True)
class ProcedureExecutionResult:
    """Normalized result returned to the controller."""

    procedure: ProcedureKind
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class So101CalibrationFlow:
    """One in-memory calibration interaction for a setup runtime."""

    monitor: Any
    calibration_path: Path
    phase: CalibrationPhase
    interval_s: float
    heartbeat_s: float
    sample_limit: int | None
    stop_event: asyncio.Event | None = None
    task: asyncio.Task[None] | None = None
    last_error: str | None = None
    next_sample_idx: int = 1
    overwrite_existing: bool = False


class ProcedureExecutor:
    """Execute a small control-surface subset of embodied procedures."""

    def __init__(self, tools: ToolRegistry, runtime_manager: RuntimeManager):
        self._loader = AdapterLoader(tools)
        self._runtime_manager = runtime_manager
        self._adapters: dict[str, Any] = {}
        self._so101_calibration_flows: dict[str, So101CalibrationFlow] = {}

    def runtime_for(
        self,
        *,
        runtime_id: str,
        setup_id: str,
        assembly_id: str,
        deployment_id: str,
        target_id: str,
        adapter_id: str,
    ) -> RuntimeSession:
        try:
            return self._runtime_manager.get(runtime_id)
        except KeyError:
            return self._runtime_manager.create(
                session_id=runtime_id,
                assembly_id=assembly_id,
                deployment_id=deployment_id,
                target_id=target_id,
                adapter_id=adapter_id,
            )

    def _adapter(self, context: ExecutionContext) -> Any:
        adapter = self._adapters.get(context.runtime.id)
        if adapter is None:
            adapter = self._loader.load(
                binding=context.adapter_binding,
                assembly=context.assembly,
                deployment=context.deployment,
                target=context.target,
                robot=context.robot,
                profile=context.profile,
            )
            self._adapters[context.runtime.id] = adapter
        return adapter

    @staticmethod
    def _preferred_language(context: Any) -> str:
        return str(getattr(context, "preferred_language", "en") or "en")

    async def _best_effort_disconnect_before_calibration(self, context: ExecutionContext) -> None:
        adapter = self._adapters.get(context.runtime.id)
        if adapter is None:
            return
        disconnect = getattr(adapter, "disconnect", None)
        if disconnect is None:
            return
        try:
            await disconnect()
        except Exception:
            return
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None

    @staticmethod
    def _is_serial_transport_error(message: str) -> bool:
        lower = message.lower()
        return any(
            token in lower
            for token in (
                "there is no status packet",
                "incorrect status packet",
                "failed to open servo device",
                "resource busy",
                "permission denied",
                "no such file or directory",
            )
        )

    @classmethod
    def _friendly_so101_calibration_error(
        cls,
        *,
        action: str,
        raw_error: Exception,
        reconnect_allowed: bool,
        language: str = "en",
    ) -> str:
        message = str(raw_error).strip()
        lower = message.lower()
        reconnect_hint = (
            localize_text(
                language,
                en=" If this setup was already working earlier, tell me to reconnect it first, then tell me to start calibration again.",
                zh=" 如果这个 setup 之前是能工作的，先告诉我重新连接它，然后再告诉我重新开始标定。",
            )
            if reconnect_allowed
            else ""
        )
        if "stable `/dev/serial/by-id/" in message or "/dev/serial/by-id/" in message and "configured" in lower:
            return localize_text(
                language,
                en=(
                    f"I could not find a stable SO101 USB/serial device, so {action}."
                    " Plug the controller into this machine and make sure the `/dev/serial/by-id/...` path is available,"
                    " then tell me to start calibration again."
                ),
                zh=(
                    f"我没有找到稳定的 SO101 USB/串口设备，因此无法{action}。"
                    " 请把控制器接到这台机器上，并确认 `/dev/serial/by-id/...` 路径可用，"
                    " 然后再告诉我开始标定。"
                ),
            )
        if "failed to open servo device" in lower or "resource busy" in lower or "permission denied" in lower:
            return localize_text(
                language,
                en=(
                    f"I found the SO101 USB device, but I could not open it, so {action}."
                    " Please make sure the arm power is on, the USB/serial cable is firmly connected,"
                    " and no other program is using the arm."
                    " Then tell me to start calibration again."
                    + reconnect_hint
                ),
                zh=(
                    f"我找到了 SO101 的 USB 设备，但无法打开它，因此无法{action}。"
                    " 请确认机械臂已经上电、USB/串口线连接牢靠，而且没有其他程序正在占用这台机械臂。"
                    " 然后再告诉我开始标定。"
                    + reconnect_hint
                ),
            )
        if cls._is_serial_transport_error(message):
            return localize_text(
                language,
                en=(
                    f"I could talk to the SO101 USB device, but the arm did not answer, so {action}."
                    " Please make sure the arm power is on and the USB/serial cable is firmly connected."
                    " If you just replugged the cable or powered the arm back on, tell me to start calibration again."
                    + reconnect_hint
                ),
                zh=(
                    f"我可以访问 SO101 的 USB 设备，但机械臂没有响应，因此无法{action}。"
                    " 请确认机械臂已经上电，并且 USB/串口线连接牢靠。"
                    " 如果你刚重新插了线或者重新上电，请再告诉我开始标定。"
                    + reconnect_hint
                ),
            )
        return localize_text(
            language,
            en=f"RoboClaw could not {action}. {message}",
            zh=f"RoboClaw 无法{action}。{message}",
        )

    async def execute_connect(
        self,
        context: ExecutionContext,
        *,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        preflight = self._ensure_calibration_ready(context)
        if preflight is not None and context.runtime.status != RuntimeStatus.READY:
            return preflight

        adapter = self._adapter(context)
        context.runtime.status = RuntimeStatus.CONNECTING

        probe = adapter.probe_env()
        deps = adapter.check_dependencies()
        if not deps.ok:
            missing = ", ".join(deps.missing_required) or "required ROS2 interfaces"
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = missing
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=f"Setup `{context.setup_id}` is not ready yet: missing {missing}.",
                details={"probe": probe.details, "missing_required": deps.missing_required},
            )

        connected = await adapter.connect(
            target_id=context.target.id,
            config=dict(context.deployment.connection),
        )
        if not connected.ok:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = connected.message or connected.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=connected.message or f"Failed to connect setup `{context.setup_id}`.",
                details={"error_code": connected.error_code, **connected.details},
            )

        ready = await adapter.ready()
        if not ready.ready:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = ready.message
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=ready.message or f"Setup `{context.setup_id}` is not ready for commands yet.",
                details={"blocked_operations": [item.value for item in ready.blocked_operations], **ready.details},
            )

        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CONNECT,
            ok=True,
            message=f"Connected setup `{context.setup_id}` on target `{context.target.id}`.",
            details={"probe": probe.details, "target_id": context.target.id},
        )

    async def execute_move(
        self,
        context: ExecutionContext,
        *,
        primitive_name: str,
        primitive_args: dict[str, Any] | None = None,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        if context.runtime.status != RuntimeStatus.READY:
            connected = await self.execute_connect(context, on_progress=on_progress)
            if not connected.ok:
                return connected

        adapter = self._adapter(context)
        context.runtime.status = RuntimeStatus.BUSY
        pre_state = await adapter.get_state()
        primitive = await adapter.execute_primitive(primitive_name, primitive_args or {})
        if not primitive.accepted:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = primitive.message or primitive.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.MOVE,
                ok=False,
                message=primitive.message or f"Primitive `{primitive_name}` was rejected.",
                details={"error_code": primitive.error_code, **primitive.output},
            )

        post_state = await adapter.get_state()
        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        completion = "completed" if primitive.completed is not False else "accepted"
        state_message = self._state_confirmation(primitive_name, pre_state.values, post_state.values)
        message = f"Primitive `{primitive_name}` {completion} on setup `{context.setup_id}`."
        if state_message:
            message = f"{message} {state_message}"
        return ProcedureExecutionResult(
            procedure=ProcedureKind.MOVE,
            ok=True,
            message=message,
            details={
                "state_before": pre_state.values,
                "state_after": post_state.values,
                **primitive.output,
            },
        )

    async def execute_debug(self, context: ExecutionContext) -> ProcedureExecutionResult:
        adapter = self._adapter(context)
        probe = adapter.probe_env()
        state = await adapter.get_state()
        snapshot = await adapter.debug_snapshot()
        context.runtime.status = RuntimeStatus.READY if snapshot.captured else RuntimeStatus.ERROR
        if not snapshot.captured:
            context.runtime.last_error = snapshot.message or snapshot.summary
        return ProcedureExecutionResult(
            procedure=ProcedureKind.DEBUG,
            ok=snapshot.captured,
            message=snapshot.summary,
            details={"probe": probe.details, "state": state.values, "artifacts": snapshot.artifacts},
        )

    async def execute_reset(self, context: ExecutionContext) -> ProcedureExecutionResult:
        adapter = self._adapter(context)
        stop_result = await adapter.stop(scope="all")
        reset_result = await adapter.reset(mode="home")
        if not reset_result.ok:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = reset_result.message or reset_result.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.RESET,
                ok=False,
                message=reset_result.message or f"Failed to reset setup `{context.setup_id}`.",
                details={
                    "stop_message": stop_result.message,
                    "error_code": reset_result.error_code,
                    **reset_result.details,
                },
            )

        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.RESET,
            ok=True,
            message=reset_result.message or f"Reset setup `{context.setup_id}` to home.",
            details={"stop_message": stop_result.message, **reset_result.details},
        )

    async def execute_calibrate(
        self,
        context: ExecutionContext,
        *,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        calibration_path = self._calibration_path(context)
        if getattr(context.profile, "robot_id", None) == "so101":
            return await self._prepare_so101_calibration(context)

        expected_path = str(calibration_path) if calibration_path is not None else None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    f"Setup `{context.setup_id}` needs calibration before execution."
                    + (f" Expected canonical path: `{expected_path}`." if expected_path else "")
                    + " Tell me to calibrate after the hardware is ready so RoboClaw can walk you through it."
                ),
                zh=(
                    f"setup `{context.setup_id}` 在执行前需要先完成标定。"
                    + (f" 标准标定文件路径应为：`{expected_path}`。" if expected_path else "")
                    + " 等硬件准备好后，直接告诉我开始标定，我就会带你走完整个流程。"
                ),
            ),
        )

    def calibration_phase(self, runtime_id: str) -> str | None:
        flow = self._so101_calibration_flows.get(runtime_id)
        if flow is None:
            return None
        return flow.phase

    async def advance_calibration(
        self,
        context: ExecutionContext,
        *,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        flow = self._so101_calibration_flows.get(context.runtime.id)
        if flow is None:
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en="There is no pending calibration interaction for this setup. Tell me to calibrate first.",
                    zh="这个 setup 当前没有待继续的标定流程。请先告诉我开始标定。",
                ),
            )
        if flow.phase == CalibrationPhase.AWAIT_MID_POSE_ACK:
            return await self._start_so101_calibration_stream(context, flow=flow, on_progress=on_progress)
        if flow.phase == CalibrationPhase.STREAMING:
            return await self._finish_so101_calibration(context, flow=flow)
        self._cleanup_so101_calibration_flow(context.runtime.id)
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en="The pending calibration interaction is in an unknown state. Tell me to calibrate to start again.",
                zh="当前待继续的标定流程处于未知状态。请重新告诉我开始标定。",
            ),
        )

    def _calibration_path(self, context: ExecutionContext) -> Path | None:
        profile = context.profile
        if profile is None or not getattr(profile, "requires_calibration", False):
            return None
        return profile.canonical_calibration_path()

    def _ensure_calibration_ready(self, context: ExecutionContext) -> ProcedureExecutionResult | None:
        calibration_path = self._calibration_path(context)
        if calibration_path is None or calibration_path.exists():
            return None

        context.runtime.status = RuntimeStatus.ERROR
        context.runtime.last_error = f"Missing calibration file: {calibration_path}"
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    f"Setup `{context.setup_id}` needs calibration before `connect` or motion."
                    f" Expected canonical path: `{calibration_path}`."
                    " Tell me to calibrate to start the live SO101 calibration guide."
                ),
                zh=(
                    f"setup `{context.setup_id}` 在 `connect` 或运动前需要先标定。"
                    f" 标准标定文件路径应为：`{calibration_path}`。"
                    " 直接告诉我开始标定，我就会启动 SO101 的实时标定引导。"
                ),
            ),
            details={"calibration_path": str(calibration_path)},
        )

    @staticmethod
    def _serial_device_by_id(context: ExecutionContext) -> str | None:
        device = str(context.deployment.connection.get("serial_device_by_id") or "").strip()
        if device:
            return device
        for robot_config in context.deployment.robots.values():
            candidate = str(robot_config.get("serial_device_by_id") or "").strip()
            if candidate:
                return candidate
        return None

    def _build_so101_calibration_monitor(self, context: ExecutionContext) -> Any:
        from roboclaw.embodied.execution.integration.control_surfaces.ros2.so101_feetech import So101CalibrationMonitor

        device_by_id = self._serial_device_by_id(context)
        if not device_by_id:
            raise RuntimeError("No stable `/dev/serial/by-id/...` device is configured for this setup yet.")
        return So101CalibrationMonitor(device_by_id=device_by_id)

    async def _prepare_so101_calibration(
        self,
        context: ExecutionContext,
    ) -> ProcedureExecutionResult:
        calibration_path = self._calibration_path(context)
        if calibration_path is None:
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en=f"Setup `{context.setup_id}` is not ready for calibration yet.",
                    zh=f"setup `{context.setup_id}` 还没有准备好开始标定。",
                ),
            )
        existing = self._so101_calibration_flows.get(context.runtime.id)
        if existing is not None:
            return self._so101_calibration_phase_message(
                context,
                phase=existing.phase,
                calibration_path=existing.calibration_path,
                overwrite_existing=existing.overwrite_existing,
            )
        overwrite_existing = calibration_path.exists()
        monitor: Any | None = None
        try:
            await self._best_effort_disconnect_before_calibration(context)
            monitor = self._build_so101_calibration_monitor(context)
            monitor.connect()
            monitor.prepare_manual_calibration()
            interval_s, heartbeat_s, sample_limit = self._so101_calibration_stream_settings()
            self._so101_calibration_flows[context.runtime.id] = So101CalibrationFlow(
                monitor=monitor,
                calibration_path=calibration_path,
                phase=CalibrationPhase.AWAIT_MID_POSE_ACK,
                interval_s=interval_s,
                heartbeat_s=heartbeat_s,
                sample_limit=sample_limit,
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            if monitor is not None:
                try:
                    monitor.disconnect()
                except Exception:
                    pass
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = str(exc)
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=self._friendly_so101_calibration_error(
                    action="start the live SO101 calibration guide",
                    raw_error=exc,
                    reconnect_allowed=overwrite_existing,
                    language=self._preferred_language(context),
                ),
                details={"raw_error": str(exc), "calibration_path": str(calibration_path)},
            )
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return self._so101_calibration_phase_message(
            context,
            phase=CalibrationPhase.AWAIT_MID_POSE_ACK,
            calibration_path=calibration_path,
            overwrite_existing=overwrite_existing,
        )

    def _so101_calibration_stream_settings(self) -> tuple[float, float, int | None]:
        interval_s = 0.2
        heartbeat_s = 1.0
        raw_limit = os.environ.get("ROBOCLAW_SO101_CALIBRATION_SAMPLE_LIMIT", "").strip()
        sample_limit = int(raw_limit) if raw_limit else None
        return interval_s, heartbeat_s, sample_limit

    def _so101_calibration_phase_message(
        self,
        context: ExecutionContext,
        *,
        phase: str | CalibrationPhase,
        calibration_path: Path,
        overwrite_existing: bool = False,
    ) -> ProcedureExecutionResult:
        expected_path = str(calibration_path)
        if phase == CalibrationPhase.AWAIT_MID_POSE_ACK:
            save_notice = (
                localize_text(
                    self._preferred_language(context),
                    en=f" RoboClaw will overwrite the existing calibration file at `{expected_path}` when you press Enter again.",
                    zh=f" 当你再次按 Enter 时，RoboClaw 会覆盖现有的标定文件 `{expected_path}`。",
                )
                if overwrite_existing
                else localize_text(
                    self._preferred_language(context),
                    en=f" RoboClaw will save the calibration file to `{expected_path}` when you press Enter again.",
                    zh=f" 当你再次按 Enter 时，RoboClaw 会把标定文件保存到 `{expected_path}`。",
                )
            )
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en=(
                        f"SO101 calibration is ready for setup `{context.setup_id}`."
                        " Move the arm to a middle pose first, then press Enter to start live calibration."
                        + save_notice
                    ),
                    zh=(
                        f"setup `{context.setup_id}` 的 SO101 标定已经准备好了。"
                        " 先把机械臂移到中间位姿，然后按 Enter 开始实时标定。"
                        + save_notice
                    ),
                ),
                details={"calibration_path": expected_path, "calibration_phase": phase},
            )
        if phase == CalibrationPhase.STREAMING:
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en=(
                        f"SO101 live calibration is already running for setup `{context.setup_id}`."
                        " Keep moving every joint through its full range of motion, then press Enter again to stop and save."
                        f" It will be saved to `{expected_path}`."
                    ),
                    zh=(
                        f"setup `{context.setup_id}` 的 SO101 实时标定已经在运行。"
                        " 继续把每个关节跑完整量程，然后再次按 Enter 停止并保存。"
                        f" 标定文件会保存到 `{expected_path}`。"
                    ),
                ),
                details={"calibration_path": expected_path, "calibration_phase": phase},
            )
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en="SO101 calibration is in an unknown state. Tell me to calibrate to restart it.",
                zh="SO101 标定当前处于未知状态。请重新告诉我开始标定。",
            ),
            details={"calibration_phase": phase},
        )

    async def _start_so101_calibration_stream(
        self,
        context: ExecutionContext,
        *,
        flow: So101CalibrationFlow,
        on_progress: Any | None,
    ) -> ProcedureExecutionResult:
        try:
            mid_pose = flow.monitor.capture_mid_pose()
            flow.monitor.apply_half_turn_homings(mid_pose)
            initial_snapshot = flow.monitor.start_observation()
            flow.stop_event = asyncio.Event()
            flow.phase = CalibrationPhase.STREAMING
            if on_progress is not None:
                await on_progress(self._format_so101_calibration_snapshot(initial_snapshot, sample_idx=1))
                flow.next_sample_idx = 2
            flow.task = asyncio.create_task(self._run_so101_calibration_stream(flow, on_progress=on_progress))
        except Exception as exc:
            self._cleanup_so101_calibration_flow(context.runtime.id)
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = str(exc)
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=self._friendly_so101_calibration_error(
                    action="start live SO101 calibration",
                    raw_error=exc,
                    reconnect_allowed=flow.overwrite_existing,
                    language=self._preferred_language(context),
                ),
                details={"raw_error": str(exc), "calibration_path": str(flow.calibration_path)},
            )

        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    f"SO101 live calibration started for setup `{context.setup_id}`."
                    " RoboClaw is now streaming a LeRobot-style `MIN | POS | MAX` table above."
                    " Move every joint through its full range of motion, then press Enter again to stop and save."
                    f" It will be saved to `{flow.calibration_path}`."
                ),
                zh=(
                    f"setup `{context.setup_id}` 的 SO101 实时标定已经开始。"
                    " RoboClaw 现在正在上方持续输出 LeRobot 风格的 `MIN | POS | MAX` 表格。"
                    " 请把每个关节都跑完整量程，然后再次按 Enter 停止并保存。"
                    f" 标定文件会保存到 `{flow.calibration_path}`。"
                ),
            ),
            details={"calibration_path": str(flow.calibration_path), "calibration_phase": "streaming"},
        )

    async def _finish_so101_calibration(
        self,
        context: ExecutionContext,
        *,
        flow: So101CalibrationFlow,
    ) -> ProcedureExecutionResult:
        try:
            if flow.stop_event is not None:
                flow.stop_event.set()
            if flow.task is not None:
                await flow.task
            if flow.last_error:
                raise RuntimeError(flow.last_error)
            flow.calibration_path.parent.mkdir(parents=True, exist_ok=True)
            payload = flow.monitor.export_calibration_payload()
            flow.calibration_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception as exc:
            self._cleanup_so101_calibration_flow(context.runtime.id)
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = str(exc)
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en=f"RoboClaw could not save the SO101 calibration file. {exc}",
                    zh=f"RoboClaw 无法保存 SO101 标定文件。{exc}",
                ),
            )

        self._cleanup_so101_calibration_flow(context.runtime.id)
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=True,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    "Calibration complete! You can now control the arm — try saying "
                    "'open gripper' or 'go to home position'."
                    f" Calibration file saved to `{flow.calibration_path}`."
                ),
                zh=(
                    '标定完成！现在你可以控制机械臂了——试试说"打开夹爪"或"回到初始位置"。'
                    f" 标定文件已保存到 `{flow.calibration_path}`。"
                ),
            ),
            details={"calibration_path": str(flow.calibration_path), "calibration_phase": "completed"},
        )

    async def _run_so101_calibration_stream(
        self,
        flow: So101CalibrationFlow,
        *,
        on_progress: Any | None,
    ) -> None:
        sample_idx = flow.next_sample_idx - 1
        last_payload = ""
        last_emit = 0.0
        try:
            while True:
                if flow.stop_event is not None and flow.stop_event.is_set():
                    return
                sample_idx += 1
                snapshot = flow.monitor.snapshot_observed()
                payload = self._format_so101_calibration_snapshot(snapshot, sample_idx=sample_idx)
                now = asyncio.get_running_loop().time()
                if on_progress is not None and (payload != last_payload or (now - last_emit) >= flow.heartbeat_s):
                    await on_progress(payload)
                    last_emit = now
                    last_payload = payload
                if flow.sample_limit is not None and sample_idx >= flow.sample_limit:
                    return
                await asyncio.sleep(flow.interval_s)
        except Exception as exc:
            flow.last_error = str(exc)
            if on_progress is not None:
                await on_progress(f"SO101 calibration stream stopped: {exc}")

    def _cleanup_so101_calibration_flow(self, runtime_id: str) -> None:
        flow = self._so101_calibration_flows.pop(runtime_id, None)
        if flow is None:
            return
        if flow.stop_event is not None:
            flow.stop_event.set()
        if flow.task is not None:
            flow.task.cancel()
        try:
            flow.monitor.disconnect()
        except Exception:
            pass

    @staticmethod
    def _format_so101_calibration_snapshot(snapshot: Any, *, sample_idx: int) -> str:
        def _cell(value: int | None) -> str:
            return "?" if value is None else str(value)

        lines = [
            f"SO101 calibration live view on `{snapshot.resolved_device or snapshot.device_by_id}`",
            "```text",
            "JOINT            ID     MIN    POS    MAX",
        ]
        for row in snapshot.rows:
            lines.append(
                f"{row.joint_name:<16} {row.servo_id:>2} { _cell(row.range_min_raw):>7} { _cell(row.position_raw):>6} { _cell(row.range_max_raw):>6}"
            )
        lines.append("```")
        return "\n".join(lines)

    @staticmethod
    def _state_confirmation(
        primitive_name: str,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> str:
        gripper_before = ProcedureExecutor._gripper_percent(pre_state)
        gripper_after = ProcedureExecutor._gripper_percent(post_state)
        if primitive_name in {"gripper_open", "gripper_close"} and gripper_after is not None:
            if primitive_name == "gripper_open":
                label = "open" if gripper_after >= 60 else "partially open"
            elif primitive_name == "gripper_close":
                label = "closed" if gripper_after <= 40 else "partially open"
            elif gripper_after >= 80:
                label = "open"
            elif gripper_after <= 20:
                label = "closed"
            else:
                label = "partially open"
            if gripper_before is not None:
                return (
                    f"Current gripper state: {label} "
                    f"({gripper_after:.1f}% open, was {gripper_before:.1f}%)."
                )
            return f"Current gripper state: {label} ({gripper_after:.1f}% open)."
        return ""

    @staticmethod
    def _gripper_percent(values: dict[str, Any]) -> float | None:
        raw = values.get("gripper_percent")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
