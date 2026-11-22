"""Gate control schemas for manual open/close."""

from pydantic import BaseModel, Field


class GateControlRequest(BaseModel):
    """Request to manually open or close a gate."""

    reason: str = Field(default="operator", max_length=200)


class ManualOpenRequest(BaseModel):
    """Supervisor-authorised manual open from the POS."""

    username: str = Field(..., max_length=50)
    password: str = Field(..., max_length=128)
    reason: str = Field(default="manual open dari POS", max_length=200)


class GateControlResponse(BaseModel):
    """Response from a gate control operation."""

    success: bool
    message: str
    gate_id: str
    command_id: str | None = None
