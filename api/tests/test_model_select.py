"""A user-supplied model, and which model answered. `M7-SET-BE-145a`.

The IPC with the host supervisor (`deploy/inference/askwell-inference`) is
exercised end to end only by the ticket's own manual walkthrough — no
subprocess runs in this test process. `_perform_swap` is monkeypatched here
so what is under test is everything on this side of that seam: validation,
persistence, the decisions record, and what a message is stamped with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.config import Settings
from askwell.inference.state import ProcessState
from askwell.model_select import (
    SETTING_ACTIVE_SHIPPED_DISPLAY_NAME,
    SETTING_ACTIVE_SOURCE,
    SETTING_USER_MODEL_PATH,
    ModelSource,
    ModelValidationError,
    SwapOutcome,
    active_model_identity,
    reapply_user_model,
    select_user_model,
    validate_model_file,
)
from askwell.models_catalog import CATALOG
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://x/x",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x/x",  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
        sandbox_readonly_password="x",  # type: ignore[arg-type]
        inference_socket=tmp_path / "inference.sock",
    )


def _write_state(tmp_path: Path, **payload: object) -> None:
    import json

    (tmp_path / "state.json").write_text(json.dumps(payload), encoding="utf-8")


def _gguf(tmp_path: Path, name: str = "custom.gguf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"GGUF" + b"\x00" * 32)
    return path


# --- validation --------------------------------------------------------------


def test_rejects_a_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ModelValidationError, match="No file at"):
        validate_model_file(tmp_path / "nope.gguf")


def test_rejects_a_relative_path(tmp_path: Path) -> None:
    with pytest.raises(ModelValidationError, match="absolute path"):
        validate_model_file(Path("relative.gguf"))


def test_rejects_a_file_that_is_not_gguf(tmp_path: Path) -> None:
    path = tmp_path / "not-a-model.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ModelValidationError, match="GGUF"):
        validate_model_file(path)


def test_accepts_a_gguf_file(tmp_path: Path) -> None:
    path = _gguf(tmp_path)
    assert validate_model_file(path) == path


# --- selection: success --------------------------------------------------


async def test_a_successful_swap_persists_the_selection_and_records_a_decision(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)

    async with factory() as db:
        outcome = await select_user_model(db, settings, model)
        await db.commit()

    assert outcome.ok is True

    async with factory() as db:
        assert await get_setting(db, SETTING_USER_MODEL_PATH) == str(model)
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.USER_SUPPLIED)

        row = (
            await db.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = 'model_swap_requested' "
                    "ORDER BY occurred_at DESC LIMIT 1"
                )
            )
        ).one()
        assert row[0]["ok"] is True
        assert row[0]["model_path"] == str(model)

        result = await verify(db, Store.DECISIONS)
        assert result.intact


async def test_a_swap_to_a_catalog_recognised_alternative_is_marked_shipped(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #632: `available_alternatives` only ever lists sha256-verified
    shipped files, so swapping to one via that list (or by typing its exact
    path) is a shipped model, whichever tier it belongs to — not
    `user_supplied`, and the settings screen's persistent unverified warning
    must not follow it.
    """
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)
    alternative_spec = next(iter(CATALOG.values()))

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)
    monkeypatch.setattr("askwell.model_select._catalog_match", lambda _path: alternative_spec)

    async with factory() as db:
        outcome = await select_user_model(db, settings, model)
        await db.commit()

    assert outcome.ok is True

    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.SHIPPED)
        assert (
            await get_setting(db, SETTING_ACTIVE_SHIPPED_DISPLAY_NAME)
            == alternative_spec.display_name
        )

        _write_state(tmp_path, state="ready", model=alternative_spec.filename)
        identity = await active_model_identity(db, settings)
        assert identity["source"] == str(ModelSource.SHIPPED)
        assert identity["display_name"] == alternative_spec.display_name


async def test_a_swap_to_a_path_that_matches_nothing_in_the_catalog_stays_unverified(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)
    monkeypatch.setattr("askwell.model_select._catalog_match", lambda _path: None)

    async with factory() as db:
        outcome = await select_user_model(db, settings, model)
        await db.commit()

    assert outcome.ok is True
    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.USER_SUPPLIED)
        assert await get_setting(db, SETTING_ACTIVE_SHIPPED_DISPLAY_NAME) is None


# --- selection: failure restores the previous model -------------------------


async def test_a_failed_swap_does_not_persist_the_selection(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(
            ok=False,
            reason="Out of memory. Staying on the previous model.",
            model_path=path,
        )

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)

    async with factory() as db:
        outcome = await select_user_model(db, settings, model)
        await db.commit()

    assert outcome.ok is False
    assert "Staying on the previous model" in (outcome.reason or "")

    async with factory() as db:
        assert await get_setting(db, SETTING_USER_MODEL_PATH) is None
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) is None

        row = (
            await db.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = 'model_swap_requested' "
                    "ORDER BY occurred_at DESC LIMIT 1"
                )
            )
        ).one()
        assert row[0]["ok"] is False


async def test_rejected_at_selection_never_reaches_the_swap(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    perform_swap = AsyncMock()
    monkeypatch.setattr("askwell.model_select._perform_swap", perform_swap)

    async with factory() as db:
        with pytest.raises(ModelValidationError):
            await select_user_model(db, settings, tmp_path / "missing.gguf")

    perform_swap.assert_not_called()


# --- active identity, for stamping a message ---------------------------------


async def test_no_model_loaded_reads_as_none_not_a_guess(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.MODEL_MISSING))

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.NONE), "display_name": None}


async def test_shipped_is_the_default_with_no_override(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="Qwen_Qwen3.5-4B-Q4_K_M.gguf")

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity["source"] == str(ModelSource.SHIPPED)
    assert identity["display_name"]


async def test_user_supplied_is_read_from_configuration_not_the_loaded_filename(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """The ticket's own validation rule: never guessed from the file name.
    Even though the state file reports a completely different filename here,
    `SETTING_ACTIVE_SOURCE` is what decides — because that is the only thing
    this module ever writes it from.
    """
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="something-else.gguf")

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, "/home/user/models/tiny.gguf")
        await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.USER_SUPPLIED))
        await db.commit()

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.USER_SUPPLIED), "display_name": "tiny.gguf"}


# --- reapply on startup -------------------------------------------------


async def test_reapply_does_nothing_when_no_selection_was_ever_made(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    await reapply_user_model(factory, settings)  # must not raise, must not touch state.json
    assert not (tmp_path / "state.json").exists()


async def test_reapply_restores_a_persisted_selection_after_restart(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="shipped.gguf")

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, str(model))
        await db.commit()

    await reapply_user_model(factory, settings)

    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.USER_SUPPLIED)

        row = (
            await db.execute(
                text("SELECT kind FROM audit_decisions ORDER BY occurred_at DESC LIMIT 1")
            )
        ).one()
        assert row[0] == "model_reapplied"


async def test_reapply_falls_back_to_shipped_when_the_file_is_gone(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="shipped.gguf")

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, str(tmp_path / "vanished.gguf"))
        await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.USER_SUPPLIED))
        await db.commit()

    await reapply_user_model(factory, settings)

    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.SHIPPED)

        row = (
            await db.execute(
                text("SELECT kind, payload FROM audit_decisions ORDER BY occurred_at DESC LIMIT 1")
            )
        ).one()
        assert row[0] == "model_reapply_failed"
        assert "vanished.gguf" in row[1]["model_path"]
