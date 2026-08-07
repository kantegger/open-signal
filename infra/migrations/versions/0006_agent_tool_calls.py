"""add agent_tool_calls table (OS-015 tool-call log; appendix C omitted it)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("investigation_runs.id"), nullable=False),
        sa.Column("agent_lineage_id", sa.Text()),
        sa.Column("tool_id", sa.Text(), nullable=False),
        sa.Column("arguments", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("result_size_bytes", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
