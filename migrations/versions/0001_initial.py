"""Initial local development schema.

Revision ID: 0001
Revises:
"""

from alembic import op
from sqlalchemy import MetaData, Table

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Initial baseline; later schema changes should use explicit Alembic operations.
    Base.metadata.create_all(bind=op.get_bind())
    workspace = Table("workspaces", MetaData(), autoload_with=op.get_bind())
    op.bulk_insert(workspace, [{"id": get_settings().workspace_id, "name": "Local development"}])


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
