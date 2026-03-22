"""CLI probe for one SCServo register read."""

from __future__ import annotations

import importlib.util
import sys

from roboclaw.embodied.execution.integration.control_surfaces.ros2.scservo import DEFAULT_BAUDRATE, probe_servo_register

SO101_GRIPPER_SERVO_ID = 6
SO101_PRESENT_POSITION_ADDR = 56


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m roboclaw.embodied.execution.integration.control_surfaces.ros2.scservo_probe <device-by-id>")
        return 2

    try:
        sdk_available = "scservo_sdk" in sys.modules or importlib.util.find_spec("scservo_sdk") is not None
    except ValueError:
        sdk_available = "scservo_sdk" in sys.modules
    if not sdk_available:
        print("ROBOCLAW_SO101_SERIAL_SDK_MISSING")
        return 0

    result = probe_servo_register(
        args[0],
        SO101_GRIPPER_SERVO_ID,
        SO101_PRESENT_POSITION_ADDR,
        baudrate=DEFAULT_BAUDRATE,
    )
    print(
        "ROBOCLAW_SO101_SERIAL_PROBE "
        f"resolved={result['resolved']} "
        f"open={int(bool(result['open']))} "
        f"baud={int(bool(result['open']))} "
        f"result={result['result']} "
        f"error={result['error']} "
        f"value={result['value']}"
    )
    if result["ok"]:
        print("ROBOCLAW_SO101_SERIAL_OK")
    else:
        print(result["detail"] or "ROBOCLAW_SO101_SERIAL_NO_STATUS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
