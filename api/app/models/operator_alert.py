"""Operator alert model."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.app.models.base import Base, IntPKMixin, TimestampMixin


class OperatorAlert(Base, IntPKMixin, TimestampMixin):
    """Real-time operator alert."""

    __tablename__ = "operator_alerts"

    gate_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 'in' or 'out'
    gate_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    alert_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # TIMEOUT, HARDWARE_FAILURE, SENSOR_STUCK, LOST_CONTACT, CORRECTION_FAILED, WORKER_UNCOVERED

    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Transaction reference
    parking_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parking_transactions.id"), nullable=True
    )

    # Resolution
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<OperatorAlert(id={self.id}, type={self.alert_type}, "
            f"gate={self.gate_id}, resolved={self.is_resolved})>"
        )
