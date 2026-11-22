"""gate_in controller link: a failed send must not kill a reconnected link."""

from unittest.mock import AsyncMock, MagicMock

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


async def test_silent_controller_is_reset_and_reported_down(monkeypatch):
    import time

    from protocols.compass.protocol import CompassTransport

    daemon = _daemon()
    link = MagicMock(spec=CompassTransport)
    link.is_connected.return_value = True
    link.recv_async = AsyncMock(return_value=b"")
    daemon.controller = link
    daemon._running = True
    daemon._setup_rss = AsyncMock()
    daemon._last_rx = time.monotonic() - 31

    assert daemon._controller_ok() is False  # TCP up, but no reply: not healthy

    def stop_loop() -> None:
        daemon._running = False

    link.abort.side_effect = stop_loop
    await daemon._rss_listener()

    link.abort.assert_called_once()
    assert link.last_error == "no data for 30s"


async def test_replying_controller_is_kept():
    import time

    from protocols.compass.protocol import CompassTransport

    daemon = _daemon()
    link = MagicMock(spec=CompassTransport)
    link.is_connected.return_value = True
    daemon.controller = link
    daemon._last_rx = time.monotonic()
    assert daemon._controller_ok() is True


async def test_sigterm_shutdown_resets_controller_link(monkeypatch):
    """systemd restart (SIGTERM) must RST the link, not leave it to process exit."""
    import asyncio

    import daemons.base as base

    daemon = _daemon()
    link = MagicMock()
    daemon.controller = link

    async def idle() -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(base.aioredis, "from_url", lambda *a, **k: MagicMock(aclose=AsyncMock()))
    daemon._connect_controller = AsyncMock()  # keep the fake link in place
    daemon._wait_for_redis_then_init = AsyncMock()
    daemon._on_started = AsyncMock()
    daemon._consume_commands = idle
    daemon._heartbeat = idle
    daemon._config_loader = None

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.05)
    daemon._request_shutdown()  # what the SIGTERM handler calls
    await asyncio.wait_for(task, timeout=2)

    link.abort.assert_called_once()
    assert daemon.controller is None
