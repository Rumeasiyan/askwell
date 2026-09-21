"""The update check, agreed to at installation. `M7-UPDATE-BE-161`.

Version comparison first, with no database and no network. Then the stored
answer, the weekly gate, and a manual check — each against a real database,
with `askwell.egress`'s permit/revoke calls spied on rather than a real
Redis, since what matters here is *that* the door opens and closes at the
right moments, not `askwell.egress`'s own mechanics (`test_egress.py` covers
those).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import update_check
from askwell.config import Settings
from askwell.update_check import (
    Answer,
    InvalidAnswer,
    Result,
    get_state,
    maybe_run_scheduled_check,
    run_check,
    set_answer,
)

# --- version comparison, no database, no network ----------------------------


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("0.6.9", "0.6.8", True),
        ("0.7.0", "0.6.8", True),
        ("1.0.0", "0.6.8", True),
        ("0.6.8", "0.6.8", False),
        ("0.6.7", "0.6.8", False),
        ("not-a-version", "0.6.8", False),
        ("", "0.6.8", False),
    ],
)
def test_version_comparison(candidate: str, current: str, expected: bool) -> None:
    assert update_check._version_gt(candidate, current) is expected


# --- database-backed ---------------------------------------------------------


pytestmark_db = pytest.mark.requires_db


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


_SETTINGS_CLEANUP = "DELETE FROM settings WHERE key LIKE 'update_check%'"


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions"))
        await opened.execute(text(_SETTINGS_CLEANUP))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions"))
        await opened.execute(text(_SETTINGS_CLEANUP))
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
    )


@dataclass
class _EgressCalls:
    permitted: list[str]
    revoked_count: int


@pytest.fixture
def egress_calls(monkeypatch: pytest.MonkeyPatch) -> _EgressCalls:
    """Records every permit/revoke without touching Redis."""
    calls = _EgressCalls(permitted=[], revoked_count=0)

    async def _permit(_settings: Settings, destination: str) -> None:
        calls.permitted.append(destination)

    async def _revoke(_settings: Settings) -> None:
        calls.revoked_count += 1

    monkeypatch.setattr(update_check.egress, "permit_destination", _permit)
    monkeypatch.setattr(update_check.egress, "revoke_destination", _revoke)
    return calls


def _ok_client_factory(version_text: str) -> update_check.ClientFactory:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("Askwell/")
        return httpx.Response(200, text=version_text)

    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    return _factory


def _unreachable_client_factory() -> update_check.ClientFactory:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    return _factory


@pytestmark_db
async def test_a_fresh_install_has_never_been_asked(
    session: AsyncSession, settings: Settings
) -> None:
    state = await get_state(session)
    assert state.answer is Answer.NOT_ASKED
    assert state.last_checked_at is None
    assert state.latest_known_version is None


@pytestmark_db
async def test_answering_yes_permits_the_feed_host_and_records_a_decision(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    state = await set_answer(session, settings, Answer.YES)
    await session.commit()

    assert state.answer is Answer.YES
    assert egress_calls.permitted == [f"{settings.update_feed_host}:443"]

    row = (
        await session.execute(
            text("SELECT kind FROM audit_decisions WHERE kind = 'update_check_enabled'")
        )
    ).first()
    assert row is not None


@pytestmark_db
async def test_answering_no_never_opens_the_destination(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    state = await set_answer(session, settings, Answer.NO)
    await session.commit()

    assert state.answer is Answer.NO
    assert egress_calls.permitted == []


@pytestmark_db
async def test_turning_it_off_after_yes_revokes_the_destination(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    await set_answer(session, settings, Answer.YES)
    await set_answer(session, settings, Answer.NO)
    await session.commit()

    assert egress_calls.revoked_count == 1


@pytestmark_db
async def test_re_answering_the_same_way_is_a_no_op(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    """Repeating an unchanged answer must not double-permit or double-log —
    an idempotent re-POST is not a new decision."""
    await set_answer(session, settings, Answer.YES)
    await set_answer(session, settings, Answer.YES)
    await session.commit()

    assert len(egress_calls.permitted) == 1
    count = (
        await session.execute(
            text("SELECT count(*) FROM audit_decisions WHERE kind = 'update_check_enabled'")
        )
    ).scalar_one()
    assert count == 1


@pytestmark_db
async def test_only_yes_or_no_may_be_recorded(session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(InvalidAnswer):
        await set_answer(session, settings, Answer.NOT_ASKED)


@pytestmark_db
async def test_a_successful_check_records_the_remote_version(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    await set_answer(session, settings, Answer.YES)
    await session.commit()

    state = await run_check(
        session, settings, manual=True, client_factory=_ok_client_factory("9.9.9")
    )
    await session.commit()

    assert state.latest_known_version == "9.9.9"
    assert state.last_result is Result.OK
    assert state.update_available is True
    assert state.last_checked_at is not None


@pytestmark_db
async def test_an_unreachable_feed_is_silent_and_retried_next_week(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    await set_answer(session, settings, Answer.YES)
    await session.commit()

    state = await run_check(
        session, settings, manual=True, client_factory=_unreachable_client_factory()
    )
    await session.commit()

    assert state.last_result is Result.UNREACHABLE
    assert state.latest_known_version is None
    assert state.last_checked_at is not None


@pytestmark_db
async def test_a_manual_check_works_even_when_the_answer_is_no(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    """The acceptance criterion, verbatim: a manual check is a deliberate act
    regardless of the standing answer, and it must close the door again
    afterwards rather than leaving it open."""
    await set_answer(session, settings, Answer.NO)
    await session.commit()
    egress_calls.permitted.clear()
    egress_calls.revoked_count = 0

    state = await run_check(
        session, settings, manual=True, client_factory=_ok_client_factory("9.9.9")
    )
    await session.commit()

    assert state.latest_known_version == "9.9.9"
    assert egress_calls.permitted == [f"{settings.update_feed_host}:443"]
    assert egress_calls.revoked_count == 1


@pytestmark_db
async def test_a_manual_check_while_already_yes_does_not_revoke_the_standing_permit(
    session: AsyncSession,
    settings: Settings,
    egress_calls: _EgressCalls,
) -> None:
    await set_answer(session, settings, Answer.YES)
    await session.commit()

    await run_check(session, settings, manual=True, client_factory=_ok_client_factory("9.9.9"))
    await session.commit()

    assert egress_calls.revoked_count == 0


@pytestmark_db
async def test_the_scheduled_check_never_runs_when_the_answer_is_not_yes(
    session: AsyncSession, settings: Settings, egress_calls: _EgressCalls
) -> None:
    ran = await maybe_run_scheduled_check(session, settings)
    await session.commit()
    assert ran is False


@pytestmark_db
async def test_the_scheduled_check_runs_once_when_due(
    session: AsyncSession, settings: Settings, egress_calls: _EgressCalls
) -> None:
    await set_answer(session, settings, Answer.YES)
    await session.commit()

    ran = await maybe_run_scheduled_check(
        session, settings, client_factory=_ok_client_factory("9.9.9")
    )
    await session.commit()

    assert ran is True
    state = await get_state(session)
    assert state.last_checked_at is not None


@pytestmark_db
async def test_the_scheduled_check_does_not_run_again_inside_the_week(
    session: AsyncSession, settings: Settings, egress_calls: _EgressCalls
) -> None:
    from askwell.settings_store import set_setting

    await set_answer(session, settings, Answer.YES)
    recent = datetime.now(UTC) - timedelta(days=1)
    await set_setting(session, update_check.LAST_CHECKED_KEY, recent.isoformat())
    await session.commit()

    ran = await maybe_run_scheduled_check(session, settings)
    await session.commit()

    assert ran is False


@pytestmark_db
async def test_a_month_offline_produces_one_check_not_a_backlog(
    session: AsyncSession, settings: Settings, egress_calls: _EgressCalls
) -> None:
    """The stored state has no notion of "missed slots" — only "was the last
    one long enough ago" — so a month-old timestamp is exactly as due as a
    week-old one, never more."""
    from askwell.settings_store import set_setting

    await set_answer(session, settings, Answer.YES)
    a_month_ago = datetime.now(UTC) - timedelta(days=30)
    await set_setting(session, update_check.LAST_CHECKED_KEY, a_month_ago.isoformat())
    await session.commit()

    ran = await maybe_run_scheduled_check(
        session, settings, client_factory=_ok_client_factory("9.9.9")
    )
    await session.commit()

    assert ran is True
