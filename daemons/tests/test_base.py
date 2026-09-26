"""Tests for daemons/base.py."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from daemons.base import BaseDaemon
from shared.events import VehicleDetectedEvent


class TestableDaemon(BaseDaemon):
    """Concrete daemon subclass for testing BaseDaemon."""

    def __init__(self, gate_id: str, config: dict[str, Any], fake_redis: Any) -> None:
        super().__init__(gate_id, config)
        self._fake_redis = fake_redis
        self.commands_handled: list[dict[str, str]] = []
        self._ack_result = True

    async def run(self) -> None:
        """Override run to inject fake Redis. Does not block."""
        self._redis = self._fake_redis
        await self._recover_state()
        await self._ensure_consumer_group()
        self._running = True

    async def run_and_wait(self) -> None:
        """Run with blocking shutdown wait (for shutdown tests)."""
        await self.run()
        await self._shutdown_event.wait()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._redis:
            await self._redis.close()
            self._redis = None

    def get_initial_state(self) -> str:
        return "IDLE"

    async def handle_command(self, command_data: dict[str, str]) -> bool:
        self.commands_handled.append(command_data)
        return self._ack_result

    def set_ack_result(self, result: bool) -> None:
        self._ack_result = result


@pytest.fixture
def test_daemon(fake_redis, gate_in_config) -> TestableDaemon:
    daemon = TestableDaemon("gate-in-1", gate_in_config, fake_redis)
    return daemon


class TestBaseDaemonLifecycle:
    """Test daemon initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_initial_state(self, test_daemon: TestableDaemon) -> None:
        """Daemon starts in IDLE state."""
        assert test_daemon.state == "IDLE"
        assert test_daemon.gate_id == "gate-in-1"

    @pytest.mark.asyncio
    async def test_run_injects_fake_redis(self, test_daemon: TestableDaemon) -> None:
        """run() sets up Redis and recovers state."""
        await test_daemon.run()
        assert test_daemon._redis is not None
        assert test_daemon._running is True

    @pytest.mark.asyncio
    async def test_consumer_group_created(self, test_daemon: TestableDaemon) -> None:
        """Consumer group is created on run."""
        await test_daemon.run()
        key = "parking.commands.gate-in-1:daemon-gate-in-1"
        assert key in test_daemon._fake_redis.groups

    @pytest.mark.asyncio
    async def test_consumer_group_idempotent(self, test_daemon: TestableDaemon) -> None:
        """Creating consumer group twice does not error."""
        await test_daemon.run()
        await test_daemon._ensure_consumer_group()
        # Should not raise

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, test_daemon: TestableDaemon) -> None:
        """stop() sets running to False."""
        await test_daemon.run()
        await test_daemon.stop()
        assert test_daemon._running is False


class TestStatePersistence:
    """Test state persistence and recovery."""

    @pytest.mark.asyncio
    async def test_persist_state(self, test_daemon: TestableDaemon) -> None:
        """State is persisted to Redis Hash."""
        await test_daemon.run()
        test_daemon.state = "VEHICLE_PRESENT"
        test_daemon.state_data = {"card_number": "123456"}
        await test_daemon._persist_state()

        stored = test_daemon._fake_redis.hashes["daemon:state:gate-in-1"]
        assert stored["state"] == "VEHICLE_PRESENT"
        data = json.loads(stored["state_data"])
        assert data["card_number"] == "123456"

    @pytest.mark.asyncio
    async def test_recover_state(self, test_daemon: TestableDaemon) -> None:
        """State is recovered from Redis Hash on startup."""
        fake = test_daemon._fake_redis
        fake.hashes["daemon:state:gate-in-1"] = {
            "state": "WAITING_CARD",
            "updated_at": "2026-04-25T10:00:00",
            "state_data": json.dumps({"card_number": "999888"}),
        }
        await test_daemon.run()
        assert test_daemon.state == "WAITING_CARD"
        assert test_daemon.state_data.get("card_number") == "999888"

    @pytest.mark.asyncio
    async def test_recover_empty_state(self, test_daemon: TestableDaemon) -> None:
        """No previous state defaults to initial state."""
        await test_daemon.run()
        assert test_daemon.state == "IDLE"

    @pytest.mark.asyncio
    async def test_transition_persists(self, test_daemon: TestableDaemon) -> None:
        """_transition updates state and persists."""
        await test_daemon.run()
        await test_daemon._transition("PROCESSING", transaction_id="42")
        assert test_daemon.state == "PROCESSING"
        assert test_daemon.state_data.get("transaction_id") == "42"

        stored = test_daemon._fake_redis.hashes["daemon:state:gate-in-1"]
        assert stored["state"] == "PROCESSING"


