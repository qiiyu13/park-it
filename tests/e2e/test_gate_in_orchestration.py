"""E2E orchestration tests for the gate-in daemon against TCP simulators.

Flow under test (``daemons/gate_in.py``):
``IDLE -> WAITING_INPUT -> method branch -> OPENING -> IDLE``

Two behaviours these tests deliberately pin down, because the previous version
of this file asserted the opposite and rotted unnoticed while `tests/` was
missing from pytest ``testpaths``:

* Vehicle detection does **not** close the barrier. ``_on_vehicle_detected``
  goes straight to WAITING_INPUT — no TRIG1 is emitted.
* E-money is **exit-only**. It no longer participates at entry at all, so there
  is no entry e-money case to cover here.
"""

import asyncio

import pytest

from daemons.gate_in import (
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_VALIDATING,
    STATE_WAITING_INPUT,
    GateInDaemon,
)
from tests.e2e.conftest import GateOrchestrator


def _config(controller_sim, *, rfid: bool = False) -> dict:
    return {
        "controller_host": controller_sim.host,
        "controller_port": controller_sim.port,
        "hardware_config": {
            "rfid": {"enabled": rfid},
            # Audio off keeps the command log to just acks and display writes.
            "audio": {"enabled": False},
        },
    }


async def _run(daemon, controller_sim, body):
    """Start daemon, run `body(published_events)`, always stop cleanly."""
    orch = GateOrchestrator(daemon, controller_sim)
    published: list = []
    original_publish = daemon.publish_event

    async def capture(event):
        published.append(event)
        await original_publish(event)

    daemon.publish_event = capture
    await orch.start()
    try:
        return await body(published)
    finally:
        await orch.stop()


@pytest.fixture
async def clean_redis(redis_client):
    """Drop per-gate daemon keys before and after each test."""
    gate_ids: list[str] = []

    async def _register(gate_id: str) -> str:
        gate_ids.append(gate_id)
        await _purge(redis_client, gate_id)
        return gate_id

    yield _register

    for gate_id in gate_ids:
        await _purge(redis_client, gate_id)


async def _purge(redis_client, gate_id: str) -> None:
    await redis_client.delete(
        f"daemon:state:{gate_id}",
        f"parking.commands.{gate_id}",
        f"parking.events.{gate_id}",
    )


@pytest.mark.asyncio
async def test_cash_entry_button_press_reaches_processing(controller_sim, clean_redis):
    """IN1 arms the lane, IN2 (ticket button) starts the cash entry."""
    gate_id = await clean_redis("e2e-gin-cash-1")
    daemon = GateInDaemon(gate_id=gate_id, config=_config(controller_sim))

    async def body(published):
        controller_sim.set_in1(True)
        await asyncio.sleep(0.3)
        assert daemon.state == STATE_WAITING_INPUT, f"got {daemon.state}"

        controller_sim.set_in2(True)
        await asyncio.sleep(0.3)
        controller_sim.set_in2(False)
        await asyncio.sleep(0.2)

        assert daemon.state == STATE_PROCESSING, f"got {daemon.state}"

        event_types = [e.event_type for e in published]
        assert "vehicle_detected" in event_types, event_types
        assert "ticket_button_pressed" in event_types, event_types

        # Regression guard: entry never closes the barrier on detection.
        commands = controller_sim.get_command_log()
        assert not any(b"TRIG1" in c for c in commands), commands

    await _run(daemon, controller_sim, body)


@pytest.mark.asyncio
async def test_ticket_button_ignored_without_vehicle(controller_sim, clean_redis):
    """IN2 with no vehicle at IN1 is a no-op — prevents ticket farming."""
    gate_id = await clean_redis("e2e-gin-cash-2")
    daemon = GateInDaemon(gate_id=gate_id, config=_config(controller_sim))

    async def body(published):
        controller_sim.set_in2(True)
        await asyncio.sleep(0.3)
        controller_sim.set_in2(False)
        await asyncio.sleep(0.2)

        assert daemon.state == STATE_IDLE, f"got {daemon.state}"
        assert "ticket_button_pressed" not in [e.event_type for e in published]

    await _run(daemon, controller_sim, body)


@pytest.mark.asyncio
async def test_vehicle_backs_up_returns_to_idle(controller_sim, clean_redis):
    """IN1 released while waiting for input resets the lane."""
    gate_id = await clean_redis("e2e-gin-cash-3")
    daemon = GateInDaemon(gate_id=gate_id, config=_config(controller_sim))

    async def body(published):
        controller_sim.set_in1(True)
        await asyncio.sleep(0.3)
        assert daemon.state == STATE_WAITING_INPUT, f"got {daemon.state}"

        controller_sim.set_in1(False)
        await asyncio.sleep(0.3)
        assert daemon.state == STATE_IDLE, f"got {daemon.state}"

    await _run(daemon, controller_sim, body)


@pytest.mark.asyncio
async def test_rfid_card_read_enters_validating(controller_sim, clean_redis):
    """Wiegand read while waiting for input hands off to the API for validation."""
    gate_id = await clean_redis("e2e-gin-rfid-1")
    daemon = GateInDaemon(gate_id=gate_id, config=_config(controller_sim, rfid=True))

    async def body(published):
        controller_sim.set_in1(True)
        await asyncio.sleep(0.3)
        assert daemon.state == STATE_WAITING_INPUT, f"got {daemon.state}"

        controller_sim.inject_wiegand("0012345678", channel="W")
        await asyncio.sleep(0.4)

        assert daemon.state == STATE_VALIDATING, f"got {daemon.state}"
        assert "rfid_card_read" in [e.event_type for e in published]

    await _run(daemon, controller_sim, body)
