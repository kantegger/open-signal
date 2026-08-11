"""seal public evidence before publication and allow audited raw purge

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-11
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS "
        "evidence_policy_version text NOT NULL DEFAULT 'legacy'"
    )
    # Keep the transitional database default on legacy so this expand migration
    # can land before the new writers without breaking the still-running
    # release. New writers opt in explicitly; migration 0015 flips the default
    # only after those writers are deployed. SET DEFAULT is required for the
    # from-scratch path because migration 0001 compiles current metadata.
    op.execute(
        "ALTER TABLE claims ALTER COLUMN evidence_policy_version "
        "SET DEFAULT 'legacy'"
    )
    op.execute(
        """
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'claims_evidence_policy_version_check'
                  AND conrelid = 'claims'::regclass
            ) THEN
                ALTER TABLE claims ADD CONSTRAINT
                claims_evidence_policy_version_check CHECK (
                    evidence_policy_version IN ('legacy', 'sealed-v1')
                );
            END IF;
        END
        $migration$
        """
    )
    op.execute(
        """
        CREATE TABLE evidence_seals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_bundle_id uuid NOT NULL UNIQUE
                REFERENCES evidence_bundles(id) ON DELETE RESTRICT,
            snapshot_hash text NOT NULL,
            object_hash text NOT NULL UNIQUE,
            storage_key text NOT NULL UNIQUE,
            byte_size bigint NOT NULL,
            content_type text NOT NULL,
            policy_version text NOT NULL,
            actor text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            sealed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT evidence_seals_hash_check CHECK (
                snapshot_hash ~ '^[0-9a-f]{64}$'
                AND object_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT evidence_seals_size_check CHECK (byte_size > 0),
            CONSTRAINT evidence_seals_content_type_check CHECK (
                content_type = 'application/json; charset=utf-8'
            ),
            CONSTRAINT evidence_seals_storage_key_check CHECK (
                storage_key = 'public/evidence/v1/' || object_hash || '.json'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX evidence_seals_sealed_at_idx "
        "ON evidence_seals (sealed_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION validate_evidence_seal_append()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            bundle_hash text;
        BEGIN
            SELECT snapshot_hash INTO bundle_hash
            FROM evidence_bundles
            WHERE id = NEW.evidence_bundle_id
            FOR SHARE;

            IF bundle_hash IS NULL
               OR bundle_hash IS DISTINCT FROM NEW.snapshot_hash
            THEN
                RAISE EXCEPTION
                    'evidence seal does not match bundle %', NEW.evidence_bundle_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidence_seals_validate_append
        BEFORE INSERT ON evidence_seals
        FOR EACH ROW EXECUTE FUNCTION validate_evidence_seal_append()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_evidence_seal_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Evidence seals are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidence_seals_reject_mutation
        BEFORE UPDATE OR DELETE ON evidence_seals
        FOR EACH ROW EXECUTE FUNCTION reject_evidence_seal_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_sealed_evidence_bundle_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM evidence_seals
                WHERE evidence_bundle_id = OLD.id
            ) THEN
                RAISE EXCEPTION 'Sealed evidence bundle % is immutable', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidence_bundles_reject_sealed_mutation
        BEFORE UPDATE OR DELETE ON evidence_bundles
        FOR EACH ROW EXECUTE FUNCTION reject_sealed_evidence_bundle_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_public_edition_evidence_seals()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            missing_claim uuid;
        BEGIN
            IF NEW.record_class != 'public_permanent' THEN
                RETURN NEW;
            END IF;

            SELECT c.id INTO missing_claim
            FROM unnest(NEW.included_claim_ids) AS included(claim_id)
            JOIN claims c ON c.id = included.claim_id
            LEFT JOIN claim_versions current_version
              ON current_version.id = c.current_version_id
            JOIN evidence_bundles bundle
              ON bundle.id = COALESCE(
                  current_version.evidence_bundle_id,
                  c.evidence_bundle_id
              )
            LEFT JOIN evidence_seals seal
              ON seal.evidence_bundle_id = bundle.id
             AND seal.snapshot_hash = bundle.snapshot_hash
            WHERE c.evidence_policy_version = 'sealed-v1'
              AND seal.id IS NULL
            LIMIT 1;

            IF missing_claim IS NOT NULL THEN
                RAISE EXCEPTION
                    'public edition requires sealed evidence for claim %', missing_claim
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER daily_editions_require_evidence_seals
        BEFORE INSERT ON daily_editions
        FOR EACH ROW EXECUTE FUNCTION require_public_edition_evidence_seals()
        """
    )

    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS payload_purged_at timestamptz"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "ADD COLUMN IF NOT EXISTS purge_policy_version text"
    )
    # The same provider may reuse an external ID across object kinds (for
    # example a Polymarket event and market). Retention identity therefore
    # includes record_type even though the legacy ingest uniqueness constraint
    # remains unchanged for rolling-deploy compatibility.
    op.execute(
        "CREATE INDEX raw_source_records_hot_retention_v2_idx "
        "ON raw_source_records "
        "(source_id, record_type, external_id, last_seen_at DESC, "
        "ingested_at DESC) WHERE retention_state = 'hot'"
    )
    op.execute(
        """
        CREATE TABLE raw_payload_purge_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            raw_source_record_id uuid NOT NULL
                REFERENCES raw_source_records(id) ON DELETE RESTRICT,
            source_id uuid NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            source_content_hash text NOT NULL,
            policy_version text NOT NULL,
            actor text NOT NULL,
            reason text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT raw_payload_purge_events_hash_check CHECK (
                source_content_hash ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX raw_payload_purge_events_created_idx "
        "ON raw_payload_purge_events (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX raw_payload_purge_events_record_idx "
        "ON raw_payload_purge_events (raw_source_record_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "DROP CONSTRAINT raw_source_records_payload_location_check"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "DROP CONSTRAINT raw_source_records_retention_state_check"
    )
    op.execute(
        "ALTER TABLE raw_source_records ADD CONSTRAINT "
        "raw_source_records_retention_state_check "
        "CHECK (retention_state IN ('hot', 'cold', 'purged'))"
    )
    op.execute(
        """
        ALTER TABLE raw_source_records ADD CONSTRAINT
        raw_source_records_payload_location_check CHECK (
            (
                retention_state = 'hot'
                AND payload IS NOT NULL
                AND payload_purged_at IS NULL
                AND purge_policy_version IS NULL
                AND (
                    (
                        payload_storage_key IS NULL
                        AND payload_archive_hash IS NULL
                        AND payload_uncompressed_bytes IS NULL
                        AND payload_compressed_bytes IS NULL
                        AND payload_compression IS NULL
                        AND payload_archived_at IS NULL
                        AND retention_policy_version IS NULL
                    ) OR (
                        payload_storage_key IS NOT NULL
                        AND payload_archive_hash IS NOT NULL
                        AND payload_uncompressed_bytes IS NOT NULL
                        AND payload_compressed_bytes IS NOT NULL
                        AND payload_compression IS NOT NULL
                        AND payload_archived_at IS NOT NULL
                        AND retention_policy_version IS NOT NULL
                    )
                )
            ) OR (
                retention_state = 'cold'
                AND payload IS NULL
                AND payload_storage_key IS NOT NULL
                AND payload_archive_hash IS NOT NULL
                AND payload_uncompressed_bytes IS NOT NULL
                AND payload_compressed_bytes IS NOT NULL
                AND payload_compression IS NOT NULL
                AND payload_archived_at IS NOT NULL
                AND retention_policy_version IS NOT NULL
                AND payload_purged_at IS NULL
                AND purge_policy_version IS NULL
            ) OR (
                retention_state = 'purged'
                AND payload IS NULL
                AND payload_purged_at IS NOT NULL
                AND purge_policy_version IS NOT NULL
                AND (
                    (
                        payload_storage_key IS NULL
                        AND payload_archive_hash IS NULL
                        AND payload_uncompressed_bytes IS NULL
                        AND payload_compressed_bytes IS NULL
                        AND payload_compression IS NULL
                        AND payload_archived_at IS NULL
                        AND retention_policy_version IS NULL
                    ) OR (
                        payload_storage_key IS NOT NULL
                        AND payload_archive_hash IS NOT NULL
                        AND payload_uncompressed_bytes IS NOT NULL
                        AND payload_compressed_bytes IS NOT NULL
                        AND payload_compression IS NOT NULL
                        AND payload_archived_at IS NOT NULL
                        AND retention_policy_version IS NOT NULL
                    )
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX raw_source_records_purged_idx "
        "ON raw_source_records (payload_purged_at DESC) "
        "WHERE retention_state = 'purged'"
    )

    op.execute("DROP TRIGGER raw_source_records_validate_storage_transition ON raw_source_records")
    op.execute("DROP TRIGGER raw_source_records_validate_storage_insert ON raw_source_records")
    op.execute("DROP FUNCTION validate_raw_payload_storage_transition()")
    _install_storage_transition_v2()
    op.execute(
        """
        CREATE FUNCTION validate_raw_payload_purge_event_append()
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
                    'purge event does not match a hot raw payload %',
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
        CREATE TRIGGER raw_payload_purge_events_validate_append
        BEFORE INSERT ON raw_payload_purge_events
        FOR EACH ROW EXECUTE FUNCTION validate_raw_payload_purge_event_append()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_raw_payload_purge_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Raw payload purge events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_payload_purge_events_reject_mutation
        BEFORE UPDATE OR DELETE ON raw_payload_purge_events
        FOR EACH ROW EXECUTE FUNCTION reject_raw_payload_purge_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS raw_payload_purge_events_reject_mutation "
        "ON raw_payload_purge_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_raw_payload_purge_event_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS raw_payload_purge_events_validate_append "
        "ON raw_payload_purge_events"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_raw_payload_purge_event_append()")
    op.execute("DROP TRIGGER raw_source_records_validate_storage_transition ON raw_source_records")
    op.execute("DROP TRIGGER raw_source_records_validate_storage_insert ON raw_source_records")
    op.execute("DROP FUNCTION validate_raw_payload_storage_transition()")
    op.execute("DROP INDEX IF EXISTS raw_source_records_purged_idx")
    op.execute(
        "ALTER TABLE raw_source_records "
        "DROP CONSTRAINT raw_source_records_payload_location_check"
    )
    op.execute(
        "ALTER TABLE raw_source_records "
        "DROP CONSTRAINT raw_source_records_retention_state_check"
    )
    op.execute(
        "ALTER TABLE raw_source_records ADD CONSTRAINT "
        "raw_source_records_retention_state_check "
        "CHECK (retention_state IN ('hot', 'cold'))"
    )
    op.execute(
        """
        ALTER TABLE raw_source_records ADD CONSTRAINT
        raw_source_records_payload_location_check CHECK (
            (retention_state = 'hot' AND payload IS NOT NULL AND
             ((payload_storage_key IS NULL AND payload_archive_hash IS NULL AND
               payload_uncompressed_bytes IS NULL AND payload_compressed_bytes IS NULL AND
               payload_compression IS NULL AND payload_archived_at IS NULL AND
               retention_policy_version IS NULL) OR
              (payload_storage_key IS NOT NULL AND payload_archive_hash IS NOT NULL AND
               payload_uncompressed_bytes IS NOT NULL AND payload_compressed_bytes IS NOT NULL AND
               payload_compression IS NOT NULL AND payload_archived_at IS NOT NULL AND
               retention_policy_version IS NOT NULL))) OR
            (retention_state = 'cold' AND payload IS NULL AND
             payload_storage_key IS NOT NULL AND payload_archive_hash IS NOT NULL AND
             payload_uncompressed_bytes IS NOT NULL AND payload_compressed_bytes IS NOT NULL AND
             payload_compression IS NOT NULL AND payload_archived_at IS NOT NULL AND
             retention_policy_version IS NOT NULL)
        )
        """
    )
    _install_storage_transition_v1()
    op.execute("DROP INDEX IF EXISTS raw_payload_purge_events_created_idx")
    op.execute("DROP INDEX IF EXISTS raw_payload_purge_events_record_idx")
    op.execute("DROP TABLE raw_payload_purge_events")
    op.execute("DROP INDEX IF EXISTS raw_source_records_hot_retention_v2_idx")
    op.execute("ALTER TABLE raw_source_records DROP COLUMN purge_policy_version")
    op.execute("ALTER TABLE raw_source_records DROP COLUMN payload_purged_at")

    op.execute(
        "DROP TRIGGER IF EXISTS daily_editions_require_evidence_seals "
        "ON daily_editions"
    )
    op.execute("DROP FUNCTION IF EXISTS require_public_edition_evidence_seals()")
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_bundles_reject_sealed_mutation "
        "ON evidence_bundles"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_sealed_evidence_bundle_mutation()")
    op.execute("DROP TRIGGER IF EXISTS evidence_seals_reject_mutation ON evidence_seals")
    op.execute("DROP FUNCTION IF EXISTS reject_evidence_seal_mutation()")
    op.execute("DROP TRIGGER IF EXISTS evidence_seals_validate_append ON evidence_seals")
    op.execute("DROP FUNCTION IF EXISTS validate_evidence_seal_append()")
    op.execute("DROP INDEX IF EXISTS evidence_seals_sealed_at_idx")
    op.execute("DROP TABLE evidence_seals")
    op.execute(
        "ALTER TABLE claims DROP CONSTRAINT IF EXISTS "
        "claims_evidence_policy_version_check"
    )
    op.execute("ALTER TABLE claims DROP COLUMN evidence_policy_version")


def _install_storage_transition_v2() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_raw_payload_storage_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            archive_event raw_payload_archive_events%ROWTYPE;
            purge_event raw_payload_purge_events%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.retention_state != 'hot'
                   OR NEW.payload IS NULL
                   OR NEW.payload_storage_key IS NOT NULL
                   OR NEW.payload_purged_at IS NOT NULL
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
            ELSIF OLD.retention_state = 'hot' AND NEW.retention_state = 'purged' THEN
                SELECT * INTO purge_event
                FROM raw_payload_purge_events
                WHERE raw_source_record_id = OLD.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1;

                IF purge_event.id IS NULL
                   OR purge_event.source_id IS DISTINCT FROM OLD.source_id
                   OR purge_event.source_content_hash IS DISTINCT FROM OLD.content_hash
                   OR purge_event.policy_version IS DISTINCT FROM NEW.purge_policy_version
                   OR purge_event.created_at IS DISTINCT FROM NEW.payload_purged_at
                THEN
                    RAISE EXCEPTION
                        'raw payload % lacks a matching purge event', OLD.id
                        USING ERRCODE = '55000';
                END IF;
            ELSIF OLD.retention_state IN ('cold', 'purged')
                  AND NEW.retention_state = 'hot' THEN
                IF NEW.payload IS NULL THEN
                    RAISE EXCEPTION
                        'rehydrating raw payload % requires payload bytes', OLD.id
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.retention_state = 'purged' AND (
                    NEW.payload_purged_at IS NOT NULL
                    OR NEW.purge_policy_version IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'rehydrating purged payload % must clear purge state', OLD.id
                        USING ERRCODE = '55000';
                END IF;
            ELSIF NEW.retention_state IS DISTINCT FROM OLD.retention_state THEN
                RAISE EXCEPTION
                    'unsupported raw payload retention transition for record %', OLD.id
                    USING ERRCODE = '55000';
            ELSIF OLD.retention_state = 'purged' AND (
                NEW.payload_purged_at IS DISTINCT FROM OLD.payload_purged_at
                OR NEW.purge_policy_version IS DISTINCT FROM OLD.purge_policy_version
            ) THEN
                RAISE EXCEPTION
                    'raw payload purge metadata is immutable for record %', OLD.id
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
                         payload_archived_at, retention_policy_version,
                         payload_purged_at, purge_policy_version
        ON raw_source_records
        FOR EACH ROW EXECUTE FUNCTION validate_raw_payload_storage_transition()
        """
    )


def _install_storage_transition_v1() -> None:
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
