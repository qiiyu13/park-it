"""Worker session Pydantic schemas."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from api.app.schemas.shift_assignment import GateSummary, ShiftSummary, WorkerSummary


class CheckInRequest(BaseModel):
    """Worker check-in request — incoming worker confirms they are on duty."""

    gate_id: int
    worker_id: int
    shift_assignment_id: int | None = None
    is_substitute: bool = False
    original_worker_id: int | None = None


class ConfirmOutgoingRequest(BaseModel):
    """Outgoing worker confirms they are leaving — step 1 of Option B handover."""

    end_type: str = Field(default="SCHEDULED", pattern=r"^(SCHEDULED|EARLY)$")
    end_reason: str | None = Field(None, max_length=255)


class ConfirmIncomingRequest(BaseModel):
    """Incoming worker confirms takeover — step 2 of Option B handover."""

    worker_id: int
    is_substitute: bool = False
    original_worker_id: int | None = None


class ForceLeaveRequest(BaseModel):
    """Force leave when incoming worker is a no-show after timeout."""

    reason: str = Field(..., min_length=1, max_length=255)


class WorkerSessionResponse(BaseModel):
    """Worker session response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    shift_id: int
    shift_assignment_id: int | None
    worker_id: int
    gate_id: int
    date: date
    status: str
    started_at: datetime
    outgoing_confirmed_at: datetime | None
    ended_at: datetime | None
    end_type: str | None
    end_reason: str | None
    is_substitute: bool
    previous_session_id: int | None
    created_at: datetime

    worker: WorkerSummary | None = None
    shift: ShiftSummary | None = None
    gate: GateSummary | None = None
