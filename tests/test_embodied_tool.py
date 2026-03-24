"""Tests for the EmbodiedTool integration with the agent."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from unittest.mock import patch as std_patch

from roboclaw.embodied.setup import (
    _CALIBRATION_ROOT,
    load_setup,
    remove_arm,
    remove_camera,
    save_setup,
    set_arm,
    set_camera,
)
from roboclaw.embodied.tool import EmbodiedTool

_MOCK_SCANNED_PORTS = [
    {"by_path": "/dev/serial/by-path/pci-0:2.1", "by_id": "/dev/serial/by-id/usb-1a86_5B14032630", "dev": "/dev/ttyACM0"},
    {"by_path": "/dev/serial/by-path/pci-0:2.2", "by_id": "/dev/serial/by-id/usb-1a86_5B14030892", "dev": "/dev/ttyACM1"},
]


def test_tool_schema() -> None:
    tool = EmbodiedTool()
    assert tool.name == "embodied"
    assert "robot" in tool.description.lower()

    params = tool.parameters
    assert params["type"] == "object"
    assert "action" in params["properties"]
    assert params["required"] == ["action"]

    action_schema = params["properties"]["action"]
    assert action_schema["type"] == "string"
    expected_actions = [
        "doctor", "calibrate", "teleoperate", "record",
        "train", "run_policy", "job_status",
        "setup_show", "set_arm", "remove_arm", "set_camera", "remove_camera",
    ]
    assert action_schema["enum"] == expected_actions


_MOCK_SETUP = {
    "version": 2,
    "arms": {
        "follower": {
            "type": "so101_follower",
            "port": "/dev/ttyACM0",
            "calibration_dir": "/cal/f",
            "calibrated": False,
        },
        "leader": {
            "type": "so101_leader",
            "port": "/dev/ttyACM1",
            "calibration_dir": "/cal/l",
            "calibrated": False,
        },
    },
    "cameras": {
        "front": {"by_path": "", "by_id": "", "dev": "/dev/video0"},
    },
    "datasets": {"root": "/data"},
    "policies": {"root": "/policies"},
    "scanned_ports": [],
    "scanned_cameras": [],
}


@pytest.mark.asyncio
async def test_doctor_action() -> None:
    tool = EmbodiedTool()
    mock_runner = AsyncMock()
    mock_runner.run.return_value = (0, "lerobot 0.5.0", "")

    with (
        patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP),
        patch("roboclaw.embodied.runner.LocalLeRobotRunner", return_value=mock_runner),
    ):
        result = await tool.execute(action="doctor")

    assert "lerobot 0.5.0" in result
    assert "setup" in result.lower()


@pytest.mark.asyncio
async def test_calibrate_all_arms() -> None:
    mock_handoff = AsyncMock()
    tool = EmbodiedTool(tty_handoff=mock_handoff)
    mock_runner = AsyncMock()
    mock_runner.run_interactive.return_value = 0

    with (
        patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP),
        patch("roboclaw.embodied.setup.update_setup"),
        patch("roboclaw.embodied.runner.LocalLeRobotRunner", return_value=mock_runner),
    ):
        result = await tool.execute(action="calibrate")

    assert "2 succeeded" in result
    assert "follower" in result
    assert "leader" in result
    assert mock_runner.run_interactive.call_count == 2
    assert mock_handoff.call_count == 4  # start+stop for each arm


@pytest.mark.asyncio
async def test_calibrate_no_arms() -> None:
    empty_setup = {**_MOCK_SETUP, "arms": {}}
    tool = EmbodiedTool()
    with patch("roboclaw.embodied.setup.ensure_setup", return_value=empty_setup):
        result = await tool.execute(action="calibrate")
    assert "no arms" in result.lower()


@pytest.mark.asyncio
async def test_calibrate_no_tty() -> None:
    tool = EmbodiedTool()  # no tty_handoff
    with patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP):
        result = await tool.execute(action="calibrate")
    assert "local terminal" in result.lower()


@pytest.mark.asyncio
async def test_record_action() -> None:
    tool = EmbodiedTool(tty_handoff=AsyncMock())
    mock_runner = AsyncMock()
    mock_runner.run_interactive.return_value = 0

    with (
        patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP),
        patch("roboclaw.embodied.runner.LocalLeRobotRunner", return_value=mock_runner),
    ):
        result = await tool.execute(action="record", dataset_name="test", task="grasp", num_episodes=5)

    assert "Recording finished" in result
    argv = mock_runner.run_interactive.call_args[0][0]
    assert "--robot.type=so101_follower" in argv
    assert "--teleop.type=so101_leader" in argv
    assert any("--robot.cameras=" in a for a in argv)


@pytest.mark.asyncio
async def test_train_action() -> None:
    tool = EmbodiedTool()
    mock_runner = AsyncMock()
    mock_runner.run_detached.return_value = "job-abc-123"

    with (
        patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP),
        patch("roboclaw.embodied.runner.LocalLeRobotRunner", return_value=mock_runner),
    ):
        result = await tool.execute(action="train", dataset_name="test", steps=5000)

    assert "job-abc-123" in result


@pytest.mark.asyncio
async def test_unknown_action() -> None:
    tool = EmbodiedTool()
    with patch("roboclaw.embodied.setup.ensure_setup", return_value=_MOCK_SETUP):
        result = await tool.execute(action="fly_to_moon")
    assert "Unknown action" in result


# ── setup.py structured mutator tests ───────────────────────────────


@pytest.fixture()
def setup_file(tmp_path: Path) -> Path:
    """Create a minimal setup.json for testing."""
    p = tmp_path / "setup.json"
    base = {
        "version": 2,
        "arms": {},
        "cameras": {},
        "datasets": {"root": "/data"},
        "policies": {"root": "/policies"},
        "scanned_ports": [
            {"by_path": "/dev/serial/by-path/pci-0:2.1", "by_id": "/dev/serial/by-id/usb-1a86_5B14032630", "dev": "/dev/ttyACM0"},
            {"by_path": "/dev/serial/by-path/pci-0:2.2", "by_id": "/dev/serial/by-id/usb-1a86_5B14030892", "dev": "/dev/ttyACM1"},
        ],
        "scanned_cameras": [
            {"by_path": "/dev/v4l/by-path/cam0", "by_id": "usb-cam0", "dev": "/dev/video0"},
            {"by_path": "/dev/v4l/by-path/cam1", "by_id": "usb-cam1", "dev": "/dev/video2"},
        ],
    }
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_set_arm(setup_file: Path) -> None:
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=_MOCK_SCANNED_PORTS):
        result = set_arm("follower", "so101_follower", "/dev/ttyACM0", path=setup_file)
    arm = result["arms"]["follower"]
    assert arm["type"] == "so101_follower"
    assert arm["port"] == "/dev/serial/by-id/usb-1a86_5B14032630"
    assert arm["calibration_dir"] == str(_CALIBRATION_ROOT / "follower")
    assert arm["calibrated"] is False
    # Verify persisted
    persisted = load_setup(setup_file)
    assert persisted["arms"]["follower"] == arm


def test_set_arm_resolves_volatile_port(setup_file: Path) -> None:
    """Volatile /dev/ttyACMx should be resolved to stable /dev/serial/by-id/..."""
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=_MOCK_SCANNED_PORTS):
        result = set_arm("leader", "so101_leader", "/dev/ttyACM1", path=setup_file)
    assert result["arms"]["leader"]["port"] == "/dev/serial/by-id/usb-1a86_5B14030892"


def test_set_arm_keeps_stable_port(setup_file: Path) -> None:
    """Already-stable by-id port should be kept as-is."""
    stable = "/dev/serial/by-id/usb-custom-device"
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=[]):
        result = set_arm("follower", "so101_follower", stable, path=setup_file)
    assert result["arms"]["follower"]["port"] == stable


def test_set_arm_unmatched_volatile_port(setup_file: Path) -> None:
    """Volatile port not in scan results should be kept as-is."""
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=[]):
        result = set_arm("follower", "so101_follower", "/dev/ttyUSB99", path=setup_file)
    assert result["arms"]["follower"]["port"] == "/dev/ttyUSB99"


def test_set_arm_invalid_type(setup_file: Path) -> None:
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=[]):
        with pytest.raises(ValueError, match="Invalid arm_type"):
            set_arm("follower", "bogus_arm", "/dev/ttyACM0", path=setup_file)


def test_set_arm_invalid_role(setup_file: Path) -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        set_arm("sidekick", "so101_follower", "/dev/ttyACM0", path=setup_file)


def test_remove_arm(setup_file: Path) -> None:
    with std_patch("roboclaw.embodied.scan.scan_serial_ports", return_value=[]):
        set_arm("follower", "so101_follower", "/dev/ttyACM0", path=setup_file)
    result = remove_arm("follower", path=setup_file)
    assert "follower" not in result["arms"]


def test_remove_arm_missing(setup_file: Path) -> None:
    with pytest.raises(ValueError, match="No arm with role"):
        remove_arm("leader", path=setup_file)


def test_set_camera(setup_file: Path) -> None:
    result = set_camera("front", 0, path=setup_file)
    cam = result["cameras"]["front"]
    assert cam["by_path"] == "/dev/v4l/by-path/cam0"
    assert cam["dev"] == "/dev/video0"
    assert cam["by_id"] == "usb-cam0"
    # Only _CAMERA_FIELDS should be copied
    assert set(cam.keys()) <= {"by_path", "by_id", "dev"}


def test_set_camera_bad_index(setup_file: Path) -> None:
    with pytest.raises(ValueError, match="out of range"):
        set_camera("front", 99, path=setup_file)


def test_remove_camera(setup_file: Path) -> None:
    set_camera("front", 0, path=setup_file)
    result = remove_camera("front", path=setup_file)
    assert "front" not in result["cameras"]


def test_remove_camera_missing(setup_file: Path) -> None:
    with pytest.raises(ValueError, match="No camera named"):
        remove_camera("nonexistent", path=setup_file)


def test_validation_rejects_unknown_arm_fields(setup_file: Path) -> None:
    """save_setup should reject arms with unexpected fields."""
    bad = load_setup(setup_file)
    bad["arms"]["follower"] = {"type": "so101_follower", "port": "/dev/x", "junk": True}
    with pytest.raises(ValueError, match="unknown fields"):
        save_setup(bad, setup_file)


def test_validation_rejects_unknown_camera_fields(setup_file: Path) -> None:
    bad = load_setup(setup_file)
    bad["cameras"]["front"] = {"dev": "/dev/video0", "fps": 30}
    with pytest.raises(ValueError, match="unknown fields"):
        save_setup(bad, setup_file)


def test_validation_rejects_bad_arm_type(setup_file: Path) -> None:
    bad = load_setup(setup_file)
    bad["arms"]["follower"] = {"type": "garbage", "port": "/dev/x"}
    with pytest.raises(ValueError, match="invalid type"):
        save_setup(bad, setup_file)
