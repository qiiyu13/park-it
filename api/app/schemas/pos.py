"""POS Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PosBase(BaseModel):
    """Base POS fields."""

    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20)
    ip_address: str | None = Field(None, max_length=45)
    default_gate_id: int | None = None
    booth_peripherals: dict = Field(default_factory=dict)
    is_active: bool = True


class PosCreate(PosBase):
    """Create POS request."""

    pass


class PosUpdate(BaseModel):
    """Update POS request."""

    name: str | None = Field(None, max_length=100)
    code: str | None = Field(None, max_length=20)
    ip_address: str | None = Field(None, max_length=45)
    default_gate_id: int | None = None
    booth_peripherals: dict | None = None
    is_active: bool | None = None


class PosResponse(PosBase):
    """POS response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    last_seen_at: datetime | None = None
    last_status: dict = Field(default_factory=dict)


class BoothRegisterRequest(BaseModel):
    """Self-registration posted by an enrolled booth installer.

    Authenticated by X-API-Key (the key obtained from /api/setup/enroll).
    Idempotent by booth_code, so re-running the booth installer updates the
    same row instead of creating duplicates.
    """

    booth_code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=100)
    ip_address: str | None = Field(None, max_length=45)
    default_gate_code: str | None = Field(None, max_length=20)


class BoothHeartbeat(BaseModel):
    """Booth-self-reported snapshot posted every 15s by booth_bridge.

    ``booth_code`` is required so the server doesn't have to guess by IP
    (booths behind NAT or with rotating DHCP leases would otherwise be hard
    to identify reliably). Everything else is best-effort; missing fields
    are stored as ``null`` in the status JSONB.
    """

    booth_code: str = Field(..., max_length=20)
    rfid_connected: bool | None = None
    gate_connected: bool | None = None
    ws_clients: int | None = None
    last_card_at: float | None = None  # monotonic seconds; informational
    bridge_version: str | None = None


class BoothHeartbeatResponse(BaseModel):
    """Echo back what the server recorded so the booth can self-verify."""

    booth_code: str
    last_seen_at: datetime
