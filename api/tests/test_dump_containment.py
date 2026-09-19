"""Containment test: a hostile dump destroys only its own database. `M4-DUMP-SEC-091`.

C3's claim is structural, not conventional — a separate Postgres instance, one
database per source, a role that cannot create a database, a role or a
superuser (`askwell.sandbox`, `deploy/sandbox/10-roles.sh`). This module is
what turns that claim from something argued into something demonstrated: six
fixture dumps, each attempting one of the attack shapes the ticket names, run
through the real `import_dump` end to end against the real sandbox instance —
not the role checked directly the way `test_sandbox.py` already does, but a
dump file that tries the attack the way an actual hostile export would.

Every fixture is expected to **fail loudly**: `import_dump` raises, the
source lands in `attention` with a reason, `audit_decisions` records
`dump_import_failed`, and the sandbox database it was loading into is gone.
Two more things are checked around every attempt, not just after it —
Askwell's own database (a canary set of tables the dump import path never
touches) and a second, already-loaded sandbox database are hashed before the
whole suite and after every single fixture, and the hash must never move.
Row counts are not enough here: an attack that overwrites a row in place
without changing the count would pass a count check and still be a breach —
`_content_hash` hashes every row's own text, not how many there are.

**The network leg of the acceptance criterion — issue #389.** "No network
request escapes, confirmed against the proxy's refusal counter" needs a real
egress proxy and the Redis it reports through, neither of which
`scripts/dev.sh test-db` brings up (only Postgres; see `test_network.py`'s
own `FakeRedis` for why that surface is unit-tested against a fake instead).
Faking them here would only prove a mock was read correctly, not that the
sandbox is walled off — the exact thing the criterion exists to demonstrate.
`test_sandbox_network_has_no_route_to_the_proxy_or_the_internet` below is
issue #389's recommended option 3 instead: a static assertion, straight out
of `compose.yaml`, that the `sandbox` network is `internal: true` and joined
by nothing but `api`, `worker` and `sandbox` itself — not `egress-proxy`, the
only service with a route off the machine. It cannot see a proxy's counter
move, but it catches the regression that would make the counter check matter
in the first place: a future change granting the sandbox network a route out.
Confirming the counter itself never moves during a real hostile import stays
the `docs/build-plan.md` cold-start manual walkthrough named in this ticket's
own Testing Notes.

The fixture set is not exhaustive, and is extended whenever a new attack
shape is thought of — this is containment, not a guarantee against every
possible dump.
"""

import os
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import dump_import
from askwell.config import Settings
from askwell.dump_import import DumpCapExceeded, DumpImportFailed, create_dump_source, import_dump
from askwell.sandbox import known_databases, readonly_url

# Not a module-level `pytestmark`: only the fixtures/tests that touch the real
# sandbox instance need `requires_db` (applied to each below). The topology
# assertion at the bottom of this module needs nothing but `compose.yaml` on
# disk and must run in every `scripts/dev.sh test`, with no network at all —
# the whole point of it existing per issue #389.
requires_db = pytest.mark.requires_db

TABLES = "sources, audit_decisions, settings, schema_notes, documents, chunks"

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "compose.yaml"


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def dump_settings(sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password=os.environ["TEST_SANDBOX_OWNER_PASSWORD"],  # type: ignore[arg-type]
        sandbox_readonly_password=os.environ["TEST_SANDBOX_READONLY_PASSWORD"],  # type: ignore[arg-type]
    )


