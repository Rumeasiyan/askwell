"""The update check, agreed to at installation. `M7-UPDATE-BE-161`.

`docs/decisions.md`, 2026-09-21, settled the shape: asked once, at
installation, in plain words, stating exactly what is sent. Yes means a
weekly check against the published release feed; no, or a dismissed
question, means the request is never made at all. This module is the
mechanism that decision described — not the install prompt itself
(`M7-PACK-DEPLOY-139`/`140`/`141`) and not how a found update is presented
(`M7-UPDATE-FE-162`). It learns that a newer version exists. Nothing more.

`M7-UPDATE-FE-162` adds three things the presentation needs and nothing
else: the date Askwell first learned of the newest version it knows about
(the feed is the bare `VERSION` file and carries no release date, so the
honest date is "found on", never "released on"), the version the person
dismissed the marker for, and a decisions record when an upgrade has been
applied (`record_running_version`).

**The stored answer has three states, and the third is load-bearing.**
`not_asked` is not `no` in the database — an install that has never been
asked must read that way forever, through any number of upgrades, so a
later decision to ask retroactively never gets confused with a decision the
user actually made. Operationally the two behave identically (no check
fires for either) — `maybe_run_scheduled_check` treats anything other than
`yes` as "do not run" — but the settings screen and the installer both need
to tell them apart, so the value itself has to.

**The permitted destination is Redis, not a stored default.** `askwell.egress`
reads it fresh on every connection; `set_answer` here is what changes it, in
the same moment the answer changes, so a "no" closes the door before this
call returns rather than on the proxy's next restart. A manual check works
regardless of the stored answer — `run_check(manual=True)` opens the door for
exactly the one request it needs and closes it again afterwards unless the
standing answer is already `yes`, in which case there is nothing to close.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import __version__, egress
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

ANSWER_KEY = "update_check_answer"
LAST_CHECKED_KEY = "update_check_last_checked_at"
LATEST_KNOWN_VERSION_KEY = "update_check_latest_known_version"
LAST_RESULT_KEY = "update_check_last_result"
LATEST_KNOWN_SINCE_KEY = "update_check_latest_known_since"
DISMISSED_VERSION_KEY = "update_check_dismissed_version"

UPDATE_CHECK_ENABLED = "update_check_enabled"
UPDATE_CHECK_DISABLED = "update_check_disabled"
UPGRADE_APPLIED = "upgrade_applied"
VERSION_CHANGED = "version_changed"

ClientFactory = Callable[[], httpx.AsyncClient]


class Answer(StrEnum):
    NOT_ASKED = "not_asked"
    YES = "yes"
    NO = "no"


class Result(StrEnum):
    OK = "ok"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class UpdateCheckState:
    answer: Answer
    last_checked_at: datetime | None
    latest_known_version: str | None
    last_result: Result | None
    latest_known_since: datetime | None = None
    dismissed_version: str | None = None

    @property
    def update_available(self) -> bool:
        if self.latest_known_version is None:
            return False
        return _version_gt(self.latest_known_version, __version__)

    @property
    def dismissed(self) -> bool:
        """Dismissed for this version or a later one. A further version
        brings the marker back; a restart never does, because the dismissal
        is stored, not held in the page."""
        if self.latest_known_version is None or self.dismissed_version is None:
            return False
        return not _version_gt(self.latest_known_version, self.dismissed_version)

    def as_dict(self) -> dict[str, object]:
        return {
            "answer": str(self.answer),
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "latest_known_version": self.latest_known_version,
            "update_available": self.update_available,
            "last_result": str(self.last_result) if self.last_result else None,
            "latest_known_since": (
                self.latest_known_since.isoformat() if self.latest_known_since else None
            ),
            "dismissed_version": self.dismissed_version,
            "dismissed": self.dismissed,
        }


def _version_gt(candidate: str, current: str) -> bool:
    """`MAJOR.MINOR.PATCH` only (`AGENTS.md` §7). An unparseable feed value
    is not a newer version — it is a feed that said something else, and this
    ticket's own job is only to compare, not to guess at malformed input."""

    def _parse(value: str) -> tuple[int, ...] | None:
        parts = value.strip().split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        return tuple(int(part) for part in parts)

    parsed_candidate, parsed_current = _parse(candidate), _parse(current)
    if parsed_candidate is None or parsed_current is None:
        return False
    return parsed_candidate > parsed_current


