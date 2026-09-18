"""Containment test: a hostile dump destroys only its own database. `M4-DUMP-SEC-091`.

`docs/data-sources.md` §3: "A malicious or broken dump wrecks its own sandbox
database. Askwell drops it and reports the failure." `test_sandbox.py` already
proves each individual role restriction in isolation (no superuser, no
`CREATE DATABASE`, no `COPY ... FROM/TO PROGRAM`, no large objects, no
`CONNECT` to the maintenance database) directly against the fixed roles.
What that does not prove is the end-to-end claim: that a real, hostile
`.sql` file — the actual shape `askwell.dump_import.import_dump` is handed —
fails safely through the whole path, is reported, and leaves nothing behind
except its own dropped database, while a database imported earlier and
Askwell's own database are both provably untouched.

Six fixtures under `tests/fixtures/hostile_dumps/`, one per attack shape named
in the ticket: privilege escalation, reading host files through `COPY FROM
PROGRAM`, connecting to another database on the instance, reaching the
network, exhausting disk, and running indefinitely. Each mechanism was
verified by hand against the real sandbox instance before being committed
here — see the fixture files' own comments for which privilege or cap stops
each one. This is containment, not a guarantee against every possible dump:
the fixture set is not exhaustive, and is extended whenever a new attack
shape is thought of (`docs/data-sources.md` §3, ticket's own "Known gaps").

The size and time caps that stop the last two fixtures are `M4-DUMP-VAL-089`,
already tested in isolation in `test_dump_import.py` against synthetic SQL
strings; what is new here is running the *fixture files* end to end alongside
the other four attack shapes, in one suite, with the containment assertions
this ticket asks for: the main database and other sandbox databases are
provably unaffected, and the egress proxy's refusal counter — which has no
route from the sandbox network to prove wrong — does not move.
"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import dump_import
from askwell.config import Settings
from askwell.dump_import import (
    DumpCapExceeded,
    DumpImportFailed,
    create_dump_source,
    import_dump,
)
from askwell.network import read_activity
from askwell.sandbox import READONLY_ROLE, drop_database, known_databases
from tests.conftest_sandbox import role_url

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hostile_dumps"

# One fixture per attack shape named in the ticket. `cap`/`limit` set the
# matching cap low before that import, the same way test_dump_import.py's own
# cap tests do — the fixture content alone does not trip a 5 GB/10 minute
# default in a test suite's own lifetime.
HOSTILE_FIXTURES: list[tuple[str, str | None, float | None]] = [
    ("privilege_escalation.sql", None, None),
    ("read_host_files_copy_program.sql", None, None),
    ("connect_to_another_database.sql", None, None),
    ("reach_network.sql", None, None),
    ("exhaust_disk.sql", "size", 1024),
    ("run_indefinitely.sql", "time", 0.3),
]

# Every table an imported dump's own content has no legitimate way to reach —
# `sources`, `audit_decisions` and `settings` are excluded because a normal,
# *successful* import writes to all three, so this is what "the main database
# is otherwise byte-identical" actually checks: nothing beyond that
# bookkeeping ever changes.
UNTOUCHED_TABLES = (
    "audit_interactions",
    "conversations",
    "memory",
    "clarifications",
    "documents",
    "messages",
    "schema_notes",
    "chunks",
    "fact_usage",
    "citations",
)

TRUNCATE_TABLES = "sources, audit_decisions, settings, " + ", ".join(UNTOUCHED_TABLES)


@pytest.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TRUNCATE_TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TRUNCATE_TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def containment_settings(sandbox_admin_url: str) -> Settings:
    """`redis_host`/`redis_port` are left at their defaults (`redis`, `6379`)
    deliberately — `scripts/dev.sh test-db` joins this run onto the stack's
    own `internal` network, the same one `redis` and `egress-proxy` sit on, so
    the real proxy counters are what this suite reads. A fake or unreachable
    Redis would make "the refusal counter did not move" untestable rather
    than testing it."""
    return Settings(
        database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password=os.environ["TEST_SANDBOX_OWNER_PASSWORD"],  # type: ignore[arg-type]
    )


async def _row_counts(session: AsyncSession, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        result = await session.execute(text(f"SELECT count(*) FROM {table}"))
        counts[table] = result.scalar_one()
    return counts


async def _make_source(factory: async_sessionmaker[AsyncSession], dump_path: Path) -> uuid.UUID:
    async with factory() as session:
        source_id = await create_dump_source(session, dump_path.stem, str(dump_path))
        await session.commit()
    return source_id


@pytest.mark.requires_db
@pytest.mark.parametrize("filename, cap, limit", HOSTILE_FIXTURES)
async def test_each_hostile_fixture_fails_safely_and_is_reported(
    filename: str,
    cap: str | None,
    limit: float | None,
    factory: async_sessionmaker[AsyncSession],
    containment_settings: Settings,
) -> None:
    fixture_path = FIXTURES_DIR / filename
    source_id = await _make_source(factory, fixture_path)

    if cap == "size":
        async with factory() as session:
            await dump_import.set_dump_size_cap_bytes(session, int(limit))  # type: ignore[arg-type]
            await session.commit()
    elif cap == "time":
        async with factory() as session:
            await dump_import.set_dump_time_cap_seconds(session, limit)  # type: ignore[arg-type]
            await session.commit()

    with pytest.raises(DumpImportFailed) as exc_info:
        await import_dump(factory, containment_settings, source_id, fixture_path)

    if cap is not None:
        assert isinstance(exc_info.value, DumpCapExceeded)
        assert exc_info.value.cap == cap

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        # Failed, reported why, and the sandbox database claim is gone — never
        # left half-loaded and reachable (`askwell.dump_import.import_dump`'s
        # own contract).
        assert row[0] == "attention"
        assert row[1] is None
        assert row[2]

        failed = (
            await session.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = 'dump_import_failed' "
                    "AND payload->>'source_id' = :id"
                ),
                {"id": str(source_id)},
            )
        ).first()
        assert failed is not None
        assert failed[0]["reason"]


@pytest.mark.requires_db
async def test_hostile_suite_leaves_the_rest_of_the_product_untouched(
    factory: async_sessionmaker[AsyncSession],
    containment_settings: Settings,
    sandbox_admin_url: str,
    tmp_path: Path,
) -> None:
    """The suite's own "Other scenarios": run every hostile fixture in
    sequence and confirm the product is fully functional afterwards — a
    source imported *before* the attack still answers, Askwell's own database
    carries nothing it should not, and the proxy's refusal counter, which has
    no route from the sandbox network to prove wrong, has not moved."""
    good_dump = tmp_path / "good_dump_for_containment.sql"
    good_dump.write_text(
        "CREATE TABLE widgets (id integer primary key, name text);\n"
        "INSERT INTO widgets VALUES (1, 'left-handed smoke shifter');\n"
    )
    try:
        good_source = await _make_source(factory, good_dump)
        tables = await import_dump(factory, containment_settings, good_source, good_dump)
        assert tables == ["widgets"]

        async with factory() as session:
            good_db = (
                await session.execute(
                    text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": good_source}
                )
            ).scalar_one()

        async with factory() as session:
            before = await _row_counts(session, UNTOUCHED_TABLES)

        activity_before = await read_activity(containment_settings)
        assert activity_before.available, activity_before.unavailable_reason

        known_before_attacks = set(known_databases(sandbox_admin_url))
        assert good_db in known_before_attacks

        for filename, cap, limit in HOSTILE_FIXTURES:
            fixture_path = FIXTURES_DIR / filename
            hostile_source = await _make_source(factory, fixture_path)
            if cap == "size":
                async with factory() as session:
                    await dump_import.set_dump_size_cap_bytes(session, int(limit))  # type: ignore[arg-type]
                    await session.commit()
            elif cap == "time":
                async with factory() as session:
                    await dump_import.set_dump_time_cap_seconds(session, limit)  # type: ignore[arg-type]
                    await session.commit()
            with pytest.raises(DumpImportFailed):
                await import_dump(factory, containment_settings, hostile_source, fixture_path)

        # Restore generous caps so the good source's own database, created
        # before the low caps below, is not what a later assertion trips on.
        async with factory() as session:
            await dump_import.set_dump_size_cap_bytes(
                session, dump_import.DEFAULT_DUMP_SIZE_CAP_BYTES
            )
            await dump_import.set_dump_time_cap_seconds(
                session, dump_import.DEFAULT_DUMP_TIME_CAP_SECONDS
            )
            await session.commit()

        # Only the good source's own database survives; every hostile one was
        # dropped, and nothing else appeared.
        assert set(known_databases(sandbox_admin_url)) == known_before_attacks

        # The good source still answers: its sandbox database still exists,
        # is still owned by a sealed owner role, and the readonly role still
        # reads exactly what was loaded.
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT status, sandbox_db FROM sources WHERE id = :id"),
                    {"id": good_source},
                )
            ).one()
            assert row[0] == "ready"
            assert row[1] == good_db

        readonly_dsn = role_url(
            sandbox_admin_url,
            role=READONLY_ROLE,
            password_env="TEST_SANDBOX_READONLY_PASSWORD",
            database=good_db,
        )
        with psycopg.connect(readonly_dsn, autocommit=True) as conn:
            assert conn.execute("SELECT id, name FROM widgets").fetchall() == [
                (1, "left-handed smoke shifter")
            ]

        # Askwell's own database: nothing beyond the bookkeeping every import
        # (successful or not) already writes to sources/audit_decisions has
        # changed.
        async with factory() as session:
            after = await _row_counts(session, UNTOUCHED_TABLES)
        assert after == before

        activity_after = await read_activity(containment_settings)
        assert activity_after.available, activity_after.unavailable_reason
        assert activity_after.refused == activity_before.refused
    finally:
        async with factory() as session:
            remaining = set(known_databases(sandbox_admin_url))
            for name in remaining:
                await drop_database(session, sandbox_admin_url, name, reason="test_cleanup")
            await session.commit()
