"""Pytest fixtures for daemon tests."""

from __future__ import annotations

from typing import Any

import pytest
import redis.asyncio as aioredis


class FakeRedis:
    """In-memory fake Redis for testing daemons without a real Redis server."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: dict[str, set[str]] = {}
        self.pubsub: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self._seq = 0
        self.closed = False

    def _next_id(self) -> str:
        self._seq += 1
        return f"{self._seq}-0"

    async def xgroup_create(
        self, stream: str, groupname: str, **kwargs: Any
    ) -> bytes:
        key = f"{stream}:{groupname}"
        if key in self.groups:
            raise aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups[key] = set()
        if kwargs.get("mkstream") and stream not in self.streams:
            self.streams[stream] = []
        return b"OK"

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 1,
        block: int | None = 5000,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        result: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream, _last_id in streams.items():
            key = f"{stream}:{groupname}"
            pending = self.streams.get(stream, [])
            entries: list[tuple[str, dict[str, str]]] = []
            for msg_id, fields in pending:
                if msg_id not in self.groups.get(key, set()):
                    entries.append((msg_id, fields))
                    self.groups[key].add(msg_id)
                    if len(entries) >= count:
                        break
            if entries:
                result.append((stream, entries))
        return result

    async def xack(self, stream: str, groupname: str, *ids: str) -> int:
        key = f"{stream}:{groupname}"
        acked = 0
        for msg_id in ids:
            if key in self.groups and msg_id in self.groups[key]:
                acked += 1
        return acked

    async def publish(self, channel: str, message: str) -> int:
        self.pubsub.setdefault(channel, []).append(message)
        return 0

    async def hset(self, name: str, mapping: dict[str, str]) -> int:
        self.hashes.setdefault(name, {}).update(mapping)
        return len(mapping)

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.hashes.get(name, {}))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Return a fresh FakeRedis instance."""
    return FakeRedis()


@pytest.fixture
def gate_in_config() -> dict[str, Any]:
    """Sample gate-in configuration."""
    return {
        "id": 1,
        "name": "Gate In Utara",
        "code": "gate-in-1",
        "gate_mode": "CASH",
        "protocol": "compass",
        "controller_host": "192.168.1.10",
        "controller_port": 4001,
        "emoney_minimum_balance": 10000,
        "print_decision_timeout_seconds": 10,
        "has_close_sensor": False,
        "gate_close_duration_ms": 5000,
        "relay_mode": "SINGLE",
        "camera_url": "http://192.168.1.50/snapshot",
    }