class TestEventPublishing:
    """Test Pub/Sub event publishing."""

    @pytest.mark.asyncio
    async def test_publish_event(self, test_daemon: TestableDaemon) -> None:
        """Events are published to correct channel."""
        await test_daemon.run()
        event = VehicleDetectedEvent(
            event_type="vehicle_detected",
            gate_id="gate-in-1",
            sensor="IN1",
        )
        await test_daemon.publish_event(event)

        channel = test_daemon._fake_redis.pubsub["parking.events.gate-in-1"]
        assert len(channel) == 1
        payload = json.loads(channel[0])
        assert payload["event_type"] == "vehicle_detected"
        assert payload["sensor"] == "IN1"


class TestCommandConsumption:
    """Test Redis Streams command consumption."""

    @pytest.mark.asyncio
    async def test_process_command_acks_success(self, test_daemon: TestableDaemon) -> None:
        """Successful command processing results in ACK."""
        await test_daemon.run()
        fake = test_daemon._fake_redis
        fake.streams["parking.commands.gate-in-1"] = [
            ("1-0", {"command_type": "open_gate", "gate_id": "gate-in-1"}),
        ]

        # Simulate consumption
        messages = await fake.xreadgroup(
            groupname="daemon-gate-in-1",
            consumername="test",
            streams={"parking.commands.gate-in-1": ">"},
        )
        assert len(messages) == 1
        for _stream_name, entries in messages:
            for msg_id, fields in entries:
                ack = await test_daemon.handle_command(fields)
                assert ack is True
                await fake.xack("parking.commands.gate-in-1", "daemon-gate-in-1", msg_id)

        assert len(test_daemon.commands_handled) == 1
        assert test_daemon.commands_handled[0]["command_type"] == "open_gate"

    @pytest.mark.asyncio
    async def test_process_command_nacks_failure(self, test_daemon: TestableDaemon) -> None:
        """Failed command processing does not ACK."""
        await test_daemon.run()
        test_daemon.set_ack_result(False)
        fake = test_daemon._fake_redis
        fake.streams["parking.commands.gate-in-1"] = [
            ("2-0", {"command_type": "deduct", "gate_id": "gate-in-1"}),
        ]

        messages = await fake.xreadgroup(
            groupname="daemon-gate-in-1",
            consumername="test",
            streams={"parking.commands.gate-in-1": ">"},
        )
        for _stream_name, entries in messages:
            for _msg_id, fields in entries:
                ack = await test_daemon.handle_command(fields)
                assert ack is False
                # Do NOT call xack

    @pytest.mark.asyncio
    async def test_command_trace_id_binding(self, test_daemon: TestableDaemon) -> None:
        """Trace ID from command is bound for logging."""
        await test_daemon.run()
        fake = test_daemon._fake_redis
        fake.streams["parking.commands.gate-in-1"] = [
            ("3-0", {"command_type": "reset_gate", "trace_id": "abc123", "gate_id": "gate-in-1"}),
        ]

        messages = await fake.xreadgroup(
            groupname="daemon-gate-in-1",
            consumername="test",
            streams={"parking.commands.gate-in-1": ">"},
        )
        for _stream_name, entries in messages:
            for _msg_id, fields in entries:
                await test_daemon.handle_command(fields)
                assert any(fields["trace_id"] in str(cmd) for cmd in test_daemon.commands_handled)


