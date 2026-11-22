"""Vehicle type Pydantic schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VehicleTypeBase(BaseModel):
    """Base vehicle type fields."""

    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=10)
    base_tariff: int = Field(default=0, ge=0)
    hourly_rate: int = Field(default=0, ge=0)
    max_daily_cap: int = Field(default=0, ge=0)
    lost_ticket_penalty: int = Field(default=0, ge=0)
    overnight_mode: str = Field(default="midnight", max_length=20)
    overnight_tariff: int = Field(default=0, ge=0)
    tariff_mode: Literal["flat", "hourly", "progressive"] = "hourly"
    grace_period_minutes: int = Field(default=15, ge=0, le=1440)


class VehicleTypeCreate(VehicleTypeBase):
    """Create vehicle type request."""

    pass


class VehicleTypeUpdate(BaseModel):
    """Update vehicle type request (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=50)
    code: str | None = Field(None, min_length=1, max_length=10)
    base_tariff: int | None = Field(None, ge=0)
    hourly_rate: int | None = Field(None, ge=0)
    max_daily_cap: int | None = Field(None, ge=0)
    lost_ticket_penalty: int | None = Field(None, ge=0)
    overnight_mode: str | None = Field(None, max_length=20)
    overnight_tariff: int | None = Field(None, ge=0)
    tariff_mode: Literal["flat", "hourly", "progressive"] | None = None
    grace_period_minutes: int | None = Field(None, ge=0, le=1440)


class VehicleTypeResponse(VehicleTypeBase):
    """Vehicle type response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
