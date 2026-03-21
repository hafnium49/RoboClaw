"""PiperX robot definition."""

from roboclaw.embodied.definition.components.robots.model import PrimitiveSpec, quick_manifest
from roboclaw.embodied.definition.foundation.schema import CapabilityFamily, CommandMode, ParameterSpec, PrimitiveKind, RobotType, ValueUnit

PIPERX_ROBOT = quick_manifest(
    id="piperx",
    name="PiperX",
    robot_type=RobotType.ARM,
    description="AgileX PiperX 6-DOF arm with gripper over CAN bus.",
    primitives=(
        PrimitiveSpec(
            name="move_joint",
            kind=PrimitiveKind.MOTION,
            capability_family=CapabilityFamily.JOINT_MOTION,
            command_mode=CommandMode.POSITION,
            description="Move one or more joints to target positions.",
            parameters=(ParameterSpec("positions", "dict[str,float]", "Joint name to target value map.", True, ValueUnit.RADIAN, "joint_space"),),
        ),
        PrimitiveSpec("gripper_open", PrimitiveKind.END_EFFECTOR, CapabilityFamily.END_EFFECTOR, CommandMode.DISCRETE_TRIGGER, "Open the gripper."),
        PrimitiveSpec("gripper_close", PrimitiveKind.END_EFFECTOR, CapabilityFamily.END_EFFECTOR, CommandMode.DISCRETE_TRIGGER, "Close the gripper."),
        PrimitiveSpec(
            name="go_named_pose",
            kind=PrimitiveKind.POSE,
            capability_family=CapabilityFamily.NAMED_POSE,
            command_mode=CommandMode.WAYPOINT,
            description="Move to a named pose such as home or ready.",
            parameters=(ParameterSpec("name", "str", "Named pose identifier.", True),),
        ),
    ),
    default_named_poses=("home", "ready"),
    setup_hints=("Use the CAN bus interface on `can0`.",),
)

__all__ = ["PIPERX_ROBOT"]
