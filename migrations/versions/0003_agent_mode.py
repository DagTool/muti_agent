"""Persist the execution mode selected for each workflow run.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workflow_runs",
        sa.Column("mode", sa.String(20), nullable=False, server_default="mock"),
    )


def downgrade():
    op.drop_column("workflow_runs", "mode")
