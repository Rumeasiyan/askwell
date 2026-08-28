"""The first-run sequence's settings and decision records, against real Postgres.

`settings_store` is the first real reader/writer of the `settings` table
(`db/models.py`'s `Setting` had no caller before this ticket) — what is under
test here is that the round trip actually works, not just that the SQL
parses. Skip and the passphrase choice both have to land as decision-audit
records (`docs/decisions.md`'s pattern every other decision-writing ticket
already follows), so the chain is checked too, not just the settings row.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.settings_store import get_setting, set_setting
from askwell.setup import PASSPHRASE_DECIDED, PROFILE_SELECTED, SKIPPED

TABLES = "settings, audit_decisions"

pytestmark = pytest.mark.requires_db


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


async def test_a_setting_round_trips(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as db:
        assert await get_setting(db, "welcome.skipped") is None
        await set_setting(db, "welcome.skipped", "true")
        await db.commit()

    async with factory() as db:
        assert await get_setting(db, "welcome.skipped") == "true"


async def test_setting_the_same_key_twice_updates_rather_than_duplicates(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as db:
        await set_setting(db, "welcome.skipped", "true")
        await set_setting(db, "welcome.skipped", "false")
        await db.commit()

    async with factory() as db:
        assert await get_setting(db, "welcome.skipped") == "false"
        count = (
            await db.execute(text("SELECT count(*) FROM settings WHERE key = 'welcome.skipped'"))
        ).scalar_one()
        assert count == 1


async def test_skip_and_passphrase_are_audited_decisions(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    from askwell.audit import record

    async with factory() as db:
        await record(db, Store.DECISIONS, SKIPPED, {})
        await record(db, Store.DECISIONS, PASSPHRASE_DECIDED, {"enabled": True})
        await db.commit()

        kinds = (
            (await db.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at")))
            .scalars()
            .all()
        )
        assert list(kinds) == [SKIPPED, PASSPHRASE_DECIDED]

        result = await verify(db, Store.DECISIONS)
        assert result.intact


async def test_choosing_a_profile_is_an_audited_decision(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The ticket puts profile selection in the decisions store beside the
    passphrase, and it had no writer at all.

    What makes it worth recording is not the tier but the disagreement: whether
    the user took the machine's own answer or overrode it, and whether they
    continued under the floor after being warned. A row saying only "standard"
    cannot answer the question somebody actually asks a year later, which is
    "why is this thing slow" — and the answer may be that they were told and
    went ahead.
    """
    from askwell.audit import record

    async with factory() as db:
        await record(
            db,
            Store.DECISIONS,
            PROFILE_SELECTED,
            {
                "tier": "light",
                "probed_tier": "standard",
                "chosen_by_user": True,
                "floor_met": False,
                "probe_source": "psutil",
            },
        )
        await db.commit()

        row = (
            await db.execute(
                text(
                    "SELECT kind, payload FROM audit_decisions "
                    "WHERE kind = :kind ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"kind": PROFILE_SELECTED},
            )
        ).one()
        assert row[0] == PROFILE_SELECTED
        assert row[1]["chosen_by_user"] is True, "an override has to be legible as an override"
        assert row[1]["floor_met"] is False

        result = await verify(db, Store.DECISIONS)
        assert result.intact
