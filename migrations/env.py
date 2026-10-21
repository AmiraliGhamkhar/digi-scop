from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401 - registers mapped tables
from app.database import Base, ensure_sqlite_parent

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A command may set sqlalchemy.url programmatically (tests do this). The explicit
# environment variable wins for normal CLI/deployment usage.
if database_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Keep Alembic consistent with app.database.create_database_engine: a file-backed
# SQLite target may live in a directory that does not exist yet on a fresh clone.
ensure_sqlite_parent(config.get_main_option("sqlalchemy.url"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA busy_timeout=30000")
            # SQLAlchemy 2 autobegins for PRAGMA statements. End that transaction
            # before Alembic opens its own migration transaction, otherwise the
            # alembic_version insert can be rolled back while SQLite keeps DDL.
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
        if connection.dialect.name == "sqlite":
            # A migration that rebuilds a table switches foreign key
            # enforcement off while it works. The connection must not keep it
            # off once the migrations are done.
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
