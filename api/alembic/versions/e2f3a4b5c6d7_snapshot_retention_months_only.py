"""settings: snapshot retention is months only (drop daily/weekly tiers)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

LABEL = "Hapus Otomatis: simpan snapshot (bulan)"
DESC = (
    "Snapshot disimpan semua selama N bulan terakhir, yang lebih lama dihapus otomatis. "
    "Isi 0 untuk menyimpan selamanya."
)


def upgrade() -> None:
    op.execute(
        "DELETE FROM settings WHERE key IN ('snapshot_retention_days', 'snapshot_keep_weeks')"
    )
    # Startup seeding never overwrites an existing row, so refresh the wording here.
    # The operator's chosen month count (value) is kept.
    op.execute(
        f"UPDATE settings SET label = '{LABEL}', description = '{DESC}' "
        "WHERE key = 'snapshot_keep_months'"
    )


def downgrade() -> None:
    # API startup re-seeds the daily/weekly rows if the old code is redeployed.
    pass
