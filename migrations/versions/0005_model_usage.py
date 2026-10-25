"""Track model tokens and a project soft budget.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("token_budget", sa.Integer(), nullable=False, server_default="500000")
    )
    op.add_column(
        "projects", sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "model_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "attempt"),
    )
    op.create_index("ix_model_usage_project_id", "model_usage", ["project_id"])
    op.create_index("ix_model_usage_run_id", "model_usage", ["run_id"])
    op.create_index("ix_model_usage_task_id", "model_usage", ["task_id"])


def downgrade():
    op.drop_index("ix_model_usage_task_id", "model_usage")
    op.drop_index("ix_model_usage_run_id", "model_usage")
    op.drop_index("ix_model_usage_project_id", "model_usage")
    op.drop_table("model_usage")
    op.drop_column("projects", "tokens_used")
    op.drop_column("projects", "token_budget")
