"""Align the pos.default_gate_id FK name with the model.

``api/app/models/pos.py`` declares this constraint as ``fk_pos_default_gate_id``
with ``use_alter=True`` — the explicit name is what lets SQLAlchemy break the
gates<->pos circular FK and emit a standalone ALTER TABLE ... DROP CONSTRAINT.
Migration ``f7a2b8c9d0e1`` created the column with an unnamed ForeignKey, so
Postgres auto-named it ``pos_default_gate_id_fkey``.

Consequence: ``Base.metadata.drop_all`` against any Alembic-built database
aborts with ``constraint "fk_pos_default_gate_id" of relation "pos" does not
exist``, leaving the schema half-dropped. That wedges the test database — every
subsequent run then fails on leftover rows.

Rename is guarded so it is a no-op on databases built by ``create_all`` (which
already carry the model's name) and on re-runs.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-26
"""

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

_OLD = "pos_default_gate_id_fkey"
_NEW = "fk_pos_default_gate_id"


def _rename(from_name: str, to_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'pos'::regclass AND conname = '{from_name}'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'pos'::regclass AND conname = '{to_name}'
            ) THEN
                ALTER TABLE pos RENAME CONSTRAINT {from_name} TO {to_name};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _rename(_OLD, _NEW)


def downgrade() -> None:
    _rename(_NEW, _OLD)
