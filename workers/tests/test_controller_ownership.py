"""Single-owner rule for PCLess controllers + controller-down alerting.

The entry gate daemon owns its controller's only TCP slot. The print worker
must never open it, and a daemon that is alive with a dead controller must
still page someone.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from workers.background import heartbeat_watcher
from workers.critical import print_worker


async def test_ticket_worker_never_opens_entry_controller(monkeypatch):
    opened = MagicMock()
    monkeypatch.setattr(print_worker, "_print_via_controller", opened)
    monkeypatch.setattr(print_worker, "_check_paper_available", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(print_worker, "get_settings", lambda: MagicMock(mock_hardware=False))
    retry = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(print_worker, "_retry_or_alert", retry)

    result = await print_worker.print_ticket(
        {},
        gate_id="GIN-01",
        barcode="B1",
        location_name="Site",
        print_config={"mode": "CONTROLLER_PASSTHROUGH", "controller_host": "10.0.0.1"},
    )

    opened.assert_not_called()
    assert result == {"status": "failed"}
    assert "owned by the gate daemon" in retry.call_args.args[3]


class _FakeRedis:
    def __init__(self, beats: dict[str, str]) -> None:
        self.store: dict[str, object] = dict(beats)

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self.store.pop(key, None)


async def test_watcher_alerts_when_controller_down_twice(monkeypatch):
    beats = {
        "gate:heartbeat:GIN-03": json.dumps({"controller_ok": False}),
        "gate:heartbeat:GIN-01": json.dumps({"controller_ok": True}),
    }
    fake = _FakeRedis(beats)

    import shared.redis as shared_redis

    client = MagicMock(connect=AsyncMock(), client=fake)
    monkeypatch.setattr(shared_redis, "redis_client", client)

    rows = MagicMock(all=lambda: [("GIN-03", "Gate 3", "IN"), ("GIN-01", "Gate 1", "IN")])

    @asynccontextmanager
    async def session():
        yield MagicMock(execute=AsyncMock(return_value=rows))

    import api.database

    monkeypatch.setattr(api.database, "AsyncSessionLocal", session)
    alert = AsyncMock(return_value=True)
    import workers.background.alerting as alerting

    monkeypatch.setattr(alerting, "enqueue_alert", alert)

    first = await heartbeat_watcher.check_gate_heartbeats({})
    assert first["controller_down"] == 0  # one bad check is a blip
    second = await heartbeat_watcher.check_gate_heartbeats({})
    assert second["controller_down"] == 1
    assert alert.call_args.kwargs["key"] == "controller_down:GIN-03"
    assert "Matikan lalu nyalakan" in alert.call_args.kwargs["message"]
