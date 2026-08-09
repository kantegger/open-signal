"""add rolling publication snapshots and atomic current channel

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08

`IF NOT EXISTS` keeps a fresh install safe because revision 0001 compiles the
current SQLAlchemy metadata. Existing installations receive the same columns
here, while fresh databases simply retain the columns already emitted by 0001.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE daily_editions ADD COLUMN IF NOT EXISTS trigger_type text NOT NULL DEFAULT 'scheduled'")
    op.execute("ALTER TABLE daily_editions ADD COLUMN IF NOT EXISTS supersedes_edition_id uuid")
    op.execute("ALTER TABLE daily_editions ADD COLUMN IF NOT EXISTS freshness_summary jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE daily_editions ADD COLUMN IF NOT EXISTS published_at timestamptz")
    op.execute("ALTER TABLE daily_editions ADD COLUMN IF NOT EXISTS policy_version text NOT NULL DEFAULT '0.1.0'")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'daily_editions_supersedes_edition_fk'
          ) THEN
            ALTER TABLE daily_editions
              ADD CONSTRAINT daily_editions_supersedes_edition_fk
              FOREIGN KEY (supersedes_edition_id) REFERENCES daily_editions(id);
          END IF;
        END $$
        """
    )

    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS position integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS data_as_of timestamptz")
    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS assessed_at timestamptz")
    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS materially_updated_at timestamptz")
    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS freshness_state text NOT NULL DEFAULT 'current'")
    op.execute("ALTER TABLE render_plans ADD COLUMN IF NOT EXISTS expires_at timestamptz")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS render_plans_edition_slot_position_uidx "
        "ON render_plans (edition_id, slot_id, position)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS publication_channels (
          id text PRIMARY KEY,
          current_edition_id uuid NOT NULL REFERENCES daily_editions(id),
          previous_edition_id uuid REFERENCES daily_editions(id),
          policy_version text NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO publication_channels
          (id, current_edition_id, previous_edition_id, policy_version, updated_at)
        SELECT 'front-page', id, NULL, COALESCE(policy_version, '0.1.0'), generated_at
        FROM daily_editions
        WHERE status IN ('published', 'sparse', 'beta', 'corrected')
        ORDER BY generated_at DESC
        LIMIT 1
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("publication_channels")
    op.execute("DROP INDEX IF EXISTS render_plans_edition_slot_position_uidx")
    op.drop_column("render_plans", "expires_at")
    op.drop_column("render_plans", "freshness_state")
    op.drop_column("render_plans", "materially_updated_at")
    op.drop_column("render_plans", "assessed_at")
    op.drop_column("render_plans", "data_as_of")
    op.drop_column("render_plans", "position")
    op.execute(
        "ALTER TABLE daily_editions DROP CONSTRAINT IF EXISTS daily_editions_supersedes_edition_fk"
    )
    op.drop_column("daily_editions", "policy_version")
    op.drop_column("daily_editions", "published_at")
    op.drop_column("daily_editions", "freshness_summary")
    op.drop_column("daily_editions", "supersedes_edition_id")
    op.drop_column("daily_editions", "trigger_type")