def _feed_destination(settings: Settings) -> str:
    return f"{settings.update_feed_host}:443"


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=None))


async def get_state(session: AsyncSession) -> UpdateCheckState:
    raw_answer = await get_setting(session, ANSWER_KEY)
    answer = Answer(raw_answer) if raw_answer in (Answer.YES, Answer.NO) else Answer.NOT_ASKED

    raw_checked = await get_setting(session, LAST_CHECKED_KEY)
    last_checked_at = datetime.fromisoformat(raw_checked) if raw_checked else None

    latest_known_version = await get_setting(session, LATEST_KNOWN_VERSION_KEY)

    raw_result = await get_setting(session, LAST_RESULT_KEY)
    last_result = Result(raw_result) if raw_result in (Result.OK, Result.UNREACHABLE) else None

    raw_since = await get_setting(session, LATEST_KNOWN_SINCE_KEY)
    latest_known_since = datetime.fromisoformat(raw_since) if raw_since else None

    return UpdateCheckState(
        answer=answer,
        last_checked_at=last_checked_at,
        latest_known_version=latest_known_version,
        last_result=last_result,
        latest_known_since=latest_known_since,
        dismissed_version=await get_setting(session, DISMISSED_VERSION_KEY),
    )


class InvalidAnswer(ValueError):
    """Only `yes` or `no` may be recorded as a decision. `not_asked` is the
    database's own default for "never answered" — nothing writes it."""


async def set_answer(session: AsyncSession, settings: Settings, answer: Answer) -> UpdateCheckState:
    if answer not in (Answer.YES, Answer.NO):
        raise InvalidAnswer("The answer must be 'yes' or 'no'.")

    current = await get_setting(session, ANSWER_KEY)
    if current == answer.value:
        # Already this answer. Re-asserting it must not re-open a destination
        # that never closed, and must not add a second decisions-log entry for
        # a choice nobody just made.
        return await get_state(session)

    await set_setting(session, ANSWER_KEY, answer.value)
    if answer is Answer.YES:
        await egress.permit_destination(settings, _feed_destination(settings))
        await record(session, Store.DECISIONS, UPDATE_CHECK_ENABLED, {})
        log.info("update_check_enabled")
    else:
        await egress.revoke_destination(settings)
        await record(session, Store.DECISIONS, UPDATE_CHECK_DISABLED, {})
        log.info("update_check_disabled")

    return await get_state(session)


async def _fetch(settings: Settings, client_factory: ClientFactory) -> tuple[Result, str | None]:
    try:
        async with client_factory() as client:
            response = await client.get(
                settings.update_feed_url,
                # The payload, stated in full: this and nothing else.
                # `docs/ux/settings.md` §7's own claim about what is sent.
                headers={"User-Agent": f"Askwell/{__version__}"},
            )
            response.raise_for_status()
            return Result.OK, response.text.strip()
    except httpx.HTTPError as error:
        log.info("update_check_unreachable", error=f"{type(error).__name__}: {error}")
        return Result.UNREACHABLE, None


async def run_check(
    session: AsyncSession,
    settings: Settings,
    *,
    manual: bool,
    client_factory: ClientFactory = _default_client,
) -> UpdateCheckState:
    """Perform one check. A scheduled call must already have decided this is
    due (`maybe_run_scheduled_check`) — this function does not gate on the
    weekly interval itself, because a manual check is exempt from it by
    definition (the ticket's own acceptance criterion)."""
    state = await get_state(session)

    opened_temporarily = manual and state.answer is not Answer.YES
    if opened_temporarily:
        await egress.permit_destination(settings, _feed_destination(settings))
    try:
        result, remote_version = await _fetch(settings, client_factory)
    finally:
        if opened_temporarily:
            await egress.revoke_destination(settings)

    now = datetime.now(UTC).isoformat()
    await set_setting(session, LAST_CHECKED_KEY, now)
    await set_setting(session, LAST_RESULT_KEY, result.value)
    if remote_version is not None:
        if remote_version != state.latest_known_version:
            # The date shown beside the version is when Askwell learned of
            # it, so it moves only when the version does — a weekly check
            # that finds the same version again must not make it look new.
            await set_setting(session, LATEST_KNOWN_SINCE_KEY, now)
        await set_setting(session, LATEST_KNOWN_VERSION_KEY, remote_version)

    return await get_state(session)


