"""Unified Gate model replacing GateIn and GateOut."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.models.base import Base, IntPKMixin, TimestampMixin


class Gate(Base, IntPKMixin, TimestampMixin):
    """Entry or exit gate with configurable peripherals."""

    __tablename__ = "gates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # 'IN' or 'OUT'
    area_parkir_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("area_parkir.id"), nullable=True
    )
    pos_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pos.id"), nullable=True
    )  # Only for OUT gates

    # Controller connection
    protocol: Mapped[str] = mapped_column(String(20), default="compass", nullable=False)
    controller_host: Mapped[str | None] = mapped_column(String(100), nullable=True)
    controller_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    controller_device: Mapped[str | None] = mapped_column(String(100), nullable=True)
    controller_baudrate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Hardware settings
    has_close_sensor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gate_close_duration_ms: Mapped[int] = mapped_column(Integer, default=5000, nullable=False)
    relay_mode: Mapped[str] = mapped_column(String(20), default="SINGLE", nullable=False)
    gate_open_timeout_s: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    sensor_stuck_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Peripherals configuration (JSONB). Default keeps display+audio off so a
    # bare controller without a display module can't be sent cmd_ds and dropped.
    hardware_config: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"display": {"enabled": False}, "audio": {"enabled": False}},
        nullable=False,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_heartbeat: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    area_parkir: Mapped["AreaParkir | None"] = relationship("AreaParkir", lazy="selectin")
    pos: Mapped["Pos | None"] = relationship("Pos", foreign_keys=[pos_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<Gate(id={self.id}, name={self.name}, direction={self.direction})>"

    @property
    def is_entry(self) -> bool:
        return self.direction == "IN"

    @property
    def is_exit(self) -> bool:
        return self.direction == "OUT"

    def get_peripheral(self, key: str) -> dict:
        """Get peripheral config by key. Returns empty dict if not configured."""
        return self.hardware_config.get(key, {})

    def is_peripheral_enabled(self, key: str) -> bool:
        """Check if a peripheral is enabled."""
        return self.get_peripheral(key).get("enabled", False)

    def get_cameras(self) -> list[dict]:
        """Return active camera configs from the ``cameras[]`` array."""
        return [
            {
                "url": c["url"],
                "label": c.get("label"),
                "username": c.get("username"),
                "password": c.get("password"),
                "auth_type": c.get("auth_type", "none"),
            }
            for c in self.hardware_config.get("cameras", [])
            if c.get("url") and c.get("enabled", True)
        ]
