"""The first-run sequence's settings and decision records, against real Postgres.

`settings_store` is the first real reader/writer of the `settings` table
(`db/models.py`'s `Setting` had no caller before this ticket) — what is under
test here is that the round trip actually works, not just that the SQL
parses. Skip and the passphrase choice both have to land as decision-audit
records (`docs/decisions.md`'s pattern every other decision-writing ticket
already follows), so the chain is checked too, not just the settings row.
"""

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.config import Settings
from askwell.probe import apply_override
from askwell.settings_store import get_setting, set_setting
from askwell.setup import PASSPHRASE_DECIDED, PROFILE_SELECTED, SKIPPED, _resolve_profile

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


# --- `M7-PROBE-FE-138`: the profile the welcome screen resolves -----------


def _probe_payload(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "profile": "standard",
        "reason": "16.0 GB RAM, no usable accelerator.",
        "detection_failed": False,
        "below_floor": False,
        "ram_gb": 16.0,
        "ram_source": "/proc/meminfo",
        "cpu": {"processor": "x86_64", "machine": "x86_64", "cores": 8},
        "accelerator": {"present": False, "kind": None, "vram_gb": None, "source": "not detected"},
        "disk_free_gb": 100.0,
        "disk_path": "/home/user",
        "platform": "Linux",
        "probed_at": time.time(),
    }
    base.update(over)
    return base


async def test_resolve_profile_prefers_the_real_probe_when_it_has_run(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            _probe_payload(
                profile="light",
                below_floor=True,
                ram_gb=6.0,
                reason="6.0 GB is below the 8 GB floor.",
            )
        ),
        encoding="utf-8",
    )
    probed_settings = settings.model_copy(update={"probe_result_path": path})

    async with factory() as db:
        profile = await _resolve_profile(db, probed_settings)
        await db.commit()

    assert profile["tier"] == "light"
    assert profile["floor_met"] is False
    assert profile["source"] == "host-probe"
    assert profile["probe_failed"] is False
    assert "8 GB floor" in profile["expectation"]


async def test_resolve_profile_names_a_detection_failure(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            _probe_payload(
                profile="standard",
                ram_gb=None,
                detection_failed=True,
                reason="Memory could not be measured on this machine. Defaulting to the "
                "standard profile.",
            )
        ),
        encoding="utf-8",
    )
    probed_settings = settings.model_copy(update={"probe_result_path": path})

    async with factory() as db:
        profile = await _resolve_profile(db, probed_settings)

    assert profile["probe_failed"] is True
    assert profile["tier"] == "standard"
    assert "standard profile" in profile["expectation"]


async def test_resolve_profile_falls_back_when_the_real_probe_has_never_run(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    probed_settings = settings.model_copy(update={"probe_result_path": tmp_path / "never-run.json"})

    async with factory() as db:
        profile = await _resolve_profile(db, probed_settings)

    assert profile["source"] in ("basic-probe", "fallback")
    assert profile["probe_failed"] is False


async def test_resolve_profile_honours_a_settings_override(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    """The override has to be applied *through* `askwell.probe.apply_override`
    — it syncs the probe first and only then writes the override on top, so
    a later `_resolve_profile` call sees the override rather than a same-
    timestamp resync clobbering it. Writing `hardware.profile` directly, out
    of that order, is not a path the application ever takes."""
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(_probe_payload(profile="light")), encoding="utf-8")
    probed_settings = settings.model_copy(update={"probe_result_path": path})

    async with factory() as db:
        await apply_override(db, path, "workstation")
        await db.commit()

    async with factory() as db:
        profile = await _resolve_profile(db, probed_settings)

    assert profile["tier"] == "workstation"
