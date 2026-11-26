"""Server-queued print jobs written to a printer on the booth PC (pty, no hardware)."""

import os
import pty
import termios
import tty

import pytest

from booth_bridge.serial_manager import SerialManager


def _read_all(fd: int) -> bytes:
    os.set_blocking(fd, False)
    out = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            return out
        if not chunk:
            return out
        out += chunk


@pytest.mark.asyncio
async def test_blank_device_uses_booth_receipt_printer_and_named_device_works():
    managed_master, managed_slave = pty.openpty()
    other_master, other_slave = pty.openpty()
    for fd in (managed_slave, other_slave):  # raw mode: no newline translation
        tty.setraw(fd, termios.TCSANOW)
    manager = SerialManager(
        {"receipt_printer": {"enabled": True, "device": os.ttyname(managed_slave), "baudrate": 9600}}
    )
    try:
        await manager.start()
        assert manager.write_device(None, 9600, b"\x1b@STRUK\n") == 8
        assert manager.write_device(os.ttyname(other_slave), 9600, b"SLIP\n") == 5
        assert _read_all(managed_master) == b"\x1b@STRUK\n"
        assert _read_all(other_master) == b"SLIP\n"
    finally:
        await manager.stop()
        for fd in (managed_master, managed_slave, other_master, other_slave):
            os.close(fd)


def test_no_device_anywhere_is_an_error():
    with pytest.raises(RuntimeError):
        SerialManager({}).write_device(None, 9600, b"x")
