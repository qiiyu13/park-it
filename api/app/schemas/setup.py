"""Setup wizard Pydantic schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SetupStateResponse(BaseModel):
    """Returned by GET /api/setup/state."""

    setup_complete: bool
    current_step: str | None = None
    topology: Literal["combo", "server_only", "booth_only", "unknown"]
    has_admin: bool
    has_session: bool


class RedeemTokenRequest(BaseModel):
    """Token redemption body."""

    token: str = Field(..., min_length=8, max_length=128)


class EnrollRequest(BaseModel):
    """Booth enrollment body — token minted by the server installer."""

    token: str = Field(..., min_length=8, max_length=128)


class EnrollResponse(BaseModel):
    """Secrets + connection details a booth PC needs to join the server."""

    api_base_url: str
    internal_api_key: str
    redis_host: str
    redis_port: int


class CreateAdminRequest(BaseModel):
    """First-admin creation body."""

    username: str = Field(default="admin", min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class PreflightCheckResult(BaseModel):
    """Single preflight check row."""

    name: str
    category: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str
    duration_ms: float = 0


class PreflightResponse(BaseModel):
    """Aggregated preflight response."""

    checks: list[PreflightCheckResult]
    passed: int
    warnings: int
    failed: int


class SetupStateUpdate(BaseModel):
    """Save wizard step data."""

    step: str = Field(..., min_length=1, max_length=50)
    data: dict[str, Any] = Field(default_factory=dict)


class SetupStateRead(BaseModel):
    """Wizard session content."""

    model_config = ConfigDict(from_attributes=True)

    current_step: str
    data: dict[str, Any]


class DetectSerialCandidate(BaseModel):
    """A detected serial device."""

    port: str
    vid_pid: str | None = None
    chip: str | None = None
    suggested_role: str | None = None
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"


class DetectSerialResponse(BaseModel):
    """Detect-serial response."""

    candidates: list[DetectSerialCandidate]


class TestDeviceRequest(BaseModel):
    """Device probe request."""

    type: Literal["serial", "tcp", "ping"]
    device: str | None = None
    baudrate: int | None = 9600
    host: str | None = None
    port: int | None = None


class TestDeviceResponse(BaseModel):
    """Device probe result."""

    ok: bool
    latency_ms: float | None = None
    detail: str | None = None
    error: str | None = None


class DiscoverGatesRequest(BaseModel):
    """LAN scan request for Compass controllers."""

    subnet: str = Field(..., description="CIDR, e.g. 192.168.1.0/24 (max /24)")
    port: int = 5000


class DiscoverGateCandidate(BaseModel):
    """A responding controller found during a LAN scan."""

    host: str
    latency_ms: float
    confirmed: bool  # True if STAT command got a Compass-shaped reply


class DiscoverGatesResponse(BaseModel):
    """LAN scan result."""

    candidates: list[DiscoverGateCandidate]


class WriteUdevRequest(BaseModel):
    """Udev symlink write request."""

    role: Literal["gate", "printer", "emoney", "scanner", "rfid"]
    port: str = Field(..., pattern=r"^/dev/")


class WriteUdevResponse(BaseModel):
    """Udev symlink write result."""

    ok: bool
    symlink: str | None = None
    error: str | None = None


class TopologyApplyRequest(BaseModel):
    """Bulk-create gates from topology preset."""

    in_count: int = Field(default=1, ge=0, le=8)
    out_count: int = Field(default=1, ge=0, le=8)
    include_local_serial: bool = False


class TestGateRequest(BaseModel):
    """Per-gate end-to-end open/close test."""

    gate_id: int
    timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)


class TestGateStep(BaseModel):
    """One step (open or close) of the gate test."""

    action: Literal["open", "close"]
    sent: bool
    acked: bool
    elapsed_ms: float | None = None
    error: str | None = None


class TestGateResponse(BaseModel):
    """Aggregated gate-test result."""

    ok: bool
    gate_code: str
    steps: list[TestGateStep] = Field(default_factory=list)
    error: str | None = None


class FinalizeResponse(BaseModel):
    """Finalize response."""

    ok: bool
    log: list[str] = Field(default_factory=list)
    error: str | None = None
