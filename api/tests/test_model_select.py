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
from askwell.inference.state import read as read_state
from askwell.model_select import (
    SETTING_ACTIVE_DISPLAY_NAME,
    SETTING_ACTIVE_SOURCE,
    SETTING_USER_MODEL_PATH,
    UNVERIFIED_STATEMENT,
    ModelSource,
    ModelValidationError,
    SwapOutcome,
    UnverifiedNotAcknowledged,
    active_model_identity,
    list_candidates,
    measured_throughput,
    reapply_user_model,
    resolve_model_file,
    select_model,
    validate_model_file,
)
from askwell.models_catalog import ModelSpec
from askwell.settings_store import get_setting, set_setting

TABLES = "settings, audit_decisions, conversations, messages"

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
        models_dir=tmp_path / "models",
    )


def _write_state(tmp_path: Path, **payload: object) -> None:
    import json

    (tmp_path / "state.json").write_text(json.dumps(payload), encoding="utf-8")


def _gguf(tmp_path: Path, name: str = "custom.gguf", body: bytes = b"\x00" * 32) -> Path:
    """A model file in the models directory, where selection looks."""
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    path = models / name
    path.write_bytes(b"GGUF" + body)
    return path


def _ship(monkeypatch: pytest.MonkeyPatch, path: Path, tier: str = "accelerated") -> ModelSpec:
    """Make `path`'s exact bytes a catalog entry, so it is a shipped model."""
    import hashlib

    data = path.read_bytes()
    spec = ModelSpec(
        tier=tier,
        display_name=f"Shipped {tier} model",
        repo="test/repo",
        filename="shipped.gguf",
        url="https://example.invalid/shipped.gguf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    monkeypatch.setattr("askwell.model_select.CATALOG", {tier: spec})
    monkeypatch.setattr("askwell.models_catalog.CATALOG", {tier: spec})
    return spec


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
        outcome = await select_model(db, settings, model.name, acknowledged_unverified=True)
        await db.commit()

    assert outcome.ok is True

    async with factory() as db:
        assert await get_setting(db, SETTING_USER_MODEL_PATH) == model.name
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
        assert row[0]["model_file"] == model.name
        assert row[0]["validated"] is False

        result = await verify(db, Store.DECISIONS)
        assert result.intact


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
        outcome = await select_model(db, settings, model.name, acknowledged_unverified=True)
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
            await select_model(db, settings, "missing.gguf", acknowledged_unverified=True)

    perform_swap.assert_not_called()


async def test_a_second_swap_while_one_runs_is_refused_and_every_permit_comes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #675: two overlapping swaps each took some generation permits and
    waited forever for the rest, hanging every answer. The second is now
    refused before it touches anything, and the first still completes."""
    import asyncio
    import json

    from askwell.ask import generation_semaphore
    from askwell.model_select import (
        SWAP_REQUEST_FILENAME,
        SWAP_RESULT_FILENAME,
        SwapInProgress,
        _perform_swap,
    )

    monkeypatch.setattr("askwell.model_select.SWAP_POLL_SECONDS", 0.01)
    settings = _settings(tmp_path)
    first = _gguf(tmp_path, "first.gguf")
    second = _gguf(tmp_path, "second.gguf")
    request = tmp_path / SWAP_REQUEST_FILENAME

    running = asyncio.create_task(_perform_swap(settings, first))
    for _ in range(500):
        if request.exists():
            break
        await asyncio.sleep(0.01)
    assert json.loads(request.read_text(encoding="utf-8")) == {"model_file": "first.gguf"}

    with pytest.raises(SwapInProgress):
        await _perform_swap(settings, second)
    # The refused swap wrote nothing over the running one's request.
    assert json.loads(request.read_text(encoding="utf-8")) == {"model_file": "first.gguf"}

    (tmp_path / SWAP_RESULT_FILENAME).write_text(
        json.dumps({"model_file": "first.gguf", "ok": True}), encoding="utf-8"
    )
    outcome = await asyncio.wait_for(running, timeout=5)
    assert outcome.ok

    semaphore = generation_semaphore(settings)
    for _ in range(settings.generation_max_concurrent):
        await asyncio.wait_for(semaphore.acquire(), timeout=1)
    for _ in range(settings.generation_max_concurrent):
        semaphore.release()


async def test_document_search_answers_while_a_swap_holds_every_generation_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Issue #678: Settings promises that search keeps working during a swap.
    That holds only because `/search` never waits on anything a swap holds, so
    it is pinned here with a swap genuinely in flight rather than by reading
    who imports the semaphore."""
    import asyncio
    import json

    import httpx
    from fastapi import FastAPI

    from askwell.ask import generation_semaphore
    from askwell.model_select import SWAP_REQUEST_FILENAME, SWAP_RESULT_FILENAME, _perform_swap
    from askwell.retrieve import register_search

    monkeypatch.setattr("askwell.model_select.SWAP_POLL_SECONDS", 0.01)
    settings = _settings(tmp_path)
    model = _gguf(tmp_path, "other.gguf")
    request = tmp_path / SWAP_REQUEST_FILENAME

    running = asyncio.create_task(_perform_swap(settings, model))
    for _ in range(500):
        if request.exists():
            break
        await asyncio.sleep(0.01)
    assert request.exists()
    # The swap is in flight: every generation permit is held and no result yet.
    assert generation_semaphore(settings).locked()

    app = FastAPI()
    register_search(app, settings, factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://askwell") as http:
        response = await asyncio.wait_for(http.get("/search", params={"q": "contract"}), 5)
    assert response.status_code == 200
    assert not running.done()

    (tmp_path / SWAP_RESULT_FILENAME).write_text(
        json.dumps({"model_file": "other.gguf", "ok": True}), encoding="utf-8"
    )
    assert (await asyncio.wait_for(running, timeout=5)).ok


@pytest.mark.parametrize("name", ["../x.gguf", "/models/x.gguf", "sub/x.gguf", ".."])
def test_only_a_bare_file_name_in_the_models_directory_is_accepted(
    tmp_path: Path, name: str
) -> None:
    """Issue #660: a path means a different place on each side of the
    container boundary, so only a name inside the shared directory does."""
    settings = _settings(tmp_path)
    _gguf(tmp_path, "x.gguf")
    with pytest.raises(ModelValidationError, match="not a file name"):
        resolve_model_file(settings, name)


# --- validated versus unverified ----------------------------------------------


async def test_an_unverified_model_is_refused_until_the_statement_was_shown(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`M7-SET-FE-146`'s validation rule: the unverified statement cannot be
    suppressed. Enforced at the endpoint, not only on screen, so no client
    reaches the swap without having shown it — and nothing is remembered,
    so the next swap needs it again."""
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)
    perform_swap = AsyncMock()
    monkeypatch.setattr("askwell.model_select._perform_swap", perform_swap)

    async with factory() as db:
        with pytest.raises(UnverifiedNotAcknowledged) as raised:
            await select_model(db, settings, model.name)

    assert str(raised.value) == UNVERIFIED_STATEMENT
    assert "Citations" in UNVERIFIED_STATEMENT and "not guaranteed" in UNVERIFIED_STATEMENT
    perform_swap.assert_not_called()


async def test_a_shipped_model_is_validated_by_its_bytes_under_any_name(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another tier's shipped model, renamed: its checksum, not its name,
    makes it validated — no statement needed, and the answer marker names it
    rather than this profile's model."""
    settings = _settings(tmp_path)
    model = _gguf(tmp_path, "renamed-anything.gguf", body=b"shipped-bytes")
    spec = _ship(monkeypatch, model)

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)
    _write_state(tmp_path, state=str(ProcessState.READY), model=model.name)

    async with factory() as db:
        outcome = await select_model(db, settings, model.name)
        await db.commit()
    assert outcome.ok

    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.SHIPPED)
        identity = await active_model_identity(db, settings)
    assert identity == {"source": str(ModelSource.SHIPPED), "display_name": spec.display_name}


async def test_a_file_with_a_shipped_models_size_but_other_bytes_is_unverified(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    shipped = _gguf(tmp_path, "real.gguf", body=b"shipped-bytes")
    _ship(monkeypatch, shipped)
    impostor = _gguf(tmp_path, "impostor.gguf", body=b"shipped-byteZ")  # same size

    listed = {c["file"]: c for c in list_candidates(settings, read_state(tmp_path / "none"))}
    assert listed["real.gguf"]["validated"] is True
    assert listed[impostor.name]["validated"] is False
    assert listed[impostor.name]["display_name"] == impostor.name


# --- the swap list -------------------------------------------------------


def test_candidates_leave_out_every_model_already_loaded(tmp_path: Path) -> None:
    """Issue #662: the model answering now is never offered as a swap to
    itself, and the embedding and reranking models are not answer models."""
    settings = _settings(tmp_path)
    for name in ("answering.gguf", "embed.gguf", "rank.gguf", "other.gguf"):
        _gguf(tmp_path, name)
    (tmp_path / "models" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "models" / "big.gguf.part").write_bytes(b"GGUF")
    _write_state(
        tmp_path,
        state=str(ProcessState.READY),
        model="answering.gguf",
        roles={
            "generation": {"state": "ready", "model": "answering.gguf"},
            "embedding": {"state": "ready", "model": "embed.gguf"},
            "reranking": {"state": "ready", "model": "rank.gguf"},
        },
    )

    state = read_state(tmp_path / "state.json")
    assert [c["file"] for c in list_candidates(settings, state)] == ["other.gguf"]


def test_no_models_directory_means_no_candidates_not_an_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert list_candidates(settings, read_state(tmp_path / "state.json")) == []


def test_the_shown_models_directory_is_the_host_path_when_given(tmp_path: Path) -> None:
    """`/models` means nothing on the user's machine — "place a model here"
    names the folder they can actually find."""
    settings = _settings(tmp_path).model_copy(
        update={
            "models_dir": Path("/models"),
            "models_dir_display": "~/.local/share/askwell/models",
        }
    )
    assert settings.models_dir_shown == "~/.local/share/askwell/models"
    assert _settings(tmp_path).models_dir_shown == str(tmp_path / "models")


# --- measured throughput -----------------------------------------------------


async def _answer(
    db: AsyncSession, display_name: str, generation: dict[str, object] | None
) -> None:
    import json
    import uuid

    conversation = uuid.uuid4()
    await db.execute(text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation})
    await db.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content, trace, model_identity) "
            "VALUES (:id, :c, 'assistant', 'x', CAST(:trace AS jsonb), CAST(:identity AS jsonb))"
        ),
        {
            "id": uuid.uuid4(),
            "c": conversation,
            "trace": json.dumps({"generation": generation}),
            "identity": json.dumps({"source": "shipped", "display_name": display_name}),
        },
    )


