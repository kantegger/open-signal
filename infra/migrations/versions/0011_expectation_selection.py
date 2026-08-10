"""add event-aware Expectations selection fields and indexes

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-10
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE source_markets ADD COLUMN volume_24h numeric")
    op.execute(
        "ALTER TABLE source_markets "
        "ADD COLUMN monitoring_last_seen_at timestamptz"
    )
    op.execute(
        """
        UPDATE source_markets sm
        SET volume_24h = CASE
              WHEN COALESCE(raw.payload->>'volume24hr', raw.payload->>'volume24h', '')
                   ~ '^[0-9]+([.][0-9]+)?$'
              THEN COALESCE(raw.payload->>'volume24hr', raw.payload->>'volume24h')::numeric
              ELSE NULL
            END,
            monitoring_last_seen_at = raw.last_seen_at
        FROM raw_source_records raw
        WHERE raw.id = sm.raw_source_record_id
        """
    )
    op.execute(
        "CREATE INDEX source_markets_event_idx "
        "ON source_markets (source_id, external_event_id)"
    )
    op.execute(
        "CREATE INDEX source_markets_monitoring_idx "
        "ON source_markets (source_id, monitoring_last_seen_at DESC)"
    )
    op.execute(
        "CREATE INDEX canonical_expectations_source_markets_idx "
        "ON canonical_expectations USING gin (source_market_ids)"
    )
    op.execute(
        "CREATE INDEX claims_public_recency_idx "
        "ON claims (status, issued_at DESC)"
    )
    op.execute(
        "CREATE INDEX section_instances_subject_claim_idx "
        "ON section_instances (subject_type, subject_id, claim_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS section_instances_subject_claim_idx")
    op.execute("DROP INDEX IF EXISTS claims_public_recency_idx")
    op.execute("DROP INDEX IF EXISTS canonical_expectations_source_markets_idx")
    op.execute("DROP INDEX IF EXISTS source_markets_monitoring_idx")
    op.execute("DROP INDEX IF EXISTS source_markets_event_idx")
    op.execute(
        "ALTER TABLE source_markets DROP COLUMN IF EXISTS monitoring_last_seen_at"
    )
    op.execute("ALTER TABLE source_markets DROP COLUMN IF EXISTS volume_24h")
