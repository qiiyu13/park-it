"""Lost-ticket report: driver identity and denda for one exit (Compass "Denda Tiket Hilang")."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from api.app.models.base import Base, IntPKMixin, TimestampMixin


class LostTicketReport(Base, IntPKMixin, TimestampMixin):
    """Identity shown by a driver who lost the entry ticket, plus the fee split."""

    __tablename__ = "lost_ticket_reports"

    transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parking_transactions.id"), nullable=False, unique=True
    )
    resi: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)
    id_number: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rt_rw: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kelurahan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kecamatan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Filled when the exit is paid: fee = tariff_amount + penalty_amount.
    tariff_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    penalty_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    gate_out_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("gates.id"), nullable=True
    )
