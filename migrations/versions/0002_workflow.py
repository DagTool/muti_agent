"""Requirements, runs, approvals and artifacts.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_project_requirements_project_id", "project_requirements", ["project_id"])
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "requirement_id",
            sa.String(36),
            sa.ForeignKey("project_requirements.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "request_key"),
    )
    op.create_index("ix_workflow_runs_project_id", "workflow_runs", ["project_id"])
    op.add_column("tasks", sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id")))
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("reviewed_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "action"),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id")),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id")),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])


def downgrade():
    op.drop_index("ix_artifacts_run_id", "artifacts")
    op.drop_index("ix_artifacts_project_id", "artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_approvals_status", "approvals")
    op.drop_index("ix_approvals_run_id", "approvals")
    op.drop_table("approvals")
    op.drop_index("ix_tasks_run_id", "tasks")
    op.drop_column("tasks", "run_id")
    op.drop_index("ix_workflow_runs_project_id", "workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_project_requirements_project_id", "project_requirements")
    op.drop_table("project_requirements")
