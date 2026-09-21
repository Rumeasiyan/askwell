"""The optional passphrase: set, change, remove, unlock. `M7-SEC-BE-151`.

Off by default. When set, it folds into the same key derivation
`askwell.crypto` (`M4-CONN-SEC-098`) already built for connection
credentials — `derive_key(install_secret, passphrase)` — so setting one does
not add a second encryption layer, it strengthens the existing one. Every row
already encrypted under the passphrase-less key is re-encrypted under the new
one in the same transaction as the change, which is what makes "no re-entry
needed" (the ticket's own assumption) literally true: the user is never asked
to retype a database password just because they added a passphrase.

**There is no recovery.** No password-reset email, no security questions, no
master key held anywhere. `set_passphrase` refuses outright unless the caller
has explicitly acknowledged that losing the passphrase means losing
everything it protects — see `docs/backlog/M7-someone-else-can-install-it.md`
`M7-SEC-BE-151`'s own acceptance criterion, "there is no recovery mechanism
anywhere." Do not add one. Ever.

The passphrase itself is never stored — only a **verifier**: a known plaintext
encrypted with the derived key. Checking a candidate passphrase means
deriving its key and trying to decrypt the verifier; `crypto.decrypt` already
tells a wrong key from a right one via `CredentialsLocked`, without this
module ever comparing the passphrase text to anything on disk.

**Unlock state is in-memory only, per process, and never written anywhere.**
Writing it to the run-directory bind mount the way the install secret itself
lives there would defeat the feature outright — that mount is host-persisted,
so a cached key surviving a container restart is exactly the "prompt before
anything decrypts" requirement failing silently. The cost is real and is
recorded rather than hidden: the API process and the worker process do not
share one unlock — see the module-level docstring note below and the issue
filed for it.

**Known architectural gap, filed rather than silently worked around:** `api`
and `worker` are separate OS processes (`compose.yaml`), each with its own
copy of this module's in-memory state. The API process unlocks when the user
enters the passphrase through `/settings/passphrase/unlock`. The worker
process has no interactive surface at all, so it never unlocks — a live
connection's background introspection and health check
(`askwell.connections.run_introspection`, `check_connection_health`) fail
`CredentialsLocked` for as long as a passphrase is set, regardless of what the
API process's own state is. This is the correct failure (locked stays locked,
nothing decrypts silently), but it means those two background jobs are
permanently non-functional once a passphrase is set, which is a real product
gap for M4's live-connection features. Filed as its own issue rather than
patched here — cross-process key sharing needs a mechanism (a local socket, a
signal through Redis) that is a change to C1's security boundary in its own
right, not a two-line fix inside a 3-4 hour ticket.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import content_encryption, crypto
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

VERIFIER_KEY = "passphrase_verifier"

PASSPHRASE_SET = "passphrase_set"
PASSPHRASE_CHANGED = "passphrase_changed"
PASSPHRASE_REMOVED = "passphrase_removed"

# Encrypted with the derived key and stored as the verifier. Never decoded for
# its content — only ever compared against itself after a round trip, so its
# value carries no meaning beyond "the same bytes came back".
_CANARY = b"askwell-passphrase-verifier-v1"

MIN_LENGTH = 8

# Process-wide, deliberately not attached to any request or session object:
# there is one user and one machine, so "unlocked" is a fact about the
# process, not about who is asking. `None` means locked (a passphrase is set
# and nobody has entered it since this process started) or simply "no
# passphrase" — `current_key` tells the two apart by checking the verifier.
_unlocked_key: bytes | None = None


class Locked(crypto.CredentialsLocked):
    """A passphrase is set and this process has not been unlocked yet.

    Subclasses `crypto.CredentialsLocked` deliberately: every existing caller
    of `crypto.derive_key`/`decrypt` (`askwell.connections`, `askwell.ask`)
    already catches that exception for "these credentials cannot be read
    back right now" and reports it the same way regardless of cause — a lost
    install secret and a not-yet-unlocked passphrase are the same fact from
    their point of view, so this needs no new `except` clause anywhere.
    """


class IncorrectPassphrase(Exception):
    """The passphrase given does not match the one on file.

    Deliberately the same message regardless of how close it was — the
    acceptance criterion is explicit that a wrong passphrase "refuses without
    revealing whether it was close."
    """


class NoPassphraseSet(Exception):
    """Change, remove or unlock was asked for, but no passphrase is set."""


class PassphraseAlreadySet(Exception):
    """Set was asked for, but a passphrase already exists. Use change."""


class NoRecoveryNotAcknowledged(Exception):
    """Set was asked for without acknowledging there is no recovery path."""


class WeakPassphrase(Exception):
    """The candidate passphrase does not meet the minimum bar."""


class Strength(StrEnum):
    WEAK = "weak"
    FAIR = "fair"
    GOOD = "good"
    STRONG = "strong"


_STRENGTH_BY_SCORE = {
    0: Strength.WEAK,
    1: Strength.WEAK,
    2: Strength.FAIR,
    3: Strength.GOOD,
    4: Strength.STRONG,
}


@dataclass(frozen=True, slots=True)
class StrengthResult:
    score: int
    strength: Strength
    meets_minimum: bool
    feedback: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "strength": self.strength.value,
            "meets_minimum": self.meets_minimum,
            "feedback": list(self.feedback),
        }


def assess_strength(passphrase: str) -> StrengthResult:
    """Feedback on a candidate passphrase. Never persisted, never logged.

    A local heuristic, not a breach-corpus check — there is no network call
    to make here even if one existed (C1), and no such corpus ships. Length
    carries most of the score, because for a passphrase (not a short
    password) length is the dominant factor; character variety adds on top
    rather than replacing it, so "a dozen random words" and "eight characters
    with a symbol" both score sensibly instead of the second beating the
    first.
    """
    feedback: list[str] = []
    meets_minimum = len(passphrase) >= MIN_LENGTH
    if not meets_minimum:
        feedback.append(f"Use at least {MIN_LENGTH} characters.")

    length_score = 0
    if len(passphrase) >= MIN_LENGTH:
        length_score = 1
    if len(passphrase) >= 12:
        length_score = 2
    if len(passphrase) >= 16:
        length_score = 3

    variety = sum(
        [
            any(char.islower() for char in passphrase),
            any(char.isupper() for char in passphrase),
            any(char.isdigit() for char in passphrase),
            any(not char.isalnum() for char in passphrase),
        ]
    )
    variety_score = max(0, variety - 1)

    if meets_minimum and variety < 2:
        feedback.append("Mix in more than one kind of character, or make it longer still.")
    if meets_minimum and len(set(passphrase)) <= 4:
        feedback.append("Avoid repeating the same few characters.")

    score = min(4, length_score + variety_score)
    return StrengthResult(
        score=score,
        strength=_STRENGTH_BY_SCORE[score],
        meets_minimum=meets_minimum,
        feedback=tuple(feedback),
    )


def _reset_lock_state_for_tests() -> None:
    """Test-only. Two tests in the same pytest process must not see each
    other's unlock state — production has exactly one process per lifetime,
    but the test suite does not.
    """
    global _unlocked_key
    _unlocked_key = None


async def is_enabled(session: AsyncSession) -> bool:
    return await get_setting(session, VERIFIER_KEY) is not None


async def status(session: AsyncSession) -> dict[str, bool]:
    enabled = await is_enabled(session)
    return {"enabled": enabled, "locked": enabled and _unlocked_key is None}


def _verify(key: bytes, verifier_b64: str) -> bool:
    try:
        plaintext = crypto.decrypt(base64.urlsafe_b64decode(verifier_b64), key)
    except crypto.CredentialsLocked:
        return False
    return plaintext == _CANARY


async def current_key(session: AsyncSession, settings: Settings) -> bytes:
    """The key every encrypt/decrypt call should use right now.

    No passphrase set: derives straight from the install secret, same as
    before this ticket existed — nothing about `M4-CONN-SEC-098`'s existing
    behaviour changes for an install that never sets one. A passphrase set and
    this process unlocked: the cached key. A passphrase set and this process
    not yet unlocked: `Locked` — the caller's job is to report that, not
    guess at a key that will not work.
    """
    if not await is_enabled(session):
        install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
        return crypto.derive_key(install_secret)
    if _unlocked_key is None:
        raise Locked("A passphrase is set. Unlock before anything decrypts.")
    return _unlocked_key


async def _reencrypt_sources(session: AsyncSession, old_key: bytes, new_key: bytes) -> None:
    """Every stored connection credential, decrypted with the old key and
    re-encrypted with the new one, in the caller's transaction. This is the
    whole reason a passphrase does not require re-entering a single
    credential (the ticket's own assumption) — Askwell does the re-encryption,
    not the user.
    """
    rows = (
        await session.execute(
            text("SELECT id, config_encrypted FROM sources WHERE config_encrypted IS NOT NULL")
        )
    ).all()
    for source_id, ciphertext in rows:
        plaintext = crypto.decrypt(bytes(ciphertext), old_key)
        reencrypted = crypto.encrypt(plaintext, new_key)
        await session.execute(
            text("UPDATE sources SET config_encrypted = :config WHERE id = :id"),
            {"config": reencrypted, "id": source_id},
        )


async def set_passphrase(
    session: AsyncSession,
    settings: Settings,
    passphrase: str,
    *,
    acknowledged_no_recovery: bool,
) -> None:
    """Set a passphrase where none existed. Unlocks this process immediately —
    the caller just typed it, so there is nothing to prompt for.
    """
    global _unlocked_key
    if not acknowledged_no_recovery:
        raise NoRecoveryNotAcknowledged(
            "Setting a passphrase requires acknowledging that there is no recovery."
        )
    if await is_enabled(session):
        raise PassphraseAlreadySet("A passphrase is already set. Use change instead.")
    await content_encryption.assert_not_migrating(session)
    strength = assess_strength(passphrase)
    if not strength.meets_minimum:
        raise WeakPassphrase(f"Passphrase must be at least {MIN_LENGTH} characters.")

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret)
    new_key = crypto.derive_key(install_secret, passphrase)

    # Chunk content first, in its own resumable batches: an interrupted run
    # leaves `is_enabled` false and every unmigrated row still readable with
    # `old_key`, so retrying this same call is a safe, ordinary resume
    # rather than a special path (`askwell.content_encryption`'s own
    # docstring). Credentials (`sources`, few rows) stay a single atomic
    # re-encrypt, unchanged from `M7-SEC-BE-151`.
    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)

    await _reencrypt_sources(session, old_key, new_key)
    verifier = crypto.encrypt(_CANARY, new_key)
    await set_setting(session, VERIFIER_KEY, base64.urlsafe_b64encode(verifier).decode("ascii"))
    await record(session, Store.DECISIONS, PASSPHRASE_SET, {})

    _unlocked_key = new_key
    log.info("passphrase_set")


async def change_passphrase(
    session: AsyncSession, settings: Settings, current_passphrase: str, new_passphrase: str
) -> None:
    """Change an existing passphrase. Requires the current one — the
    acceptance criterion draws no exception for "already unlocked" here, and
    requiring it again is cheap insurance against a browser left open.
    """
    global _unlocked_key
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    verifier_b64 = await get_setting(session, VERIFIER_KEY)
    if verifier_b64 is None:
        raise NoPassphraseSet("No passphrase is set. Use set instead.")

    old_key = crypto.derive_key(install_secret, current_passphrase)
    if not _verify(old_key, verifier_b64):
        raise IncorrectPassphrase("Incorrect passphrase.")
    await content_encryption.assert_not_migrating(session)

    strength = assess_strength(new_passphrase)
    if not strength.meets_minimum:
        raise WeakPassphrase(f"Passphrase must be at least {MIN_LENGTH} characters.")

    new_key = crypto.derive_key(install_secret, new_passphrase)
    # The verifier on file is still `old_key`'s, so a crash here and a retry
    # with the same two passphrases re-derives identical `old_key`/`new_key`
    # values and resumes from whatever `content_encrypted` left behind.
    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)
    await _reencrypt_sources(session, old_key, new_key)
    verifier = crypto.encrypt(_CANARY, new_key)
    await set_setting(session, VERIFIER_KEY, base64.urlsafe_b64encode(verifier).decode("ascii"))
    await record(session, Store.DECISIONS, PASSPHRASE_CHANGED, {})

    _unlocked_key = new_key
    log.info("passphrase_changed")


async def remove_passphrase(
    session: AsyncSession, settings: Settings, current_passphrase: str
) -> None:
    """Remove the passphrase. Decrypts everything back to the install-secret-
    only key and states the consequence — the caller is responsible for
    surfacing `docs/ux/settings.md` §4's "losing it means losing the library"
    framing in reverse: removing it means a stolen laptop is a breach again.
    """
    global _unlocked_key
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    verifier_b64 = await get_setting(session, VERIFIER_KEY)
    if verifier_b64 is None:
        raise NoPassphraseSet("No passphrase is set.")

    old_key = crypto.derive_key(install_secret, current_passphrase)
    if not _verify(old_key, verifier_b64):
        raise IncorrectPassphrase("Incorrect passphrase.")
    await content_encryption.assert_not_migrating(session)

    new_key = crypto.derive_key(install_secret)
    await content_encryption.migrate_chunk_content(
        session, old_key, new_key, target_encrypted=False
    )
    await _reencrypt_sources(session, old_key, new_key)
    await session.execute(text("DELETE FROM settings WHERE key = :key"), {"key": VERIFIER_KEY})
    await record(session, Store.DECISIONS, PASSPHRASE_REMOVED, {})

    _unlocked_key = None
    log.info("passphrase_removed")


async def unlock(session: AsyncSession, settings: Settings, passphrase: str) -> None:
    """Unlock this process. Called on restart, before anything else decrypts.

    Not a decisions record — unlocking is not a choice about the library the
    way setting, changing or removing the passphrase is; it is the ordinary
    start of a session, and recording every one would make the decisions
    store noise rather than signal (`docs/audit-log.md` §7's own bar).
    """
    global _unlocked_key
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    verifier_b64 = await get_setting(session, VERIFIER_KEY)
    if verifier_b64 is None:
        raise NoPassphraseSet("No passphrase is set. There is nothing to unlock.")

    key = crypto.derive_key(install_secret, passphrase)
    if not _verify(key, verifier_b64):
        raise IncorrectPassphrase("Incorrect passphrase.")

    _unlocked_key = key
    log.info("passphrase_unlocked")


class StrengthRequest(BaseModel):
    passphrase: str


class SetPassphraseRequest(BaseModel):
    passphrase: str
    acknowledged_no_recovery: bool = False


class ChangePassphraseRequest(BaseModel):
    current_passphrase: str
    new_passphrase: str


class RemovePassphraseRequest(BaseModel):
    current_passphrase: str


class UnlockRequest(BaseModel):
    passphrase: str


def register_passphrase(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`/settings/passphrase*` — `docs/ux/settings.md` §4 and §8."""

    @app.get("/settings/passphrase")
    async def get_status() -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse(await status(db))

    @app.get("/settings/passphrase/migration")
    async def migration_status() -> JSONResponse:
        """`docs/ux/settings.md` §4's progress bar polls this while a
        passphrase set/change/remove is migrating chunk content."""
        async with session_scope(factory) as db:
            return JSONResponse(await content_encryption.migration_progress(db))

    @app.post("/settings/passphrase/strength")
    async def strength(body: StrengthRequest) -> JSONResponse:
        return JSONResponse(assess_strength(body.passphrase).as_dict())

    @app.post("/settings/passphrase/set")
    async def set_route(body: SetPassphraseRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                await set_passphrase(
                    db,
                    settings,
                    body.passphrase,
                    acknowledged_no_recovery=body.acknowledged_no_recovery,
                )
            except (NoRecoveryNotAcknowledged, PassphraseAlreadySet, WeakPassphrase) as error:
                return JSONResponse({"error": str(error)}, status_code=400)
            except content_encryption.MigrationInProgress as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            return JSONResponse({"enabled": True})

    @app.post("/settings/passphrase/change")
    async def change_route(body: ChangePassphraseRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                await change_passphrase(db, settings, body.current_passphrase, body.new_passphrase)
            except NoPassphraseSet as error:
                return JSONResponse({"error": str(error)}, status_code=400)
            except IncorrectPassphrase as error:
                return JSONResponse({"error": str(error)}, status_code=401)
            except WeakPassphrase as error:
                return JSONResponse({"error": str(error)}, status_code=400)
            except content_encryption.MigrationInProgress as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            return JSONResponse({"enabled": True})

    @app.post("/settings/passphrase/remove")
    async def remove_route(body: RemovePassphraseRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                await remove_passphrase(db, settings, body.current_passphrase)
            except NoPassphraseSet as error:
                return JSONResponse({"error": str(error)}, status_code=400)
            except IncorrectPassphrase as error:
                return JSONResponse({"error": str(error)}, status_code=401)
            except content_encryption.MigrationInProgress as error:
                return JSONResponse({"error": str(error)}, status_code=409)
            return JSONResponse(
                {
                    "enabled": False,
                    "message": (
                        "The passphrase has been removed. Your library and stored "
                        "credentials are decrypted with this machine's own key "
                        "again — a stolen laptop is a data breach until a "
                        "passphrase is set again."
                    ),
                }
            )

    @app.post("/settings/passphrase/unlock")
    async def unlock_route(body: UnlockRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            try:
                await unlock(db, settings, body.passphrase)
            except NoPassphraseSet as error:
                return JSONResponse({"error": str(error)}, status_code=400)
            except IncorrectPassphrase as error:
                return JSONResponse({"error": str(error)}, status_code=401)
            return JSONResponse({"locked": False})
