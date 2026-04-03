"""Feetech (STS3215 / scservo_sdk) port prober."""
from __future__ import annotations

from roboclaw.embodied.hardware.probers import register_prober

DEFAULT_BAUDRATE = 1_000_000
MOTOR_IDS = list(range(1, 7))

# STS3215 Present_Position register
_FEETECH_POS_ADDR = 56
_FEETECH_POS_LEN = 2


class FeetechProber:
    """Probe and read Feetech servo motors on a serial port."""

    def probe(self, port_path: str, baudrate: int = DEFAULT_BAUDRATE) -> list[int]:
        """Try reading Present_Position for Feetech motor IDs 1-6."""
        from roboclaw.embodied.stub import is_stub_mode, stub_motor_ids

        if is_stub_mode():
            return stub_motor_ids(port_path)
        import scservo_sdk as scs

        handler = scs.PortHandler(port_path)
        try:
            if not handler.openPort():
                return []
        except OSError:
            return []
        handler.setBaudRate(baudrate)
        packet = scs.PacketHandler(0)
        found = []
        for mid in MOTOR_IDS:
            val, result, _ = packet.read2ByteTxRx(handler, mid, _FEETECH_POS_ADDR)
            if result == scs.COMM_SUCCESS:
                found.append(mid)
        handler.closePort()
        return found

    def read_positions(
        self, port_path: str, motor_ids: list[int], baudrate: int = DEFAULT_BAUDRATE,
    ) -> dict[int, int]:
        """Read Feetech Present_Position for each motor ID."""
        from roboclaw.embodied.stub import is_stub_mode

        if is_stub_mode():
            return {mid: 0 for mid in motor_ids}
        import scservo_sdk as scs

        handler = scs.PortHandler(port_path)
        if not handler.openPort():
            return {}
        handler.setBaudRate(baudrate)
        packet = scs.PacketHandler(0)
        positions: dict[int, int] = {}
        for mid in motor_ids:
            val, result, _ = packet.read2ByteTxRx(handler, mid, _FEETECH_POS_ADDR)
            if result == scs.COMM_SUCCESS:
                positions[mid] = val
        handler.closePort()
        return positions


register_prober("feetech", FeetechProber)
