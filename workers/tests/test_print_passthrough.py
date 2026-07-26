"""Controller-passthrough printing resolves the right command per protocol.

Regression guard: the compass branch used to import ``cmd_pr4``, which only
exists in the ENET module. Every CONTROLLER_PASSTHROUGH print job raised
ImportError, got swallowed by the worker's ``except Exception``, and
dead-lettered — tickets silently never printed.
"""

import pytest

from workers.critical.print_worker import _print_via_controller


class _FakeTransport:
    """Captures the framed bytes instead of talking to a controller."""

    sent: bytes | None = None

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def connect(self, timeout: float = 5.0) -> None:
        pass

    def send(self, data: bytes) -> None:
        type(self).sent = data

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("protocol", "expected_cmd"),
    [("compass", b"PR3"), ("enet", b"PR4")],
)
def test_passthrough_uses_protocol_specific_print_command(monkeypatch, protocol, expected_cmd):
    _FakeTransport.sent = None
    monkeypatch.setattr("protocols.compass.protocol.CompassTransport", _FakeTransport)

    _print_via_controller(
        b"HELLO",
        {"protocol": protocol, "controller_host": "127.0.0.1", "controller_port": 5000},
    )

    assert _FakeTransport.sent is not None, "transport.send was never called"
    assert expected_cmd in _FakeTransport.sent
    assert b"HELLO" in _FakeTransport.sent


def test_passthrough_rejects_unknown_protocol():
    with pytest.raises(ValueError, match="not supported"):
        _print_via_controller(
            b"HELLO",
            {"protocol": "serial-direct", "controller_host": "127.0.0.1", "controller_port": 5000},
        )
