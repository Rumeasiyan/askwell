"""Source and document records, and the rule that stops one file being three.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-BE-023`.

This is where a queued batch stops being a list in a browser tab and becomes
something that exists. Until now the add flow ended at *queued* and said so; it
now ends at rows in `sources` and `documents`, an audit record naming every path
Askwell was given, and — for a file it already has — a sentence saying so rather
than a second copy of the same passage in every future answer.

Four ideas carry the module.

**The hash is over the content, and only the content.** Not the name, not the
size, not the modification time. Somebody whose filing is untidy has
`contract.pdf` and `contract copy.pdf` and `contract (1).pdf`, and by every
attribute except their bytes those are three different files. Indexing them
three times does not merely waste an afternoon of CPU: it pollutes retrieval
with three identical passages and makes a citation ambiguous, which is the
thing C4 exists to prevent.

**Askwell never trusts what the browser said a file was.** The client detects by
content too, and that answer is what the user is shown while a drop is being
read — but it is a courtesy, not a boundary. Everything stored here is
recomputed from the bytes on disk at the moment the server opens the file
(`askwell.filetypes`). A record built from a client-declared type would send a
renamed executable to a document extractor.

**A file that moves under Askwell's feet is caught rather than half-recorded.**
The head, the hash and the size are read in one pass, and the file's identity is
checked before and after. A file being written while it is hashed produces a
hash that matches bytes nobody will ever read again; noticing costs one `stat`
and the alternative is a document whose content hash is a lie.

**Nothing is read that a nominated root does not cover.** The permission check is
`askwell.roots`, unchanged and re-used: the roots are read once and every path
in the batch is checked against them, including its real path, so a symlink in a
dropped folder cannot reach outside the tree the user nominated.

Since `M1-ADD-ING-025` a fifth thing happens here: every document recorded gets
an ingestion queue row, written in **this** transaction, and the worker is woken
after the commit. The order matters in both directions. A document committed
without a queue row is a file the user was told was queued and which nothing
will ever pick up; a worker woken before the commit is a worker sent to collect
rows that do not exist yet. See `askwell.ingest`.
"""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import ingest, roots
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.filetypes import HEAD_BYTES, Detection, Verdict, detect
from askwell.logging import get_logger

log = get_logger(__name__)

# Audit kinds. Adding material is a decision the user took about their own
# files, which `docs/audit-log.md` §2 puts in the decisions store. A refusal and
# a duplicate are **not** decisions records: nothing changed, and a store that
# is kept forever should hold what happened rather than what did not.
SOURCE_ADDED = "source_added"
DOCUMENT_ADDED = "document_added"

# How much is read at a time while hashing. Large enough that a 400 MB scan is
# not a million syscalls, small enough that the buffer is not a consideration on
# a laptop already running a model.
READ_CHUNK = 1024 * 1024

# How many times a file that changed under the hash is re-read before Askwell
# gives up on it. A file being saved settles in well under three passes; one
# being appended to continuously never will, and hashing it forever is how a
# drop of sixty contracts never finishes.
HASH_ATTEMPTS = 3

# The most files one request will take. The same cap the browser applies when
# expanding a drop — stated here as well because this endpoint is the boundary
# and the browser is not.
MAX_FILES = 5000


class Outcome(StrEnum):
    """What happened to one file. Four answers, and none of them is silence."""

    ADDED = "added"
    DUPLICATE = "duplicate"
    LATER = "later"
    REFUSED = "refused"


class AddRefused(ValueError):
    """The whole request cannot proceed. The message is shown to the user."""


