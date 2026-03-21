from roboclaw.embodied.builtins import list_builtin_embodiments
from roboclaw.embodied.builtins.piperx import PIPERX_BUILTIN
from roboclaw.embodied.definition.components.robots import PIPERX_ROBOT


def test_piperx_manifest_is_valid() -> None:
    assert PIPERX_ROBOT.id == "piperx"
    assert {primitive.name for primitive in PIPERX_ROBOT.primitives} == {
        "move_joint",
        "gripper_open",
        "gripper_close",
        "go_named_pose",
    }
    assert PIPERX_ROBOT.observation_schema.fields
    assert PIPERX_ROBOT.health_schema.fields


def test_piperx_builtin_is_discoverable() -> None:
    builtins = {embodiment.id: embodiment for embodiment in list_builtin_embodiments()}
    assert builtins["piperx"] is PIPERX_BUILTIN


def test_piperx_builtin_has_no_calibration_driver() -> None:
    assert PIPERX_BUILTIN.calibration_driver_id is None


def test_piperx_capability_profile_has_joints_and_gripper() -> None:
    profile = PIPERX_ROBOT.capability_profile()
    assert profile.has("has_joints") is True
    assert profile.has("has_gripper") is True
