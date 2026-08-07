"""add market_observations default partition (spec §104, OS-008)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-07

market_observations is range-partitioned by observed_at (appendix C); rows
need at least one partition to insert into. This default partition keeps
development simple; production may add monthly RANGE partitions alongside.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE market_observations_default "
        "PARTITION OF market_observations DEFAULT"
    )


def downgrade() -> None:
    op.execute("DROP TABLE market_observations_default")
