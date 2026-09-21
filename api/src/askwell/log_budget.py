"""Log storage budget: measurement and staged degradation.

`docs/audit-log.md` §3, `docs/states-and-edge-cases.md` §1, ticket
`M7-LOG-BE-153`.

Three stages that matter here (a fourth, the decisions store itself failing to
write, is already `askwell.audit`'s generic fail-the-action behaviour and
needs nothing new):

1. Under 80% of budget — nothing happens.
2. 80% and over — a notice, surfaced by `GET /log-budget` for the settings
   screen to render. Never enforced here; a notice is not a refusal.
3. At or over budget — new ingestion is refused (`IngestionRefused`), while
   asking questions is untouched, because ingestion is the biggest writer and
   stopping it first keeps the product usable.

The budget measured against is not the configured cap alone. It is the
smaller of the configured cap and 5% of *current* free disk, recomputed on
every call rather than snapshotted once at install — so a disk that fills
from something else entirely tightens the effective budget the same way
lowering the setting would (the ticket's own edge case). This is also why a
lowered setting shows the notice immediately: nothing is cached between calls.

Measured across the interaction store and the trace ring buffer only. The
decisions store is excluded on purpose — it is kilobytes, kept forever, and
never part of what a budget prunes (`docs/audit-log.md` §8).
"""

import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting
from askwell.traces import TraceRing

log = get_logger(__name__)

BUDGET_KEY = "log_budget_bytes"
BUDGET_CHANGED = "log_budget_changed"
_STAGE_KEY = "log_budget_stage"

DEFAULT_BUDGET_BYTES = 2 * 1024**3  # 2 GB, `docs/audit-log.md` §8
FREE_DISK_FRACTION = 0.05
NOTICE_RATIO = 0.80

# `docs/audit-log.md` §8. Only the *value* lives here — the prune that acts on
# it is `M7-LOG-BE-154`, not yet built, and this module does not pretend
# otherwise (`docs/decisions.md`, this date).
RETENTION_KEY = "interaction_retention_months"
RETENTION_CHANGED = "interaction_retention_changed"
DEFAULT_RETENTION_MONTHS = 12


class Stage(StrEnum):
    OK = "ok"
    NOTICE = "notice"
    HARD_LIMIT = "hard_limit"


class IngestionRefused(RuntimeError):
    """New ingestion cannot proceed: log storage is at its hard limit."""


class InvalidBudget(ValueError):
    """A budget of zero or less would make every stage HARD_LIMIT forever."""


@dataclass(frozen=True, slots=True)
class Usage:
    interactions_bytes: int
    traces_bytes: int
    budget_bytes: int
    # The cap the user actually set (issue #484). `budget_bytes` above is the
    # *effective* cap — `min(configured_bytes, 5% of free disk)` — so a caller
    # can tell "you set this" from "free disk is overriding what you set"
    # only by comparing the two; neither field alone says which is true.
    configured_bytes: int
    free_disk_bytes: int
    stage: Stage

    @property
    def used_bytes(self) -> int:
        return self.interactions_bytes + self.traces_bytes

    def as_dict(self) -> dict[str, object]:
        return {
            "interactions_bytes": self.interactions_bytes,
            "traces_bytes": self.traces_bytes,
            "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes,
            "configured_bytes": self.configured_bytes,
            "free_disk_bytes": self.free_disk_bytes,
            "stage": self.stage.value,
        }


async def get_configured_budget(session: AsyncSession) -> int:
    """The user's own cap, or the shipped default if never set."""
    stored = await get_setting(session, BUDGET_KEY)
    return DEFAULT_BUDGET_BYTES if stored is None else int(stored)


async def set_budget(session: AsyncSession, budget_bytes: int) -> int:
    """The only way the cap changes. Always a decisions record — a budget
    change is exactly the kind of thing `docs/audit-log.md` §7 lists.
    """
    if budget_bytes <= 0:
        raise InvalidBudget("Log storage budget must be a positive number of bytes.")
    previous = await get_configured_budget(session)
    await set_setting(session, BUDGET_KEY, str(budget_bytes))
    await record(
        session,
        Store.DECISIONS,
        BUDGET_CHANGED,
        {"previous_bytes": str(previous), "new_bytes": str(budget_bytes)},
    )
    return budget_bytes


async def _interactions_bytes(session: AsyncSession) -> int:
    result = await session.execute(
        text(f"SELECT pg_total_relation_size('{Store.INTERACTIONS.value}')")
    )
    return int(result.scalar_one())


def _free_disk_bytes(directory: Path) -> int:
    # `directory` may not exist yet on a fresh install — `TraceRing` creates it
    # lazily on first write. Its parent is on the same filesystem and always
    # exists once the container image is unpacked.
    probe = directory if directory.exists() else directory.parent
    return shutil.disk_usage(probe).free


