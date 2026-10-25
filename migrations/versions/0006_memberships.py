"""Local users, workspace roles and hashed personal API tokens.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"]
    )
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_api_tokens_workspace_id", "api_tokens", ["workspace_id"])
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])


def downgrade():
    op.drop_index("ix_api_tokens_user_id", "api_tokens")
    op.drop_index("ix_api_tokens_workspace_id", "api_tokens")
    op.drop_table("api_tokens")
    op.drop_index("ix_workspace_memberships_user_id", "workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", "workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_table("users")
