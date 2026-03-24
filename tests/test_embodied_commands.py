"""Tests for SO101Controller and ACTPipeline CLI arg generation."""

from roboclaw.embodied.embodiment.so101 import SO101Controller
from roboclaw.embodied.learning.act import ACTPipeline


def test_doctor_command() -> None:
    argv = SO101Controller().doctor()
    assert argv[0] == "python3"
    assert "import lerobot" in argv[2]


def test_calibrate_follower() -> None:
    argv = SO101Controller().calibrate("so101_follower", "/dev/ttyACM0", "/cal/follower")
    assert "lerobot-calibrate" in argv
    assert "--robot.type=so101_follower" in argv
    assert "--robot.port=/dev/ttyACM0" in argv
    assert any("--robot.calibration_dir=" in a for a in argv)


def test_calibrate_leader() -> None:
    argv = SO101Controller().calibrate("so101_leader", "/dev/ttyACM1", "/cal/leader")
    assert "lerobot-calibrate" in argv
    assert "--teleop.type=so101_leader" in argv
    assert "--teleop.port=/dev/ttyACM1" in argv
    assert any("--teleop.calibration_dir=" in a for a in argv)


def test_teleoperate() -> None:
    argv = SO101Controller().teleoperate(
        "so101_follower", "/dev/ttyACM0", "/cal/f",
        "so101_leader", "/dev/ttyACM1", "/cal/l",
    )
    assert "lerobot-teleoperate" in argv
    assert "--robot.type=so101_follower" in argv
    assert "--teleop.type=so101_leader" in argv


def test_record() -> None:
    cameras = {"front": {"type": "opencv", "index": 0}}
    argv = SO101Controller().record(
        "so101_follower", "/dev/ttyACM0", "/cal/f",
        "so101_leader", "/dev/ttyACM1", "/cal/l",
        cameras=cameras, repo_id="local/test_data",
        task="pick and place", fps=30, num_episodes=5,
    )
    assert "lerobot-record" in argv
    assert "--robot.type=so101_follower" in argv
    assert "--teleop.type=so101_leader" in argv
    assert any("--robot.cameras=" in a for a in argv)
    assert "--dataset.repo_id=local/test_data" in argv
    assert "--dataset.single_task=pick and place" in argv
    assert "--dataset.fps=30" in argv
    assert "--dataset.num_episodes=5" in argv


def test_run_policy() -> None:
    cameras = {"front": {"type": "opencv", "index": 0}}
    argv = SO101Controller().run_policy(
        "so101_follower", "/dev/ttyACM0", "/cal/f",
        cameras=cameras, policy_path="/models/act_checkpoint",
    )
    assert "lerobot-record" in argv
    assert "--robot.type=so101_follower" in argv
    assert any("--policy.path=" in a for a in argv)
    assert any("--robot.cameras=" in a for a in argv)
    assert not any("--teleop" in a for a in argv)


def test_train() -> None:
    argv = ACTPipeline().train(
        repo_id="local/test_data",
        dataset_root="/data",
        output_dir="/output",
        steps=50000,
        device="cuda",
    )
    assert "lerobot-train" in argv
    assert "--dataset.repo_id=local/test_data" in argv
    assert "--dataset.root=/data" in argv
    assert "--policy.type=act" in argv
    assert "--steps=50000" in argv
    assert "--policy.device=cuda" in argv


def test_checkpoint_path() -> None:
    path = ACTPipeline().checkpoint_path("/output")
    assert "checkpoints/last/pretrained_model" in path
