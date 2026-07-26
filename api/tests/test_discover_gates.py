"""Self-check for the LAN discovery scan used by the setup wizard.

Not an HTTP-level test (route needs setup-session/admin auth wiring this
repo's other route tests don't share a fixture for yet) — exercises the
actual scan coroutine against a real loopback listener instead, which is
what matters: does it find an open port and skip closed ones.
"""

import asyncio
import ipaddress
import socket

import pytest

from api.app.routes.setup import _scan_subnet


@pytest.mark.asyncio
async def test_scan_subnet_finds_open_loopback_port():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    try:
        network = ipaddress.ip_network("127.0.0.1/32", strict=False)
        candidates = await asyncio.wait_for(_scan_subnet(network, port), timeout=5.0)
    finally:
        server.close()

    assert len(candidates) == 1
    assert candidates[0].host == "127.0.0.1"
    assert candidates[0].confirmed is False  # not a real Compass controller
    assert candidates[0].latency_ms >= 0


@pytest.mark.asyncio
async def test_scan_subnet_skips_closed_port():
    closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()  # port is now free but nothing listens on it

    network = ipaddress.ip_network("127.0.0.1/32", strict=False)
    candidates = await asyncio.wait_for(_scan_subnet(network, closed_port), timeout=5.0)

    assert candidates == []
