"""Seeds the SQL fixture: a sandbox database with a realistic schema, loaded
the same way a real dump import lands one (`askwell.sandbox.create_database`,
C3), registered as a `ready` dump source, and introspected for schema notes
through the real path (`askwell.schema_introspect`) rather than hand-inserted
rows. `M4-EVAL-TEST-112`.

Mirrors `eval.grounded.seed_corpus`'s own shape: idempotent (a second run
against a database that already has this fixture reuses it rather than
creating a second sandbox database), and every write goes through the
product's own functions so a result here says something about the real
generate -> validate -> execute path, not a shortcut around it.

`schema.sql`/`seed.sql` are trusted content this repository controls, not an
untrusted dump -- loaded directly with `psql` (mirroring
`askwell.dump_import`'s own use of it) rather than through
`askwell.dump_import.import_dump`, which exists to police a file nobody here
wrote.
"""

import asyncio
import subprocess
import uuid
from pathlib import Path

from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.memory import write_schema_note
from askwell.sandbox import create_database, generate_name, owner_url, readonly_url
from askwell.schema_introspect import introspect_blocking, write_schema_inventory
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sql"

SOURCE_NAME = "eval-sql-fixture"

# The one column that is genuinely unguessable from its type alone --
# `schema.sql`'s own docstring names why. Written as a `user`-origin note,
# the same shape `askwell.review.answer_clarification` would produce for a
# clarification answer, per `eval.memory_apply`'s identical precedent for
# memory facts.
_UNGUESSABLE_NOTE = (
    "orders",
    "stat_cd",
    (
        "orders.stat_cd is a single-letter order status code: "
        "'P' = placed/pending, 'S' = shipped, 'C' = cancelled, 'R' = returned."
    ),
)


class SqlFixtureError(RuntimeError):
    """The fixture could not be loaded -- a harness failure, never a score."""


def _load_fixture_sql_blocking(dsn: str, path: Path) -> None:
    result = subprocess.run(
        [
            "psql",
            dsn,
            "--set",
            "ON_ERROR_STOP=1",
            "--no-psqlrc",
            "--quiet",
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SqlFixtureError(
            f"loading {path.name} into the sandbox failed: {result.stderr}"
        )


async def _find_existing(session: AsyncSession) -> tuple[uuid.UUID, str] | None:
    row = (
        await session.execute(
            sql_text(
                "SELECT id, sandbox_db FROM sources "
                "WHERE name = :name AND status = 'ready' AND sandbox_db IS NOT NULL"
            ),
            {"name": SOURCE_NAME},
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


async def seed_sql_fixture(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[uuid.UUID, str]:
    """Returns `(source_id, sandbox_database_name)`. Safe to call against a
    database that already has this fixture -- returns the existing source
    rather than building a second one."""
    async with session_scope(factory) as db:
        existing = await _find_existing(db)
    if existing is not None:
        return existing

    admin_url = settings.sandbox_database_url.get_secret_value()
    owner_password = settings.sandbox_owner_password.get_secret_value()
    readonly_password = settings.sandbox_readonly_password.get_secret_value()
    database = generate_name()

    async with session_scope(factory) as db:
        await create_database(db, admin_url, database)

    owner_dsn = owner_url(admin_url, database, owner_password)
    _load_fixture_sql_blocking(owner_dsn, FIXTURES_DIR / "schema.sql")
    _load_fixture_sql_blocking(owner_dsn, FIXTURES_DIR / "seed.sql")

    source_id = uuid.uuid4()
    async with session_scope(factory) as db:
        await db.execute(
            sql_text(
                "INSERT INTO sources (id, kind, name, sandbox_db, status) "
                "VALUES (:id, 'dump', :name, :database, 'ready')"
            ),
            {"id": source_id, "name": SOURCE_NAME, "database": database},
        )

        readonly_dsn = readonly_url(admin_url, database, readonly_password)
        inventory = await asyncio.to_thread(
            introspect_blocking, "postgresql", readonly_dsn
        )
        await write_schema_inventory(db, source_id, inventory)

        table_name, column_name, description = _UNGUESSABLE_NOTE
        await write_schema_note(
            db,
            source_id=source_id,
            table_name=table_name,
            column_name=column_name,
            description=description,
            origin="user",
        )

    return source_id, database
