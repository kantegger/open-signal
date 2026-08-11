"""add permanent Edition archive and append-only event ledger

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-11
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE daily_editions "
        "ADD COLUMN IF NOT EXISTS first_published_at timestamptz"
    )
    op.execute(
        "ALTER TABLE daily_editions "
        "ADD COLUMN IF NOT EXISTS record_class text NOT NULL "
        "DEFAULT 'operational_ttl'"
    )
    op.execute(
        "ALTER TABLE daily_editions "
        "ADD COLUMN IF NOT EXISTS payload_hash text"
    )
    op.execute(
        """
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'daily_editions_record_class_check'
                  AND conrelid = 'daily_editions'::regclass
            ) THEN
                ALTER TABLE daily_editions
                ADD CONSTRAINT daily_editions_record_class_check
                CHECK (record_class IN ('public_permanent', 'operational_ttl'));
            END IF;
        END
        $migration$
        """
    )

    # A row is permanent once it has ever been public.  Include channel
    # pointers so an old deployment that omitted published_at cannot strand a
    # reader-visible snapshot outside the archive.
    op.execute(
        """
        UPDATE daily_editions e
        SET first_published_at = COALESCE(e.first_published_at, e.published_at,
                                         e.generated_at),
            record_class = 'public_permanent'
        WHERE e.published_at IS NOT NULL
           OR e.status IN ('published', 'sparse', 'beta', 'corrected')
           OR EXISTS (
                SELECT 1
                FROM publication_channels pc
                WHERE pc.current_edition_id = e.id
                   OR pc.previous_edition_id = e.id
           )
        """
    )
    op.execute(
        """
        UPDATE daily_editions
        SET payload_hash = encode(
            digest(convert_to(edition_payload::text, 'UTF8'), 'sha256'),
            'hex'
        )
        WHERE payload_hash IS NULL
        """
    )
    op.execute(
        "ALTER TABLE daily_editions ALTER COLUMN payload_hash SET NOT NULL"
    )
    op.execute(
        """
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'daily_editions_public_class_check'
                  AND conrelid = 'daily_editions'::regclass
            ) THEN
                ALTER TABLE daily_editions
                ADD CONSTRAINT daily_editions_public_class_check CHECK (
                    (record_class = 'public_permanent'
                     AND first_published_at IS NOT NULL)
                    OR (record_class = 'operational_ttl'
                        AND first_published_at IS NULL)
                );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'daily_editions_payload_hash_check'
                  AND conrelid = 'daily_editions'::regclass
            ) THEN
                ALTER TABLE daily_editions
                ADD CONSTRAINT daily_editions_payload_hash_check
                CHECK (payload_hash ~ '^[0-9a-f]{64}$');
            END IF;
        END
        $migration$
        """
    )

    op.execute(
        """
        CREATE TABLE edition_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            edition_id uuid NOT NULL
                REFERENCES daily_editions(id) ON DELETE RESTRICT,
            sequence_no bigint NOT NULL,
            event_type text NOT NULL,
            actor text NOT NULL,
            reason text,
            related_edition_id uuid
                REFERENCES daily_editions(id) ON DELETE RESTRICT,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            previous_event_hash text,
            event_hash text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT edition_events_sequence_unique
                UNIQUE (edition_id, sequence_no),
            CONSTRAINT edition_events_type_check CHECK (
                event_type IN (
                    'published', 'corrected', 'withdrawn',
                    'superseded', 'storage_migrated'
                )
            ),
            CONSTRAINT edition_events_hash_check CHECK (
                event_hash ~ '^[0-9a-f]{64}$'
                AND (
                    previous_event_hash IS NULL
                    OR previous_event_hash ~ '^[0-9a-f]{64}$'
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX edition_events_edition_sequence_idx "
        "ON edition_events (edition_id, sequence_no)"
    )
    op.execute(
        "CREATE INDEX daily_editions_public_archive_idx "
        "ON daily_editions (generated_at DESC, id DESC) "
        "WHERE first_published_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX daily_editions_public_date_idx "
        "ON daily_editions (edition_date DESC, generated_at DESC, id DESC) "
        "WHERE first_published_at IS NOT NULL"
    )

    # Give every historical public snapshot an auditable publication event.
    # The hash is deterministic so rebuilding a branch from the same migration
    # yields the same backfill ledger.
    op.execute(
        """
        INSERT INTO edition_events
          (edition_id, sequence_no, event_type, actor, detail,
           event_hash, created_at)
        SELECT e.id,
               1,
               'published',
               'migration/0012',
               jsonb_build_object('backfilled', true, 'source', '0012'),
               encode(
                   digest(
                       convert_to(
                           concat_ws(
                               '|', 'published', e.id::text,
                               e.first_published_at::text,
                               COALESCE(e.payload_hash, '')
                           ),
                           'UTF8'
                       ),
                       'sha256'
                   ),
                   'hex'
               ),
               e.first_published_at
        FROM daily_editions e
        WHERE e.first_published_at IS NOT NULL
        """
    )

    # Keep classification and hashing correct for legacy writers and test
    # fixtures while current code also supplies the explicit archive fields.
    op.execute(
        """
        CREATE FUNCTION classify_daily_edition_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.payload_hash := encode(
                digest(convert_to(NEW.edition_payload::text, 'UTF8'), 'sha256'),
                'hex'
            );
            IF NEW.first_published_at IS NOT NULL
               OR NEW.published_at IS NOT NULL
               OR NEW.record_class = 'public_permanent'
               OR NEW.status IN ('published', 'sparse', 'beta', 'corrected')
            THEN
                NEW.first_published_at := COALESCE(
                    NEW.first_published_at,
                    NEW.published_at,
                    NEW.generated_at,
                    now()
                );
                NEW.record_class := 'public_permanent';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER daily_editions_classify_write
        BEFORE INSERT OR UPDATE ON daily_editions
        FOR EACH ROW EXECUTE FUNCTION classify_daily_edition_write()
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_public_edition_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.first_published_at IS NOT NULL
               OR OLD.record_class = 'public_permanent'
            THEN
                RAISE EXCEPTION
                    'public Edition % is immutable; append an edition_event instead',
                    OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE'
               AND (
                   NEW.first_published_at IS NOT NULL
                   OR NEW.published_at IS NOT NULL
                   OR NEW.record_class = 'public_permanent'
                   OR NEW.status IN ('published', 'sparse', 'beta', 'corrected')
               )
            THEN
                RAISE EXCEPTION
                    'publish Editions by inserting a new immutable snapshot'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER daily_editions_reject_public_mutation
        BEFORE UPDATE OR DELETE ON daily_editions
        FOR EACH ROW EXECUTE FUNCTION reject_public_edition_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_public_render_plan_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_is_public boolean;
        BEGIN
            SELECT (first_published_at IS NOT NULL
                    OR record_class = 'public_permanent')
            INTO parent_is_public
            FROM daily_editions
            WHERE id = OLD.edition_id;

            IF COALESCE(parent_is_public, false) THEN
                RAISE EXCEPTION
                    'Render Plan % belongs to immutable public Edition %',
                    OLD.id, OLD.edition_id
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER render_plans_reject_public_mutation
        BEFORE UPDATE OR DELETE ON render_plans
        FOR EACH ROW EXECUTE FUNCTION reject_public_render_plan_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION validate_edition_event_append()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            latest_hash text;
            latest_sequence bigint;
        BEGIN
            PERFORM 1
            FROM daily_editions
            WHERE id = NEW.edition_id
            FOR UPDATE;

            SELECT event_hash, sequence_no
            INTO latest_hash, latest_sequence
            FROM edition_events
            WHERE edition_id = NEW.edition_id
            ORDER BY sequence_no DESC
            LIMIT 1;

            IF NEW.sequence_no != COALESCE(latest_sequence, 0) + 1 THEN
                RAISE EXCEPTION
                    'edition event sequence mismatch for Edition %', NEW.edition_id
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.previous_event_hash IS DISTINCT FROM latest_hash THEN
                RAISE EXCEPTION
                    'edition event chain mismatch for Edition %', NEW.edition_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER edition_events_validate_append
        BEFORE INSERT ON edition_events
        FOR EACH ROW EXECUTE FUNCTION validate_edition_event_append()
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_edition_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Edition events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER edition_events_reject_mutation
        BEFORE UPDATE OR DELETE ON edition_events
        FOR EACH ROW EXECUTE FUNCTION reject_edition_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS edition_events_reject_mutation ON edition_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_edition_event_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS edition_events_validate_append ON edition_events"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_edition_event_append()")
    op.execute(
        "DROP TRIGGER IF EXISTS render_plans_reject_public_mutation ON render_plans"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_public_render_plan_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS daily_editions_reject_public_mutation "
        "ON daily_editions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_public_edition_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS daily_editions_classify_write ON daily_editions"
    )
    op.execute("DROP FUNCTION IF EXISTS classify_daily_edition_write()")
    op.execute("DROP INDEX IF EXISTS daily_editions_public_date_idx")
    op.execute("DROP INDEX IF EXISTS daily_editions_public_archive_idx")
    op.execute("DROP INDEX IF EXISTS edition_events_edition_sequence_idx")
    op.execute("DROP TABLE IF EXISTS edition_events")
    op.execute(
        "ALTER TABLE daily_editions "
        "DROP CONSTRAINT IF EXISTS daily_editions_payload_hash_check"
    )
    op.execute(
        "ALTER TABLE daily_editions "
        "DROP CONSTRAINT IF EXISTS daily_editions_public_class_check"
    )
    op.execute(
        "ALTER TABLE daily_editions "
        "DROP CONSTRAINT IF EXISTS daily_editions_record_class_check"
    )
    op.execute("ALTER TABLE daily_editions DROP COLUMN IF EXISTS payload_hash")
    op.execute("ALTER TABLE daily_editions DROP COLUMN IF EXISTS record_class")
    op.execute(
        "ALTER TABLE daily_editions DROP COLUMN IF EXISTS first_published_at"
    )
