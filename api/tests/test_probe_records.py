"""The API side of the host probe: reading its result, recording the
selection and its evidence, and the `/probe` surface. `M7-PROBE-DEPLOY-137`.

The host script (`deploy/probe/askwell-probe`) is exercised on its own in
`test_probe_host.py`, against real subprocess calls and platform reads. This
file is the seam and the database: the JSON it would have written, and
whether that JSON lands as a settings value plus a hash-chained decisions
record — the same pattern `test_setup_records.py` already established for
`PROFILE_SELECTED`.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.probe import (
    NOT_PROBED_REASON,
    PROFILE_OVERRIDDEN,
    PROFILE_PROBED,
    PROFILE_SETTING_KEY,
    ProbeResult,
    UnknownProfile,
    _current_state,
    apply_override,
    apply_probe_result,
    read_probe_result,
    sync_probe_result,
)
from askwell.settings_store import get_setting, set_setting

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


def _result(**over: object) -> ProbeResult:
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
    return ProbeResult(**base)  # type: ignore[arg-type]


# --- reading the host script's JSON -----------------------------------------


def test_reads_back_what_the_host_script_would_have_written(tmp_path: Path) -> None:
    payload = {
        "profile": "accelerated",
        "reason": "16.0 GB RAM with an accelerator, 8.0 GB VRAM.",
        "detection_failed": False,
        "below_floor": False,
        "ram_gb": 16.0,
        "ram_source": "/proc/meminfo",
        "cpu": {"processor": "x86_64", "machine": "x86_64", "cores": 8},
        "accelerator": {"present": True, "kind": "nvidia", "vram_gb": 8.0, "source": "nvidia-smi"},
        "disk_free_gb": 200.0,
        "disk_path": "/home/user",
        "platform": "Linux",
        "probed_at": time.time(),
    }
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = read_probe_result(path)

    assert result is not None
    assert result.profile == "accelerated"
    assert result.accelerator["kind"] == "nvidia"
    assert not result.stale


def test_a_probe_that_has_never_run_reads_as_absent_not_a_guess(tmp_path: Path) -> None:
    assert read_probe_result(tmp_path / "probe.json") is None


def test_a_corrupt_result_file_reads_as_absent(tmp_path: Path) -> None:
    path = tmp_path / "probe.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_probe_result(path) is None


def test_an_unrecognised_profile_reads_as_absent(tmp_path: Path) -> None:
    """An older API against a newer probe. Guessing at a profile it does not
    know would be worse than saying nothing has run."""
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"profile": "quantum-superposition"}), encoding="utf-8")
    assert read_probe_result(path) is None


def test_the_not_probed_reason_says_it_runs_on_the_host() -> None:
    assert "runs on the host" in NOT_PROBED_REASON
    assert "scripts/dev.sh probe" in NOT_PROBED_REASON


# --- recording -----------------------------------------------------------


async def test_the_selection_and_its_evidence_are_recorded(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    result = _result(
        profile="workstation",
        ram_gb=32.0,
        accelerator={
            "present": True,
            "kind": "nvidia",
            "vram_gb": 16.0,
            "source": "nvidia-smi",
        },
    )

    async with factory() as db:
        await apply_probe_result(db, result)
        await db.commit()

    async with factory() as db:
        assert await get_setting(db, "hardware.profile") == "workstation"
        evidence = json.loads(await get_setting(db, "hardware.probe_evidence") or "{}")
        assert evidence["accelerator"]["vram_gb"] == 16.0

        row = (
            await db.execute(
                text(
                    "SELECT kind, payload FROM audit_decisions "
                    "WHERE kind = :kind ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"kind": PROFILE_PROBED},
            )
        ).one()
        assert row[0] == PROFILE_PROBED
        assert row[1]["profile"] == "workstation"
        # Floats are never stored in an audit payload (askwell.audit rejects
        # them outright) — gigabytes become fixed-unit megabytes.
        assert row[1]["accelerator"]["vram_mb"] == 16 * 1024
        assert "vram_gb" not in row[1]["accelerator"]

        outcome = await verify(db, Store.DECISIONS)
        assert outcome.intact


async def test_a_rerun_confirming_the_same_profile_is_still_recorded(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every selection event is a decisions record, not just changes — the
    same rule `setup.PROFILE_SELECTED` already follows. A year later "why is
    this on light" needs an answer even when light was chosen twice in a
    row."""
    first = _result(probed_at=1000.0)
    second = _result(probed_at=2000.0)

    async with factory() as db:
        await apply_probe_result(db, first)
        await apply_probe_result(db, second)
        await db.commit()

    async with factory() as db:
        count = (
            await db.execute(
                text("SELECT count(*) FROM audit_decisions WHERE kind = :kind"),
                {"kind": PROFILE_PROBED},
            )
        ).scalar_one()
        assert count == 2


