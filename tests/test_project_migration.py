from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_request_budget_migration_backfills_existing_projects(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.0007_project_request_budget")
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    try:
        with engine.begin() as db:
            db.execute(
                text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, token_budget INTEGER)")
            )
            db.execute(text("INSERT INTO projects VALUES ('legacy', 123000)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(db)))
            migration.upgrade()
            row = db.execute(
                text("SELECT token_budget, request_token_budget FROM projects WHERE id = 'legacy'")
            ).one()
            assert row == (123000, 123000)
            migration.downgrade()
            columns = db.execute(text("PRAGMA table_info(projects)")).all()
            assert "request_token_budget" not in {column[1] for column in columns}
    finally:
        engine.dispose()
