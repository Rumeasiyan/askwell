"""`validate_query` against a real Postgres. `M4-SQL-VAL-104`/`M4-SQL-OBS-108`.

What only a real database can prove: every outcome — accepted or rejected —
is actually recorded to `audit_interactions` with its full field set
(`M4-SQL-OBS-108`'s own Audit Requirement), that the hash chain still
verifies, and that neither a very long query nor one containing
credential-looking text is truncated or redacted before it lands. Every
hostile SQL shape itself is proven without a database in
`test_sql_validate.py` — `_validate_sync` is pure.
"""

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.config import Settings
from askwell.sql import validate as sql_validate
from askwell.sql.observability import sql_rejection_rate
from askwell.sql.validate import RejectionReason, ValidationResult, validate_query

pytestmark = pytest.mark.requires_db

_TABLES = "audit_decisions, audit_interactions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        sql_validation_timeout_seconds=2.0,
    )


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


async def _interaction_rows(session: AsyncSession) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            text("SELECT payload FROM audit_interactions WHERE kind = 'sql_query' ORDER BY id")
        )
    ).all()
    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


async def test_rejection_is_recorded_with_its_reason(
    session: AsyncSession, settings: Settings
) -> None:
    result = await validate_query(
        session,
        settings,
        engine="postgresql",
        query="SELECT id FROM orders; DELETE FROM orders",
    )
    await session.commit()

    assert not result.accepted
    assert result.reason == RejectionReason.MULTIPLE_STATEMENTS

    rows = await _interaction_rows(session)
    assert len(rows) == 1
    assert rows[0]["validated"] is False
    assert rows[0]["rejection_reason"] == RejectionReason.MULTIPLE_STATEMENTS.value
    assert rows[0]["query"] == "SELECT id FROM orders; DELETE FROM orders"
    assert rows[0]["engine"] == "postgresql"
    assert rows[0]["detail"]
    # Not yet wired to limit injection or execution — recorded as far as
    # validation itself got, honestly, not invented.
    assert rows[0]["limit_injected"] is None
    assert rows[0]["rows"] is None
    assert rows[0]["duration_ms"] is None


async def test_every_named_rejection_reason_is_recorded(
    session: AsyncSession, settings: Settings
) -> None:
    hostile_queries = {
        RejectionReason.EMPTY: "",
        RejectionReason.MULTIPLE_STATEMENTS: "SELECT 1; SELECT 2",
        RejectionReason.NOT_A_SINGLE_READ: "DELETE FROM orders",
        RejectionReason.WRITE_DETECTED: "SELECT * INTO t FROM orders",
        RejectionReason.LOCKING_READ: "SELECT * FROM orders FOR UPDATE",
        RejectionReason.SIDE_EFFECT_FUNCTION: "SELECT pg_terminate_backend(123)",
        RejectionReason.UNPARSEABLE: "SELECT * FROM WHERE",
    }
    for reason, query in hostile_queries.items():
        result = await validate_query(session, settings, engine="postgresql", query=query)
        assert result.reason == reason, f"{query!r} -> {result.reason}, expected {reason}"
    await session.commit()

    rows = await _interaction_rows(session)
    assert len(rows) == len(hostile_queries)
    recorded_reasons = {row["rejection_reason"] for row in rows}
    assert recorded_reasons == {reason.value for reason in hostile_queries}
    assert all(row["validated"] is False for row in rows)


async def test_accepted_query_is_also_recorded(session: AsyncSession, settings: Settings) -> None:
    source_id = uuid.uuid4()
    result = await validate_query(
        session, settings, engine="postgresql", query="SELECT id FROM orders", source_id=source_id
    )
    await session.commit()

    assert result.accepted

    rows = await _interaction_rows(session)
    assert len(rows) == 1
    assert rows[0]["validated"] is True
    assert rows[0]["rejection_reason"] is None
    assert rows[0]["source_id"] == str(source_id)


async def test_timeout_is_recorded_when_parsing_exceeds_the_configured_wait(
    session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    def _slow_validate(engine: object, query: str) -> ValidationResult:
        time.sleep(0.2)
        return ValidationResult(accepted=True, reason=None, detail=None)

    monkeypatch.setattr(sql_validate, "_validate_sync", _slow_validate)
    fast_settings = settings.model_copy(update={"sql_validation_timeout_seconds": 0.01})

    result = await validate_query(session, fast_settings, engine="postgresql", query="SELECT 1")
    await session.commit()

    assert not result.accepted
    assert result.reason == RejectionReason.TIMEOUT

    rows = await _interaction_rows(session)
    assert len(rows) == 1
    assert rows[0]["rejection_reason"] == RejectionReason.TIMEOUT.value


async def test_a_very_long_query_is_stored_in_full(
    session: AsyncSession, settings: Settings
) -> None:
    # Truncating the thing a maintainer is trying to diagnose defeats the
    # purpose (the ticket's own edge case) — a long `IN (...)` list is a
    # realistic shape for a generated query to take.
    long_list = ", ".join(str(n) for n in range(20_000))
    query = f"SELECT id FROM orders WHERE id IN ({long_list})"
    result = await validate_query(session, settings, engine="postgresql", query=query)
    await session.commit()

    assert result.accepted
    rows = await _interaction_rows(session)
    assert len(rows) == 1
    assert rows[0]["query"] == query
    assert len(str(rows[0]["query"])) == len(query)


async def test_credential_looking_literal_is_stored_verbatim_not_redacted(
    session: AsyncSession, settings: Settings
) -> None:
    # The query text is stored exactly as generated — never redacted or
    # scrubbed, per the ticket's own edge case. This is not the same claim
    # as "a real credential can appear here": generation only ever draws on
    # schema notes and memory (`askwell.agent.sql_generate`), which never
    # contain a connection's own stored credential, so a literal that merely
    # *looks* like one in a `WHERE` clause is user-visible generated SQL,
    # not a secret leaking through this path.
    query = "SELECT * FROM api_tokens WHERE token = 'sk-ABC123XYZ-not-a-real-secret'"
    result = await validate_query(session, settings, engine="postgresql", query=query)
    await session.commit()

    assert result.accepted
    rows = await _interaction_rows(session)
    assert rows[0]["query"] == query
    assert "sk-ABC123XYZ-not-a-real-secret" in str(rows[0]["query"])


async def test_rejection_rate_over_a_window_reflects_recorded_outcomes(
    session: AsyncSession, settings: Settings
) -> None:
    accepted = "SELECT id FROM orders"
    rejected = "DELETE FROM orders"
    for query in (accepted, accepted, rejected, accepted, rejected):
        await validate_query(session, settings, engine="postgresql", query=query)
    await session.commit()

    rate = await sql_rejection_rate(session)
    assert rate.covered == 5
    assert rate.rejected == 2
    assert rate.rate == 2 / 5


async def test_rejection_rate_is_none_with_nothing_validated_yet(session: AsyncSession) -> None:
    rate = await sql_rejection_rate(session)
    assert rate.covered == 0
    assert rate.rate is None


async def test_the_interaction_chain_still_verifies_after_sql_records(
    session: AsyncSession, settings: Settings
) -> None:
    for query in ("SELECT id FROM orders", "DELETE FROM orders", "SELECT 1"):
        await validate_query(session, settings, engine="postgresql", query=query)
    await session.commit()

    result = await verify(session, Store.INTERACTIONS)
    assert result.intact
    assert result.checked == 3
