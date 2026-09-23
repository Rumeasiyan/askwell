"""A user-supplied model, and which model answered. `M7-SET-BE-145a`.

Three things this module is careful to keep separate.

**Selecting a model is not the same as swapping it.** Selection is validated
and persisted here; the swap itself happens on the host, inside
`deploy/inference/askwell-inference`, because that is the process that
actually owns the `llama-server` child (`docs/decisions.md`). This module and
that script agree on two file names in the same run directory the inference
socket and state file already live in — the same seam `askwell.model_download`
uses for a fetch, and `askwell.probe` for a hardware re-probe.

**A user-supplied model is never marked validated.** `validate_model_file`
only confirms the path is readable and looks like a GGUF file — enough to
reject a text file or a typo at selection time rather than at the next
question, per the ticket's own edge case. It is not the registry-license
check C9 requires, and never claims to be: C9 governs what Askwell *ships*
inside `models_catalog.py`; a file someone placed on their own disk carries
no such guarantee and this module does not invent one.

**Shipped-versus-user-supplied is a fact this module writes, never one it
infers.** The ticket's own validation rule forbids guessing the distinction
from a file name. So `active_model_identity` reads it back from
`SETTING_ACTIVE_SOURCE`, a value only ever written here, at the moment a swap
actually succeeds or fails — never compared against what is loaded.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.inference.state import ProcessState
from askwell.inference.state import read as read_inference_state
from askwell.logging import get_logger
from askwell.model_download import DownloadStatus, ModelDownloadManager, sha256_file
from askwell.models_catalog import ModelSpec, spec_for_sha256, spec_for_tier
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

# Both sides of the container boundary agree on these two names and nothing
# else, the same shape `askwell.model_download`'s `FETCH_REQUEST`/
# `FETCH_PROGRESS` already establishes: the API writes the first, the host
# supervisor writes the second.
SWAP_REQUEST_FILENAME = "model-swap-request.json"
SWAP_RESULT_FILENAME = "model-swap-result.json"

# How long a swap may take before the API gives up waiting and reports it
# timed out. Matches `askwell-inference`'s own `READY_TIMEOUT_SECONDS` — a
# swap that has not resolved by then is not going to, and the API should not
# claim to know less than the supervisor already does.
SWAP_TIMEOUT_SECONDS = 300.0
SWAP_POLL_SECONDS = 0.5

SETTING_USER_MODEL_PATH = "model.user_model_path"
SETTING_ACTIVE_SOURCE = "model.active_source"
# Set only alongside SETTING_ACTIVE_SOURCE=shipped, and only when the swap
# target was a *different* shipped tier than `settings.profile` configures
# (issue #632's fix): read back here rather than re-hashing a multi-GB file
# on every turn just to learn its display name again.
SETTING_ACTIVE_SHIPPED_DISPLAY_NAME = "model.active_shipped_display_name"

GGUF_MAGIC = b"GGUF"

# Above this fraction of probed RAM, a selection is still accepted — this
# product states consequences rather than blocking (AGENTS.md, this ticket's
# own edge case) — but the outcome carries a warning rather than pretending
# the file will simply work.
_SIZE_WARNING_RAM_FRACTION = 0.6


class ModelSource(StrEnum):
    SHIPPED = "shipped"
    USER_SUPPLIED = "user_supplied"
    NONE = "none"
    UNKNOWN = "unknown"


class ModelValidationError(Exception):
    """A path is not usable as a model. The message names the reason."""


@dataclass(frozen=True, slots=True)
class SwapOutcome:
    ok: bool
    reason: str | None
    model_path: Path
    size_warning: str | None = None


def validate_model_file(path: Path) -> Path:
    """Reject at selection, with the reason — never at the next question.

    Checks only that the path exists, is a regular file, is readable, and
    starts with the GGUF magic bytes `llama-server` requires. It is
    deliberately not a licence or provenance check (C9 is about what
    Askwell bundles, not about a file the user places themselves) and it is
    never described to the user as "validated" for that reason.
    """
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ModelValidationError(
            f"{path} is not an absolute path. Give the full path to the model file."
        )
    if not expanded.is_file():
        raise ModelValidationError(f"No file at {expanded}.")
    try:
        with open(expanded, "rb") as handle:
            magic = handle.read(len(GGUF_MAGIC))
    except OSError as error:
        raise ModelValidationError(f"{expanded} could not be read: {error}.") from error
    if magic != GGUF_MAGIC:
        raise ModelValidationError(
            f"{expanded} does not look like a GGUF model file — its first bytes are not "
            f"'GGUF'. Askwell's inference engine only loads GGUF files."
        )
    return expanded


def _size_warning(model_path: Path, settings: Settings) -> str | None:
    """The consequence of a model too large for the probed hardware, stated
    rather than acted on — this product never silently refuses a choice.
    """
    try:
        model_gb = model_path.stat().st_size / (1024**3)
    except OSError:
        return None

    ram_gb: float | None = None
    try:
        from askwell.probe import read_probe_result

        probed = read_probe_result(settings.probe_result_path)
        if probed is not None:
            ram_gb = probed.ram_gb
    except OSError:
        ram_gb = None

    if ram_gb is None:
        from askwell.hardware import probe as basic_probe

        ram_gb = basic_probe().ram_gb

    if ram_gb and model_gb > ram_gb * _SIZE_WARNING_RAM_FRACTION:
        return (
            f"This model file is {model_gb:.1f} GB and this machine has "
            f"{ram_gb:.1f} GB of RAM. It may load slowly, fail to fit in memory, "
            f"or make the machine unresponsive while it tries. Askwell will "
            f"still attempt to load it."
        )
    return None


def _run_dir(settings: Settings) -> Path:
    return settings.inference_socket.parent


async def _perform_swap(settings: Settings, model_path: Path) -> SwapOutcome:
    """Ask the host supervisor to swap, and wait for its answer.

    Holds every permit of `askwell.ask.generation_semaphore` for the
    duration: a turn already generating keeps its permit until it finishes
    (the swap waits behind it, not the other way round — the ticket's own
    "swap requested mid-answer" edge case), and no new turn can acquire one
    until the swap has released them, so a question asked during the swap
    queues rather than racing it.
    """
    from askwell.ask import generation_semaphore

    run_dir = _run_dir(settings)
    request_path = run_dir / SWAP_REQUEST_FILENAME
    result_path = run_dir / SWAP_RESULT_FILENAME

    limit = settings.generation_max_concurrent
    semaphore = generation_semaphore(settings)
    held = 0
    try:
        for _ in range(limit):
            await semaphore.acquire()
            held += 1

        run_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            result_path.unlink()
        request_path.write_text(json.dumps({"model_path": str(model_path)}), encoding="utf-8")

        deadline = time.monotonic() + SWAP_TIMEOUT_SECONDS
        outcome: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                candidate = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                candidate = None
            if isinstance(candidate, dict) and candidate.get("model_path") == str(model_path):
                outcome = candidate
                break
            await asyncio.sleep(SWAP_POLL_SECONDS)
    finally:
        for _ in range(held):
            semaphore.release()

    warning = _size_warning(model_path, settings)

    if outcome is None:
        return SwapOutcome(
            ok=False,
            reason=(
                f"The inference supervisor did not respond within "
                f"{SWAP_TIMEOUT_SECONDS:g}s. It runs on the host, not in a "
                f"container — confirm it is running with: scripts/dev.sh inference"
            ),
            model_path=model_path,
            size_warning=warning,
        )
    return SwapOutcome(
        ok=bool(outcome.get("ok")),
        reason=outcome.get("reason") if isinstance(outcome.get("reason"), str) else None,
        model_path=model_path,
        size_warning=warning,
    )


def _catalog_match(path: Path) -> ModelSpec | None:
    """Whether a swap target is a shipped model by content, not by name or
    which control reached it (issue #632). The same check
    `ModelDownloadManager.available_alternatives` already computes to build
    the swap-candidate list this ticket's settings screen renders — a path
    typed by hand that happens to match a catalog entry's bytes is just as
    validated as one reached via that list.
    """
    try:
        digest = sha256_file(path)
    except OSError:
        return None
    return spec_for_sha256(digest)


async def select_user_model(session: AsyncSession, settings: Settings, path: Path) -> SwapOutcome:
    """Validate, swap, persist. In that order — nothing is persisted unless
    the swap that follows validation actually succeeded (`docs/audit-log.md`
    §2: settings changes are a decisions record either way).
    """
    validated = validate_model_file(path)
    outcome = await _perform_swap(settings, validated)

    await record(
        session,
        Store.DECISIONS,
        "model_swap_requested",
        {
            "model_path": str(validated),
            "ok": outcome.ok,
            "reason": outcome.reason or "",
        },
    )

    if outcome.ok:
        # Hashing a multi-GB file is the same cost `available_alternatives`
        # already pays to build the list this swap likely came from — off
        # the event loop for the same reason `GET /model` already guards.
        matched = await asyncio.to_thread(_catalog_match, validated)
        await set_setting(session, SETTING_USER_MODEL_PATH, str(validated))
        if matched is not None:
            await set_setting(session, SETTING_ACTIVE_SOURCE, str(ModelSource.SHIPPED))
            await set_setting(session, SETTING_ACTIVE_SHIPPED_DISPLAY_NAME, matched.display_name)
        else:
            await set_setting(session, SETTING_ACTIVE_SOURCE, str(ModelSource.USER_SUPPLIED))

    return outcome


async def active_model_identity(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    """What a message written right now should carry.

    `source` is never derived by inspecting the loaded file's name — only
    from `SETTING_ACTIVE_SOURCE`, which this module is the only writer of.
    """
    state = read_inference_state(settings.inference_socket.parent / "state.json")
    if not state.usable:
        return {"source": str(ModelSource.NONE), "display_name": None}

    source = await get_setting(session, SETTING_ACTIVE_SOURCE)
    if source == str(ModelSource.USER_SUPPLIED):
        user_path = await get_setting(session, SETTING_USER_MODEL_PATH)
        return {
            "source": str(ModelSource.USER_SUPPLIED),
            "display_name": Path(user_path).name if user_path else state.model,
        }

    # A swap to a shipped alternative (issue #632) may be a different tier
    # than `settings.profile` configures — its own recorded display name
    # takes precedence over guessing from the configured profile.
    swapped_display_name = await get_setting(session, SETTING_ACTIVE_SHIPPED_DISPLAY_NAME)
    if swapped_display_name:
        return {"source": str(ModelSource.SHIPPED), "display_name": swapped_display_name}

    shipped = spec_for_tier(str(settings.profile))
    return {"source": str(ModelSource.SHIPPED), "display_name": shipped.display_name}


async def reapply_user_model(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    """Put the persisted selection back in front of the inference process
    after a restart (`M7-SET-BE-145a`'s own acceptance criterion: a
    user-supplied model "persists across a restart, and is the model
    actually used for the next answer").

    Runs as a background task from application startup rather than blocking
    it — the shipped default the host boots with can take up to five minutes
    to answer on a cold, light-profile machine, and startup must not wait on
    that twice.
    """
    async with session_scope(factory) as db:
        user_path = await get_setting(db, SETTING_USER_MODEL_PATH)
    if not user_path:
        return

    state_path = settings.inference_socket.parent / "state.json"
    deadline = time.monotonic() + SWAP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = read_inference_state(state_path)
        if state.usable:
            break
        if state.state in (ProcessState.MODEL_MISSING, ProcessState.UNAVAILABLE):
            log.warning("model_reapply_skipped", reason=state.reason)
            return
        await asyncio.sleep(1.0)
    else:
        log.warning("model_reapply_timed_out", model_path=user_path)
        return

    try:
        validated = validate_model_file(Path(user_path))
    except ModelValidationError as error:
        log.warning("model_reapply_invalid", model_path=user_path, error=str(error))
        async with session_scope(factory) as db:
            await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.SHIPPED))
            await record(
                db,
                Store.DECISIONS,
                "model_reapply_failed",
                {"model_path": user_path, "reason": str(error)},
            )
        return

    outcome = await _perform_swap(settings, validated)
    async with session_scope(factory) as db:
        await set_setting(
            db,
            SETTING_ACTIVE_SOURCE,
            str(ModelSource.USER_SUPPLIED if outcome.ok else ModelSource.SHIPPED),
        )
        await record(
            db,
            Store.DECISIONS,
            "model_reapplied" if outcome.ok else "model_reapply_failed",
            {"model_path": str(validated), "ok": outcome.ok, "reason": outcome.reason or ""},
        )
    if not outcome.ok:
        log.warning("model_reapply_failed", model_path=str(validated), reason=outcome.reason)


class SelectModelRequest(BaseModel):
    model_path: str


def register_model_select(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach `/model`. `M7-SET-BE-145a`'s own backend half of the settings
    section `M7-SET-FE-146` renders.
    """

    @app.get("/model")
    async def model_state(request: Request) -> JSONResponse:
        async with session_scope(factory) as db:
            identity = await active_model_identity(db, settings)
            user_path = await get_setting(db, SETTING_USER_MODEL_PATH)

        manager: ModelDownloadManager = request.app.state.model_download
        # Same guard `askwell.setup._model_dict` already uses: a transfer
        # that is `DOWNLOADING`/`VERIFYING` gets polled repeatedly, and
        # hashing every catalog-recognised sibling file on each of those
        # polls costs far more than the answer is worth while nothing about
        # the directory is likely changing (#612). Off the event loop the
        # rest of the time, same reason as `setup`'s.
        progress = manager.snapshot(str(settings.profile))
        alternatives = (
            await asyncio.to_thread(manager.available_alternatives)
            if progress.status not in (DownloadStatus.DOWNLOADING, DownloadStatus.VERIFYING)
            else []
        )

        # Memory footprint, `M7-SET-FE-146`: the file size of whichever
        # model is actually active — real and already on disk, not a rating.
        # Not the resident RAM `llama-server` holds once loaded (this
        # process has no way to read that), but the honest number available
        # without adding a probe to the inference bridge for it. `user_path`
        # is set by any successful swap regardless of source label — a
        # swap to a shipped alternative (issue #632) still changes which
        # file is active, so it takes precedence over `manager.target_path`
        # (the *configured profile's* default) the same as a user-supplied
        # swap does.
        active_path = Path(user_path) if user_path else manager.target_path
        try:
            size_gb: float | None = active_path.stat().st_size / (1024**3)
        except OSError:
            size_gb = None

        return JSONResponse(
            {
                **identity,
                "user_model_path": user_path,
                "expected_path": str(manager.target_path),
                "alternatives": alternatives,
                "active_model_size_gb": size_gb,
            }
        )

    @app.post("/model/select")
    async def model_select(body: SelectModelRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                outcome = await select_user_model(db, settings, Path(body.model_path))
        except ModelValidationError as error:
            return JSONResponse({"error": str(error)}, status_code=422)

        return JSONResponse(
            {
                "ok": outcome.ok,
                "reason": outcome.reason,
                "model_path": str(outcome.model_path),
                "size_warning": outcome.size_warning,
            },
            status_code=200 if outcome.ok else 409,
        )
