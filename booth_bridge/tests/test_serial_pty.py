"""Real serial-manager test over a Linux pty pair (no hardware)."""

import os
import pty
import threading

import pytest

from booth_bridge.serial_manager import SerialManager
from protocols.passti.frame import build_response, is_complete_frame


@pytest.mark.asyncio
async def test_serial_manager_reads_response_from_pty():
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    response = build_response(0x00, b"\x00\x00\x00", b"\x01\x02\x03")
    requests: list[bytes] = []

    def responder() -> None:
        try:
            requests.append(os.read(master_fd, 1024))
            os.write(master_fd, response)
        except OSError:
            pass

    thread = threading.Thread(target=responder, daemon=True)
    thread.start()

    manager = SerialManager(
        {
            "emoney_reader": {
                "enabled": True,
                "device": slave_name,
                "baudrate": 38400,
            }
        }
    )
    try:
        await manager.start()
        assert manager.is_connected("emoney_reader")

        got = manager.send(
            "emoney_reader",
            b"\x02\x00\x04\xef\x01\x02\x00\x00\x00\x00",
            response_timeout_s=2.0,
            is_complete=is_complete_frame,
        )
        assert got == response
    finally:
        await manager.stop()
        os.close(master_fd)
        os.close(slave_fd)

    thread.join(timeout=1)
    assert requests, "serial manager never wrote the request"
