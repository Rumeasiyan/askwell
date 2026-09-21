"""Interaction retention: how far back the log stays, and the prune that
enforces it. `docs/audit-log.md` §8, ticket `M7-LOG-BE-154`.

The window's *value* (`askwell.log_budget.get_retention_months`/
`set_retention_months`) already existed before this module — `M7-SET-FE-148`
built it deliberately with no prune behind it, and stated so on the settings
screen rather than implying the number already did something. This module is
that prune.

**Pruning never runs without an export that already covers the range being
removed.** `askwell.log_export.run_job` calls `mark_exported_through` here
the moment a *full-history* export (`since is None`) finishes, recording the
latest point in time the interactions store is provably written out to disk
somewhere other than the database. A windowed export (`since` set) proves
nothing about records before its own start and must never advance this
marker — `log_export.py`'s own call site is guarded on `since is None`, not
this module, because only the caller knows which kind of export just ran.

**The hash chain survives a prune because the prune records where it now
starts.** Deleting the oldest interactions the ordinary way would leave the
oldest *surviving* record's `prev_hash` pointing at a hash that is no longer
in the table — indistinguishable, to `askwell.audit.verify`, from someone
deleting a record by hand. The difference is that a prune is expected to do
exactly that, on purpose, so it writes a decisions record naming the cutoff,
how many records went, and the hash the chain now starts from
(`first_remaining_prev_hash`) — the same reasoning `askwell.log_export`'s
windowed export already established for "does not chain to genesis" not
being tampering by itself. `askwell.audit.verify`'s own CLI
(`askwell-verify`) reads the latest such record via `latest_prune_boundary`
and starts the interactions walk there instead of at the universal genesis
value.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import GENESIS, Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.log_budget import get_retention_months
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

PRUNE_KIND = "interaction_prune"
_EXPORTED_THROUGH_KEY = "interactions_exported_through"


class PruneNotExported(RuntimeError):
    """Interactions older than the window have not all been exported yet."""


@dataclass(frozen=True, slots=True)
class PruneResult:
    cutoff: datetime
    records_removed: int

    def as_dict(self) -> dict[str, object]:
        return {"cutoff": self.cutoff.isoformat(), "records_removed": self.records_removed}


async def mark_exported_through(session: AsyncSession, until: datetime) -> None:
    """Record that a full-history export covered everything up to `until`.

    Only ever moves forward — an earlier or equal value already on record is
    left alone, so an older, narrower export run after a newer one cannot
    quietly roll this marker backwards.
    """
    current = await get_setting(session, _EXPORTED_THROUGH_KEY)
    if current is not None and datetime.fromisoformat(current) >= until:
        return
    await set_setting(session, _EXPORTED_THROUGH_KEY, until.astimezone(UTC).isoformat())


async def exported_through(session: AsyncSession) -> datetime | None:
    """The latest point a full-history export is known to cover, or `None`
    if one has never completed."""
    stored = await get_setting(session, _EXPORTED_THROUGH_KEY)
    return None if stored is None else datetime.fromisoformat(stored)


async def get_cutoff(session: AsyncSession) -> datetime:
    """The current retention window, resolved to a point in time.

    Computed in Postgres rather than Python — month arithmetic (28, 29, 30 or
    31 days depending on where `now()` falls) is exactly the kind of thing an
    `interval` gets right and a fixed-day approximation does not.
    """
    months = await get_retention_months(session)
    result = await session.execute(
        text("SELECT now() - (:months || ' months')::interval"), {"months": months}
    )
    return result.scalar_one()  # type: ignore[no-any-return]


async def prune(session: AsyncSession) -> PruneResult:
    """Delete interactions older than the retention window, in the caller's
    transaction, only once their range has already been exported.

    Deletion and the decisions record that explains it commit together —
    the same "an action and its record are one transaction" rule
    `askwell.audit` establishes for every other write here.
    """
    cutoff = await get_cutoff(session)

    exported = await exported_through(session)
    if exported is None or exported < cutoff:
        raise PruneNotExported(
            "Interactions older than the retention window have not all been "
            "exported yet. Export the log first — pruning unexported records "
            "destroys them for good."
        )

    # The oldest record that will *survive* the prune: its `prev_hash` is the
    # hash of the last record about to be deleted, and is what the chain
    # starts from once that record is gone. Empty (nothing survives) means
    # the chain starts fresh — `askwell.audit.verify` treats an empty store
    # as trivially intact, so no boundary is needed for that case.
    survivor = (
        await session.execute(
            text(
                f"SELECT prev_hash FROM {Store.INTERACTIONS.value} WHERE occurred_at >= :cutoff "
                f"ORDER BY occurred_at ASC, id ASC LIMIT 1"
            ),
            {"cutoff": cutoff},
        )
    ).first()
    first_remaining_prev_hash = GENESIS if survivor is None else str(survivor[0])

    deleted = await session.execute(
        text(f"DELETE FROM {Store.INTERACTIONS.value} WHERE occurred_at < :cutoff"),
        {"cutoff": cutoff},
    )
    removed = int(deleted.rowcount)  # type: ignore[attr-defined]

    if removed == 0:
        return PruneResult(cutoff=cutoff, records_removed=0)

    await record(
        session,
        Store.DECISIONS,
        PRUNE_KIND,
        {
            "cutoff": cutoff.astimezone(UTC).isoformat(),
            "records_removed": str(removed),
            "first_remaining_prev_hash": first_remaining_prev_hash,
        },
    )
    log.info("interaction_prune", cutoff=cutoff.isoformat(), records_removed=removed)
    return PruneResult(cutoff=cutoff, records_removed=removed)


async def latest_prune_boundary(session: AsyncSession) -> str | None:
    """The `first_remaining_prev_hash` of the most recent prune, or `None` if
    the interactions store has never been pruned.

    `askwell.audit.verify`'s CLI uses this as the interactions chain's
    starting point instead of the universal genesis value, once a prune has
    run — the same reasoning `askwell.log_export`'s windowed export already
    established for a chain that legitimately does not start at genesis.
    """
    row = (
        await session.execute(
            text(
                "SELECT payload FROM audit_decisions WHERE kind = :kind "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"kind": PRUNE_KIND},
        )
    ).first()
    return None if row is None else str(row[0]["first_remaining_prev_hash"])


def register_retention(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /log-prune` — prune interactions outside the retention window.

    No `GET`: the window itself is already `GET /log-budget/retention`
    (`askwell.log_budget`), and a prune has no state to poll — it is a single
    transaction, not a background job like export.
    """

    @app.post("/log-prune")
    async def prune_interactions() -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                result = await prune(db)
        except PruneNotExported as error:
            return JSONResponse({"error": str(error), "export_offered": True}, status_code=409)
        return JSONResponse(result.as_dict())
