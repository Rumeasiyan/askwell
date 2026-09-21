"""Encrypting `chunks.content` at rest, and the resumable migration between
plaintext and encrypted corpora. `M7-SEC-BE-152`.

**What this protects, and what it honestly does not.** `chunks.content` is
the extracted text of a user's own documents — the thing a stolen, imaged
disk actually exposes. `chunks.content_tsv` (full-text search) and
`chunks.embedding` (dense retrieval) stay derived from *plaintext*, always,
regardless of whether a passphrase is set — `docs/architecture.md` §7 names
this as the accepted leak rather than a gap nobody noticed: a database
tokeniser cannot usefully index ciphertext, and re-deriving the embedding
model to operate on encrypted vectors is outside what a single-machine
product can do (this ticket's own Out of Scope line). The honest claim is
narrower than "the corpus is encrypted": *the content is*; the fact that
forty documents exist, roughly how long each is, and what words they use are
all still visible to anyone with database access.

**Migration is per-row and resumable without re-deriving anything.** Each
chunk's `content_encrypted` flag says whether `content` currently holds
plaintext or a Fernet token. `migrate_chunk_content` repeatedly selects a
batch of rows whose flag does not yet match the target and flips them,
committing after every batch — so a crash mid-migration leaves some rows
already flipped and the rest untouched, and the *next* call (the same
`set_passphrase`/`change_passphrase`/`remove_passphrase` invocation, retried
with the same passphrase, which is a normal retry from the caller's point of
view, not a special resume operation) simply continues: its `WHERE` clause
already excludes the rows a previous, interrupted run finished. No cursor,
no persisted key material, nothing to reconcile — the database rows
themselves are the only state that needs to survive a crash.

**`content_encryption_state` (`settings`) is the concurrency guard**, not
part of the resume logic. While a migration is running, `assert_not_migrating`
refuses a second migration (calling `set_passphrase` again mid-batch from a
racing request) and is the hook a future backup/export feature must call
before copying the database out from under a half-migrated corpus — that
feature does not exist yet (grep confirms no `backup`/`export` route in
`api/src/askwell`), so the hook is here and unused rather than invented
against a caller that is not there; filed as issue #(see docs/decisions.md).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto
from askwell.audit import Store, record
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

STATE_KEY = "content_encryption_state"
TARGET_KEY = "content_encryption_target"

STATE_IDLE = "idle"
STATE_MIGRATING = "migrating"

CONTENT_ENCRYPTION_STARTED = "content_encryption_started"
CONTENT_ENCRYPTION_COMPLETED = "content_encryption_completed"

# Rows per batch, and per commit. Small enough that a crash loses at most
# this many rows' worth of re-work, large enough that a corpus of a few
# thousand chunks — the size this product's single-user, single-machine
# scale actually reaches — migrates in a handful of round trips rather than
# one per row.
BATCH_SIZE = 500


class MigrationInProgress(Exception):
    """A content-encryption migration is already running.

    Raised by `assert_not_migrating` for a second `set_passphrase`/
    `change_passphrase`/`remove_passphrase` call racing the first, and is
    the guard a future backup/export path must call before copying the
    database — see the module docstring.
    """


async def is_migrating(session: AsyncSession) -> bool:
    return await get_setting(session, STATE_KEY) == STATE_MIGRATING


async def assert_not_migrating(session: AsyncSession) -> None:
    if await is_migrating(session):
        raise MigrationInProgress(
            "A content-encryption migration is already in progress. Wait for it to finish."
        )


async def migration_progress(session: AsyncSession) -> dict[str, object]:
    """The state a settings screen renders as a progress bar.

    `target` is `None` when nothing is migrating — there is no meaningful
    "migrated of total" figure for a target that was never set, and a
    screen polling this between migrations should show nothing rather than
    a stale number from the last run.
    """
    migrating = await is_migrating(session)
    target_raw = await get_setting(session, TARGET_KEY)
    target = None if target_raw is None else target_raw == "true"

    total = (
        await session.execute(text("SELECT count(*) FROM chunks WHERE content IS NOT NULL"))
    ).scalar_one()
    if not migrating or target is None:
        return {"migrating": migrating, "migrated": total, "total": total}

    remaining = (
        await session.execute(
            text(
                "SELECT count(*) FROM chunks "
                "WHERE content IS NOT NULL AND content_encrypted != :target"
            ),
            {"target": target},
        )
    ).scalar_one()
    return {"migrating": True, "migrated": total - remaining, "total": total}


def _plaintext_bytes(content: str, *, content_encrypted: bool, old_key: bytes) -> bytes:
    if content_encrypted:
        return crypto.decrypt(content.encode("ascii"), old_key)
    return content.encode("utf-8")


def _stored_value(plaintext: bytes, *, target_encrypted: bool, new_key: bytes) -> str:
    if target_encrypted:
        return crypto.encrypt(plaintext, new_key).decode("ascii")
    return plaintext.decode("utf-8")


async def migrate_chunk_content(
    session: AsyncSession,
    old_key: bytes,
    new_key: bytes,
    *,
    target_encrypted: bool,
) -> None:
    """Migrate every chunk's `content` to `target_encrypted`, in batches,
    resumably. Caller's job: decide `old_key`/`new_key` (they are the same
    key when nothing about the corpus's protection is changing — the
    strength check and `assert_not_migrating` above already ran) and hold
    the transaction the caller is already in; this function commits the
    session repeatedly, which is safe because a crash between commits is
    exactly the interruption this design tolerates.
    """
    already_migrating = await is_migrating(session)
    if not already_migrating:
        await set_setting(session, STATE_KEY, STATE_MIGRATING)
        await set_setting(session, TARGET_KEY, "true" if target_encrypted else "false")
        await record(
            session,
            Store.DECISIONS,
            CONTENT_ENCRYPTION_STARTED,
            {"target_encrypted": target_encrypted},
        )
        await session.commit()

    migrated_any_batch = False
    while True:
        rows = (
            await session.execute(
                text(
                    "SELECT id, content, content_encrypted FROM chunks "
                    "WHERE content IS NOT NULL AND content_encrypted != :target "
                    "ORDER BY id LIMIT :batch_size"
                ),
                {"target": target_encrypted, "batch_size": BATCH_SIZE},
            )
        ).all()
        if not rows:
            break
        for chunk_id, content, content_encrypted in rows:
            plaintext = _plaintext_bytes(
                content, content_encrypted=content_encrypted, old_key=old_key
            )
            stored = _stored_value(plaintext, target_encrypted=target_encrypted, new_key=new_key)
            await session.execute(
                text(
                    "UPDATE chunks SET content = :content, content_encrypted = :encrypted "
                    "WHERE id = :id"
                ),
                {"content": stored, "encrypted": target_encrypted, "id": chunk_id},
            )
        await session.commit()
        migrated_any_batch = True
        log.info("content_encryption_batch", rows=len(rows), target_encrypted=target_encrypted)

    await set_setting(session, STATE_KEY, STATE_IDLE)
    await record(
        session,
        Store.DECISIONS,
        CONTENT_ENCRYPTION_COMPLETED,
        {"target_encrypted": target_encrypted},
    )
    await session.commit()
    if migrated_any_batch or not already_migrating:
        log.info("content_encryption_completed", target_encrypted=target_encrypted)
