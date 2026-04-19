"""Tests for the current CalibrationSession flow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from roboclaw.embodied.board import Board, SessionState
from roboclaw.embodied.command.builder import CommandBuilder
from roboclaw.embodied.embodiment.manifest import Manifest
from roboclaw.embodied.embodiment.manifest.binding import Binding
from roboclaw.embodied.embodiment.manifest.helpers import save_manifest
from roboclaw.embodied.service import EmbodiedService
from roboclaw.embodied.service.session.calibrate import (
    CalibrationOutputConsumer,
    _resolve_targets,
    _sync_calibration_to_motors,
)


def _manifest_from_data(tmp_path: Path, data: dict) -> Manifest:
    path = tmp_path / "manifest.json"
    save_manifest(data, path)
    return Manifest(path=path)


@pytest.fixture
def manifest_data(tmp_path: Path) -> Manifest:
    serial_a = "F001"
    serial_b = "L001"
    return _manifest_from_data(
        tmp_path,
        {
            "version": 2,
            "arms": [
                {
                    "alias": "follower_a",
                    "type": "so101_follower",
                    "port": f"/dev/serial/by-id/{serial_a}",
                    "calibration_dir": str(tmp_path / "calibration" / serial_a),
                    "calibrated": False,
                },
                {
                    "alias": "leader_b",
                    "type": "so101_leader",
                    "port": f"/dev/serial/by-id/{serial_b}",
                    "calibration_dir": str(tmp_path / "calibration" / serial_b),
                    "calibrated": True,
                },
            ],
            "hands": [],
            "cameras": [],
            "datasets": {"root": "/data"},
            "policies": {"root": "/policies"},
        },
    )


def test_output_consumer_parses_position_rows_and_steps() -> None:
    board = Board()
    consumer = CalibrationOutputConsumer(board, stdout=None)

    async def _run() -> None:
        await consumer.parse_line("shoulder_pan | -100 | 0 | 100")
        await consumer.parse_line("Press Enter to use provided calibration")
        await consumer.parse_line("Move joint to middle and press Enter")
        await consumer.parse_line("Recording positions. Press Enter to stop")
        await consumer.parse_line("Calibration saved")

    import asyncio

    asyncio.run(_run())

    state = board.state
    assert state["calibration_positions"] == {
        "shoulder_pan": {"min": -100, "pos": 0, "max": 100}
    }
    assert state["calibration_step"] == "done"


@pytest.mark.asyncio
async def test_start_calibration_uses_current_command_builder(
    manifest_data: Manifest,
) -> None:
    service = EmbodiedService(manifest=manifest_data)
    session = service.calibration
    arm = manifest_data.arms[0]

    with patch.object(session, "start", AsyncMock()) as start:
        await session.start_calibration(arm, manifest_data)

    start.assert_awaited_once_with(
        CommandBuilder.calibrate(arm),
        initial_state=SessionState.CALIBRATING,
        auto_confirm=False,
    )
    assert service.board.state["calibration_arm"] == arm.alias


def test_status_line_and_result_reflect_current_board_state(
    manifest_data: Manifest,
) -> None:
    service = EmbodiedService(manifest=manifest_data)
    session = service.calibration

    service.board.set_field("calibration_arm", "follower_a")
    service.board.set_field("calibration_step", "recording")
    assert session.status_line() == "Calibrating follower_a: recording range of motion"

    service.board.set_field("calibration_step", "done")
    assert session.result() == "Calibration of follower_a completed successfully."

    service.board.set_field("state", SessionState.ERROR)
    service.board.set_field("error", "serial timeout")
    service.board.set_field("calibration_step", "")
    assert session.result() == "Calibration of follower_a failed: serial timeout"


def test_resolve_targets_skips_calibrated_arms_by_default(
    manifest_data: Manifest,
) -> None:
    targets = _resolve_targets(manifest_data, {})
    assert [arm.alias for arm in targets] == ["follower_a"]


def test_resolve_targets_keeps_explicit_selection_even_if_calibrated(
    manifest_data: Manifest,
) -> None:
    targets = _resolve_targets(manifest_data, {"arms": "leader_b"})
    assert [arm.alias for arm in targets] == ["leader_b"]


def test_sync_calibration_to_motors_writes_expected_registers(tmp_path: Path) -> None:
    serial = "SYNC001"
    cal_dir = tmp_path / "calibration" / serial
    cal_dir.mkdir(parents=True)
    cal_path = cal_dir / f"{serial}.json"
    cal_path.write_text(
        json.dumps(
            {
                "shoulder_pan": {
                    "id": 1,
                    "drive_mode": 0,
                    "homing_offset": 10,
                    "range_min": -20,
                    "range_max": 30,
                }
            }
        ),
        encoding="utf-8",
    )
    arm = Binding.from_dict(
        {
            "alias": "follower_sync",
            "type": "so101_follower",
            "port": "/dev/ttyACM0",
            "calibration_dir": str(cal_dir),
            "calibrated": True,
        },
        "arm",
        {},
    )
    fake_bus = MagicMock()
    fake_module = SimpleNamespace(FeetechMotorsBus=lambda **kwargs: fake_bus)
    fake_motor_module = SimpleNamespace(
        Motor=lambda **kwargs: SimpleNamespace(**kwargs),
        MotorCalibration=lambda **kwargs: SimpleNamespace(**kwargs),
        MotorNormMode=SimpleNamespace(DEGREES="degrees"),
    )

    with (
        patch.dict(sys.modules, {"lerobot.motors.motors_bus": fake_motor_module}),
        patch(
            "roboclaw.embodied.service.session.calibrate.importlib.import_module",
            return_value=fake_module,
        ),
    ):
        _sync_calibration_to_motors(arm)

    fake_bus.connect.assert_called_once_with()
    assert fake_bus.write.call_args_list == [
        (("Homing_Offset", "shoulder_pan", 10), {"normalize": False}),
        (("Min_Position_Limit", "shoulder_pan", -20), {"normalize": False}),
        (("Max_Position_Limit", "shoulder_pan", 30), {"normalize": False}),
    ]
    fake_bus.disconnect.assert_called_once_with()
