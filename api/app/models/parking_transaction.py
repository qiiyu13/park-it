"""Parking transaction model — the core business entity."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.models.base import Base, IntPKMixin, TimestampMixin


class ParkingTransaction(Base, IntPKMixin, TimestampMixin):
    """A single parking transaction from entry to exit."""

    __tablename__ = "parking_transactions"

    # Barcode / ticket
    barcode: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    card_number: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )

    # Vehicle info
    plate_number: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    vehicle_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_types.id"), nullable=True
    )

    # Gate references (unified gates table)
    gate_in_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("gates.id"), nullable=True, index=True
    )
    gate_out_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("gates.id"), nullable=True, index=True
    )

    # Timestamps
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    exit_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Payment (v2 additions)
    payment_method: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # CASH, RFID_MEMBER, EMONEY, PENDING
    fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Member link (v2 addition)
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id"), nullable=True, index=True
    )

    # E-money link (v2 addition) — no FK to avoid circular dependency
    emoney_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20), default="ACTIVE", nullable=False, index=True
    )  # ACTIVE, COMPLETED, LOST_CONTACT

    # Shift
    shift_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shifts.id"), nullable=True
    )

    # Snapshots — no FK to avoid circular dependency
    entry_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    exit_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )

    # Operator
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )

    # Notes
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_lost_ticket: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Relationships (use lazy="noload" to prevent N+1 on list endpoints)
    vehicle_type: Mapped["VehicleType | None"] = relationship(
        "VehicleType", lazy="noload"
    )
    gate_in: Mapped["Gate | None"] = relationship("Gate", foreign_keys=[gate_in_id], lazy="noload")
    gate_out: Mapped["Gate | None"] = relationship("Gate", foreign_keys=[gate_out_id], lazy="noload")
    member: Mapped["Member | None"] = relationship("Member", lazy="noload")
    shift: Mapped["Shift | None"] = relationship("Shift", lazy="noload")
    operator: Mapped["User | None"] = relationship("User", lazy="noload")

    # Partial indexes on *active* rows. The ticket barcode stays unique (one
    # physical ticket = one stay), while the member card is only indexed:
    # anti-passback / vehicle quota is enforced in the RFID entry handler so
    # sites can allow several vehicles per card.
    __table_args__ = (
        Index(
            "ix_active_card",
            "card_number",
            postgresql_where=(status == "ACTIVE") & (card_number.isnot(None)),
        ),
        Index(
            "uq_active_barcode",
            "barcode",
            unique=True,
            postgresql_where=(status == "ACTIVE") & (barcode.isnot(None)),
        ),
    )

    def __repr__(self) -> str:
        return f"<ParkingTransaction(id={self.id}, barcode={self.barcode}, status={self.status})>"