async def test_throughput_before_any_question_is_unmeasured_not_zero(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as db:
        measured = await measured_throughput(db, "Qwen3.5 4B (Q4_K_M)")
    assert measured == {
        "turns": 0,
        "tokens_per_second": None,
        "prompt_tokens_per_second": None,
        "median_answer_ms": None,
    }


async def test_throughput_is_weighted_over_real_turns_of_the_model_in_use(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two answers from the model in use: 40 tokens in 4 s and 10 in 1 s is
    10 tokens/s. An answer from another model, and a turn with no timings
    (stopped, abstained), do not count."""
    async with factory() as db:
        await _answer(
            db,
            "In use",
            {
                "predicted_tokens": 40,
                "predicted_ms": 4000,
                "prompt_tokens": 900,
                "prompt_ms": 30000,
                "duration_ms": 40000,
            },
        )
        await _answer(
            db,
            "In use",
            {
                "predicted_tokens": 10,
                "predicted_ms": 1000,
                "prompt_tokens": 100,
                "prompt_ms": 10000,
                "duration_ms": 20000,
            },
        )
        await _answer(db, "In use", None)
        # Not the shape `askwell.ask` writes — not a measurement at all.
        await _answer(db, "In use", {"tokens": 65, "tokens_per_second": 6.9})
        await _answer(
            db,
            "Another model",
            {
                "predicted_tokens": 1000,
                "predicted_ms": 1000,
                "prompt_tokens": 1,
                "prompt_ms": 1,
                "duration_ms": 1,
            },
        )
        await db.commit()

    async with factory() as db:
        measured = await measured_throughput(db, "In use")

    assert measured["turns"] == 2
    assert measured["tokens_per_second"] == pytest.approx(10.0)
    assert measured["prompt_tokens_per_second"] == pytest.approx(25.0)
    assert measured["median_answer_ms"] == 30000


# --- active identity, for stamping a message ---------------------------------


async def test_no_model_loaded_reads_as_none_not_a_guess(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.MODEL_MISSING))

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.NONE), "display_name": None}


async def test_the_default_is_shipped_only_when_its_bytes_are_a_shipped_models(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No swap ever made: the loaded default is checked, not assumed (#672)."""
    settings = _settings(tmp_path)
    default = _gguf(tmp_path, "Qwen_Qwen3.5-4B-Q4_K_M.gguf", body=b"shipped-bytes")
    spec = _ship(monkeypatch, default)
    _write_state(tmp_path, state=str(ProcessState.READY), model=default.name)

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.SHIPPED), "display_name": spec.display_name}