async def _content_hash(session: AsyncSession, table: str) -> str:
    """Every row of `table`, hashed as its own text — not a row count.

    An `UPDATE` in place leaves the count untouched; hashing each row's own
    `::text` and aggregating in a stable order catches it. `coalesce` so an
    empty table hashes to a real, comparable value rather than `NULL`.
    """
    result = await session.execute(
        text(f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {table} t")
    )
    return str(result.scalar_one())


async def _main_db_fingerprint(session: AsyncSession) -> tuple[str, ...]:
    """A canary the dump-import path never touches: `documents` and `chunks`.

    Not `sources`/`audit_decisions` — those change on every import attempt,
    hostile or not, because recording that an attempt happened is the
    machinery working correctly. What has to stay byte-identical is material
    that has nothing to do with importing a dump at all.
    """
    return (
        await _content_hash(session, "documents"),
        await _content_hash(session, "chunks"),
    )


def _sandbox_fingerprint(dsn: str) -> tuple[tuple[str, str], ...]:
    """Every base table in a loaded sandbox database, hashed by name."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
        fingerprint = []
        for (name,) in tables:
            row = conn.execute(
                sql.SQL(
                    "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {} t"
                ).format(sql.Identifier(name))
            ).fetchone()
            assert row is not None
            fingerprint.append((str(name), str(row[0])))
    return tuple(fingerprint)


async def _make_dump_source(
    factory: async_sessionmaker[AsyncSession], dump_path: Path, name: str
) -> uuid.UUID:
    async with factory() as session:
        source_id = await create_dump_source(session, name, str(dump_path))
        await session.commit()
    return source_id


async def _seed_canary(factory: async_sessionmaker[AsyncSession]) -> None:
    """ "One good dump already imported and some documents indexed" —
    the ticket's own cold-start walkthrough state, in miniature. Only the
    `documents`/`chunks` half matters to this module; the good dump is
    loaded separately, into the real sandbox, by the caller."""
    async with factory() as session:
        source_id = (
            await session.execute(
                text(
                    "INSERT INTO sources (kind, name, status) "
                    "VALUES ('file', 'a colleague''s notes', 'ready') RETURNING id"
                )
            )
        ).scalar_one()
        document_id = (
            await session.execute(
                text(
                    "INSERT INTO documents (source_id, filename, path, sha256, status) "
                    "VALUES (:source_id, 'notes.txt', '/notes.txt', "
                    "'deadbeef00000000000000000000000000000000000000000000000000ff', 'ready') "
                    "RETURNING id"
                ),
                {"source_id": source_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO chunks (document_id, ordinal, content) "
                "VALUES (:document_id, 0, 'the quarterly numbers are in the appendix')"
            ),
            {"document_id": document_id},
        )
        await session.commit()


async def _load_good_dump(
    factory: async_sessionmaker[AsyncSession], dump_settings: Settings, tmp_path: Path
) -> tuple[uuid.UUID, str]:
    """The "one good dump already imported" half of the walkthrough state.

    Returns the source id and the sandbox database name so the caller can
    fingerprint it and, at the end, tear it down.
    """
    dump_path = tmp_path / "good.sql"
    dump_path.write_text(
        "CREATE TABLE ledger (id integer primary key, note text);\n"
        "INSERT INTO ledger VALUES (1, 'left-handed smoke shifter');\n"
    )
    source_id = await _make_dump_source(factory, dump_path, "a good export")
    await import_dump(factory, dump_settings, source_id, dump_path)

    async with factory() as session:
        database = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).scalar_one()
    return source_id, str(database)


# --- the six hostile attack shapes -------------------------------------------

HOSTILE_FIXTURES = {
    "privilege_escalation": (
        "CREATE ROLE askwell_hostile_escalation LOGIN SUPERUSER PASSWORD 'x';\n",
        None,
    ),
    "read_host_file_via_program": (
        "CREATE TABLE stolen (line text);\nCOPY stolen FROM PROGRAM 'cat /etc/passwd';\n",
        None,
    ),
    "connect_to_another_database": (
        "CREATE EXTENSION IF NOT EXISTS dblink;\n"
        "SELECT dblink_connect('host=127.0.0.1 dbname=postgres');\n",
        None,
    ),
    "reach_the_network": (
        "CREATE TABLE net_probe (line text);\n"
        "COPY net_probe FROM PROGRAM "
        "'curl -s http://169.254.169.254/latest/meta-data/ -o /dev/null; echo done';\n",
        None,
    ),
    "exhaust_disk": (
        "CREATE TABLE bloat (id integer);\n",
        {"size_cap_bytes": 1024},
    ),
    "run_indefinitely": (
        "SELECT pg_sleep(30);\n",
        {"time_cap_seconds": 0.3},
    ),
}


@requires_db
@pytest.mark.parametrize("fixture_name", sorted(HOSTILE_FIXTURES))
async def test_hostile_dump_fails_safely_and_leaves_no_trace(
    fixture_name: str,
    factory: async_sessionmaker[AsyncSession],
    dump_settings: Settings,
    sandbox_admin_url: str,
    tmp_path: Path,
) -> None:
    sql_content, caps = HOSTILE_FIXTURES[fixture_name]

    await _seed_canary(factory)
    good_source_id, good_database = await _load_good_dump(factory, dump_settings, tmp_path)
    good_dsn = readonly_url(
        sandbox_admin_url, good_database, os.environ["TEST_SANDBOX_READONLY_PASSWORD"]
    )

    async with factory() as session:
        main_before = await _main_db_fingerprint(session)
    good_before = _sandbox_fingerprint(good_dsn)

    if caps:
        async with factory() as session:
            if "size_cap_bytes" in caps:
                await dump_import.set_dump_size_cap_bytes(session, caps["size_cap_bytes"])
            if "time_cap_seconds" in caps:
                await dump_import.set_dump_time_cap_seconds(session, caps["time_cap_seconds"])
            await session.commit()

    dump_path = tmp_path / f"{fixture_name}.sql"
    dump_path.write_text(sql_content)
    hostile_source_id = await _make_dump_source(factory, dump_path, fixture_name)

    with pytest.raises(DumpImportFailed) as exc_info:
        await import_dump(factory, dump_settings, hostile_source_id, dump_path)

    # Reported: the source carries why, not a bare "failed".
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": hostile_source_id},
            )
        ).one()
        assert row[0] == "attention"
        assert row[1] is None
        assert row[2]
        assert row[2] == str(exc_info.value)

        failed = (
            await session.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = 'dump_import_failed' "
                    "AND payload->>'source_id' = :id"
                ),
                {"id": str(hostile_source_id)},
            )
        ).first()
        assert failed is not None
        assert failed[0]["reason"] == row[2]
        if isinstance(exc_info.value, DumpCapExceeded):
            assert failed[0]["cap"] == exc_info.value.cap

    # Leaves nothing behind except a dropped sandbox database: `sources` no
    # longer claims one for this attempt, and the instance's own database
    # list (checked below) confirms nothing new survives.
    async with factory() as session:
        remaining = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": hostile_source_id}
            )
        ).scalar_one()
    assert remaining is None

    live = set(known_databases(sandbox_admin_url))
    assert live == {good_database}

    # Askwell's own database: byte-identical.
    async with factory() as session:
        main_after = await _main_db_fingerprint(session)
    assert main_after == main_before

    # The other, already-loaded sandbox database: byte-identical.
    good_after = _sandbox_fingerprint(good_dsn)
    assert good_after == good_before

    # The good source is still exactly as it was — the product stays usable.
    async with factory() as session:
        good_row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"),
                {"id": good_source_id},
            )
        ).one()
        assert good_row[0] == "ready"
        assert good_row[1] == good_database

    async with factory() as session:
        await dump_import.sandbox.drop_database(session, sandbox_admin_url, good_database)
        await session.commit()


@requires_db
async def test_the_whole_hostile_suite_in_sequence_leaves_the_product_functional(
    factory: async_sessionmaker[AsyncSession],
    dump_settings: Settings,
    sandbox_admin_url: str,
    tmp_path: Path,
) -> None:
    """`AGENTS.md`'s own "run it" rule, for the suite as a whole: import every
    hostile fixture back to back against the same good state and confirm
    what is left afterwards is exactly the good source and nothing else —
    not one fixture in isolation, but the sequence a real session would run
    through the normal add-source flow."""
    await _seed_canary(factory)
    good_source_id, good_database = await _load_good_dump(factory, dump_settings, tmp_path)
    good_dsn = readonly_url(
        sandbox_admin_url, good_database, os.environ["TEST_SANDBOX_READONLY_PASSWORD"]
    )

    async with factory() as session:
        main_before = await _main_db_fingerprint(session)
    good_before = _sandbox_fingerprint(good_dsn)

    for fixture_name in sorted(HOSTILE_FIXTURES):
        sql_content, caps = HOSTILE_FIXTURES[fixture_name]
        if caps:
            async with factory() as session:
                if "size_cap_bytes" in caps:
                    await dump_import.set_dump_size_cap_bytes(session, caps["size_cap_bytes"])
                if "time_cap_seconds" in caps:
                    await dump_import.set_dump_time_cap_seconds(session, caps["time_cap_seconds"])
                await session.commit()
        else:
            async with factory() as session:
                await dump_import.set_dump_size_cap_bytes(
                    session, dump_import.DEFAULT_DUMP_SIZE_CAP_BYTES
                )
                await dump_import.set_dump_time_cap_seconds(
                    session, dump_import.DEFAULT_DUMP_TIME_CAP_SECONDS
                )
                await session.commit()

        dump_path = tmp_path / f"{fixture_name}.sql"
        dump_path.write_text(sql_content)
        hostile_source_id = await _make_dump_source(factory, dump_path, fixture_name)

        with pytest.raises(DumpImportFailed):
            await import_dump(factory, dump_settings, hostile_source_id, dump_path)

    live = set(known_databases(sandbox_admin_url))
    assert live == {good_database}

    async with factory() as session:
        main_after = await _main_db_fingerprint(session)
        good_row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"),
                {"id": good_source_id},
            )
        ).one()
    assert main_after == main_before
    assert good_row == ("ready", good_database)
    assert _sandbox_fingerprint(good_dsn) == good_before

    async with factory() as session:
        await dump_import.sandbox.drop_database(session, sandbox_admin_url, good_database)
        await session.commit()


# --- issue #389: the network leg, as a static topology assertion ------------


def _compose_chunks(block: str) -> dict[str, str]:
    """Split a `compose.yaml` top-level section into per-entry text, keyed by
    the 2-space-indented name each entry starts with. Regex over the literal
    file rather than a YAML parser — no YAML library is a dependency of this
    project (see `test_env_example.py`, which parses the same file the same
    way), and this only ever needs to answer "what does entry X list.\""""
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([a-zA-Z][\w-]*):", block, re.M)]
    chunks = {}
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(block)
        chunks[name] = block[start:end]
    return chunks


def test_sandbox_network_has_no_route_to_the_proxy_or_the_internet() -> None:
    """Issue #389, option 3: the topology assertion the network-counter check
    cannot do without a running proxy and Redis (`scripts/dev.sh test-db`
    brings up only Postgres). `compose.yaml`'s own comment states the
    guarantee this checks structurally: "sandbox... is not on internal and
    not on egress... no path to Askwell's own database and no path to the
    proxy, let alone the internet." A regression that granted the sandbox
    network a route out — the only way the counter check would ever have
    something to catch — shows up here first, deterministically, in CI,
    without needing the real stack up."""
    raw = COMPOSE.read_text(encoding="utf-8")
    services_block = re.search(r"^services:\n(.*?)^networks:\n", raw, re.S | re.M)
    networks_block = re.search(r"^networks:\n(.*?)^volumes:\n", raw, re.S | re.M)
    assert services_block is not None
    assert networks_block is not None

    services = _compose_chunks(services_block.group(1))
    networks = _compose_chunks(networks_block.group(1))

    assert "internal: true" in networks["sandbox"], (
        "the sandbox network must be internal: true — an absence of routing, "
        "not a rule that could be relaxed"
    )

    def joined_networks(service: str) -> set[str]:
        match = re.search(r"networks:\s*\[([^\]]*)\]", services[service])
        return {n.strip() for n in match.group(1).split(",")} if match else set()

    sandbox_members = {name for name in services if "sandbox" in joined_networks(name)}
    assert sandbox_members == {"api", "worker", "sandbox"}, (
        f"only api, worker and the sandbox service itself may join the sandbox "
        f"network; found {sorted(sandbox_members)}. Anything else — especially "
        f"egress-proxy, the only service with a route off this machine — is C3 "
        f"broken at the topology level."
    )
