"""Abstract base daemon for gate controllers.

Handles Redis Streams command consumption (ACK-based), Pub/Sub event publishing,
heartbeat, and state persistence/recovery.
"""

from __future__ import annotations

import asyncio
import json
import signal
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from shared.config import get_settings
from shared.events import BaseEvent, HeartbeatEvent
from shared.logging import bind_trace_id, clear_context, get_logger

logger = get_logger(__name__)


class BaseDaemon(ABC):
    """Abstract base class for gate daemons.

    Responsibilities:
    - Connect to Redis (independent connection, not shared singleton)
    - Consume commands from Redis Streams (consumer group, ACK-based)
    - Publish events to Redis Pub/Sub
    - Heartbeat every 30 seconds
    - Persist/recover state from Redis Hash
    - Graceful shutdown on SIGTERM/SIGINT
    """

    def __init__(self, gate_id: str, config: dict[str, Any]) -> None:
        """Initialize daemon.

        Args:
            gate_id: Unique gate identifier (e.g., "gate-in-1")
            config: Gate configuration dict from database (host, port, mode, etc.)
        """
        self.gate_id = gate_id
        self.config = config
        self.state: str = self.get_initial_state()
        self.state_data: dict[str, Any] = {}
        self._redis: aioredis.Redis | None = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._consumer_group = f"daemon-{gate_id}"
        self._consumer_name = f"{gate_id}-{uuid.uuid4().hex[:8]}"
        self._command_stream = f"parking.commands.{gate_id}"
        self._event_channel = f"parking.events.{gate_id}"
        self._state_key = f"daemon:state:{gate_id}"
        # Redelivery accounting for reclaimed (never-ACKed) commands — a
        # permanently failing command must not loop forever.
        self._redelivery_counts: dict[str, int] = {}
        self._max_redeliveries = 3

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point. Connects to Redis, recovers state, starts loops."""
        settings = get_settings()
        self._redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            health_check_interval=30,
        )

        # Redis may not be reachable at boot (broker still starting). Retry
        # state recovery + consumer-group creation with backoff so the daemon
        # comes up cleanly without a systemd restart loop.
        await self._wait_for_redis_then_init()

        self._running = True
        logger.info(
            "daemon_starting",
            gate_id=self.gate_id,
            state=self.state,
            consumer_group=self._consumer_group,
        )

        # Allow subclasses to start additional tasks before base tasks
        self._tasks = []
        await self._on_started()

        # Start concurrent tasks
        self._tasks.extend([
            asyncio.create_task(self._consume_commands(), name="consume"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ])

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown)

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Cancel all tasks
        logger.info("daemon_shutting_down", gate_id=self.gate_id)
        for task in self._tasks:
            task.cancel()

        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for task, result in zip(self._tasks, results, strict=False):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.error(
                    "daemon_task_error",
                    gate_id=self.gate_id,
                    task=task.get_name(),
                    error=str(result),
                )

        if self._redis:
            await self._redis.aclose()
            self._redis = None

        logger.info("daemon_stopped", gate_id=self.gate_id)

    def _request_shutdown(self) -> None:
        """Signal handler — request graceful shutdown."""
        self._running = False
        self._shutdown_event.set()

    async def stop(self) -> None:
        """Programmatic stop (for testing)."""
        self._running = False
        self._shutdown_event.set()

    async def _wait_for_redis_then_init(self) -> None:
        """Block until Redis answers PING, then recover state + ensure group.

        Caps backoff at 30s so we don't sit silent forever.
        """
        if self._redis is None:
            raise RuntimeError("Redis not initialized")
        delay = 1.0
        while True:
            try:
                await self._redis.ping()
                await self._recover_state()
                await self._ensure_consumer_group()
                return
            except Exception as e:
                logger.warning(
                    "redis_init_retry",
                    gate_id=self.gate_id,
                    error=str(e),
                    next_retry_s=delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _on_started(self) -> None:  # noqa: B027 — optional override hook, not abstract
        """Hook called after _running is set to True but before main tasks start.

        Subclasses can override this to start additional background tasks
        (e.g., controller polling) that will be cancelled alongside base tasks.
        """
        pass

    def _controller_ok(self) -> bool:
        """Report controller link health for heartbeat/liveness.

        Base default assumes healthy (no controller concept). Subclasses that
        own a hardware link should override to reflect real connectivity so
        monitoring can see a dead controller even while the daemon is alive.
        """
        return True

    def _spawn_tracked(self, coro: Any, name: str) -> asyncio.Task:
        """Create a background task that is tracked and exception-logged.

        Bare ``asyncio.create_task`` swallows exceptions silently — if the
        coroutine raises, the failure vanishes and the state machine can wedge
        with no trace. This wraps creation so every task is cancelled on
        shutdown and any non-cancellation exception is logged.
        """
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)

        def _on_done(t: asyncio.Task) -> None:
            if t in self._tasks:
                self._tasks.remove(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error(
                    "tracked_task_error",
                    gate_id=self.gate_id,
                    task=name,
                    error=str(exc),
                )

        task.add_done_callback(_on_done)
        return task

    # ------------------------------------------------------------------
    # Redis Streams — Command Consumption
    # ------------------------------------------------------------------

    async def _ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        try:
            await self._redis.xgroup_create(
                self._command_stream,
                self._consumer_group,
                id="0",  # Process from beginning if new
                mkstream=True,
            )
            logger.info(
                "consumer_group_created",
                gate_id=self.gate_id,
                group=self._consumer_group,
            )
        except aioredis.ResponseError as e:
            if "already exists" in str(e):
                logger.debug(
                    "consumer_group_exists",
                    gate_id=self.gate_id,
                    group=self._consumer_group,
                )
            else:
                raise

    async def _consume_commands(self) -> None:
        """Main command consumption loop."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")

        while self._running:
            try:
                # First reclaim commands that were read but never ACKed —
                # handler exception or a daemon crash mid-processing. The
                # consumer name is per-boot, so without XAUTOCLAIM those PEL
                # entries are orphaned forever (not ACKing alone never
                # redelivers to a fresh consumer). Idle threshold 30s keeps
                # us from stealing a message this same consumer is still
                # working on.
                await self._reclaim_stale_commands()

                messages = await self._redis.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._consumer_name,
                    streams={self._command_stream: ">"},
                    count=1,
                    block=5000,  # 5 second block
                )

                if not messages:
                    continue

                for _stream_name, entries in messages:
                    for msg_id, fields in entries:
                        await self._process_command(msg_id, fields)

            except asyncio.CancelledError:
                logger.debug("consume_cancelled", gate_id=self.gate_id)
                raise
            except Exception as e:
                logger.error(
                    "consume_error",
                    gate_id=self.gate_id,
                    error=str(e),
                )
                await asyncio.sleep(1)

    async def _reclaim_stale_commands(self) -> None:
        """Claim never-ACKed commands from the group's PEL and reprocess."""
        if self._redis is None:
            return
        try:
            _next_id, entries, _deleted = await self._redis.xautoclaim(
                self._command_stream,
                self._consumer_group,
                self._consumer_name,
                min_idle_time=30_000,
                start_id="0-0",
                count=10,
            )
        except Exception as e:
            logger.warning(
                "command_reclaim_error",
                gate_id=self.gate_id,
                error=str(e),
            )
            return

        for msg_id, fields in entries:
            attempts = self._redelivery_counts.get(msg_id, 0) + 1
            if attempts > self._max_redeliveries:
                # Poison command: drop it rather than hot-loop, and make the
                # loss loud — the API believes "command sent" means delivered.
                self._redelivery_counts.pop(msg_id, None)
                logger.error(
                    "command_redelivery_exhausted_dropped",
                    gate_id=self.gate_id,
                    command_type=fields.get("command_type", "unknown"),
                    msg_id=msg_id,
                    attempts=self._max_redeliveries,
                )
                await self._redis.xack(
                    self._command_stream, self._consumer_group, msg_id
                )
                continue
            self._redelivery_counts[msg_id] = attempts
            logger.warning(
                "command_reclaimed",
                gate_id=self.gate_id,
                command_type=fields.get("command_type", "unknown"),
                msg_id=msg_id,
                attempt=attempts,
            )
            await self._process_command(msg_id, fields)

    async def _process_command(self, msg_id: str, fields: dict[str, str]) -> None:
        """Process a single command message."""
        if self._redis is None:
            return

        try:
            # Bind trace_id for structured logging correlation
            trace_id = fields.get("trace_id", uuid.uuid4().hex[:16])
            bind_trace_id(trace_id)

            command_type = fields.get("command_type", "unknown")
            logger.info(
                "command_received",
                gate_id=self.gate_id,
                command_type=command_type,
                msg_id=msg_id,
            )

            # Deserialize fields into a RedisCommand-like dict
            command_data = dict(fields)

            # Let subclass handle the command
            ack = await self.handle_command(command_data)

            if ack:
                await self._redis.xack(
                    self._command_stream,
                    self._consumer_group,
                    msg_id,
                )
                self._redelivery_counts.pop(msg_id, None)
                logger.info(
                    "command_acked",
                    gate_id=self.gate_id,
                    command_type=command_type,
                    msg_id=msg_id,
                )
            else:
                # Not ACKed: the entry stays in our PEL and is re-claimed by
                # _reclaim_stale_commands after 30s idle (up to
                # _max_redeliveries, then dropped with an error log).
                logger.warning(
                    "command_nack",
                    gate_id=self.gate_id,
                    command_type=command_type,
                    msg_id=msg_id,
                )

        except Exception as e:
            logger.error(
                "command_processing_error",
                gate_id=self.gate_id,
                command_type=fields.get("command_type", "unknown"),
                error=str(e),
            )
            # Not ACKed — same reclaim path as a NACK above.
        finally:
            clear_context()

    # ------------------------------------------------------------------
    # Pub/Sub — Event Publishing
    # ------------------------------------------------------------------

    async def publish_event(self, event: BaseEvent) -> int:
        """Publish an event to Pub/Sub (fanout) AND append to a bounded Stream.

        The Stream gives POS clients a replay buffer to fill in events that
        arrived during a Redis blip or WS reconnect. MAXLEN ~1000 keeps the
        log cheap; older entries are trimmed automatically.

        Returns:
            Number of subscribers that received the Pub/Sub message.
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        base_payload = event.model_dump_json()

        # Best-effort Stream tee. Pub/Sub remains the primary delivery path;
        # if XADD fails we still want fanout to succeed. When XADD succeeds
        # we inject its returned stream id into the published payload so live
        # WS clients can track a high-water mark for replay on reconnect.
        stream_id: str | None = None
        try:
            stream_id = await self._redis.xadd(
                f"parking.eventlog.{self.gate_id}",
                {"event": base_payload},
                maxlen=1000,
                approximate=True,
            )
        except Exception as e:
            logger.warning(
                "event_stream_xadd_failed",
                gate_id=self.gate_id,
                event_type=event.event_type,
                error=str(e),
            )

        if stream_id:
            try:
                obj = json.loads(base_payload)
                obj["_event_id"] = stream_id
                payload = json.dumps(obj)
            except json.JSONDecodeError:
                payload = base_payload
        else:
            payload = base_payload

        result = await self._redis.publish(self._event_channel, payload)
        logger.debug(
            "event_published",
            gate_id=self.gate_id,
            event_type=event.event_type,
            subscribers=result,
        )
        return result

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat(self) -> None:
        """Publish heartbeat every 30 seconds with daemon state."""
        while self._running:
            try:
                controller_ok = self._controller_ok()
                event = HeartbeatEvent(
                    event_type="heartbeat",
                    gate_id=self.gate_id,
                    controller_ok=controller_ok,
                )
                await self.publish_event(event)
                # Publish additional state info for monitoring
                if self._redis:
                    state_payload = json.dumps({
                        "event_type": "heartbeat_state",
                        "gate_id": self.gate_id,
                        "state": self.state,
                        "state_data": self.state_data,
                    })
                    await self._redis.publish(f"parking.events.{self.gate_id}", state_payload)
                    # Liveness key — 60s TTL so a missed heartbeat (30s cadence)
                    # tolerates one drop, two drops = STALE.
                    from datetime import datetime
                    status_payload = json.dumps({
                        "gate_id": self.gate_id,
                        "state": self.state,
                        "controller_ok": controller_ok,
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    await self._redis.set(
                        f"gate:heartbeat:{self.gate_id}",
                        status_payload,
                        ex=60,
                    )
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=30.0,
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.debug("heartbeat_cancelled", gate_id=self.gate_id)
                raise
            except Exception as e:
                logger.error("heartbeat_error", gate_id=self.gate_id, error=str(e))
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # State Persistence & Recovery
    # ------------------------------------------------------------------

    async def _persist_state(self) -> None:
        """Persist current state and state_data to Redis Hash."""
        if self._redis is None:
            return
        data = {
            "state": self.state,
            "updated_at": datetime.now(UTC).isoformat(),
            "state_data": json.dumps(self.state_data, default=str),
        }
        await self._redis.hset(self._state_key, mapping=data)
        logger.debug(
            "state_persisted",
            gate_id=self.gate_id,
            state=self.state,
        )

    async def _recover_state(self) -> None:
        """Recover state from Redis Hash on startup."""
        if self._redis is None:
            return
        try:
            data = await self._redis.hgetall(self._state_key)
            if data:
                self.state = data.get("state", self.get_initial_state())
                try:
                    self.state_data = json.loads(data.get("state_data", "{}"))
                except json.JSONDecodeError:
                    self.state_data = {}
                logger.info(
                    "state_recovered",
                    gate_id=self.gate_id,
                    state=self.state,
                )
            else:
                logger.info(
                    "state_no_previous",
                    gate_id=self.gate_id,
                    state=self.state,
                )
        except Exception as e:
            logger.error("state_recovery_error", gate_id=self.gate_id, error=str(e))
            self.state = self.get_initial_state()
            self.state_data = {}

    async def _transition(self, new_state: str, **kwargs: Any) -> None:
        """Transition to a new state and persist.

        Args:
            new_state: The new state name.
            **kwargs: Additional data to store in state_data.
        """
        old_state = self.state
        self.state = new_state
        if kwargs:
            self.state_data.update(kwargs)
        await self._persist_state()
        logger.info(
            "state_transition",
            gate_id=self.gate_id,
            old_state=old_state,
            new_state=new_state,
        )

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    async def handle_command(self, command_data: dict[str, str]) -> bool:
        """Process a command from Redis Streams.

        Args:
            command_data: Dict of command fields from Redis Stream.

        Returns:
            True if command was processed successfully (will ACK).
            False if command should be retried (will NOT ACK).
        """
        ...

    @abstractmethod
    def get_initial_state(self) -> str:
        """Return the initial state for this daemon."""
        ...