async def test_a_default_whose_bytes_match_no_shipped_model_is_user_supplied(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #672: a file placed under the default's name is not validated by
    its name. Its answers carry the unverified marker like any other."""
    settings = _settings(tmp_path)
    shipped = _gguf(tmp_path, "catalog.gguf", body=b"shipped-bytes")
    _ship(monkeypatch, shipped)
    shipped.unlink()
    default = _gguf(tmp_path, "Qwen_Qwen3.5-4B-Q4_K_M.gguf", body=b"shipped-byteZ")  # same size
    _write_state(tmp_path, state=str(ProcessState.READY), model=default.name)

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.USER_SUPPLIED), "display_name": default.name}


async def test_a_loaded_file_the_api_cannot_see_is_unknown_not_shipped(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="nowhere.gguf")

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.UNKNOWN), "display_name": "nowhere.gguf"}


async def test_a_recorded_swap_describes_the_file_it_was_recorded_for(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """The record written at a swap is trusted while that file is loaded."""
    settings = _settings(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="tiny.gguf")

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, "tiny.gguf")
        await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.USER_SUPPLIED))
        await set_setting(db, SETTING_ACTIVE_DISPLAY_NAME, "tiny.gguf")
        await db.commit()

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.USER_SUPPLIED), "display_name": "tiny.gguf"}


async def test_a_legacy_record_with_only_a_path_is_judged_by_the_loaded_bytes(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """A `M7-SET-BE-145a` record carried an absolute path and no display name."""
    settings = _settings(tmp_path)
    tiny = _gguf(tmp_path, "tiny.gguf")
    _write_state(tmp_path, state=str(ProcessState.READY), model=tiny.name)

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, "/home/user/models/tiny.gguf")
        await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.USER_SUPPLIED))
        await db.commit()

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.USER_SUPPLIED), "display_name": "tiny.gguf"}


async def test_a_supervisor_that_restarted_onto_its_default_is_not_named_as_the_swap(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #670: the record says a shipped model was swapped in, but the host
    rebooted a user-supplied default. The unverified marker must not be lost."""
    settings = _settings(tmp_path)
    shipped = _gguf(tmp_path, "other-tier.gguf", body=b"shipped-bytes")
    _ship(monkeypatch, shipped)
    default = _gguf(tmp_path, "my-default.gguf", body=b"their-own-bytes")
    _write_state(tmp_path, state=str(ProcessState.READY), model=default.name)

    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, shipped.name)
        await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.SHIPPED))
        await set_setting(db, SETTING_ACTIVE_DISPLAY_NAME, "Shipped accelerated model")
        await db.commit()

    async with factory() as db:
        identity = await active_model_identity(db, settings)

    assert identity == {"source": str(ModelSource.USER_SUPPLIED), "display_name": default.name}


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
        await set_setting(db, SETTING_USER_MODEL_PATH, model.name)
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
        assert "vanished.gguf" in row[1]["model_file"]


