"""Log storage budget: staging without a database, then against a real one.

`docs/audit-log.md` §3, ticket `M7-LOG-BE-153`.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings
from askwell.log_budget import (
    DEFAULT_RETENTION_MONTHS,
    IngestionRefused,
    InvalidBudget,
    InvalidRetention,
    Stage,
    enforce_ingestion_allowed,
    get_configured_budget,
    get_retention_months,
    measure,
    set_budget,
    set_retention_months,
    stage_for,
)


def test_under_the_notice_ratio_is_ok() -> None:
    assert stage_for(used_bytes=100, budget_bytes=1000) is Stage.OK


def test_eighty_percent_is_the_notice_stage() -> None:
    assert stage_for(used_bytes=800, budget_bytes=1000) is Stage.NOTICE
    assert stage_for(used_bytes=799, budget_bytes=1000) is Stage.OK


def test_at_or_over_budget_is_the_hard_limit() -> None:
    assert stage_for(used_bytes=1000, budget_bytes=1000) is Stage.HARD_LIMIT
    assert stage_for(used_bytes=1500, budget_bytes=1000) is Stage.HARD_LIMIT


def test_a_zero_or_negative_budget_is_always_the_hard_limit() -> None:
    """`disk_usage` returning no free space must not divide by, or compare
    against, a non-positive number in a way that reads as `OK`."""
    assert stage_for(used_bytes=0, budget_bytes=0) is Stage.HARD_LIMIT
    assert stage_for(used_bytes=0, budget_bytes=-1) is Stage.HARD_LIMIT


pytestmark_db = pytest.mark.requires_db


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings_cleanup = (
        "DELETE FROM settings WHERE key LIKE 'log_budget%' OR key = 'interaction_retention_months'"
    )
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.execute(text(settings_cleanup))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.execute(text(settings_cleanup))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        trace_dir=tmp_path / "traces",
        trace_max_bytes=1024 * 1024,
    )


@pytestmark_db
async def test_the_default_budget_is_two_gigabytes_or_less(
    session: AsyncSession, settings: Settings
) -> None:
    default = await get_configured_budget(session)
    assert default == 2 * 1024**3


@pytestmark_db
async def test_changing_the_budget_writes_a_decision_record(
    session: AsyncSession, settings: Settings
) -> None:
    await set_budget(session, 12_345)
    await session.commit()

    assert await get_configured_budget(session) == 12_345
    row = (
        await session.execute(
            text("SELECT kind, payload FROM audit_decisions WHERE kind = 'log_budget_changed'")
        )
    ).first()
    assert row is not None
    assert row[1]["new_bytes"] == "12345"


@pytestmark_db
async def test_a_non_positive_budget_is_refused(session: AsyncSession) -> None:
    with pytest.raises(InvalidBudget):
        await set_budget(session, 0)


@pytestmark_db
async def test_measurement_carries_the_configured_cap_separately_from_the_effective_one(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    """Issue #484: a caller must be able to tell "you set this" from "free
    disk is overriding what you set" without re-deriving `min()` itself."""
    huge = 10 * 1024**4  # far larger than 5% of any real free disk
    await set_budget(session, huge)
    await session.commit()

    usage = await measure(session, settings)

    assert usage.configured_bytes == huge
    assert usage.budget_bytes < usage.configured_bytes


@pytestmark_db
async def test_the_default_retention_is_twelve_months(
    session: AsyncSession, settings: Settings
) -> None:
    assert await get_retention_months(session) == DEFAULT_RETENTION_MONTHS == 12


@pytestmark_db
async def test_changing_the_retention_window_writes_a_decision_record(
    session: AsyncSession, settings: Settings
) -> None:
    await set_retention_months(session, 6)
    await session.commit()

    assert await get_retention_months(session) == 6
    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'interaction_retention_changed'")
        )
    ).first()
    assert row is not None
    assert row[0]["previous_months"] == "12"
    assert row[0]["new_months"] == "6"


@pytestmark_db
async def test_a_non_positive_retention_window_is_refused(session: AsyncSession) -> None:
    with pytest.raises(InvalidRetention):
        await set_retention_months(session, 0)


@pytestmark_db
async def test_measurement_reflects_a_lowered_budget_immediately(
    session: AsyncSession, settings: Settings
) -> None:
    """Lowering the budget below current use shows the notice immediately —
    the ticket's own edge case. Nothing here is cached between calls."""
    await set_budget(session, 1)  # smaller than anything, but still positive
    await session.commit()

    usage = await measure(session, settings)
    assert usage.stage is Stage.HARD_LIMIT


@pytestmark_db
async def test_ingestion_is_refused_at_the_hard_limit(
    session: AsyncSession, settings: Settings
) -> None:
    await set_budget(session, 1)
    await session.commit()

    with pytest.raises(IngestionRefused):
        await enforce_ingestion_allowed(session, settings)


@pytestmark_db
async def test_ingestion_is_allowed_well_under_budget(
    session: AsyncSession, settings: Settings
) -> None:
    await set_budget(session, 2 * 1024**3)
    await session.commit()

    await enforce_ingestion_allowed(session, settings)  # must not raise


@pytestmark_db
async def test_decisions_store_size_is_excluded_from_the_measurement(
    session: AsyncSession, settings: Settings
) -> None:
    """`docs/audit-log.md` §8: decisions are never pruned at any budget, and
    are never what a budget check is measuring in the first place."""
    for _ in range(5):
        await set_budget(session, 2 * 1024**3)
    await session.commit()

    usage = await measure(session, settings)
    assert usage.interactions_bytes >= 0
    assert not hasattr(usage, "decisions_bytes")


# --- over HTTP, the real app -------------------------------------------------
#
# The unit-level tests above cover what the check decides; these cover what a
# caller actually receives — the refusal reaches `POST /sources` as a 507 with
# a stated reason, and asking still works, which is this ticket's own
# headline acceptance criterion.


@pytest.fixture
def app_client(
    settings: Settings, app_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    live = create_app(
        settings.model_copy(
            update={
                "database_url": SecretStr(app_database_url),
                "web_assets_dir": built,
                "trace_dir": tmp_path / "traces",
            }
        )
    )
    return TestClient(live)


@pytestmark_db
def test_new_ingestion_is_refused_over_http_at_the_hard_limit(
    app_client: TestClient, database_url: str, tmp_path: Path
) -> None:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE roots, sources, documents, audit_decisions CASCADE")
        setup.execute("DELETE FROM settings WHERE key LIKE 'log_budget%'")
        setup.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('log_budget_bytes', '1', now())"
        )
        setup.execute("INSERT INTO roots (path) VALUES (%s)", (str(tmp_path),))

    folder = tmp_path / "clients"
    folder.mkdir()
    (folder / "contract.pdf").write_bytes(b"%PDF-1.7\nSome terms.\n")

    with app_client as client:
        client.get("/", headers={"accept": "text/html"})
        response = client.post("/sources", json={"folder": str(folder), "files": ["contract.pdf"]})

    assert response.status_code == 507, response.text
    assert "limit" in response.json()["error"].lower()

    with psycopg.connect(database_url, autocommit=True) as check:
        count = check.execute("SELECT count(*) FROM documents").fetchone()
    assert count is not None and count[0] == 0, "a refused batch must not commit any rows"

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE roots, sources, documents, audit_decisions CASCADE")
        clean.execute("DELETE FROM settings WHERE key LIKE 'log_budget%'")