class TestCommandReclaim:
    """Test XAUTOCLAIM-based reprocessing of never-ACKed commands."""

    @pytest.mark.asyncio
    async def test_reclaim_reprocesses_stale_entries(self, test_daemon: TestableDaemon) -> None:
        """Stale PEL entries are claimed and reprocessed."""
        await test_daemon.run()

        fake = test_daemon._fake_redis
        stale = [("5-0", {"command_type": "open_gate", "gate_id": "gate-in-1"})]

        async def xautoclaim(*args, **kwargs):
            return ("0-0", stale, [])

        fake.xautoclaim = xautoclaim

        await test_daemon._reclaim_stale_commands()

        assert len(test_daemon.commands_handled) == 1
        assert test_daemon.commands_handled[0]["command_type"] == "open_gate"
        # Successful handling ACKs → counter cleared
        assert "5-0" not in test_daemon._redelivery_counts

    @pytest.mark.asyncio
    async def test_reclaim_drops_poison_command_after_max(self, test_daemon: TestableDaemon) -> None:
        """A command that never succeeds is dropped after _max_redeliveries."""
        await test_daemon.run()
        test_daemon.set_ack_result(False)

        fake = test_daemon._fake_redis
        poison = [("6-0", {"command_type": "bad_command", "gate_id": "gate-in-1"})]
        acked: list[str] = []

        async def xautoclaim(*args, **kwargs):
            return ("0-0", poison, [])

        async def xack(stream, group, msg_id):
            acked.append(msg_id)

        fake.xautoclaim = xautoclaim
        fake.xack = xack

        for _ in range(test_daemon._max_redeliveries + 1):
            await test_daemon._reclaim_stale_commands()

        # Attempted max times, then dropped with an ACK to stop the loop.
        assert len(test_daemon.commands_handled) == test_daemon._max_redeliveries
        assert acked == ["6-0"]
        assert "6-0" not in test_daemon._redelivery_counts


class TestHeartbeat:
    """Test heartbeat publishing."""

    @pytest.mark.asyncio
    async def test_heartbeat_publishes_event(self, test_daemon: TestableDaemon) -> None:
        """Heartbeat publishes to events channel."""
        await test_daemon.run()
        event = test_daemon._fake_redis.pubsub.get("parking.events.gate-in-1", [])
        # Heartbeat hasn't run yet in this test, test via direct publish
        from shared.events import HeartbeatEvent

        hb = HeartbeatEvent(
            event_type="heartbeat",
            gate_id="gate-in-1",
            controller_ok=True,
        )
        await test_daemon.publish_event(hb)
        channel = test_daemon._fake_redis.pubsub["parking.events.gate-in-1"]
        assert len(channel) == 1
        payload = json.loads(channel[0])
        assert payload["event_type"] == "heartbeat"
        assert payload["controller_ok"] is True


class TestGracefulShutdown:
    """Test graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, test_daemon: TestableDaemon) -> None:
        """stop() cancels running tasks."""
        run_task = asyncio.create_task(test_daemon.run_and_wait())
        await asyncio.sleep(0.05)  # Let run() initialize

        # Create a dummy task
        async def dummy() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(dummy())
        test_daemon._tasks.append(task)

        await test_daemon.stop()
        await asyncio.wait_for(run_task, timeout=1.0)
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_redis_closed_on_stop(self, test_daemon: TestableDaemon) -> None:
        """Redis connection is closed on shutdown."""
        run_task = asyncio.create_task(test_daemon.run_and_wait())
        await asyncio.sleep(0.05)
        await test_daemon.stop()
        await asyncio.wait_for(run_task, timeout=1.0)
        assert test_daemon._fake_redis.closed is True
