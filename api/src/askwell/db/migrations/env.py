"""Alembic environment.

Runs synchronously against `postgresql://` rather than through the async
driver. Alembic's async support exists, but a migration is a one-shot script
where concurrency buys nothing and the async path makes every failure a longer
traceback for no benefit.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from askwell.config import load_settings
from askwell.db import models  # noqa: F401  - imported for its side effect: table registration
from askwell.db.base import Base
from askwell.db.engine import driver_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    """The connection string, from configuration and never from alembic.ini."""
    return driver_url(load_settings().database_url.get_secret_value())


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
