"""add section_instances table (OS-011; referenced by claim_bundles and
render_plans but omitted from appendix C)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "section_instances",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("section_id", sa.Text(), nullable=False),
        sa.Column("capability_id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid()),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Uuid()),
        sa.Column("edition_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("section_instances")
