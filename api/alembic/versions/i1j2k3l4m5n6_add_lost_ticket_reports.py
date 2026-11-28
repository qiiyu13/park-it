"""add lost_ticket_reports (driver identity + denda for lost tickets)

Revision ID: i1j2k3l4m5n6
Revises: e2f3a4b5c6d7
"""

import sqlalchemy as sa
from alembic import op

revision: str = "i1j2k3l4m5n6"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lost_ticket_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "transaction_id",
            sa.BigInteger(),
            sa.ForeignKey("parking_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("resi", sa.String(20), nullable=True, unique=True),
        sa.Column("plate_number", sa.String(20), nullable=False, index=True),
        sa.Column("driver_name", sa.String(100), nullable=False),
        sa.Column("id_number", sa.String(50), nullable=False),
        sa.Column("address", sa.String(200), nullable=True),
        sa.Column("rt_rw", sa.String(20), nullable=True),
        sa.Column("kelurahan", sa.String(100), nullable=True),
        sa.Column("kecamatan", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column("tariff_amount", sa.Integer(), nullable=True),
        sa.Column("penalty_amount", sa.Integer(), nullable=True),
        sa.Column("operator_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("gate_out_id", sa.BigInteger(), sa.ForeignKey("gates.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lost_ticket_reports")
