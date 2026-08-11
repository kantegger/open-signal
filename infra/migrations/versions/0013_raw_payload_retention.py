"""add cold-storage boundary for raw source payloads

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-11
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw_source_records ALTER COLUMN payload DROP NOT NULL")
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS retention_state text NOT NULL DEFAULT 'hot'"
    )
    op.execute(
        "ALTER TABLE raw_source_records ADD COLUMN IF NOT EXISTS payload_storage_key text"
    )
    op.execute(
        "ALTER TABLE raw_source_records ADD COLUMN IF NOT EXISTS payload_archive_hash text"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS payload_uncompressed_bytes bigint"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS payload_compressed_bytes bigint"
    )
    op.execute(
        "ALTER TABLE raw_source_records ADD COLUMN IF NOT EXISTS payload_compression text"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS payload_archived_at timestamptz"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS retention_policy_version text"
    )

    for constraint_name, expression in (
        (
            "raw_source_records_retention_state_check",
            "retention_state IN ('hot', 'cold')",
        ),
        (
            "raw_source_records_archive_hash_check",
            (
                "payload_archive_hash IS NULL "
                "OR payload_archive_hash ~ '^[0-9a-f]{64}$'"
            ),
        ),
        (
            "raw_source_records_compression_check",
            "payload_compression IS NULL OR payload_compression = 'gzip'",
        ),
        (
            "raw_source_records_archive_size_check",
            (
                "(payload_uncompressed_bytes IS NULL "
                "OR payload_uncompressed_bytes >= 0) "
                "AND (payload_compressed_bytes IS NULL "
                "OR payload_compressed_bytes >= 0)"
            ),
        ),
        (
            "raw_source_records_payload_location_check",
            (
                "(retention_state = 'hot' AND payload IS NOT NULL AND "
                "((payload_storage_key IS NULL AND payload_archive_hash IS NULL AND "
                "payload_uncompressed_bytes IS NULL AND "
                "payload_compressed_bytes IS NULL AND "
                "payload_compression IS NULL AND payload_archived_at IS NULL AND "
                "retention_policy_version IS NULL) OR "
                "(payload_storage_key IS NOT NULL AND "
                "payload_archive_hash IS NOT NULL AND "
                "payload_uncompressed_bytes IS NOT NULL AND "
                "payload_compressed_bytes IS NOT NULL AND "
                "payload_compression IS NOT NULL AND "
                "payload_archived_at IS NOT NULL AND "
                "retention_policy_version IS NOT NULL))) OR "
                "(retention_state = 'cold' AND payload IS NULL AND "
                "payload_storage_key IS NOT NULL AND "
                "payload_archive_hash IS NOT NULL AND "
                "payload_uncompressed_bytes IS NOT NULL AND "
                "payload_compressed_bytes IS NOT NULL AND "
                "payload_compression IS NOT NULL AND "
                "payload_archived_at IS NOT NULL AND "
                "retention_policy_version IS NOT NULL)"
            ),
        ),
    ):
        op.execute(
            f"""
            DO $migration$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = '{constraint_name}'
                      AND conrelid = 'raw_source_records'::regclass
                ) THEN
                    ALTER TABLE raw_source_records
                    ADD CONSTRAINT {constraint_name} CHECK ({expression});
                END IF;
            END
            $migration$
            """
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_payload_archive_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            raw_source_record_id uuid NOT NULL UNIQUE
                REFERENCES raw_source_records(id) ON DELETE RESTRICT,
            source_id uuid NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            storage_key text NOT NULL,
            archive_hash text NOT NULL,
            source_content_hash text NOT NULL,
            uncompressed_bytes bigint NOT NULL,
            compressed_bytes bigint NOT NULL,
            compression text NOT NULL,
            policy_version text NOT NULL,
            actor text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT raw_payload_archive_events_hash_check CHECK (
                archive_hash ~ '^[0-9a-f]{64}$'
                AND source_content_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT raw_payload_archive_events_size_check CHECK (
                uncompressed_bytes >= 0 AND compressed_bytes >= 0
            ),
            CONSTRAINT raw_payload_archive_events_compression_check CHECK (
                compression = 'gzip'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS raw_payload_archive_events_created_idx "
        "ON raw_payload_archive_events (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS raw_source_records_hot_retention_idx "
        "ON raw_source_records "
        "(source_id, external_id, last_seen_at DESC, ingested_at DESC) "
        "WHERE retention_state = 'hot'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS raw_source_records_hot_age_idx "
        "ON raw_source_records (last_seen_at) WHERE retention_state = 'hot'"
    )

    # A payload can be cleared only after a matching append-only storage event
    # exists in the same transaction.  Rehydration is allowed, but the verified
    # archive pointer and hashes remain immutable.
    op.execute(
        """
        CREATE FUNCTION validate_raw_payload_storage_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            archive_event raw_payload_archive_events%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.retention_state != 'hot'
                   OR NEW.payload IS NULL
                   OR NEW.payload_storage_key IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new raw source records must start with a hot payload'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.payload_storage_key IS NOT NULL AND (
                NEW.payload_storage_key IS DISTINCT FROM OLD.payload_storage_key
                OR NEW.payload_archive_hash IS DISTINCT FROM OLD.payload_archive_hash
                OR NEW.payload_uncompressed_bytes IS DISTINCT FROM OLD.payload_uncompressed_bytes
                OR NEW.payload_compressed_bytes IS DISTINCT FROM OLD.payload_compressed_bytes
                OR NEW.payload_compression IS DISTINCT FROM OLD.payload_compression
                OR NEW.payload_archived_at IS DISTINCT FROM OLD.payload_archived_at
                OR NEW.retention_policy_version IS DISTINCT FROM OLD.retention_policy_version
            ) THEN
                RAISE EXCEPTION
                    'verified raw payload archive metadata is immutable for record %', OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.retention_state = 'hot' AND NEW.retention_state = 'cold' THEN
                SELECT * INTO archive_event
                FROM raw_payload_archive_events
                WHERE raw_source_record_id = OLD.id;

                IF archive_event.id IS NULL
                   OR archive_event.source_id IS DISTINCT FROM OLD.source_id
                   OR archive_event.storage_key IS DISTINCT FROM NEW.payload_storage_key
                   OR archive_event.archive_hash IS DISTINCT FROM NEW.payload_archive_hash
                   OR archive_event.source_content_hash IS DISTINCT FROM OLD.content_hash
                   OR archive_event.uncompressed_bytes IS DISTINCT FROM NEW.payload_uncompressed_bytes
                   OR archive_event.compressed_bytes IS DISTINCT FROM NEW.payload_compressed_bytes
                   OR archive_event.compression IS DISTINCT FROM NEW.payload_compression
                   OR archive_event.policy_version IS DISTINCT FROM NEW.retention_policy_version
                THEN
                    RAISE EXCEPTION
                        'raw payload % lacks a matching verified archive event', OLD.id
                        USING ERRCODE = '55000';
                END IF;
            ELSIF OLD.retention_state = 'cold' AND NEW.retention_state = 'hot' THEN
                IF NEW.payload IS NULL THEN
                    RAISE EXCEPTION
                        'rehydrating raw payload % requires payload bytes', OLD.id
                        USING ERRCODE = '55000';
                END IF;
            ELSIF NEW.retention_state IS DISTINCT FROM OLD.retention_state THEN
                RAISE EXCEPTION
                    'unsupported raw payload retention transition for record %', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_source_records_validate_storage_insert
        BEFORE INSERT ON raw_source_records
        FOR EACH ROW EXECUTE FUNCTION validate_raw_payload_storage_transition()
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_source_records_validate_storage_transition
        BEFORE UPDATE OF payload, retention_state, payload_storage_key,
                         payload_archive_hash, payload_uncompressed_bytes,
                         payload_compressed_bytes, payload_compression,
                         payload_archived_at, retention_policy_version
        ON raw_source_records
        FOR EACH ROW EXECUTE FUNCTION validate_raw_payload_storage_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_raw_payload_archive_event_append()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            raw_source_id uuid;
            raw_content_hash text;
            raw_retention_state text;
            raw_has_payload boolean;
        BEGIN
            SELECT source_id, content_hash, retention_state, payload IS NOT NULL
            INTO raw_source_id, raw_content_hash, raw_retention_state, raw_has_payload
            FROM raw_source_records
            WHERE id = NEW.raw_source_record_id
            FOR UPDATE;

            IF raw_source_id IS NULL
               OR raw_source_id IS DISTINCT FROM NEW.source_id
               OR raw_content_hash IS DISTINCT FROM NEW.source_content_hash
               OR raw_retention_state != 'hot'
               OR NOT COALESCE(raw_has_payload, false)
            THEN
                RAISE EXCEPTION
                    'archive event does not match a hot raw payload %',
                    NEW.raw_source_record_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_payload_archive_events_validate_append
        BEFORE INSERT ON raw_payload_archive_events
        FOR EACH ROW EXECUTE FUNCTION validate_raw_payload_archive_event_append()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_raw_payload_archive_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Raw payload archive events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_payload_archive_events_reject_mutation
        BEFORE UPDATE OR DELETE ON raw_payload_archive_events
        FOR EACH ROW EXECUTE FUNCTION reject_raw_payload_archive_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS raw_payload_archive_events_reject_mutation "
        "ON raw_payload_archive_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_raw_payload_archive_event_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS raw_payload_archive_events_validate_append "
        "ON raw_payload_archive_events"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_raw_payload_archive_event_append()")
    op.execute(
        "DROP TRIGGER IF EXISTS raw_source_records_validate_storage_transition "
        "ON raw_source_records"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS raw_source_records_validate_storage_insert "
        "ON raw_source_records"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_raw_payload_storage_transition()")
    op.execute("DROP INDEX IF EXISTS raw_source_records_hot_age_idx")
    op.execute("DROP INDEX IF EXISTS raw_source_records_hot_retention_idx")
    op.execute("DROP INDEX IF EXISTS raw_payload_archive_events_created_idx")
    op.execute("DROP TABLE IF EXISTS raw_payload_archive_events")
    for constraint_name in (
        "raw_source_records_payload_location_check",
        "raw_source_records_archive_size_check",
        "raw_source_records_compression_check",
        "raw_source_records_archive_hash_check",
        "raw_source_records_retention_state_check",
    ):
        op.execute(
            "ALTER TABLE raw_source_records "
            f"DROP CONSTRAINT IF EXISTS {constraint_name}"
        )
    for column_name in (
        "retention_policy_version",
        "payload_archived_at",
        "payload_compression",
        "payload_compressed_bytes",
        "payload_uncompressed_bytes",
        "payload_archive_hash",
        "payload_storage_key",
        "retention_state",
    ):
        op.execute(
            f"ALTER TABLE raw_source_records DROP COLUMN IF EXISTS {column_name}"
        )
    op.execute("ALTER TABLE raw_source_records ALTER COLUMN payload SET NOT NULL")
