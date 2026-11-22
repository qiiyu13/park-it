"""POS Pydantic schemas."""

import ipaddress
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def canonical_ip(value: str | None) -> str | None:
    """Normalise an IPv4/IPv6 string.

    The booth wizard used to store "192.168.1.081", which never matched the
    real client address 192.168.1.81 and locked the POS out of its own booth.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return raw
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return raw


class PosBase(BaseModel):
    """Base POS fields."""

    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20)
    ip_address: str | None = Field(None, max_length=45)
    default_gate_id: int | None = None
    booth_peripherals: dict = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("ip_address")
    @classmethod
    def _normalise_ip(cls, v: str | None) -> str | None:
        return canonical_ip(v)


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

    @field_validator("ip_address")
    @classmethod
    def _normalise_ip(cls, v: str | None) -> str | None:
        return canonical_ip(v)


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

    @field_validator("ip_address")
    @classmethod
    def _normalise_ip(cls, v: str | None) -> str | None:
        return canonical_ip(v)


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


class ReprintReceiptRequest(BaseModel):
    """Print the receipt of the last completed transaction at a gate."""

    gate_id: int


class PendingOpenRequest(BaseModel):
    """Poll for an admin-queued gate open (booth bridge)."""

    booth_code: str = Field(..., max_length=20)
