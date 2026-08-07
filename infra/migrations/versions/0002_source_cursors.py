"""add source_cursors table (spec §93, OS-007)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-07

Note: columns are declared explicitly (op.create_table accepts a Table
object as name only; explicit columns are unambiguous).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_cursors",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id"), primary_key=True),
        sa.Column("cursor_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("last_successful_fetch_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_source_timestamp", sa.DateTime(timezone=True)),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("source_cursors")
