"""Verify Alembic up/down on a disposable local PostgreSQL database."""

import os
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from apps.api.app.core.config import get_settings


def main():
    source = make_url(get_settings().database_url)
    if source.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Fresh migration test requires local PostgreSQL")
    database = f"agentforge_migration_test_{uuid4().hex[:12]}"
    maintenance = {
        "host": source.host,
        "port": source.port or 5432,
        "user": source.username,
        "password": source.password,
        "dbname": "postgres",
        "autocommit": True,
        "connect_timeout": 5,
    }
    env = os.environ.copy()
    env["AGENTFORGE_DATABASE_URL"] = source.set(database=database).render_as_string(
        hide_password=False
    )
    with psycopg.connect(**maintenance) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        for args in (("upgrade", "head"), ("check",), ("downgrade", "base")):
            subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                env=env,
                check=True,
                timeout=120,
            )
        print("Fresh PostgreSQL migration upgrade/check/downgrade passed")
    finally:
        if not database.startswith("agentforge_migration_test_"):
            raise RuntimeError("Refusing to drop unexpected database")
        with psycopg.connect(**maintenance) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


if __name__ == "__main__":
    main()
