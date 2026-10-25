from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata
LANGGRAPH_TABLES = {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"}


def include_name(name, type_, parent_names):
    return not (type_ == "table" and name in LANGGRAPH_TABLES)


def run_migrations_offline():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_name=include_name
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
