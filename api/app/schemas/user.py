"""User Pydantic schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Base user fields."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=100)
    role: str = Field(default="operator", pattern="^(admin|operator|supervisor)$")
    is_active: bool = True
    phone: str | None = Field(None, max_length=20)


class UserCreate(UserBase):
    """Create user request."""

    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    """Update user request (all fields optional)."""

    username: str | None = Field(None, min_length=3, max_length=50)
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=100)
    role: str | None = Field(None, pattern="^(admin|operator|supervisor)$")
    is_active: bool | None = None
    phone: str | None = Field(None, max_length=20)
    password: str | None = Field(None, min_length=6, max_length=128)


class UserResponse(UserBase):
    """User response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # Plain str: one stored address the validator dislikes must not take down
    # every list that returns users, such as the POS worker picker.
    email: str | None = None
    worker_pin: bool = False  # True if PIN is set (hash is never exposed)

    @field_validator("worker_pin", mode="before")
    @classmethod
    def coerce_pin_to_bool(cls, v: object) -> bool:
        return bool(v)