async def test_reapply_reads_a_pre_146_absolute_path_by_its_name(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selection persisted before `M7-SET-FE-146` holds a path; the file
    it names is found by name in the models directory."""
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model="shipped.gguf")
    swapped: list[Path] = []

    async def fake_perform_swap(_settings: Settings, path: Path) -> SwapOutcome:
        swapped.append(path)
        return SwapOutcome(ok=True, reason=None, model_path=path)

    monkeypatch.setattr("askwell.model_select._perform_swap", fake_perform_swap)
    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, f"/root/.local/share/x/{model.name}")
        await db.commit()

    await reapply_user_model(factory, settings)
    assert swapped == [model]


async def test_reapply_does_not_reload_the_model_already_answering(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    model = _gguf(tmp_path)
    _write_state(tmp_path, state=str(ProcessState.READY), model=model.name)
    perform_swap = AsyncMock()
    monkeypatch.setattr("askwell.model_select._perform_swap", perform_swap)
    async with factory() as db:
        await set_setting(db, SETTING_USER_MODEL_PATH, model.name)
        await db.commit()

    await reapply_user_model(factory, settings)

    perform_swap.assert_not_called()
    async with factory() as db:
        assert await get_setting(db, SETTING_ACTIVE_SOURCE) == str(ModelSource.USER_SUPPLIED)
