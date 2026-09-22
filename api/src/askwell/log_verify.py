"""The settings-screen verifier. `docs/audit-log.md` §4, ticket `M7-LOG-FE-156`.

`askwell.audit.verify` is the whole check — a chain walk that already exists
and is already exercised by `askwell-verify` (the CLI, `askwell.audit.main`).
This module is only the HTTP seam `askwell.audit`'s own docstring named as
missing: "The settings surface for this arrives in M7. Until then it is a
command." Read-only, so a single request across both stores is honest —
there is nothing to resume, retry, or leave half-done, which is why this is
not a job table the way export and prune are.

**Tamper-evident, never immutable.** Every string this module writes,
including the decisions record below, says so.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, VerificationResult, prune_boundaries, record, verify
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

VERIFICATION_RUN = "log_verification_run"


def _result_as_dict(result: VerificationResult) -> dict[str, Any]:
    return {
        "store": result.store.value,
        "checked": result.checked,
        "intact": result.intact,
        "reason": result.reason.value if result.reason else None,
        "detail": result.detail,
        "note": result.note,
        "broken_record_id": str(result.first_break) if result.first_break else None,
        "broken_at": result.broken_at.isoformat() if result.broken_at else None,
    }


async def run(session: AsyncSession) -> dict[str, Any]:
    """Verify both stores and record that this run happened, with its result.

    The decisions record is written after both chains are read, in its own
    statement — it describes this run, it is not part of what this run
    checked.
    """
    boundaries = await prune_boundaries(session)
    decisions_result = await verify(session, Store.DECISIONS)
    interactions_result = await verify(session, Store.INTERACTIONS, prune_boundaries=boundaries)

    payload: dict[str, Any] = {
        "decisions_intact": str(decisions_result.intact),
        "interactions_intact": str(interactions_result.intact),
    }
    for label, result in (
        ("decisions", decisions_result),
        ("interactions", interactions_result),
    ):
        if not result.intact:
            payload[f"{label}_reason"] = result.reason.value if result.reason else ""
            payload[f"{label}_broken_record_id"] = (
                str(result.first_break) if result.first_break else ""
            )
            payload[f"{label}_broken_at"] = result.broken_at.isoformat() if result.broken_at else ""
    await record(session, Store.DECISIONS, VERIFICATION_RUN, payload)

    log.info(
        "log_verification_run",
        decisions_intact=decisions_result.intact,
        interactions_intact=interactions_result.intact,
    )

    return {
        "intact": decisions_result.intact and interactions_result.intact,
        "decisions": _result_as_dict(decisions_result),
        "interactions": _result_as_dict(interactions_result),
    }


def register_log_verify(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """`GET /log-verify` — run the chain check across both stores now and
    report the result. No job table: a read that touches nothing has nothing
    to resume, and a year of interactions is a hash walk over rows already in
    memory, not an operation that needs surviving a crash."""

    @app.get("/log-verify")
    async def verify_log() -> JSONResponse:
        async with session_scope(factory) as db:
            result = await run(db)
        return JSONResponse(result)