class FileUnsettled(OSError):
    """The file changed while it was being read, repeatedly."""


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Everything one pass over a file establishes about it."""

    sha256: str
    size: int
    head: bytes


@dataclass(frozen=True, slots=True)
class Existing:
    """The document a duplicate turned out to be.

    Both paths are carried to the surface — this one and the one being added —
    because "already present" without saying *where* leaves the user unsure
    which of their three copies Askwell is actually reading, and that is exactly
    the confusion the duplicate rule exists to remove.
    """

    id: uuid.UUID
    path: str
    filename: str
    source_id: uuid.UUID

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": str(self.id),
            "path": self.path,
            "filename": self.filename,
            "source_id": str(self.source_id),
        }


@dataclass(frozen=True, slots=True)
class FileResult:
    """What happened to one file, in terms the screen can render verbatim."""

    relative_path: str
    path: str
    filename: str
    outcome: Outcome
    detection: Detection | None = None
    document_id: uuid.UUID | None = None
    existing: Existing | None = None
    sha256: str | None = None
    size: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "path": self.path,
            "filename": self.filename,
            "outcome": str(self.outcome),
            "format": self.detection.format if self.detection else None,
            "mime": self.detection.mime if self.detection else None,
            "mismatch": self.detection.mismatch if self.detection else None,
            "arrives": self.detection.arrives if self.detection else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "existing": self.existing.as_dict() if self.existing else None,
            "sha256": self.sha256,
            "size": self.size,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AddResult:
    """What a whole add did.

    `source` is None when nothing was added — every file was a duplicate, a
    later format or refused. Creating an empty source in that case would put a
    row in the library that holds nothing and explains nothing.
    """

    files: list[FileResult] = field(default_factory=list)
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    # The source's status as stored, read rather than assumed. A source added
    # to a second time may have moved past `queued` — and a response that says
    # `queued` about a source that is ready is a progress bar running backwards.
    source_status: str | None = None
    root_path: str | None = None
    created_source: bool = False
    # The documents that now have a queue row. Carried out of `add` because
    # waking a worker must happen *after* the transaction commits — dispatching
    # inside it would ask a worker to pick up rows that do not exist yet, and on
    # a rolled-back add would ask it to pick up rows that never will.
    queued: list[uuid.UUID] = field(default_factory=list)

    def count(self, outcome: Outcome) -> int:
        return sum(1 for item in self.files if item.outcome is outcome)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": (
                None
                if self.source_id is None
                else {
                    "id": str(self.source_id),
                    "name": self.source_name,
                    "root_path": self.root_path,
                    # Recorded and waiting. `queued` for a source created here:
                    # nothing is reading these yet, and saying `indexing` would
                    # be a progress bar for work that has not started.
                    "status": self.source_status,
                    "created": self.created_source,
                }
            ),
            "added": self.count(Outcome.ADDED),
            "duplicates": self.count(Outcome.DUPLICATE),
            "later": self.count(Outcome.LATER),
            "refused": self.count(Outcome.REFUSED),
            "files": [item.as_dict() for item in self.files],
        }


# --- reading a file ---------------------------------------------------------


def _identity(path: str) -> tuple[int, int, int, int]:
    """What has to still be true after the read for the hash to mean anything.

    Device and inode catch the file being replaced — the common shape, because
    every careful editor writes a temporary file and renames it over the
    original, so the path stays valid and the contents are somebody else's.
    Size and modification time catch it being written in place.
    """
    stat = os.stat(path)
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def fingerprint(path: str, attempts: int = HASH_ATTEMPTS) -> Fingerprint:
    """Hash a file's contents, and be sure the contents held still.

    Blocking, deliberately visible as such: every caller reaches it through
    `asyncio.to_thread`. Reading a 400 MB scan on the event loop would stop the
    API answering anything, `/health` included.

    One pass produces both the head and the hash. Opening the file twice would
    be two chances for it to change between them, and the head is what decides
    the file's type — so a second read could type one version of a file and
    hash another.
    """
    for attempt in range(attempts):
        before = _identity(path)
        digest = hashlib.sha256()
        head = b""
        size = 0
        with open(path, "rb") as handle:
            while True:
                block = handle.read(READ_CHUNK)
                if not block:
                    break
                if len(head) < HEAD_BYTES:
                    head += block[: HEAD_BYTES - len(head)]
                size += len(block)
                digest.update(block)
        if _identity(path) == before:
            return Fingerprint(sha256=digest.hexdigest(), size=size, head=head)
        log.info("file_changed_while_hashing", path=path, attempt=attempt + 1)

    raise FileUnsettled(
        f"{path} kept changing while Askwell was reading it, over {attempts} "
        f"attempts. Something else on this machine is still writing to it."
    )


UNSETTLED_REASON = (
    "This file changed while Askwell was reading it, every time it tried. "
    "Something else is still writing to it — close it, or wait for whatever is "
    "producing it to finish, and add it again. Nothing was recorded for it."
)

MISSING_REASON = (
    "Askwell could not find this file. It may have been moved or renamed since "
    "it was dropped. Nothing on disk was changed."
)

UNREADABLE_REASON = (
    "Askwell is not allowed to read this file. Check its permissions — and on a "
    "machine with SELinux, that the folder's bind mount is labelled so a "
    "container may traverse it."
)


def _outside_reason(folder: str) -> str:
    return (
        f"This path is not inside {folder}, which is the folder these files were "
        f"said to come from. Nothing was recorded for it."
    )


def _uncovered_reason(path: str) -> str:
    return (
        f"No folder you have nominated covers {path}, so Askwell will not read "
        f"it. Nominate the folder it is in first — Askwell reads your files "
        f"where they are and never copies them, so it has to be told which "
        f"folders it may open."
    )


# --- the record path --------------------------------------------------------


async def _live_source(session: AsyncSession, root_path: str) -> tuple[uuid.UUID, str, str] | None:
    """The source already covering this folder, if there is one.

    One source per folder, re-used rather than re-created. Adding the same
    folder twice is an ordinary thing to do — a few more contracts arrived —
    and two sources over one folder would show the same material twice in the
    library and make the per-source duplicate index meaningless.
    """
    result = await session.execute(
        text(
            "SELECT id, name, status FROM sources WHERE kind = 'file' AND root_path = :path "
            "AND status <> 'deleted' ORDER BY added_at LIMIT 1"
        ),
        {"path": root_path},
    )
    row = result.first()
    return (row[0], row[1], row[2]) if row is not None else None


async def _create_source(session: AsyncSession, root_path: str) -> tuple[uuid.UUID, str, str]:
    name = os.path.basename(root_path) or root_path
    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, root_path, status) "
            "VALUES ('file', :name, :root_path, 'queued') RETURNING id, name, status"
        ),
        {"name": name, "root_path": root_path},
    )
    row = result.one()
    await record(
        session,
        Store.DECISIONS,
        SOURCE_ADDED,
        {"source_id": str(row[0]), "name": name, "root_path": root_path},
    )
    log.info("source_added", source_id=str(row[0]), root_path=root_path)
    return (row[0], row[1], row[2])


async def _duplicate_of(session: AsyncSession, sha256: str) -> Existing | None:
    """The live document that already holds this content, anywhere.

    Deliberately across every source rather than only the one being added to.
    The user's problem is the same contract in three folders, and three folders
    are three sources — a per-source check would recognise none of them and the
    ticket's own example would fail.

    The per-source *index* is narrower than this on purpose, and the two are not
    redundant: the index cannot be global, because a file legitimately present
    under two nominated folders must still be recordable if a later ticket
    decides it should be. Recognition is a product rule and lives here; the
    index is a floor under it.
    """
    result = await session.execute(
        text(
            "SELECT id, path, filename, source_id FROM documents "
            "WHERE sha256 = :sha256 AND deleted_at IS NULL AND superseded_by IS NULL "
            "ORDER BY added_at LIMIT 1"
        ),
        {"sha256": sha256},
    )
    row = result.first()
    if row is None:
        return None
    return Existing(id=row[0], path=row[1], filename=row[2], source_id=row[3])


async def add(
    session: AsyncSession,
    folder: str,
    relative_paths: list[str],
) -> AddResult:
    """Record a batch of files as documents under one source.

    Refuses the whole request only for things that are wrong about the request
    itself: a folder that is not an absolute path, an empty list, a list longer
    than the cap. Everything else — including a path no nominated root covers —
    is reported against the individual file and the rest of the batch carries
    on. One archive among sixty contracts must not take the contracts with it,
    and neither must one file that has been moved since it was dropped.
    """
    root_path = roots.normalise(folder)

    if not relative_paths:
        raise AddRefused("No files were named.")
    if len(relative_paths) > MAX_FILES:
        raise AddRefused(
            f"{len(relative_paths)} files is more than Askwell takes in one go. "
            f"Add them in batches of {MAX_FILES} or fewer."
        )

    # Read once, for the whole batch. `roots.covering` would re-read them per
    # file, which for five thousand files is five thousand queries to learn one
    # fact that cannot change mid-request.
    nominated = [item.path for item in await roots.active(session)]

    files: list[FileResult] = []
    source: tuple[uuid.UUID, str, str] | None = None
    created = False
    # Two files with the same content inside one batch. The database would
    # catch it on the second insert, but as an integrity error rather than as a
    # sentence — and the ticket's own example is exactly this: `contract.pdf`
    # and `contract copy.pdf`, dropped together.
    seen: dict[str, Existing] = {}

    for relative in relative_paths:
        # Off the loop: `_resolve` calls `realpath`, which is a syscall per path
        # component, and a network share that has gone away does not answer it
        # quickly. AGENTS.md §6 forbids a blocking call in a request handler,
        # and the concrete consequence is that one dead share would stop the API
        # answering anything, `/health` included.
        path, filename, refusal = await asyncio.to_thread(_resolve, root_path, relative, nominated)
        if refusal is not None:
            files.append(_refused(relative, path, filename, refusal))
            continue

        try:
            stamp = await asyncio.to_thread(fingerprint, path)
        except FileNotFoundError:
            files.append(_refused(relative, path, filename, MISSING_REASON))
            continue
        except PermissionError:
            files.append(_refused(relative, path, filename, UNREADABLE_REASON))
            continue
        except FileUnsettled:
            files.append(_refused(relative, path, filename, UNSETTLED_REASON))
            continue
        except OSError as error:
            why = f"Askwell could not read this file: {error.strerror}."
            files.append(_refused(relative, path, filename, why))
            continue

        detection = detect(filename, stamp.head, stamp.size)

        if detection.verdict is Verdict.REFUSED:
            # Logged, not recorded: nothing changed, and the decisions store is
            # kept forever. This is the durable record of a refusal that the
            # browser's local counter is not.
            log.info(
                "file_refused",
                path=path,
                format=detection.format,
                reason=detection.refusal,
                size=stamp.size,
            )
            files.append(
                FileResult(
                    relative_path=relative,
                    path=path,
                    filename=filename,
                    outcome=Outcome.REFUSED,
                    detection=detection,
                    size=stamp.size,
                    reason=detection.refusal,
                )
            )
            continue

        if detection.verdict is Verdict.LATER:
            log.info(
                "file_arrives_later",
                path=path,
                format=detection.format,
                arrives=detection.arrives,
            )
            files.append(
                FileResult(
                    relative_path=relative,
                    path=path,
                    filename=filename,
                    outcome=Outcome.LATER,
                    detection=detection,
                    size=stamp.size,
                )
            )
            continue

        existing = seen.get(stamp.sha256) or await _duplicate_of(session, stamp.sha256)
        if existing is not None:
            log.info("file_duplicate", path=path, of=existing.path, sha256=stamp.sha256)
            files.append(
                FileResult(
                    relative_path=relative,
                    path=path,
                    filename=filename,
                    outcome=Outcome.DUPLICATE,
                    detection=detection,
                    existing=existing,
                    sha256=stamp.sha256,
                    size=stamp.size,
                )
            )
            continue

        if source is None:
            source = await _live_source(session, root_path)
            if source is None:
                source = await _create_source(session, root_path)
                created = True

        document_id = await _insert_document(
            session,
            source_id=source[0],
            path=path,
            filename=filename,
            mime=detection.mime,
            sha256=stamp.sha256,
        )
        seen[stamp.sha256] = Existing(
            id=document_id, path=path, filename=filename, source_id=source[0]
        )
        files.append(
            FileResult(
                relative_path=relative,
                path=path,
                filename=filename,
                outcome=Outcome.ADDED,
                detection=detection,
                document_id=document_id,
                sha256=stamp.sha256,
                size=stamp.size,
            )
        )

    added = [item.document_id for item in files if item.document_id is not None]
    if source is not None and added:
        # In this transaction, deliberately. A document that exists with no
        # queue row is a file the user was told was queued and which nothing
        # will ever pick up — and the two writes being in one transaction is
        # the only thing that makes that impossible rather than unlikely.
        # Waking a worker is a separate matter and happens after the commit.
        await ingest.enqueue(session, source[0], added)

    return AddResult(
        files=files,
        source_id=source[0] if source else None,
        source_name=source[1] if source else None,
        source_status=source[2] if source else None,
        root_path=root_path,
        created_source=created,
        queued=added,
    )


def _refused(relative: str, path: str, filename: str, reason: str) -> FileResult:
    log.info("file_refused", path=path, reason=reason)
    return FileResult(
        relative_path=relative,
        path=path,
        filename=filename,
        outcome=Outcome.REFUSED,
        reason=reason,
    )


def _resolve(root_path: str, relative: str, nominated: list[str]) -> tuple[str, str, str | None]:
    """Where a named file actually is, and whether Askwell may open it.

    Two separate checks, and neither implies the other. Containment stops a
    relative path climbing out of the folder the user named — `../../etc` is a
    string a client can send, and the fact that today's client would not send it
    is not a property of this endpoint. Coverage is the roots permission, which
    is what decides whether any path may be read at all, and it is applied to
    the file's real path as well as its literal one so that a symlink dropped
    inside a nominated folder cannot stand in for the whole disk.
    """
    joined = os.path.normpath(os.path.join(root_path, relative))
    filename = os.path.basename(joined)

    if not roots.contains(root_path, joined):
        return (joined, filename, _outside_reason(root_path))

    real = os.path.realpath(joined)
    if roots.first_covering(nominated, joined, real) is None:
        return (joined, filename, _uncovered_reason(joined))

    return (joined, filename, None)


async def _insert_document(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    path: str,
    filename: str,
    mime: str | None,
    sha256: str,
) -> uuid.UUID:
    """One document row and the decisions record that says it was added.

    Both in the caller's transaction. A document Askwell cannot say it was given
    is a document nobody can later explain, and `docs/audit-log.md` treats the
    decisions store as the record of what the user chose — "I gave Askwell these
    sixty files" is exactly that.
    """
    result = await session.execute(
        text(
            "INSERT INTO documents (source_id, filename, path, mime, sha256, status) "
            "VALUES (:source_id, :filename, :path, :mime, :sha256, 'queued') RETURNING id"
        ),
        {
            "source_id": source_id,
            "filename": filename,
            "path": path,
            "mime": mime,
            "sha256": sha256,
        },
    )
    document_id: uuid.UUID = result.scalar_one()
    await record(
        session,
        Store.DECISIONS,
        DOCUMENT_ADDED,
        {
            "document_id": str(document_id),
            "source_id": str(source_id),
            "path": path,
            "filename": filename,
            "mime": mime,
            "sha256": sha256,
        },
    )
    return document_id


# --- the surface ------------------------------------------------------------


class AddRequest(BaseModel):
    """A folder, and the files under it that were dropped.

    Paths are relative to the folder and the folder is absolute, which is the
    shape the browser can actually produce: it hands over names and a tree, never
    a location, so the location is asked once per drop and typed.
    `M7-TAURI-FE-182` replaces that question with the platform's directory
    dialog and hands back the same two fields.

    No bytes cross this boundary. Askwell indexes in place — the server opens
    the user's own file at the path they named, and this must never become an
    upload.
    """

    folder: str = Field(min_length=1, max_length=4096)
    files: list[str] = Field(min_length=1, max_length=MAX_FILES)


def register_sources(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the sources surface. Register before the interface catch-all."""

    @app.post("/sources")
    async def add_source(body: AddRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                result = await add(db, body.folder, body.files)
        except (AddRefused, roots.RootRefused) as refusal:
            # 400, not 422: the request is exactly the shape the interface meant
            # to send, and what is wrong is the folder. A validation error would
            # tell the caller their JSON was malformed, which it was not.
            return JSONResponse({"error": str(refusal), "folder": body.folder}, status_code=400)

        # After the commit, and never able to fail the request. The queue rows
        # are already durable; this only saves the worker waiting for its next
        # reconcile, so a Redis that is down costs half a minute rather than an
        # import.
        await ingest.dispatch(settings, result.queued)
        return JSONResponse(result.as_dict(), status_code=201)
