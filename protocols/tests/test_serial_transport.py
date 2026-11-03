"""SerialTransport over a Linux pty pair (no barrier hardware)."""

import os
import pty
import threading

from protocols.compass.protocol import SerialTransport


def test_serial_transport_send_recv_over_pty():
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    request: list[bytes] = []

    def responder() -> None:
        try:
            request.append(os.read(master_fd, 1024))
            os.write(master_fd, b"\xa6OK\xa9")
        except OSError:
            pass

    thread = threading.Thread(target=responder, daemon=True)
    thread.start()

    transport = SerialTransport(slave_name, baudrate=9600)
    try:
        transport.connect(timeout=1.0)
        assert transport.is_connected()

        response = transport.send_recv(b"\xa6STAT\xa9", timeout=2.0)
        assert response == b"\xa6OK\xa9"
    finally:
        transport.close()
        os.close(master_fd)
        os.close(slave_fd)

    thread.join(timeout=1)
    assert request == [b"\xa6STAT\xa9"]
