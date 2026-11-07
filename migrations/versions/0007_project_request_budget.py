"""Keep project creation budget separate from its editable budget.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("request_token_budget", sa.Integer(), nullable=False, server_default="500000")
        )
    # The original request is unavailable for existing rows; preserve the current budget.
    op.execute(sa.text("UPDATE projects SET request_token_budget = token_budget"))


def downgrade():
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("request_token_budget")
