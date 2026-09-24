"""Online AI, authorised per conversation. `M8-ONLINE-SEC-169`.

C1 permits one deliberate exception to "nothing leaves this machine": the
user switching one conversation to online AI. This module is that switch's
authorisation, and the one key it uses (`M8-KEY-BE-173`). The provider client
is `askwell.inference.provider`; the key's storage is `askwell.provider_key`.

**The destination is the key's.** Online AI is available only while a
provider key is held and readable, and the one destination a conversation is
authorised for is the one stored with that key. Removing the key, or
replacing it with one for a different provider, revokes every conversation's
authorisation in the same transaction, with the reason recorded — a grant
for a provider the user no longer holds a key for is a door to nowhere they
chose.

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

**Nothing is sent before it is described** (`M8-ONLINE-FE-171`). Being
online authorises the destination; it does not permit a send. A send also
needs the conversation to have confirmed the current pre-send disclosure
(`DISCLOSURE`), a decisions record naming the conversation. While
`DISCLOSURE` is `None`, because the wording of what is sent is not decided
yet (#737), nothing can be confirmed, so nothing is sent: `POST /ask` refuses
the question and `askwell.ask._online_client` answers locally. The
confirmation outlives the authorisation. A conversation that lapses back to
local and is switched on again is not asked again, unless the statement
itself has changed, which is what its version is for.

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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import egress, passphrase, provider_key
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

ONLINE_AI_ENABLED = "online_ai_enabled"
ONLINE_AI_REVOKED = "online_ai_revoked"
ONLINE_AI_DISCLOSURE_CONFIRMED = "online_ai_disclosure_confirmed"

# Why an authorisation ended. Recorded, never inferred later.
REVOKED_BY_USER = "disabled"
REVOKED_LAPSED = "lapsed"
REVOKED_ON_RESTART = "restart"

REVOKED_KEY_REPLACED = "key_replaced"
REVOKED_KEY_REMOVED = "key_removed"
# `M8-KEY-FE-175`: the provider said no in a way it will keep saying until
# the user acts — the key rejected, or the account out of quota. Named
# apart because the two have different fixes, neither of them in Askwell.
REVOKED_PROVIDER_REJECTED_KEY = "provider_rejected_key"
REVOKED_PROVIDER_QUOTA_EXHAUSTED = "provider_quota_exhausted"

ONLINE_KEY_STORED = "online_key_stored"
ONLINE_KEY_REPLACED = "online_key_replaced"
ONLINE_KEY_REMOVED = "online_key_removed"

NO_KEY = (
    "Online AI is not available: no provider key is stored, so there is no "
    "provider to send to. Add one in Settings. Nothing has left this machine."
)

KEY_LOCKED = (
    "Online AI is not available until Askwell is unlocked: your provider key is "
    "encrypted under your passphrase. Nothing has left this machine."
)


@dataclass(frozen=True, slots=True)
class Disclosure:
    """The statement of exactly what an online conversation sends, shown
    before its first send. `version` is what a confirmation names, so a
    changed statement is confirmed again rather than inherited."""

    version: str
    text: str


# `M8-ONLINE-FE-171`: `None` until the wording is decided (#737). While it
# is `None`, no conversation can confirm it and nothing is sent online. The
# refusal is the safeguard. Do not fill this with a placeholder.
DISCLOSURE: Disclosure | None = None

DISCLOSURE_UNDEFINED = (
    "What online AI would send has not been decided yet, so Askwell will not send "
    "anything online. Nothing has left this machine."
)

DISCLOSURE_CHANGED = (
    "The statement of what online AI sends has changed since it was shown. Read it "
    "again before confirming. Nothing has left this machine."
)

NOT_CONFIRMED = (
    "This conversation is set to online AI, and what it would send has not been "
    "confirmed for it. Nothing was sent."
)

# Conversation id → the credential its grant was opened under. In memory
# only, deliberately: see the module docstring.
_credentials: dict[str, str] = {}


class ConversationNotFound(LookupError):
    pass


class OnlineUnavailable(RuntimeError):
    pass


class DisclosureNotConfirmable(RuntimeError):
    """The disclosure is undefined, or not the one the user was shown."""


@dataclass(frozen=True, slots=True)
class OnlineState:
    conversation_id: str
    online: bool
    destination: str | None
    expires_in_seconds: int | None
    available: bool
    unavailable_reason: str | None
    # `M8-ONLINE-FE-171`. Whether online AI was ever switched on for this
    # conversation, which the marker keeps showing after it lapses. And
    # whether the current disclosure was confirmed for it.
    used_online: bool = False
    disclosure_confirmed: bool = False
    # `M8-KEY-FE-175`. Why the conversation's most recent authorisation
    # ended, from its own revocation record: what the marker names once it
    # is local again. None while online, and for one never switched on.
    ended_reason: str | None = None

    @property
    def send_permitted(self) -> bool:
        """Whether a question in this conversation may go to the provider:
        online, and the statement of what goes confirmed."""
        return self.online and DISCLOSURE is not None and self.disclosure_confirmed

    def as_dict(self) -> dict[str, Any]:
        disclosure = DISCLOSURE
        return {
            "conversation_id": self.conversation_id,
            "ai_backend": "online" if self.online else "local",
            "destination": self.destination,
            "expires_in_seconds": self.expires_in_seconds,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "used_online": self.used_online,
            "ended_reason": None if self.online else self.ended_reason,
            "disclosure": {
                "defined": disclosure is not None,
                "version": disclosure.version if disclosure is not None else None,
                "text": disclosure.text if disclosure is not None else None,
                "confirmed": self.disclosure_confirmed,
            },
            "send_permitted": self.send_permitted,
        }


async def _availability(
    db: AsyncSession,
) -> tuple[provider_key.Provider | None, str | None]:
    """The provider a conversation could go online to, and if none, why not:
    no key held, or a key held that this process cannot read yet. Decrypts
    nothing — the passphrase state says whether it could."""
    held = await provider_key.stored_provider(db)
    if held is None:
        return None, NO_KEY
    if (await passphrase.status(db))["locked"]:
        return None, KEY_LOCKED
    return held, None


async def key_for_send(db: AsyncSession, settings: Settings) -> provider_key.ProviderKey | None:
    """The key, decrypted, at the moment of sending. None when none is held.
    Raises `askwell.passphrase.Locked` on a locked install. For the provider
    (`askwell.ask._online_client`) — nothing else should ask."""
    return await provider_key.load(db, await passphrase.current_key(db, settings))


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


async def backend_of(db: AsyncSession, conversation_id: uuid.UUID) -> str:
    """`conversations.ai_backend` as recorded, without reading the grant.
    For a caller that only needs to know whether reconciling is worth it."""
    return await _backend(db, conversation_id)


async def _record_facts(
    db: AsyncSession, conversation_id: uuid.UUID
) -> tuple[bool, bool, str | None]:
    """Whether this conversation was ever switched online, whether the
    current disclosure was confirmed for it, and why its most recent
    authorisation ended. All three come from its own decisions records,
    which are append-only, so none can be quietly undone."""
    disclosure = DISCLOSURE
    row = (
        await db.execute(
            text(
                "SELECT "
                "bool_or(kind = :enabled), "
                "bool_or(kind = :confirmed AND payload->>'version' = :version), "
                "(array_agg(payload->>'reason' ORDER BY occurred_at DESC, id DESC) "
                "FILTER (WHERE kind = :revoked))[1] "
                "FROM audit_decisions "
                "WHERE kind IN (:enabled, :confirmed, :revoked) "
                "AND payload->>'conversation_id' = :id"
            ),
            {
                "enabled": ONLINE_AI_ENABLED,
                "confirmed": ONLINE_AI_DISCLOSURE_CONFIRMED,
                "revoked": ONLINE_AI_REVOKED,
                "version": disclosure.version if disclosure is not None else "",
                "id": str(conversation_id),
            },
        )
    ).one()
    return (
        bool(row[0]),
        disclosure is not None and bool(row[1]),
        str(row[2]) if row[2] is not None else None,
    )


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


async def _state(
    db: AsyncSession,
    settings: Settings,
    conversation_id: uuid.UUID,
    grant: egress.ConversationGrant | None,
) -> OnlineState:
    held, unavailable_reason = await _availability(db)
    used_online, confirmed, ended_reason = await _record_facts(db, conversation_id)
    return OnlineState(
        conversation_id=str(conversation_id),
        online=grant is not None,
        destination=grant.destination if grant is not None else None,
        expires_in_seconds=grant.expires_in_seconds if grant is not None else None,
        available=held is not None,
        unavailable_reason=unavailable_reason,
        used_online=used_online,
        disclosure_confirmed=confirmed,
        ended_reason=ended_reason,
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
        return await _state(db, settings, conversation_id, None)

    if backend == "local" and grant is not None:
        # A grant with nothing on record behind it. Closed, not adopted.
        await egress.close_conversation_grant(settings, str(conversation_id))
        _credentials.pop(str(conversation_id), None)
        log.warning("online_ai_orphan_grant_closed", conversation_id=str(conversation_id))
        return await _state(db, settings, conversation_id, None)

    return await _state(db, settings, conversation_id, grant if usable else None)


async def enable(db: AsyncSession, settings: Settings, conversation_id: uuid.UUID) -> OnlineState:
    """Authorise the stored key's destination for this conversation.

    Enabling a conversation that is already online changes nothing and adds
    no second record — the same rule `askwell.update_check.set_answer` keeps
    for a choice nobody just made again.
    """
    current = await get_state(db, settings, conversation_id)
    if current.online:
        return current
    held, unavailable_reason = await _availability(db)
    if held is None:
        raise OnlineUnavailable(unavailable_reason or NO_KEY)
    destination = held.destination

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
        used_online=True,
        disclosure_confirmed=current.disclosure_confirmed,
    )


async def confirm_disclosure(
    db: AsyncSession, settings: Settings, conversation_id: uuid.UUID, version: str
) -> OnlineState:
    """Record that the user read and confirmed the pre-send disclosure for
    this conversation (`M8-ONLINE-FE-171`).

    Refused while there is no disclosure (#737), because a statement that
    does not exist cannot have been read. Also refused for a version other
    than the current one, because the user confirmed words that are no longer
    the ones in force. Confirming again changes nothing and adds no second
    record.
    """
    current = await get_state(db, settings, conversation_id)
    disclosure = DISCLOSURE
    if disclosure is None:
        raise DisclosureNotConfirmable(DISCLOSURE_UNDEFINED)
    if version != disclosure.version:
        raise DisclosureNotConfirmable(DISCLOSURE_CHANGED)
    if current.disclosure_confirmed:
        return current
    await record(
        db,
        Store.DECISIONS,
        ONLINE_AI_DISCLOSURE_CONFIRMED,
        {"conversation_id": str(conversation_id), "version": disclosure.version},
    )
    await db.flush()
    log.info(
        "online_ai_disclosure_confirmed",
        conversation_id=str(conversation_id),
        version=disclosure.version,
    )
    return await get_state(db, settings, conversation_id)


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
    return await _state(db, settings, conversation_id, None)


async def end_after_provider_refusal(
    db: AsyncSession, settings: Settings, conversation_id: uuid.UUID, reason: str
) -> bool:
    """The provider rejected the key or the account is out of quota: end
    this conversation's authorisation, recorded with that reason.
    `M8-KEY-FE-175`.

    Every later question would be refused the same way, and each refusal
    still carries the question and its passages to the provider
    (`M8-ONLINE-OBS-172`) — sending them again for a no that is already
    known is egress for nothing. So the conversation goes local, and stays
    local when the key or the quota is fixed: coming back online is the
    user switching it on again, never Askwell noticing it could. Returns
    whether it was online to end.

    The credential goes first: without it this process cannot present the
    grant to the proxy, so nothing more is sent even if what follows fails.
    Then the grant, then the record, as in `disable`.
    """
    _credentials.pop(str(conversation_id), None)
    if await _backend(db, conversation_id) != "online":
        return False
    grant = await egress.read_conversation_grant(settings, str(conversation_id))
    await egress.close_conversation_grant(settings, str(conversation_id))
    await _set_local(
        db,
        conversation_id,
        destination=grant.destination if grant is not None else None,
        reason=reason,
    )
    return True


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


async def _revoke_every_conversation(db: AsyncSession, settings: Settings, reason: str) -> int:
    """End every conversation's authorisation, in the caller's transaction,
    each with a revocation record naming `reason`. The grants close first,
    so the proxy stops forwarding before anything here can fail."""
    _credentials.clear()
    standing = await egress.close_all_conversation_grants(settings)
    rows = (
        await db.execute(text("SELECT id FROM conversations WHERE ai_backend = 'online'"))
    ).all()
    for (conversation_id,) in rows:
        await _set_local(
            db, conversation_id, destination=standing.get(str(conversation_id)), reason=reason
        )
    return len(rows)


async def store_key(
    db: AsyncSession, settings: Settings, destination: str, model: str, api_key: str
) -> provider_key.Provider:
    """Store the user's provider key, replacing any held before. `M8-KEY-BE-173`.

    Encrypted under the same key as every other credential, so a locked
    install refuses (`askwell.passphrase.Locked`) rather than storing it
    under a key that is not the one in force. Replacing it with a key for a
    different destination ends every conversation's authorisation, because
    each was for the old destination. A key for the same destination takes
    over at the next send with the grants left standing: the door is the
    same one the user opened. The record names the provider, never the key.
    """
    provider = provider_key.validate(destination, model, api_key)
    encryption_key = await passphrase.current_key(db, settings)
    previous = await provider_key.store(db, encryption_key, provider, api_key)
    if previous is None:
        await record(db, Store.DECISIONS, ONLINE_KEY_STORED, provider.as_dict())
    else:
        await record(
            db,
            Store.DECISIONS,
            ONLINE_KEY_REPLACED,
            {**provider.as_dict(), "previous": previous.as_dict()},
        )
        if previous.destination != provider.destination:
            await _revoke_every_conversation(db, settings, REVOKED_KEY_REPLACED)
    log.info(
        "online_key_replaced" if previous is not None else "online_key_stored",
        destination=provider.destination,
        model=provider.model,
    )
    return provider


async def remove_key(db: AsyncSession, settings: Settings) -> bool:
    """Remove the key. Every conversation's authorisation ends with it, so
    online AI is unavailable from this moment, not at the next question.
    Returns whether a key was held. Removing nothing records nothing."""
    previous = await provider_key.remove(db)
    if previous is None:
        return False
    await record(db, Store.DECISIONS, ONLINE_KEY_REMOVED, previous.as_dict())
    await _revoke_every_conversation(db, settings, REVOKED_KEY_REMOVED)
    log.info("online_key_removed", destination=previous.destination)
    return True


async def key_status(db: AsyncSession) -> dict[str, Any]:
    """Whether a key is held and for which provider — never the key itself,
    not even masked. `M8-KEY-FE-174` renders this."""
    held = await provider_key.stored_provider(db)
    _available, unavailable_reason = await _availability(db)
    return {
        "set": held is not None,
        "provider": held.as_dict() if held is not None else None,
        "available": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
    }


class DisclosureConfirmation(BaseModel):
    """`POST /conversations/{id}/online/disclosure`: which statement the user
    was shown, so a confirmation of stale words is refused by name."""

    version: str = Field(min_length=1, max_length=64)


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

    @app.post("/conversations/{conversation_id}/online/disclosure")
    async def confirm_route(
        conversation_id: uuid.UUID, body: DisclosureConfirmation
    ) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                state = await confirm_disclosure(db, settings, conversation_id, body.version)
            except ConversationNotFound:
                return _not_found()
            except DisclosureNotConfirmable as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            return JSONResponse(state.as_dict())

    @app.get("/settings/online-key")
    async def key_read_route() -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse(await key_status(db))

    @app.put("/settings/online-key")
    async def key_store_route(request: Request) -> JSONResponse:
        # Parsed by hand rather than as a typed body: FastAPI's validation
        # error echoes the offending input, and for a body missing one field
        # that input is the whole body, key included.
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "Send the provider key as JSON."}, status_code=400)
        fields = body if isinstance(body, dict) else {}
        values = [fields.get(name) for name in ("destination", "model", "api_key")]
        if not all(isinstance(value, str) for value in values):
            return JSONResponse(
                {"error": "A provider key needs a destination, a model and the key, each text."},
                status_code=400,
            )
        destination, model, api_key = (str(value) for value in values)
        try:
            async with session_scope(factory) as db:
                await store_key(db, settings, destination, model, api_key)
        except provider_key.InvalidProviderKey as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except passphrase.Locked:
            return JSONResponse({"error": KEY_LOCKED}, status_code=423)
        async with session_scope(factory) as db:
            return JSONResponse(await key_status(db))

    @app.delete("/settings/online-key")
    async def key_remove_route() -> JSONResponse:
        async with session_scope(factory) as db:
            await remove_key(db, settings)
        async with session_scope(factory) as db:
            return JSONResponse(await key_status(db))

    @app.delete("/conversations/{conversation_id}/online")
    async def disable_route(conversation_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                state = await disable(db, settings, conversation_id)
            except ConversationNotFound:
                return _not_found()
            return JSONResponse(state.as_dict())
