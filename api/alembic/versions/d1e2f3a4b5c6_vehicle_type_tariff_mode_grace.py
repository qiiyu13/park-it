"""vehicle_types: tariff_mode + grace_period_minutes (replaces is_progressive)

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicle_types",
        sa.Column("tariff_mode", sa.String(20), nullable=False, server_default="hourly"),
    )
    op.add_column(
        "vehicle_types",
        sa.Column("grace_period_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.execute("UPDATE vehicle_types SET tariff_mode = 'progressive' WHERE is_progressive")
    op.drop_column("vehicle_types", "is_progressive")


def downgrade() -> None:
    op.add_column(
        "vehicle_types",
        sa.Column("is_progressive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE vehicle_types SET is_progressive = (tariff_mode = 'progressive')")
    op.drop_column("vehicle_types", "grace_period_minutes")
    op.drop_column("vehicle_types", "tariff_mode")