async def test_sync_only_records_a_genuinely_newer_probe(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """A settings screen polling `GET /probe` must not write a fresh
    decisions record on every poll — only when the host script has actually
    probed again."""
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(_result(probed_at=1000.0).as_dict()), encoding="utf-8")

    async with factory() as db:
        await sync_probe_result(db, path)
        await sync_probe_result(db, path)
        await sync_probe_result(db, path)
        await db.commit()

    async with factory() as db:
        count = (
            await db.execute(
                text("SELECT count(*) FROM audit_decisions WHERE kind = :kind"),
                {"kind": PROFILE_PROBED},
            )
        ).scalar_one()
        assert count == 1


# --- `M7-PROBE-FE-138`: warn-and-continue, and the settings override -----


async def test_current_state_names_the_below_floor_reading_without_an_override(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            _result(
                profile="light",
                below_floor=True,
                ram_gb=6.0,
                reason="6.0 GB is below the 8 GB floor. Askwell will run, but slowly.",
            ).as_dict()
        ),
        encoding="utf-8",
    )

    async with factory() as db:
        state = await _current_state(db, path)
        await db.commit()

    probe = state["probe"]
    assert probe["profile"] == "light"
    assert probe["below_floor"] is True
    assert probe["overridden"] is False
    assert probe["detected_profile"] == "light"


async def test_current_state_names_a_detection_failure_distinctly_from_below_floor(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            _result(
                profile="standard",
                ram_gb=None,
                below_floor=False,
                detection_failed=True,
                reason="Memory could not be measured on this machine. Defaulting to the "
                "standard profile.",
            ).as_dict()
        ),
        encoding="utf-8",
    )

    async with factory() as db:
        state = await _current_state(db, path)
        await db.commit()

    probe = state["probe"]
    assert probe["detection_failed"] is True
    assert probe["below_floor"] is False
    assert "standard" in probe["reason"]


async def test_an_override_is_reflected_and_named_as_such(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(_result(profile="light").as_dict()), encoding="utf-8")

    async with factory() as db:
        await sync_probe_result(db, path)
        await set_setting(db, PROFILE_SETTING_KEY, "standard")
        await db.commit()

    async with factory() as db:
        state = await _current_state(db, path)

    probe = state["probe"]
    assert probe["profile"] == "standard"
    assert probe["overridden"] is True
    assert probe["detected_profile"] == "light"


async def test_no_real_probe_yet_still_reports_a_named_shape(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Nothing has ever run `askwell-probe` on this machine — `_current_state`
    falls back to the interim in-container reading, reshaped into the real
    probe's own field names so a caller does not need two branches."""
    async with factory() as db:
        state = await _current_state(db, tmp_path / "never-run.json")

    probe = state["probe"]
    assert state["recorded"] is False
    assert probe["profile"] in ("light", "standard", "accelerated", "workstation")
    assert probe["detection_failed"] is False
    assert probe["overridden"] is False
    assert NOT_PROBED_REASON in probe["reason"]


async def test_apply_override_records_the_detected_and_chosen_profile(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(_result(profile="light").as_dict()), encoding="utf-8")

    async with factory() as db:
        await sync_probe_result(db, path)
        await db.commit()

    async with factory() as db:
        state = await apply_override(db, path, "accelerated")
        await db.commit()

    assert state["probe"]["profile"] == "accelerated"
    assert state["probe"]["overridden"] is True
    assert state["probe"]["detected_profile"] == "light"

    async with factory() as db:
        assert await get_setting(db, PROFILE_SETTING_KEY) == "accelerated"

        row = (
            await db.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = :kind "
                    "ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"kind": PROFILE_OVERRIDDEN},
            )
        ).one()
        assert row[0]["detected"] == "light"
        assert row[0]["chosen"] == "accelerated"

        outcome = await verify(db, Store.DECISIONS)
        assert outcome.intact


async def test_apply_override_rejects_an_unknown_profile(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    with pytest.raises(UnknownProfile):
        async with factory() as db:
            await apply_override(db, tmp_path / "probe.json", "quantum-superposition")


async def test_sync_records_again_once_the_host_reprobes(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(_result(probed_at=1000.0).as_dict()), encoding="utf-8")

    async with factory() as db:
        await sync_probe_result(db, path)
        await db.commit()

    path.write_text(
        json.dumps(_result(probed_at=2000.0, profile="light").as_dict()), encoding="utf-8"
    )

    async with factory() as db:
        await sync_probe_result(db, path)
        await db.commit()

    async with factory() as db:
        assert await get_setting(db, "hardware.profile") == "light"
        count = (
            await db.execute(
                text("SELECT count(*) FROM audit_decisions WHERE kind = :kind"),
                {"kind": PROFILE_PROBED},
            )
        ).scalar_one()
        assert count == 2
