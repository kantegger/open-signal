"""add editorial object idempotency keys

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-08
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS idempotency_key text"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS claims_idempotency_key_uidx "
        "ON claims (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE research_signal_candidates "
        "ADD COLUMN IF NOT EXISTS idempotency_key text"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "research_signal_candidates_idempotency_key_uidx "
        "ON research_signal_candidates (idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS "
        "research_signal_candidates_idempotency_key_uidx"
    )
    op.execute(
        "ALTER TABLE research_signal_candidates "
        "DROP COLUMN IF EXISTS idempotency_key"
    )
    op.execute("DROP INDEX IF EXISTS claims_idempotency_key_uidx")
    op.execute(
        "ALTER TABLE claims DROP COLUMN IF EXISTS idempotency_key"
    )
