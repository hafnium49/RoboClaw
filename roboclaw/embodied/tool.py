"""Embodied tool — bridges agent to the embodied robotics layer."""

import json
from pathlib import Path
from typing import Any

from roboclaw.agent.tools.base import Tool

_ACTIONS = [
    "doctor",
    "calibrate",
    "teleoperate",
    "record",
    "train",
    "run_policy",
    "job_status",
    "setup_show",
    "set_arm",
    "remove_arm",
    "set_camera",
    "remove_camera",
]

_LOGS_DIR = Path("~/.roboclaw/workspace/embodied/jobs").expanduser()
_NO_TTY_MSG = "This action requires a local terminal. Run: roboclaw agent"


class EmbodiedTool(Tool):
    """Control embodied robots via the agent.

    The agent maintains setup.json through structured actions
    (set_arm, remove_arm, set_camera, remove_camera, setup_show).
    All hardware actions read setup.json for arm ports, cameras, calibration dirs.
    """

    def __init__(self, tty_handoff: Any = None):
        self._tty_handoff = tty_handoff

    @property
    def name(self) -> str:
        return "embodied"

    @property
    def description(self) -> str:
        return (
            "Control embodied robots — connect, calibrate, collect data, "
            "train policies, and run inference. "
            "Use setup_show to view current config. "
            "Use set_arm/remove_arm to configure arms (role: follower/leader, "
            "optional alias for friendly display name). "
            "Use set_camera/remove_camera to configure cameras "
            "(picks from scanned_cameras by index)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": _ACTIONS,
                    "description": "The action to perform.",
                },
                "dataset_name": {
                    "type": "string",
                    "description": "Name for the dataset.",
                },
                "task": {
                    "type": "string",
                    "description": "Task description for recording.",
                },
                "num_episodes": {
                    "type": "integer",
                    "description": "Number of episodes to record or run.",
                },
                "fps": {
                    "type": "integer",
                    "description": "Frames per second for recording.",
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of training steps.",
                },
                "checkpoint_path": {
                    "type": "string",
                    "description": "Path to a trained policy checkpoint.",
                },
                "job_id": {
                    "type": "string",
                    "description": "ID of a background training job.",
                },
                "device": {
                    "type": "string",
                    "description": "Device for training (default: cuda).",
                },
                "role": {
                    "type": "string",
                    "enum": ["follower", "leader"],
                    "description": "Arm role (for set_arm / remove_arm).",
                },
                "arm_type": {
                    "type": "string",
                    "enum": ["so101_follower", "so101_leader"],
                    "description": "Arm hardware type (for set_arm).",
                },
                "port": {
                    "type": "string",
                    "description": "Serial port path (for set_arm).",
                },
                "camera_name": {
                    "type": "string",
                    "description": "Camera name like front/side (for set_camera / remove_camera).",
                },
                "camera_index": {
                    "type": "integer",
                    "description": "Index into scanned_cameras (for set_camera).",
                },
                "alias": {
                    "type": "string",
                    "description": "Friendly display name for the arm (for set_arm).",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from roboclaw.embodied.setup import ensure_setup, load_setup

        action = kwargs.get("action", "")

        if action == "setup_show":
            return json.dumps(load_setup(), indent=2, ensure_ascii=False)

        if action in ("set_arm", "remove_arm", "set_camera", "remove_camera"):
            return self._handle_setup_action(action, kwargs)

        setup = ensure_setup()

        if action == "doctor":
            return await self._do_doctor(setup)
        if action == "calibrate":
            return await self._do_calibrate(setup)
        if action == "teleoperate":
            return await self._do_teleoperate(setup)
        if action == "record":
            return await self._do_record(setup, kwargs)
        if action == "train":
            return await self._do_train(setup, kwargs)
        if action == "run_policy":
            return await self._do_run_policy(setup, kwargs)
        if action == "job_status":
            return await self._do_job_status(kwargs)

        return f"Unknown action: {action}"

    def _handle_setup_action(self, action: str, kwargs: dict) -> str:
        """Dispatch structured setup mutations. Returns user-facing message."""
        from roboclaw.embodied.setup import remove_arm, remove_camera, set_arm, set_camera

        if action == "set_arm":
            return self._do_set_arm(kwargs, set_arm)
        if action == "remove_arm":
            return self._do_remove_arm(kwargs, remove_arm)
        if action == "set_camera":
            return self._do_set_camera(kwargs, set_camera)
        return self._do_remove_camera(kwargs, remove_camera)

    @staticmethod
    def _do_set_arm(kwargs: dict, fn: Any) -> str:
        from roboclaw.embodied.setup import arm_display_name

        role = kwargs.get("role", "")
        arm_type = kwargs.get("arm_type", "")
        port = kwargs.get("port", "")
        if not all([role, arm_type, port]):
            return "set_arm requires role, arm_type, and port."
        alias = kwargs.get("alias") or None
        updated = fn(role, arm_type, port, alias=alias)
        arm = updated["arms"][role]
        display = arm_display_name(role, arm)
        return f"Arm '{display}' configured.\n{json.dumps(arm, indent=2)}"

    @staticmethod
    def _do_remove_arm(kwargs: dict, fn: Any) -> str:
        role = kwargs.get("role", "")
        if not role:
            return "remove_arm requires role."
        fn(role)
        return f"Arm '{role}' removed."

    @staticmethod
    def _do_set_camera(kwargs: dict, fn: Any) -> str:
        name = kwargs.get("camera_name", "")
        index = kwargs.get("camera_index")
        if not name or index is None:
            return "set_camera requires camera_name and camera_index."
        updated = fn(name, index)
        return f"Camera '{name}' configured.\n{json.dumps(updated['cameras'][name], indent=2)}"

    @staticmethod
    def _do_remove_camera(kwargs: dict, fn: Any) -> str:
        name = kwargs.get("camera_name", "")
        if not name:
            return "remove_camera requires camera_name."
        fn(name)
        return f"Camera '{name}' removed."

    async def _do_doctor(self, setup: dict) -> str:
        from roboclaw.embodied.embodiment.so101 import SO101Controller
        from roboclaw.embodied.runner import LocalLeRobotRunner

        result = await self._run(LocalLeRobotRunner(), SO101Controller().doctor())
        return result + f"\n\nCurrent setup:\n{json.dumps(setup, indent=2, ensure_ascii=False)}"

    async def _do_calibrate(self, setup: dict) -> str:
        from roboclaw.embodied.embodiment.so101 import SO101Controller
        from roboclaw.embodied.runner import LocalLeRobotRunner
        from roboclaw.embodied.setup import arm_display_name, update_setup

        arms = setup.get("arms", {})
        if not arms:
            return "No arms configured in setup. Use set_arm to add arms first."
        uncalibrated = {name: arm for name, arm in arms.items() if arm.get("calibrated") is not True}
        if not uncalibrated:
            return "All arms are already calibrated."
        if not self._tty_handoff:
            return _NO_TTY_MSG
        controller = SO101Controller()
        runner = LocalLeRobotRunner()
        succeeded, failed = 0, 0
        results = []
        for name, arm in uncalibrated.items():
            display = arm_display_name(name, arm)
            argv = controller.calibrate(arm["type"], arm["port"], arm.get("calibration_dir", ""))
            returncode = await self._run_tty(runner, argv, f"lerobot-calibrate ({display})")
            if returncode == 0:
                succeeded += 1
                update_setup({"arms": {name: {"calibrated": True}}})
                results.append(f"{display}: OK")
            else:
                failed += 1
                results.append(f"{display}: FAILED (exit {returncode})")
        return f"{succeeded} succeeded, {failed} failed.\n" + "\n".join(results)

    async def _do_teleoperate(self, setup: dict) -> str:
        from roboclaw.embodied.embodiment.so101 import SO101Controller
        from roboclaw.embodied.runner import LocalLeRobotRunner
        from roboclaw.embodied.setup import arm_display_name

        follower, leader = self._resolve_arms(setup)
        if isinstance(follower, str):
            return follower
        if not self._tty_handoff:
            return _NO_TTY_MSG
        arms = setup.get("arms", {})
        f_name = arm_display_name("follower", arms.get("follower", {}))
        l_name = arm_display_name("leader", arms.get("leader", {}))
        argv = SO101Controller().teleoperate(
            robot_type=follower["type"], robot_port=follower["port"], robot_cal_dir=follower["calibration_dir"],
            teleop_type=leader["type"], teleop_port=leader["port"], teleop_cal_dir=leader["calibration_dir"],
        )
        rc = await self._run_tty(LocalLeRobotRunner(), argv, f"lerobot-teleoperate ({f_name} + {l_name})")
        return "Teleoperation finished." if rc == 0 else f"Teleoperation failed (exit {rc})."

    async def _do_record(self, setup: dict, kwargs: dict) -> str:
        from roboclaw.embodied.embodiment.so101 import SO101Controller
        from roboclaw.embodied.runner import LocalLeRobotRunner
        from roboclaw.embodied.setup import arm_display_name

        follower, leader = self._resolve_arms(setup)
        if isinstance(follower, str):
            return follower
        if not self._tty_handoff:
            return _NO_TTY_MSG
        arms = setup.get("arms", {})
        f_name = arm_display_name("follower", arms.get("follower", {}))
        cameras = self._resolve_cameras(setup)
        dataset_name = kwargs.get("dataset_name", "default")
        argv = SO101Controller().record(
            robot_type=follower["type"], robot_port=follower["port"], robot_cal_dir=follower["calibration_dir"],
            teleop_type=leader["type"], teleop_port=leader["port"], teleop_cal_dir=leader["calibration_dir"],
            cameras=cameras,
            repo_id=f"local/{dataset_name}",
            task=kwargs.get("task", "default_task"),
            fps=kwargs.get("fps", 30),
            num_episodes=kwargs.get("num_episodes", 10),
        )
        rc = await self._run_tty(LocalLeRobotRunner(), argv, f"lerobot-record ({f_name})")
        return "Recording finished." if rc == 0 else f"Recording failed (exit {rc})."

    async def _do_train(self, setup: dict, kwargs: dict) -> str:
        from roboclaw.embodied.learning.act import ACTPipeline
        from roboclaw.embodied.runner import LocalLeRobotRunner

        dataset_name = kwargs.get("dataset_name", "default")
        dataset_root = setup.get("datasets", {}).get("root", "")
        policies_root = setup.get("policies", {}).get("root", "")
        argv = ACTPipeline().train(
            repo_id=f"local/{dataset_name}",
            dataset_root=dataset_root,
            output_dir=policies_root,
            steps=kwargs.get("steps", 100_000),
            device=kwargs.get("device", "cuda"),
        )
        job_id = await LocalLeRobotRunner().run_detached(argv=argv, log_dir=_LOGS_DIR)
        return f"Training started. Job ID: {job_id}"

    async def _do_run_policy(self, setup: dict, kwargs: dict) -> str:
        from roboclaw.embodied.embodiment.so101 import SO101Controller
        from roboclaw.embodied.learning.act import ACTPipeline
        from roboclaw.embodied.runner import LocalLeRobotRunner

        follower = setup.get("arms", {}).get("follower")
        if not follower:
            return "No follower arm configured. Use set_arm to add one."
        cameras = self._resolve_cameras(setup)
        policies_root = setup.get("policies", {}).get("root", "")
        checkpoint = kwargs.get("checkpoint_path") or ACTPipeline().checkpoint_path(policies_root)
        argv = SO101Controller().run_policy(
            robot_type=follower["type"], robot_port=follower["port"], robot_cal_dir=follower["calibration_dir"],
            cameras=cameras, policy_path=checkpoint,
            num_episodes=kwargs.get("num_episodes", 1),
        )
        return await self._run(LocalLeRobotRunner(), argv)

    async def _do_job_status(self, kwargs: dict) -> str:
        from roboclaw.embodied.runner import LocalLeRobotRunner

        job_id = kwargs.get("job_id", "")
        status = await LocalLeRobotRunner().job_status(job_id=job_id, log_dir=_LOGS_DIR)
        return "\n".join(f"{k}: {v}" for k, v in status.items())

    def _resolve_arms(self, setup: dict) -> tuple[dict, dict] | tuple[str, None]:
        """Get follower and leader arm configs from setup. Returns error string if missing."""
        arms = setup.get("arms", {})
        follower = arms.get("follower")
        leader = arms.get("leader")
        if not follower:
            return "No follower arm configured. Use set_arm to add arms.", None
        if not leader:
            return "No leader arm configured. Use set_arm to add arms.", None
        return follower, leader

    def _resolve_cameras(self, setup: dict) -> dict[str, dict]:
        """Convert setup cameras to LeRobot camera format {name: {type, index_or_path}}."""
        cameras = setup.get("cameras", {})
        result = {}
        for name, cam in cameras.items():
            path = cam.get("by_path") or cam.get("dev", "")
            if not path:
                continue
            result[name] = {"type": "opencv", "index_or_path": path}
        return result

    async def _run_tty(self, runner: Any, argv: list[str], label: str) -> int:
        """Run interactive command with TTY handoff. Always calls stop even on error."""
        await self._tty_handoff(start=True, label=label)
        try:
            return await runner.run_interactive(argv)
        finally:
            await self._tty_handoff(start=False, label=label)

    @staticmethod
    async def _run(runner: Any, argv: list[str]) -> str:
        returncode, stdout, stderr = await runner.run(argv)
        if returncode != 0:
            return f"Command failed (exit {returncode}).\nstdout: {stdout}\nstderr: {stderr}"
        return stdout or "Done."
