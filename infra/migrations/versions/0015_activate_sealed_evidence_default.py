"""activate sealed evidence as the database default

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-11
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Contract step: run only after every production Claim writer that predates
    # 0014 has been replaced. The application already opts in explicitly, so
    # this default is defense in depth for future or out-of-band writers.
    op.execute(
        "ALTER TABLE claims ALTER COLUMN evidence_policy_version "
        "SET DEFAULT 'sealed-v1'"
    )


def downgrade() -> None:
    # Restores compatibility with the pre-sealing writers during rollback.
    op.execute(
        "ALTER TABLE claims ALTER COLUMN evidence_policy_version "
        "SET DEFAULT 'legacy'"
    )
