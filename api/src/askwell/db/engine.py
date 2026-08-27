"""The async engine and session factory.

The connection string is stored in plain `postgresql://` form because that is
what every other tool on the machine understands — `psql`, a user pasting it
into their editor. The driver is substituted here rather than being what the
user has to type.

That driver is psycopg 3 for both the async application and Alembic's
synchronous path. asyncpg is faster on paper, but it cannot do the sync half,
so the alternative was two drivers with two sets of type adapters and two
failure modes on a machine where nobody is watching. On one user's laptop the
difference in throughput is unmeasurable and the difference in things that can
break is not.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from askwell.config import Settings

DRIVER = "postgresql+psycopg://"
SYNC_PREFIX = "postgresql://"


def driver_url(url: str) -> str:
    """Rewrite a plain postgresql:// URL to name the driver explicitly.

    Without this SQLAlchemy picks psycopg2, which is not installed — and says
    so with a bare `ModuleNotFoundError` that mentions neither Askwell nor the
    URL.
    """
    if url.startswith(DRIVER):
        return url
    if url.startswith(SYNC_PREFIX):
        return DRIVER + url[len(SYNC_PREFIX) :]
    raise ValueError(
        f"ASKWELL_DATABASE_URL must start with {SYNC_PREFIX!r}, got "
        f"{url.split('://')[0] + '://'!r}. Askwell stores the plain form and "
        f"substitutes the async driver itself."
    )


def build_engine(settings: Settings) -> AsyncEngine:
    """One engine per process."""
    return create_async_engine(
        driver_url(settings.database_url.get_secret_value()),
        # One user, one machine. A large pool here competes with the model for
        # memory and buys nothing — there is no concurrency to absorb.
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A session that commits on success and rolls back on anything else."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
