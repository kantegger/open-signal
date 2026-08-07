"""initial schema from spec appendix C

Revision ID: 0001
Revises:
Create Date: 2026-08-07

36 tables + extensions, triggers and postponed (circular) foreign keys.
"""

import sys
from pathlib import Path

from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "python"))

from open_signal.db import models  # noqa: E402

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_dialect = postgresql.dialect()


def upgrade() -> None:
    # --- extensions and helper functions (appendix C.1) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'This table is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )

    # --- tables (topologically sorted; use_alter FKs excluded) ---
    # NOTE: 0001 creates only the 36 appendix-C tables; later revisions add
    # their own tables (source_cursors, calculation_records, section_instances,
    # feature_flags, audit_events).
    _LATER_TABLES = frozenset({"source_cursors", "calculation_records", "section_instances", "feature_flags", "audit_events"})
    for table in models.metadata.sorted_tables:
        if table.name in _LATER_TABLES:
            continue
        op.execute(str(CreateTable(table).compile(dialect=_dialect)).strip())
        for index in table.indexes:
            op.execute(str(CreateIndex(index).compile(dialect=_dialect)).strip())

    # --- triggers ---
    op.execute(
        "CREATE TRIGGER sources_set_updated_at BEFORE UPDATE ON sources "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER claim_versions_no_update BEFORE UPDATE OR DELETE "
        "ON claim_versions FOR EACH ROW EXECUTE FUNCTION prevent_mutation()"
    )
    op.execute(
        "CREATE TRIGGER claim_events_no_update BEFORE UPDATE OR DELETE "
        "ON claim_events FOR EACH ROW EXECUTE FUNCTION prevent_mutation()"
    )

    # --- postponed circular foreign keys (appendix C.9/C.11) ---
    op.execute(
        "ALTER TABLE claims ADD CONSTRAINT claims_current_version_fk "
        "FOREIGN KEY (current_version_id) REFERENCES claim_versions(id)"
    )
    op.execute(
        "ALTER TABLE claims ADD CONSTRAINT claims_bundle_fk "
        "FOREIGN KEY (bundle_id) REFERENCES claim_bundles(id)"
    )
    op.execute(
        "ALTER TABLE claims ADD CONSTRAINT claims_family_fk "
        "FOREIGN KEY (claim_family_id) REFERENCES claim_families(id)"
    )
    op.execute(
        "ALTER TABLE claim_bundles ADD CONSTRAINT claim_bundles_headline_fk "
        "FOREIGN KEY (headline_claim_id) REFERENCES claims(id)"
    )
    op.execute(
        "ALTER TABLE claims ADD CONSTRAINT claims_resolution_contract_fk "
        "FOREIGN KEY (resolution_contract_id) REFERENCES resolution_contracts(id)"
    )
    op.execute(
        "ALTER TABLE canonical_rules ADD CONSTRAINT canonical_rules_current_version_fk "
        "FOREIGN KEY (current_version_id) REFERENCES rule_versions(id)"
    )
    op.execute(
        "ALTER TABLE resolution_contracts ADD CONSTRAINT resolution_contracts_template_fk "
        "FOREIGN KEY (template_id, template_version) "
        "REFERENCES resolution_templates(id, version)"
    )


def downgrade() -> None:
    for table in reversed(models.metadata.sorted_tables):
        op.drop_table(table.name)
    op.execute("DROP FUNCTION IF EXISTS prevent_mutation()")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
