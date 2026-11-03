"""Pydantic schemas for all Redis IPC messages.

Daemon -> FastAPI: parking.events.{gate_id} (Pub/Sub)
FastAPI -> Daemon: parking.commands.{gate_id} (Redis Streams)
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================

class GateMode(StrEnum):
    """Gate-in operational mode."""

    CASH = "CASH"
    RFID = "RFID"


class DeductStatus(StrEnum):
    """E-money deduct result status."""

    SUCCESS = "SUCCESS"
    LOST_CONTACT = "LOST_CONTACT"
    CORRECTION_VERIFIED = "CORRECTION_VERIFIED"
    CORRECTION_FAILED = "CORRECTION_FAILED"
    WRONG_CARD = "WRONG_CARD"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


# =============================================================================
# Daemon -> FastAPI Events (Pub/Sub)
# =============================================================================

class BaseEvent(BaseModel):
    """Base class for all events."""

    event_type: str
    gate_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VehicleDetectedEvent(BaseEvent):
    """Vehicle detected at sensor."""

    event_type: Literal["vehicle_detected"] = "vehicle_detected"
    sensor: str


class RfidCardReadEvent(BaseEvent):
    """RFID card read by Wiegand reader."""

    event_type: Literal["rfid_card_read"] = "rfid_card_read"
    card_number: str
    channel: str  # W or X


class PlayAudioEvent(BaseEvent):
    """Request frontend to play audio locally (serial/booth gates only)."""

    event_type: Literal["play_audio"] = "play_audio"
    track: int


class HeartbeatEvent(BaseEvent):
    """Daemon heartbeat."""

    event_type: Literal["heartbeat"] = "heartbeat"
    controller_ok: bool


RedisEvent = (
    VehicleDetectedEvent
    | RfidCardReadEvent
    | PlayAudioEvent
    | HeartbeatEvent
)


# =============================================================================
# FastAPI -> Daemon Commands (Redis Streams)
# =============================================================================

class BaseCommand(BaseModel):
    """Base class for all commands."""

    command_type: str
    gate_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Correlation id propagated through the Redis command stream so daemon log
    # lines can be tied back to the API request that issued the command.
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])


class OpenGateCommand(BaseCommand):
    """Open the gate."""

    command_type: Literal["open_gate"] = "open_gate"
    duration_seconds: int | None = None
    reason: str = "operator"


class CloseGateCommand(BaseCommand):
    """Close the gate."""

    command_type: Literal["close_gate"] = "close_gate"
    reason: str = "operator"


class BrakeGateCommand(BaseCommand):
    """Brake/stop the barrier motor (TRIPLE relay mode only)."""

    command_type: Literal["brake_gate"] = "brake_gate"
    reason: str = "operator"


class PlayAudioCommand(BaseCommand):
    """Play audio track."""

    command_type: Literal["play_audio"] = "play_audio"
    track: int


class DisplayTextCommand(BaseCommand):
    """Display text on LED."""

    command_type: Literal["display_text"] = "display_text"
    line1: str
    line2: str = ""
    brightness: int = 100
    mode: str = "normal"


class PrintTicketThenOpenCommand(BaseCommand):
    """Print entry ticket then open gate (cash flow)."""

    command_type: Literal["print_ticket_then_open"] = "print_ticket_then_open"
    barcode: str
    gate_name: str


class ResetGateCommand(BaseCommand):
    """Reset gate to IDLE."""

    command_type: Literal["reset_gate"] = "reset_gate"
    reason: str


class RejectCardCommand(BaseCommand):
    """Reject RFID/card tap — show error then return to WAITING_INPUT for retry."""

    command_type: Literal["reject_card"] = "reject_card"
    line1: str
    line2: str = ""
    audio_track: int = 3
    display_seconds: float = 3.0


# Union type for all commands
RedisCommand = (
    OpenGateCommand
    | CloseGateCommand
    | BrakeGateCommand
    | PlayAudioCommand
    | DisplayTextCommand
    | PrintTicketThenOpenCommand
    | ResetGateCommand
    | RejectCardCommand
)
