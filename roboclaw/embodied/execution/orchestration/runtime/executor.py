"""Runtime execution helpers for embodied procedures."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roboclaw.agent.tools.registry import ToolRegistry
from roboclaw.embodied.definition.components.robots.model import RobotManifest
from roboclaw.embodied.definition.systems.assemblies.model import AssemblyManifest
from roboclaw.embodied.definition.systems.deployments.model import DeploymentProfile
from roboclaw.embodied.execution.integration.adapters.loader import AdapterLoader
from roboclaw.embodied.execution.integration.carriers.model import ExecutionTarget
from roboclaw.embodied.execution.orchestration.procedures.model import ProcedureKind
from roboclaw.embodied.execution.orchestration.runtime.manager import RuntimeManager
from roboclaw.embodied.execution.orchestration.runtime.model import RuntimeSession, RuntimeStatus


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
    phase: str
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
            message=(
                f"Setup `{context.setup_id}` needs calibration before execution."
                + (f" Expected canonical path: `{expected_path}`." if expected_path else "")
                + " Reply with `calibrate` after the hardware is ready so RoboClaw can walk you through it."
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
                message="There is no pending calibration interaction for this setup. Reply with `calibrate` first.",
            )
        if flow.phase == "await_mid_pose_ack":
            return await self._start_so101_calibration_stream(context, flow=flow, on_progress=on_progress)
        if flow.phase == "streaming":
            return await self._finish_so101_calibration(context, flow=flow)
        self._cleanup_so101_calibration_flow(context.runtime.id)
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message="The pending calibration interaction is in an unknown state. Reply with `calibrate` to start again.",
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
            message=(
                f"Setup `{context.setup_id}` needs calibration before `connect` or motion."
                f" Expected canonical path: `{calibration_path}`."
                " Reply with `calibrate` to start the live SO101 calibration guide."
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
                message=f"Setup `{context.setup_id}` does not declare a canonical calibration path.",
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
        try:
            monitor = self._build_so101_calibration_monitor(context)
            monitor.connect()
            monitor.prepare_manual_calibration()
            interval_s, heartbeat_s, sample_limit = self._so101_calibration_stream_settings()
            self._so101_calibration_flows[context.runtime.id] = So101CalibrationFlow(
                monitor=monitor,
                calibration_path=calibration_path,
                phase="await_mid_pose_ack",
                interval_s=interval_s,
                heartbeat_s=heartbeat_s,
                sample_limit=sample_limit,
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = str(exc)
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=(
                    "RoboClaw could not start the live SO101 calibration guide."
                    f" {exc}"
                ),
            )
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return self._so101_calibration_phase_message(
            context,
            phase="await_mid_pose_ack",
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
        phase: str,
        calibration_path: Path,
        overwrite_existing: bool = False,
    ) -> ProcedureExecutionResult:
        expected_path = str(calibration_path)
        if phase == "await_mid_pose_ack":
            save_notice = (
                f" RoboClaw will overwrite the existing calibration file at `{expected_path}` when you press Enter again."
                if overwrite_existing
                else f" RoboClaw will save the canonical calibration file to `{expected_path}` when you press Enter again."
            )
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=(
                    f"SO101 calibration is ready for setup `{context.setup_id}`."
                    " Move the arm to a middle pose first, then press Enter to start live calibration."
                    + save_notice
                ),
                details={"calibration_path": expected_path, "calibration_phase": phase},
            )
        if phase == "streaming":
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=(
                    f"SO101 live calibration is already running for setup `{context.setup_id}`."
                    " Keep moving every joint through its full range of motion, then press Enter again to stop and save."
                    f" Canonical path: `{expected_path}`."
                ),
                details={"calibration_path": expected_path, "calibration_phase": phase},
            )
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message="SO101 calibration is in an unknown state. Reply with `calibrate` to restart it.",
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
            flow.phase = "streaming"
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
                message=f"RoboClaw could not start live SO101 calibration. {exc}",
            )

        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=(
                f"SO101 live calibration started for setup `{context.setup_id}`."
                " RoboClaw is now streaming a LeRobot-style `MIN | POS | MAX` table above."
                " Move every joint through its full range of motion, then press Enter again to stop and save."
                f" Canonical path: `{flow.calibration_path}`."
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
                message=f"RoboClaw could not save the SO101 calibration file. {exc}",
            )

        self._cleanup_so101_calibration_flow(context.runtime.id)
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=True,
            message=(
                f"Saved SO101 calibration for setup `{context.setup_id}` to `{flow.calibration_path}`."
                " You can retry `connect` or your motion command now."
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
            f"SO101 calibration live view frame {sample_idx} on `{snapshot.resolved_device or snapshot.device_by_id}`",
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