async def maybe_run_scheduled_check(
    session: AsyncSession,
    settings: Settings,
    *,
    client_factory: ClientFactory = _default_client,
) -> bool:
    """The weekly half. Returns whether a check actually ran.

    Time-based, not counter-based: a machine that was off for a month has one
    overdue check, not four queued ones, because this asks "has a week passed
    since the last one" rather than "how many weekly slots were missed."
    """
    state = await get_state(session)
    if state.answer is not Answer.YES:
        return False
    if state.last_checked_at is not None:
        elapsed = (datetime.now(UTC) - state.last_checked_at).total_seconds()
        if elapsed < settings.update_check_interval_seconds:
            return False
    await run_check(session, settings, manual=False, client_factory=client_factory)
    return True


class InvalidDismissal(ValueError):
    """Only a `MAJOR.MINOR.PATCH` version may be dismissed."""


async def dismiss(session: AsyncSession, version: str) -> UpdateCheckState:
    """Dismiss the marker for `version`. The caller names the version it
    showed, rather than this reading "whatever is newest now", so a check
    that lands between the page loading and the click can never have its
    newer version dismissed unseen."""
    if not _version_gt(version, "0.0.0"):
        raise InvalidDismissal("A version like 1.2.0 must be named.")
    await set_setting(session, DISMISSED_VERSION_KEY, version)
    return await get_state(session)


async def record_running_version(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> str | None:
    """At startup: if this machine last started as a different version, an
    upgrade was applied — a decisions record says so. Returns the kind
    recorded, or `None`.

    The version last started as lives in a file on the state volume
    (`Settings.running_version_path`), not in the database. A first start
    writes the file and nothing else: a fresh install's `audit_decisions`
    must stay empty until a restore lands its historical chain there, or
    the two genesis records fork (issue #697, `askwell.restore`'s module
    docstring), and `settings` must stay empty for restore's own
    existing-data check (issue #597). Restore does not touch the file, so a
    machine restored from an older backup records no upgrade it never ran.

    The record commits before the file is rewritten. If the file write
    fails the next start records the same upgrade again — a duplicate
    record, never a missing one.
    """
    path = settings.running_version_path
    try:
        previous = path.read_text(encoding="utf-8").strip() if path.exists() else None
    except OSError as error:
        log.warning("running_version_unreadable", path=str(path), error=str(error))
        return None

    kind: str | None = None
    if previous is not None and previous != __version__:
        kind = UPGRADE_APPLIED if _version_gt(__version__, previous) else VERSION_CHANGED
        async with session_scope(factory) as session:
            await record(session, Store.DECISIONS, kind, {"from": previous, "to": __version__})
        log.info(kind, previous=previous, current=__version__)

    if previous != __version__:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{__version__}\n", encoding="utf-8")
        except OSError as error:
            log.warning("running_version_unwritable", path=str(path), error=str(error))
    return kind


class AnswerRequest(BaseModel):
    answer: Literal["yes", "no"]


class DismissRequest(BaseModel):
    version: str


def register_update_check(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`/settings/update-check*` — `docs/ux/settings.md` §7 and §9."""

    @app.get("/settings/update-check")
    async def get_status() -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse((await get_state(db)).as_dict())

    @app.post("/settings/update-check")
    async def set_status(body: AnswerRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            state = await set_answer(db, settings, Answer(body.answer))
            return JSONResponse(state.as_dict())

    @app.post("/settings/update-check/run")
    async def run_now() -> JSONResponse:
        """The manual "check now" control. Works regardless of the stored
        answer — a check the user just asked for is a deliberate act by
        definition, the same reasoning C1 already applies to online AI and
        web search."""
        async with session_scope(factory) as db:
            state = await run_check(db, settings, manual=True)
            return JSONResponse(state.as_dict())

    @app.post("/settings/update-check/dismiss")
    async def dismiss_marker(body: DismissRequest) -> JSONResponse:
        """Hide the newer-version marker until a further version appears."""
        async with session_scope(factory) as db:
            try:
                state = await dismiss(db, body.version)
            except InvalidDismissal as error:
                return JSONResponse({"detail": str(error)}, status_code=422)
            return JSONResponse(state.as_dict())
