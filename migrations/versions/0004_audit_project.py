"""Scope audit events to their projects for the activity timeline.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("project_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_audit_logs_project_id", "audit_logs", "projects", ["project_id"], ["id"]
    )
    op.create_index("ix_audit_logs_project_id", "audit_logs", ["project_id"])
    op.execute(
        "UPDATE audit_logs a SET project_id = p.id FROM projects p WHERE a.resource_id = p.id"
    )
    op.execute(
        "UPDATE audit_logs a SET project_id = t.project_id FROM tasks t WHERE a.resource_id = t.id"
    )
    op.execute(
        "UPDATE audit_logs a SET project_id = r.project_id FROM workflow_runs r WHERE a.resource_id = r.id"
    )
    op.execute(
        "UPDATE audit_logs a SET project_id = q.project_id FROM project_requirements q WHERE a.resource_id = q.id"
    )
    op.execute(
        "UPDATE audit_logs a SET project_id = r.project_id "
        "FROM approvals p JOIN workflow_runs r ON r.id = p.run_id "
        "WHERE a.resource_id = p.id"
    )


def downgrade():
    op.drop_index("ix_audit_logs_project_id", "audit_logs")
    op.drop_constraint("fk_audit_logs_project_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "project_id")
