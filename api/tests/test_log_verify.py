"""The settings-screen verifier. `docs/audit-log.md` §4, ticket `M7-LOG-FE-156`.

Against a real Postgres — `askwell.log_verify.run` calls `askwell.audit.verify`
directly, and that module's own tests (`test_audit_chain.py`) already prove
the chain-walk logic in isolation. What is new here: both stores reported
together, the run itself recorded as a decisions entry, and the HTTP seam.
"""

import json
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
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.log_verify import VERIFICATION_RUN, run

pytestmark = pytest.mark.requires_db


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
    await engine.dispose()


async def test_an_empty_log_verifies_intact_in_both_stores(session: AsyncSession) -> None:
    result = await run(session)
    await session.commit()

    assert result["intact"] is True
    assert result["decisions"]["intact"] is True
    assert result["interactions"]["intact"] is True


async def test_the_run_itself_is_recorded(session: AsyncSession) -> None:
    await run(session)
    await session.commit()

    row = (
        await session.execute(
            text("SELECT kind, payload FROM audit_decisions WHERE kind = :kind"),
            {"kind": VERIFICATION_RUN},
        )
    ).first()
    assert row is not None
    assert row[0] == VERIFICATION_RUN
    assert row[1]["decisions_intact"] == "True"
    assert row[1]["interactions_intact"] == "True"


async def test_a_break_names_the_record_and_its_date(session: AsyncSession) -> None:
    for index in range(3):
        await record(session, Store.INTERACTIONS, f"event_{index}", {"index": index})
    await session.commit()

    target = (
        await session.execute(
            text(
                "SELECT id, occurred_at FROM audit_interactions "
                "ORDER BY occurred_at ASC OFFSET 1 LIMIT 1"
            )
        )
    ).first()
    assert target is not None
    await session.execute(
        text("UPDATE audit_interactions SET payload = CAST(:p AS jsonb) WHERE id = :id"),
        {"p": json.dumps({"index": 99}), "id": target[0]},
    )
    await session.commit()

    result = await run(session)
    await session.commit()

    assert result["intact"] is False
    assert result["decisions"]["intact"] is True
    interactions = result["interactions"]
    assert interactions["intact"] is False
    assert interactions["broken_record_id"] == str(target[0])
    assert interactions["broken_at"] is not None
    assert interactions["reason"] == "altered"

    logged = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = :kind"),
            {"kind": VERIFICATION_RUN},
        )
    ).first()
    assert logged is not None
    assert logged[0]["interactions_reason"] == "altered"
    assert logged[0]["interactions_broken_record_id"] == str(target[0])


async def test_a_prune_boundary_reports_as_an_explained_boundary_not_tampering(
    session: AsyncSession,
) -> None:
    for index in range(4):
        await record(session, Store.INTERACTIONS, f"event_{index}", {"index": index})
    await session.commit()

    rows = (
        await session.execute(
            text("SELECT id, hash FROM audit_interactions ORDER BY occurred_at ASC")
        )
    ).all()
    boundary_hash = rows[0][1]
    await session.execute(text("DELETE FROM audit_interactions WHERE id = :id"), {"id": rows[0][0]})
    await record(
        session,
        Store.DECISIONS,
        "interactions_pruned",
        {
            "cutoff": "2026-01-01T00:00:00+00:00",
            "boundary_hash": boundary_hash,
            "pruned_count": "1",
        },
    )
    await session.commit()

    result = await run(session)
    await session.commit()

    assert result["intact"] is True
    assert result["interactions"]["intact"] is True
    assert "prune" in result["interactions"]["note"]


# --- over HTTP, the real app -------------------------------------------------


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


def test_get_log_verify_over_http(app_client: TestClient) -> None:
    with app_client as client:
        client.get("/", headers={"accept": "text/html"})
        response = client.get("/log-verify")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "intact" in body
    assert "decisions" in body
    assert "interactions" in body
