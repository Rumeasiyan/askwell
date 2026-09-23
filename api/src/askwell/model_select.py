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

**Shipped-versus-user-supplied is decided by bytes, never by a name.** The
ticket's own validation rule forbids guessing the distinction from a file
name. A file whose sha256 matches a `models_catalog` entry is that shipped
model under any name; anything else is user-supplied (`M7-SET-FE-146`). A
swap writes that verdict to `SETTING_ACTIVE_SOURCE`; `active_model_identity`
trusts the record only while the loaded file is the one it was written for,
and otherwise checks the loaded file's own bytes (issues #670, #672).

**A model is named across the container boundary by file name only**
(`M7-SET-FE-146`, issue #660). The API sees the models directory at
`Settings.models_dir` (`/models` in the stack); the host supervisor sees it
wherever the user keeps it. A path means a different place on each side, so
the swap request carries a bare file name and each side resolves it against
its own view of the one shared directory.
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

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.db.models import Message
from askwell.inference.state import InferenceState, ProcessState
from askwell.inference.state import read as read_inference_state
from askwell.logging import get_logger
from askwell.model_download import sha256_cached
from askwell.models_catalog import CATALOG, ModelSpec, spec_for_sha256
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

# Holds a file name inside the models directory since `M7-SET-FE-146`. A
# value written before then is an absolute path; only its name is used.
SETTING_USER_MODEL_PATH = "model.user_model_path"
SETTING_ACTIVE_SOURCE = "model.active_source"
# The display name written alongside the source at a successful swap, so a
# swap to another tier's shipped model names that model, not this profile's.
SETTING_ACTIVE_DISPLAY_NAME = "model.active_display_name"

# How many recent answers the throughput figures average over. A rolling
# window over real turns (issue #617), not a benchmark: recent enough to
# follow a swap, long enough that one unusually long answer does not swing it.
THROUGHPUT_WINDOW = 20

UNVERIFIED_STATEMENT = (
    "This model has not been tested against Askwell's checks. Citations and "
    '"I don\'t know" are behaviours Askwell verifies for the models it ships. '
    "With your own model, they are not guaranteed."
)

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


class UnverifiedNotAcknowledged(Exception):
    """A swap to an unverified model was asked for without the request
    carrying that the statement was shown. `M7-SET-FE-146`'s validation rule:
    the statement cannot be suppressed — enforced here, not only on screen,
    so no client can make the swap frictionless by skipping it.
    """


class SwapInProgress(Exception):
    """A swap was asked for while another was still running (issue #675).

    Refused rather than queued: the second request is almost always a second
    tab or a stale click, and queueing it would silently swap again after the
    first finished. The message says nothing changed.
    """


# One swap at a time. Two overlapping swaps would each take some of the
# generation permits and wait forever for the rest, hanging every answer
# until a restart, and would overwrite each other's request and result files
# (issue #675).
_swap_lock = asyncio.Lock()

SWAP_IN_PROGRESS_REASON = (
    "Another model swap is already running. Nothing was changed by this request."
)


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


def resolve_model_file(settings: Settings, name: str) -> Path:
    """A file name inside the models directory, validated.

    A name carrying a directory is refused rather than resolved: the host
    supervisor resolves the same name against its own view of this
    directory, and only a bare name means the same file on both sides.
    """
    if not name or name in (".", "..") or Path(name).name != name or "\\" in name:
        raise ModelValidationError(
            f"{name!r} is not a file name. Place the model file in "
            f"{settings.models_dir_shown} and choose it by name."
        )
    return validate_model_file(settings.models_dir / name)


def shipped_spec_for_file(path: Path) -> ModelSpec | None:
    """The catalog entry this file's bytes are, if any — never its name.

    Only a file whose size equals a catalog entry's is hashed at all, and a
    hash is paid once per version of the file (`sha256_cached`, issue #669).
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size not in {spec.size_bytes for spec in CATALOG.values()}:
        return None
    try:
        return spec_for_sha256(sha256_cached(path))
    except OSError:
        return None


def list_candidates(settings: Settings, state: InferenceState) -> list[dict[str, Any]]:
    """Every model file in the models directory a swap could go to.

    Everything with a `.gguf` suffix, less what is already loaded: the
    generation model answering now (issue #662 — never offered as a swap to
    itself) and the embedding and reranking models, which are not answer
    models at all. Each is marked validated only if its bytes are a shipped
    model's. Blocking — hashes on first sight; call off the event loop.
    """
    directory = settings.models_dir
    if not directory.is_dir():
        return []
    loaded = {state.model, *(role.model for role in state.roles.values())}
    loaded |= {settings.embedding_model_path.name, settings.reranker_model_path.name}
    candidates: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() != ".gguf" or path.name in loaded or not path.is_file():
            continue
        spec = shipped_spec_for_file(path)
        candidates.append(
            {
                "file": path.name,
                "display_name": spec.display_name if spec is not None else path.name,
                "validated": spec is not None,
                "size_bytes": path.stat().st_size,
            }
        )
    return candidates


async def measured_throughput(session: AsyncSession, display_name: str | None) -> dict[str, Any]:
    """Tokens per second and typical answer time, from real answers.

    Over the last `THROUGHPUT_WINDOW` completed answers the model now in use
    produced (`messages.trace["generation"]`, written by `askwell.ask`).
    Weighted by tokens rather than a mean of per-turn rates, so a two-token
    answer does not count as much as a two-hundred-token one. Nothing
    measured yet is `turns: 0` with every figure `None` — the screen says so
    rather than showing zero.

    `median_answer_ms` is there because generation speed alone does not
    explain a slow answer on CPU: reading the retrieved passages first is
    most of the wait (issue #661).
    """
    empty: dict[str, Any] = {
        "turns": 0,
        "tokens_per_second": None,
        "prompt_tokens_per_second": None,
        "median_answer_ms": None,
    }
    if display_name is None:
        return empty

    rows = (
        await session.execute(
            select(Message.trace)
            .where(Message.role == "assistant")
            .where(Message.model_identity["display_name"].astext == display_name)
            .order_by(Message.created_at_.desc())
            .limit(THROUGHPUT_WINDOW * 5)
        )
    ).scalars()

    measured: list[dict[str, Any]] = []
    for trace in rows:
        generation = trace.get("generation") if isinstance(trace, dict) else None
        if _is_measurement(generation):
            assert isinstance(generation, dict)
            measured.append(generation)
        if len(measured) == THROUGHPUT_WINDOW:
            break
    if not measured:
        return empty

    def rate(tokens_key: str, ms_key: str) -> float | None:
        tokens = sum(float(g.get(tokens_key) or 0) for g in measured)
        ms = sum(float(g.get(ms_key) or 0) for g in measured)
        return tokens * 1000.0 / ms if ms > 0 and tokens > 0 else None

    durations = sorted(int(g.get("duration_ms") or 0) for g in measured)
    middle = len(durations) // 2
    median = (
        durations[middle]
        if len(durations) % 2
        else (durations[middle - 1] + durations[middle]) // 2
    )
    return {
        "turns": len(measured),
        "tokens_per_second": rate("predicted_tokens", "predicted_ms"),
        "prompt_tokens_per_second": rate("prompt_tokens", "prompt_ms"),
        "median_answer_ms": median if median > 0 else None,
    }


def _is_measurement(generation: object) -> bool:
    """A `trace["generation"]` in the shape `askwell.ask` writes — anything
    else (absent, `None`, another shape) is not a measurement and must not
    count as a turn with nothing measured in it."""
    if not isinstance(generation, dict):
        return False
    keys = ("predicted_tokens", "predicted_ms", "prompt_tokens", "prompt_ms", "duration_ms")
    return all(
        isinstance(generation.get(key), (int, float)) and not isinstance(generation.get(key), bool)
        for key in keys
    )


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

    Raises `SwapInProgress` without touching anything if another swap holds
    `_swap_lock`.
    """
    if _swap_lock.locked():
        raise SwapInProgress(SWAP_IN_PROGRESS_REASON)
    async with _swap_lock:
        return await _perform_swap_locked(settings, model_path)


async def _perform_swap_locked(settings: Settings, model_path: Path) -> SwapOutcome:
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
        request_path.write_text(json.dumps({"model_file": model_path.name}), encoding="utf-8")

        deadline = time.monotonic() + SWAP_TIMEOUT_SECONDS
        outcome: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                candidate = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                candidate = None
            if isinstance(candidate, dict) and candidate.get("model_file") == model_path.name:
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


async def select_model(
    session: AsyncSession,
    settings: Settings,
    model_file: str,
    *,
    acknowledged_unverified: bool = False,
) -> SwapOutcome:
    """Validate, classify, swap, persist. In that order — nothing is
    persisted unless the swap that follows actually succeeded
    (`docs/audit-log.md` §2: settings changes are a decisions record either
    way).

    An unverified model is permitted — the consequence is stated, never
    blocked — but only once the request says the statement was shown.
    """
    validated = resolve_model_file(settings, model_file)
    spec = await asyncio.to_thread(shipped_spec_for_file, validated)
    if spec is None and not acknowledged_unverified:
        raise UnverifiedNotAcknowledged(UNVERIFIED_STATEMENT)

    outcome = await _perform_swap(settings, validated)

    await record(
        session,
        Store.DECISIONS,
        "model_swap_requested",
        {
            "model_file": validated.name,
            "validated": spec is not None,
            "ok": outcome.ok,
            "reason": outcome.reason or "",
        },
    )

    if outcome.ok:
        await _persist_active(session, validated.name, spec)

    return outcome


async def _persist_active(session: AsyncSession, model_file: str, spec: ModelSpec | None) -> None:
    await set_setting(session, SETTING_USER_MODEL_PATH, model_file)
    await set_setting(
        session,
        SETTING_ACTIVE_SOURCE,
        str(ModelSource.SHIPPED if spec is not None else ModelSource.USER_SUPPLIED),
    )
    await set_setting(
        session, SETTING_ACTIVE_DISPLAY_NAME, spec.display_name if spec is not None else model_file
    )


async def active_model_identity(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    """What a message written right now should carry.

    `source` is never derived from the loaded file's name. It comes from
    `SETTING_ACTIVE_SOURCE` (this module is its only writer) while that
    record describes the loaded file, and otherwise from the loaded file's
    own bytes (issues #670, #672).
    """
    state = read_inference_state(settings.inference_socket.parent / "state.json")
    if not state.usable:
        return {"source": str(ModelSource.NONE), "display_name": None}

    source = await get_setting(session, SETTING_ACTIVE_SOURCE)
    display = await get_setting(session, SETTING_ACTIVE_DISPLAY_NAME)
    user_path = await get_setting(session, SETTING_USER_MODEL_PATH)
    recorded = (
        source in (str(ModelSource.SHIPPED), str(ModelSource.USER_SUPPLIED))
        and bool(display)
        and bool(user_path)
        and Path(str(user_path)).name == state.model
    )
    if recorded:
        # The swap that loaded this file classified its bytes and wrote this.
        return {"source": str(source), "display_name": display}

    # No swap recorded (a fresh install's default, issue #672), or the
    # supervisor is running something other than what was recorded (it
    # restarted on its own and booted the default, issue #670). Either way
    # the record does not describe what is loaded, so the loaded file's own
    # bytes decide — the same checksum a swap uses, cached per file version.
    # The name is only compared to withdraw the record, never to make a claim.
    return await asyncio.to_thread(_identity_of_loaded, settings, state.model)


def _identity_of_loaded(settings: Settings, model_file: str | None) -> dict[str, Any]:
    """Shipped only when the loaded file's bytes are a catalog entry's.

    A file the API cannot see is `unknown`, not shipped: nothing was checked.
    Blocking — may hash on first sight of a file version.
    """
    if not model_file:
        return {"source": str(ModelSource.UNKNOWN), "display_name": None}
    path = settings.models_dir / model_file
    if not path.is_file():
        return {"source": str(ModelSource.UNKNOWN), "display_name": model_file}
    spec = shipped_spec_for_file(path)
    if spec is not None:
        return {"source": str(ModelSource.SHIPPED), "display_name": spec.display_name}
    return {"source": str(ModelSource.USER_SUPPLIED), "display_name": model_file}


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
        # Nothing to reapply, but the first answer stamps the loaded model's
        # identity from its bytes (issue #672). Hash it now, off the request
        # path, if it is already loaded; otherwise the first question pays.
        booted = read_inference_state(settings.inference_socket.parent / "state.json")
        if booted.usable:
            await asyncio.to_thread(_identity_of_loaded, settings, booted.model)
        return
    # A value from before `M7-SET-FE-146` is a path; only its name means the
    # same file on both sides of the container boundary.
    model_file = Path(user_path).name

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
        validated = resolve_model_file(settings, model_file)
    except ModelValidationError as error:
        log.warning("model_reapply_invalid", model_file=model_file, error=str(error))
        async with session_scope(factory) as db:
            await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.SHIPPED))
            await set_setting(db, SETTING_ACTIVE_DISPLAY_NAME, "")
            await record(
                db,
                Store.DECISIONS,
                "model_reapply_failed",
                {"model_file": model_file, "reason": str(error)},
            )
        return

    spec = await asyncio.to_thread(shipped_spec_for_file, validated)
    if state.model == validated.name:
        # Already what the host booted with — a swap would only make the
        # assistant unavailable to reload the same file.
        async with session_scope(factory) as db:
            await _persist_active(db, validated.name, spec)
        return

    try:
        outcome = await _perform_swap(settings, validated)
    except SwapInProgress:
        # The user swapped from Settings while this startup reapply waited.
        # Their swap records its own outcome; writing ours would overwrite it.
        log.info("model_reapply_skipped", reason=SWAP_IN_PROGRESS_REASON)
        return
    async with session_scope(factory) as db:
        if outcome.ok:
            await _persist_active(db, validated.name, spec)
        else:
            await set_setting(db, SETTING_ACTIVE_SOURCE, str(ModelSource.SHIPPED))
            await set_setting(db, SETTING_ACTIVE_DISPLAY_NAME, "")
        await record(
            db,
            Store.DECISIONS,
            "model_reapplied" if outcome.ok else "model_reapply_failed",
            {"model_file": validated.name, "ok": outcome.ok, "reason": outcome.reason or ""},
        )
    if not outcome.ok:
        log.warning("model_reapply_failed", model_path=str(validated), reason=outcome.reason)


class SelectModelRequest(BaseModel):
    model_file: str
    # True only when the client showed `UNVERIFIED_STATEMENT` for this swap.
    acknowledged_unverified: bool = False


def register_model_select(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach `/model`. `M7-SET-BE-145a`'s own backend half of the settings
    section `M7-SET-FE-146` renders.
    """

    @app.get("/model")
    async def model_state() -> JSONResponse:
        state = read_inference_state(settings.inference_socket.parent / "state.json")
        async with session_scope(factory) as db:
            identity = await active_model_identity(db, settings)
            throughput = await measured_throughput(db, identity["display_name"])

        # Hashes a file it has not seen before; off the event loop for the
        # same reason `askwell.setup`'s poll path already guards against it.
        candidates = await asyncio.to_thread(list_candidates, settings, state)

        loaded_bytes: int | None = None
        if state.model:
            with contextlib.suppress(OSError):
                loaded_bytes = (settings.models_dir / state.model).stat().st_size

        return JSONResponse(
            {
                **identity,
                "state": str(state.state),
                "reason": state.reason,
                "loaded_file": state.model,
                "memory_bytes": state.memory_bytes if state.usable else None,
                # Resident memory leaves out whatever llama.cpp offloaded to a
                # graphics card, so the screen has to say so (issue #674).
                "acceleration": state.acceleration if state.usable else None,
                "file_bytes": loaded_bytes,
                "throughput": throughput,
                "models_dir": settings.models_dir_shown,
                "candidates": candidates,
                "unverified_statement": UNVERIFIED_STATEMENT,
                # The longest a swap waits before reporting failure — the
                # "expected duration" the swap states, from the one constant
                # the wait itself uses rather than a number re-typed on screen.
                "swap_timeout_seconds": int(SWAP_TIMEOUT_SECONDS),
            }
        )

    @app.post("/model/select")
    async def model_select(body: SelectModelRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                outcome = await select_model(
                    db,
                    settings,
                    body.model_file,
                    acknowledged_unverified=body.acknowledged_unverified,
                )
        except ModelValidationError as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        except UnverifiedNotAcknowledged as error:
            return JSONResponse(
                {"error": str(error), "unverified_statement_required": True}, status_code=422
            )
        except SwapInProgress as error:
            return JSONResponse(
                {
                    "ok": False,
                    "reason": str(error),
                    "model_file": body.model_file,
                    "size_warning": None,
                },
                status_code=409,
            )

        return JSONResponse(
            {
                "ok": outcome.ok,
                "reason": outcome.reason,
                "model_file": outcome.model_path.name,
                "size_warning": outcome.size_warning,
            },
            status_code=200 if outcome.ok else 409,
        )
