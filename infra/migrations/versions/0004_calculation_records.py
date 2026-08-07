"""add calculation_records table (OS-010; referenced by evidence_bundles and
resolution_records but omitted from appendix C)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calculation_records",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("calculation_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid()),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("input_snapshot", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("calculation_version", sa.Text(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("calculation_records")
