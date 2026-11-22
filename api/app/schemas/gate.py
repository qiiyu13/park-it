"""Gate Pydantic schemas."""

from pydantic import BaseModel, ConfigDict, Field


class HardwareConfig(BaseModel):
    """Complete hardware configuration for a gate.

    ``extra="allow"`` keeps site-specific keys (track_map, lane_reset_seconds,
    ...) in API responses instead of silently dropping them — otherwise the
    edit form reopened with defaults and looked like the save was lost.
    """

    model_config = ConfigDict(extra="allow")

    gate_open_timeout_s: int | None = 10
    sensor_stuck_s: int | None = 30

    # Serial relay barrier commands (ASCII or hex string)
    open_command: str = ""
    close_command: str = ""
    close_delay_seconds: float = 3.0

    # Lane configuration (for exit POS gates)
    lane_type: str = Field(default="MIXED", pattern="^(SINGLE|MIXED)$")
    default_vehicle_type_id: int | None = None

    # Shared device references (cameras/printers tables). Same physical device
    # can be referenced by several gates/booths.
    camera_ids: list[int] = Field(default_factory=list)
    printer_id: int | None = None
    cameras: list[dict] = Field(default_factory=list)

    # Peripherals — each is a freeform dict with optional {"enabled": bool, ...}
    rfid: dict = Field(default_factory=dict)
    ticket_printer: dict = Field(default_factory=dict)
    emoney: dict = Field(default_factory=dict)
    camera: dict = Field(default_factory=dict)
    audio: dict = Field(default_factory=dict)
    led: dict = Field(default_factory=dict)
    omnikey_reader: dict = Field(default_factory=dict)
    receipt_printer: dict = Field(default_factory=dict)


class GateBase(BaseModel):
    """Base gate fields."""

    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20)
    direction: str = Field(..., pattern="^(IN|OUT)$")
    area_parkir_id: int | None = None
    pos_id: int | None = None
    protocol: str = Field(default="compass", pattern="^(compass|enet|serial)$")
    controller_host: str | None = Field(None, max_length=100)
    controller_port: int | None = None
    controller_device: str | None = Field(None, max_length=100)
    controller_baudrate: int | None = None
    has_close_sensor: bool = False
    gate_close_duration_ms: int = Field(default=5000, ge=0)
    relay_mode: str = Field(default="SINGLE", pattern="^(SINGLE|DUAL|TRIPLE)$")
    hardware_config: HardwareConfig = Field(default_factory=HardwareConfig)
    is_active: bool = True


class GateCreate(GateBase):
    """Create gate request."""

    pass


class GateUpdate(BaseModel):
    """Update gate request (all fields optional)."""

    name: str | None = Field(None, max_length=100)
    code: str | None = Field(None, max_length=20)
    direction: str | None = Field(None, pattern="^(IN|OUT)$")
    protocol: str | None = Field(None, pattern="^(compass|enet|serial)$")
    pos_id: int | None = None
    controller_host: str | None = Field(None, max_length=100)
    controller_port: int | None = None
    controller_device: str | None = Field(None, max_length=100)
    controller_baudrate: int | None = None
    has_close_sensor: bool | None = None
    gate_close_duration_ms: int | None = Field(None, ge=0)
    relay_mode: str | None = Field(None, pattern="^(SINGLE|DUAL|TRIPLE)$")
    # Plain dict: the gate form merges the full hardware_config (including keys
    # HardwareConfig does not model, e.g. track_map); a typed model would
    # silently drop them on every save.
    hardware_config: dict | None = None
    is_active: bool | None = None


class GateLaneConfigUpdate(BaseModel):
    """Update only lane configuration (safe merge into hardware_config)."""

    lane_type: str = Field(..., pattern="^(SINGLE|MIXED)$")
    default_vehicle_type_id: int | None = None


class GateResponse(GateBase):
    """Gate response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_online: bool
    controller_ok: bool | None = None
    last_heartbeat: str | None = None
