"""Online AI, authorised per conversation. `M8-ONLINE-SEC-169`.

C1 permits one deliberate exception to "nothing leaves this machine": the
user switching one conversation to online AI. This module is that switch's
authorisation, and nothing else — no provider (`askwell.inference.provider`), no key
(`M8-KEY-BE-173`), no disclosure (`M8-ONLINE-FE-171`).

**The egress proxy's grant is the authority; `conversations.ai_backend` is
the record of it.** A conversation is online only while both agree. Every
read reconciles them, and a disagreement always resolves towards local: a
grant with no conversation marked online behind it is closed, and a
conversation marked online with no live grant behind it — expired, cleared by
a proxy restart, or never opened because Redis failed — is put back to local
and the revocation recorded with its reason. Resolving the other way would be
restoring an authorisation nobody just asked for, which is exactly the drift
the ticket forbids.

**Scoped by a credential, not only a destination.** Enabling mints a random
token for that conversation; the proxy forwards to the destination only for a
`CONNECT` presenting it (`askwell.egress.CONVERSATION_GRANT_KEY_PREFIX`). A
second conversation, or a dependency making its own call to the same host,
has no token and is refused. The token lives only in this process — Redis
holds its SHA-256 — so a restart makes any surviving grant unusable even
before startup revokes it (`revoke_all_on_startup`).

**What the credential is not.** Redis has no authentication on the internal
network, so anything already able to write to Redis could write a grant of
its own. The credential scopes the door to the conversation that opened it
against accidental use — a local conversation, a telemetry call — not against
a compromised container, which already has the database too.

**"The conversation ends."** Askwell has no ended state for a conversation.
An authorisation ends when the user disables it, when its time bound lapses
(`Settings.online_ai_authorisation_ttl_seconds`), when Askwell or its proxy
restarts, or when a reset deletes the conversation. Nothing renews it.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import egress
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

ONLINE_AI_ENABLED = "online_ai_enabled"
ONLINE_AI_REVOKED = "online_ai_revoked"

# Why an authorisation ended. Recorded, never inferred later.
REVOKED_BY_USER = "disabled"
REVOKED_LAPSED = "lapsed"
REVOKED_ON_RESTART = "restart"

NOT_CONFIGURED = (
    "Online AI is not available: no online provider is configured, so there is "
    "no destination to authorise. Nothing has left this machine."
)

# Conversation id → the credential its grant was opened under. In memory
# only, deliberately: see the module docstring.
_credentials: dict[str, str] = {}


class ConversationNotFound(LookupError):
    pass


class OnlineUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OnlineState:
    conversation_id: str
    online: bool
    destination: str | None
    expires_in_seconds: int | None
    available: bool
    unavailable_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "ai_backend": "online" if self.online else "local",
            "destination": self.destination,
            "expires_in_seconds": self.expires_in_seconds,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


def configured(settings: Settings) -> bool:
    """Whether there is a provider to go online to: a destination to
    authorise and a model to ask it for (`M8-ONLINE-BE-170`). Either alone
    is not one."""
    return settings.online_ai_destination is not None and settings.online_ai_model is not None


def proxy_credentials(conversation_id: uuid.UUID) -> tuple[str, str] | None:
    """The `(username, password)` a request on this conversation's behalf
    presents to the egress proxy, or None when it is not online in this
    process. For the provider (`M8-ONLINE-BE-170`) — nothing else should ask."""
    token = _credentials.get(str(conversation_id))
    if token is None:
        return None
    return f"{egress.CONVERSATION_CREDENTIAL_USER_PREFIX}{conversation_id}", token


async def _backend(db: AsyncSession, conversation_id: uuid.UUID) -> str:
    row = (
        await db.execute(
            text("SELECT ai_backend FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
    ).first()
    if row is None:
        raise ConversationNotFound(str(conversation_id))
    return str(row[0])


async def _last_enabled_destination(db: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    """The destination this conversation was last enabled for, from its own
    decisions record — for an ending whose grant was already gone (a proxy
    restart clears it before the API starts), so the revocation record
    still names what it revoked."""
    row = (
        await db.execute(
            text(
                "SELECT payload->>'destination' FROM audit_decisions "
                "WHERE kind = :kind AND payload->>'conversation_id' = :id "
                "ORDER BY occurred_at DESC LIMIT 1"
            ),
            {"kind": ONLINE_AI_ENABLED, "id": str(conversation_id)},
        )
    ).first()
    return str(row[0]) if row is not None and row[0] is not None else None


async def _set_local(
    db: AsyncSession, conversation_id: uuid.UUID, *, destination: str | None, reason: str
) -> None:
    if destination is None:
        destination = await _last_enabled_destination(db, conversation_id)
    await db.execute(
        text("UPDATE conversations SET ai_backend = 'local' WHERE id = :id"),
        {"id": conversation_id},
    )
    await record(
        db,
        Store.DECISIONS,
        ONLINE_AI_REVOKED,
        {
            "conversation_id": str(conversation_id),
            "destination": destination,
            "reason": reason,
        },
    )
    log.info(
        "online_ai_revoked",
        conversation_id=str(conversation_id),
        destination=destination,
        reason=reason,
    )


def _state(
    settings: Settings, conversation_id: uuid.UUID, grant: egress.ConversationGrant | None
) -> OnlineState:
    available = configured(settings)
    return OnlineState(
        conversation_id=str(conversation_id),
        online=grant is not None,
        destination=grant.destination if grant is not None else None,
        expires_in_seconds=grant.expires_in_seconds if grant is not None else None,
        available=available,
        unavailable_reason=None if available else NOT_CONFIGURED,
    )


async def get_state(
    db: AsyncSession, settings: Settings, conversation_id: uuid.UUID
) -> OnlineState:
    """The conversation's authorisation as the proxy holds it, reconciled
    with the database towards local (module docstring)."""
    backend = await _backend(db, conversation_id)
    grant = await egress.read_conversation_grant(settings, str(conversation_id))
    held = _credentials.get(str(conversation_id))
    usable = (
        grant is not None
        and held is not None
        and grant.token_sha256 == egress.credential_digest(held)
    )

    if backend == "online" and not usable:
        # Lapsed on its time bound, cleared by a proxy restart, or opened by
        # a process that no longer exists. Whichever: it ended, and saying
        # so is the record. `lapsed` covers every case where nothing here
        # revoked it — the destination is the grant's if one was still
        # readable, else unknown.
        if grant is not None:
            await egress.close_conversation_grant(settings, str(conversation_id))
        _credentials.pop(str(conversation_id), None)
        await _set_local(
            db,
            conversation_id,
            destination=grant.destination if grant is not None else None,
            reason=REVOKED_LAPSED,
        )
        return _state(settings, conversation_id, None)

    if backend == "local" and grant is not None:
        # A grant with nothing on record behind it. Closed, not adopted.
        await egress.close_conversation_grant(settings, str(conversation_id))
        _credentials.pop(str(conversation_id), None)
        log.warning("online_ai_orphan_grant_closed", conversation_id=str(conversation_id))
        return _state(settings, conversation_id, None)

    return _state(settings, conversation_id, grant if usable else None)


async def enable(db: AsyncSession, settings: Settings, conversation_id: uuid.UUID) -> OnlineState:
    """Authorise the one configured destination for this conversation.

    Enabling a conversation that is already online changes nothing and adds
    no second record — the same rule `askwell.update_check.set_answer` keeps
    for a choice nobody just made again.
    """
    current = await get_state(db, settings, conversation_id)
    if current.online:
        return current
    destination = settings.online_ai_destination
    if destination is None or not configured(settings):
        raise OnlineUnavailable(NOT_CONFIGURED)

    token = secrets.token_urlsafe(32)
    # The grant first, then the record: if the record cannot be written the
    # grant is closed again below, so "online" is never on the proxy without
    # being on the record — a decision that could not be recorded did not
    # happen (`askwell.audit.record`).
    await egress.open_conversation_grant(
        settings,
        conversation_id=str(conversation_id),
        destination=destination,
        token=token,
        ttl_seconds=settings.online_ai_authorisation_ttl_seconds,
    )
    try:
        await db.execute(
            text("UPDATE conversations SET ai_backend = 'online' WHERE id = :id"),
            {"id": conversation_id},
        )
        await record(
            db,
            Store.DECISIONS,
            ONLINE_AI_ENABLED,
            {
                "conversation_id": str(conversation_id),
                "destination": destination,
                "ttl_seconds": int(settings.online_ai_authorisation_ttl_seconds),
            },
        )
        await db.flush()
    except BaseException:
        await egress.close_conversation_grant(settings, str(conversation_id))
        raise
    _credentials[str(conversation_id)] = token
    log.info("online_ai_enabled", conversation_id=str(conversation_id), destination=destination)
    return OnlineState(
        conversation_id=str(conversation_id),
        online=True,
        destination=destination,
        expires_in_seconds=int(settings.online_ai_authorisation_ttl_seconds),
        available=True,
        unavailable_reason=None,
    )


async def disable(db: AsyncSession, settings: Settings, conversation_id: uuid.UUID) -> OnlineState:
    """Revoke it, immediately. The grant goes first and unconditionally — the
    proxy stops forwarding before anything else here can fail — and open
    tunnels are cut within `askwell.egress.CONVERSATION_RECHECK_SECONDS`."""
    backend = await _backend(db, conversation_id)
    grant = await egress.read_conversation_grant(settings, str(conversation_id))
    await egress.close_conversation_grant(settings, str(conversation_id))
    _credentials.pop(str(conversation_id), None)
    if backend == "online":
        await _set_local(
            db,
            conversation_id,
            destination=grant.destination if grant is not None else None,
            reason=REVOKED_BY_USER,
        )
    return _state(settings, conversation_id, None)


async def revoke_all(settings: Settings) -> dict[str, str]:
    """Close every conversation's grant and forget every credential, without
    touching the database. For a reset, whose own transaction has already
    deleted the conversations these belonged to."""
    _credentials.clear()
    return await egress.close_all_conversation_grants(settings)


async def revoke_all_on_startup(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    """A restart does not restore an authorisation (`M8-ONLINE-SEC-169`).

    Every grant still in Redis is closed and every conversation still marked
    online is put back to local, each with a decisions record saying it was
    the restart that ended it. Returns how many conversations that was.
    """
    _credentials.clear()
    standing = await egress.close_all_conversation_grants(settings)
    async with session_scope(factory) as db:
        rows = (
            await db.execute(text("SELECT id FROM conversations WHERE ai_backend = 'online'"))
        ).all()
        for (conversation_id,) in rows:
            await _set_local(
                db,
                conversation_id,
                destination=standing.get(str(conversation_id)),
                reason=REVOKED_ON_RESTART,
            )
    return len(rows)


def register_online(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`/conversations/{id}/online` — read, enable, revoke."""

    def _not_found() -> JSONResponse:
        return JSONResponse({"error": "Askwell has no conversation with that id."}, status_code=404)

    @app.get("/conversations/{conversation_id}/online")
    async def read_route(conversation_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                state = await get_state(db, settings, conversation_id)
            except ConversationNotFound:
                return _not_found()
            return JSONResponse(state.as_dict())

    @app.post("/conversations/{conversation_id}/online")
    async def enable_route(conversation_id: uuid.UUID) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                try:
                    state = await enable(db, settings, conversation_id)
                except ConversationNotFound:
                    return _not_found()
                except OnlineUnavailable as error:
                    return JSONResponse({"error": str(error)}, status_code=409)
        except BaseException:
            # The commit itself failed after the grant opened: the record of
            # enabling did not land, so neither may the authorisation.
            _credentials.pop(str(conversation_id), None)
            await egress.close_conversation_grant(settings, str(conversation_id))
            raise
        return JSONResponse(state.as_dict())

    @app.delete("/conversations/{conversation_id}/online")
    async def disable_route(conversation_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                state = await disable(db, settings, conversation_id)
            except ConversationNotFound:
                return _not_found()
            return JSONResponse(state.as_dict())
