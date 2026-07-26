"""E2E test fixtures and helpers for daemon orchestration tests."""

import asyncio
from typing import Any

import pytest_asyncio
import redis.asyncio as aioredis

from shared.config import get_settings
from tests.e2e.simulator.controller_sim import CompassControllerSimulator
from tests.e2e.simulator.passti_sim import PasstiSimulator


@pytest_asyncio.fixture
async def controller_sim():
    """Yield a started Compass controller simulator."""
    sim = CompassControllerSimulator(host="127.0.0.1", port=0)
    await sim.start()
    yield sim
    await sim.stop()


@pytest_asyncio.fixture
async def passti_sim():
    """Yield a started PASSTI reader simulator."""
    sim = PasstiSimulator(host="127.0.0.1", port=0)
    await sim.start()
    yield sim
    await sim.stop()


@pytest_asyncio.fixture
async def redis_client():
    """Yield a Redis client for test cleanup."""
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


class GateOrchestrator:
    """Helper to run a daemon against simulators and collect events."""

    def __init__(self, daemon: Any, controller_sim: CompassControllerSimulator, passti_sim: PasstiSimulator | None = None) -> None:
        self.daemon = daemon
        self.controller = controller_sim
        self.passti = passti_sim
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the daemon in a background task."""
        self._task = asyncio.create_task(self.daemon.run())
        # Give daemon time to connect to controller and Redis
        await asyncio.sleep(0.5)

    async def stop(self) -> None:
        """Request daemon shutdown and wait for it to stop."""
        await self.daemon.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def inject_vehicle_sequence(self, in1_duration: float = 0.3, in3_after: float = 0.2) -> None:
        """Simulate vehicle arriving and passing through the gate."""
        self.controller.set_in1(True)
        await asyncio.sleep(in1_duration)
        self.controller.set_in1(False)
        await asyncio.sleep(in3_after)
        self.controller.set_in3(True)
        await asyncio.sleep(0.2)
        self.controller.set_in3(False)

    async def inject_ticket_button(self) -> None:
        """Simulate ticket button press."""
        self.controller.set_in2(True)
        await asyncio.sleep(0.1)
        self.controller.set_in2(False)

    async def inject_wiegand(self, card_hex: str, channel: str = "W") -> None:
        """Simulate RFID card read."""
        self.controller.inject_wiegand(card_hex, channel)
        await asyncio.sleep(0.1)