def stage_for(used_bytes: int, budget_bytes: int) -> Stage:
    if budget_bytes <= 0 or used_bytes >= budget_bytes:
        return Stage.HARD_LIMIT
    if used_bytes >= budget_bytes * NOTICE_RATIO:
        return Stage.NOTICE
    return Stage.OK


async def _note_transition(session: AsyncSession, stage: Stage) -> None:
    """Log a stage change once, the first time each call notices it.

    Not itself a decisions record — the ticket's own Audit Requirement draws
    that line at budget *changes*, made by a person; a stage transition is
    the system noticing, and belongs in the ordinary structured log.
    """
    previous = await get_setting(session, _STAGE_KEY)
    if previous == stage.value:
        return
    await set_setting(session, _STAGE_KEY, stage.value)
    log.info("log_budget_stage_transition", previous=previous, stage=stage.value)


async def measure(session: AsyncSession, settings: Settings) -> Usage:
    """Current usage and stage, recomputed fresh every call."""
    configured = await get_configured_budget(session)
    free_disk = _free_disk_bytes(settings.trace_dir)
    effective_budget = min(configured, int(free_disk * FREE_DISK_FRACTION))

    interactions = await _interactions_bytes(session)
    traces = TraceRing(settings.trace_dir, settings.trace_max_bytes).total_bytes()

    stage = stage_for(interactions + traces, effective_budget)
    await _note_transition(session, stage)

    return Usage(
        interactions_bytes=interactions,
        traces_bytes=traces,
        budget_bytes=effective_budget,
        configured_bytes=configured,
        free_disk_bytes=free_disk,
        stage=stage,
    )


class InvalidRetention(ValueError):
    """A retention window of zero or fewer months has no meaning."""


async def get_retention_months(session: AsyncSession) -> int:
    """The user's own interaction-retention window, or the shipped default."""
    stored = await get_setting(session, RETENTION_KEY)
    return DEFAULT_RETENTION_MONTHS if stored is None else int(stored)


async def set_retention_months(session: AsyncSession, months: int) -> int:
    """The only way the window changes. Always a decisions record, same shape
    as `set_budget` above — a retention change is exactly the kind of thing
    `docs/audit-log.md` §7 lists. This does not itself prune anything: the
    prune that acts on this value is `M7-LOG-BE-154`, not yet built.
    """
    if months <= 0:
        raise InvalidRetention("Retention window must be a positive number of months.")
    previous = await get_retention_months(session)
    await set_setting(session, RETENTION_KEY, str(months))
    await record(
        session,
        Store.DECISIONS,
        RETENTION_CHANGED,
        {"previous_months": str(previous), "new_months": str(months)},
    )
    return months


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover - unreachable, GB always returns above


async def enforce_ingestion_allowed(session: AsyncSession, settings: Settings) -> None:
    """Raise `IngestionRefused` if log storage is at its hard limit.

    Called from the add-source routes only. Asking a question never calls
    this — that is the entire point of staging the refusal here rather than
    behind a blanket disk check every request goes through.
    """
    usage = await measure(session, settings)
    if usage.stage is not Stage.HARD_LIMIT:
        return
    raise IngestionRefused(
        f"Log storage is at its limit ({_human(usage.used_bytes)} of "
        f"{_human(usage.budget_bytes)}). New ingestion is refused until space "
        f"is freed — export, archive or prune the log, or free disk space. "
        f"Asking questions still works."
    )


class SetBudgetRequest(BaseModel):
    budget_bytes: int = Field(gt=0)


class SetRetentionRequest(BaseModel):
    months: int = Field(gt=0)


def register_log_budget(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`GET`/`POST /log-budget` — read current usage and stage, and change the
    cap. The same read/write-pair shape `register_retrieval_threshold` already
    established for a per-install setting that is also a decisions record.

    `GET`/`POST /log-budget/retention` is the same shape for the interaction
    retention window (`docs/audit-log.md` §8) — the value only, not the prune
    that acts on it (`M7-LOG-BE-154`).
    """

    @app.get("/log-budget")
    async def get_log_budget() -> JSONResponse:
        async with session_scope(factory) as db:
            usage = await measure(db, settings)
        return JSONResponse(usage.as_dict())

    @app.post("/log-budget")
    async def set_log_budget(body: SetBudgetRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            await set_budget(db, body.budget_bytes)
            usage = await measure(db, settings)
        return JSONResponse(usage.as_dict())

    @app.get("/log-budget/retention")
    async def get_retention() -> JSONResponse:
        async with session_scope(factory) as db:
            months = await get_retention_months(db)
        return JSONResponse({"months": months})

    @app.post("/log-budget/retention")
    async def set_retention(body: SetRetentionRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            months = await set_retention_months(db, body.months)
        return JSONResponse({"months": months})
