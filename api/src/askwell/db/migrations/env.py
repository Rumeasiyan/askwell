"""Alembic environment.

Runs synchronously against `postgresql://` rather than through the async
driver. Alembic's async support exists, but a migration is a one-shot script
where concurrency buys nothing and the async path makes every failure a longer
traceback for no benefit.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from askwell.config import load_settings
from askwell.db import models  # noqa: F401  - imported for its side effect: table registration
from askwell.db.base import Base
from askwell.db.engine import driver_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The advisory lock every online migration run holds. See run_migrations_online.
_LOCK_KEY = "askwell_migrate"


def _url() -> str:
    """The connection string, from configuration and never from alembic.ini.

    A caller may override it through Alembic's own config — which is how the
    test harness migrates a disposable database without setting environment
    variables for a process it does not own.
    """
    override = config.get_main_option("sqlalchemy.url", None)
    if override:
        return driver_url(override)
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
        # One migration at a time, whoever started it (#813). The installer runs
        # `migrate` in the foreground while the desktop shell's supervisor, a
        # session unit or a person typing `up` can start another, and Alembic
        # takes no lock of its own: two runs would both see the old revision and
        # one would fail on a duplicate object. A session-level lock rather than
        # a transaction one, so it holds across any commit a migration makes; the
        # second run waits here, then reads the version table the first one
        # committed and finds nothing to do. Released on disconnect if a run dies.
        connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY})
        # The lock statement autobegan a transaction. Commit it, or Alembic sees a
        # transaction already open and never commits the migrations itself.
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
            )
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
