"""Robot exports."""

from roboclaw.embodied.definition.components.robots.arms.piperx import PIPERX_ROBOT
from roboclaw.embodied.definition.components.robots.arms import SO101_ROBOT
from roboclaw.embodied.definition.components.robots.config import RobotConfig, Ros2RobotConfig
from roboclaw.embodied.definition.components.robots.model import PrimitiveSpec, RobotManifest
from roboclaw.embodied.definition.components.robots.registry import RobotRegistry

__all__ = [
    "PrimitiveSpec",
    "PIPERX_ROBOT",
    "RobotConfig",
    "RobotManifest",
    "RobotRegistry",
    "Ros2RobotConfig",
    "SO101_ROBOT",
]
