"""gate_in controller link: a failed send must not kill a reconnected link."""

from unittest.mock import MagicMock

from daemons.gate_in import GateInDaemon


def _daemon() -> GateInDaemon:
    return GateInDaemon(
        gate_id="GIN01",
        config={"controller_host": "192.168.1.100", "controller_port": 5000, "hardware_config": {}},
    )


async def test_send_failure_aborts_only_its_own_link():
    daemon = _daemon()
    old, new = MagicMock(), MagicMock()
    old.is_connected.return_value = True

    def stall_then_fail(_cmd: bytes) -> None:
        daemon.controller = new  # RSS listener reconnected while send stalled
        raise TimeoutError("timed out")

    old.send.side_effect = stall_then_fail
    daemon.controller = old

    assert await daemon._send_controller_command(b"\xa6STAT\xa9") is False
    new.abort.assert_not_called()
    assert daemon._cb_fail_count == 0


async def test_send_failure_aborts_dead_link_with_reason():
    daemon = _daemon()
    link = MagicMock()
    link.is_connected.return_value = True
    link.send.side_effect = TimeoutError("timed out")
    daemon.controller = link

    assert await daemon._send_controller_command(b"\xa6STAT\xa9") is False
    link.abort.assert_called_once()
    assert link.last_error == "send failed: timed out"
    assert daemon._cb_fail_count == 1
