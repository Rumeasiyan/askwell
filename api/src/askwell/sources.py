"""Sources and documents: what Askwell has been given, and what it already had.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-BE-023`.

Adding material writes two kinds of row. A `sources` row is the folder the user
pointed at; a `documents` row is one file inside it, with the path it was found
at, its content hash and the stage it has reached. Nothing is copied — Askwell
indexes in place, so `documents.path` is a location on the user's own disk and
not a handle into a store Askwell owns.

Three ideas carry this module.

**A file is its bytes.** Duplicate recognition hashes content and nothing else:
not the name, not the size, not the modification time. `contract.pdf` and
`contract copy.pdf` are the same document, and `report.pdf` saved twice from
different templates is two, and neither of those is a judgement any filename
could support. The hash is computed here, before indexing, because the whole
point is to *not* index the second copy — a duplicate discovered during
extraction has already cost the work it exists to save.

**Recognition is a link, not a refusal.** A duplicate is not an error and is
never reported as one. The reply names both paths — the one already indexed and
the one just offered — because a user with the same contract in three folders
needs to know *which* copy answers are citing, and "already present" without a
path leaves them hunting. `docs/ux/add-source.md` §5 and
`docs/states-and-edge-cases.md` §3 both say linked, not rejected.

**The database enforces it too, and differently.** The code rule here is global:
a hash live anywhere is recognised. The partial unique index
`uq_documents_live_source_id_sha256` created with the v1 schema is narrower —
one live version per (source, hash) — and is a backstop against a future code
path that forgets, not a restatement of this one. Two checks, neither derived
from the other, is the same shape as C2's parser plus read-only role.

Status is a real stage rather than a mood. A row lands `queued`, because that is
what it is: written, waiting, with no worker looking at it. It becomes
`indexing` when one does, and then `ready` or `attention`. `docs/architecture.md`
§7's word for indexed is `ready`, and this module uses the schema's vocabulary
rather than the ticket's prose.

What is deliberately *not* here: supersession of a changed file, which is
`M1-INDEX-BE-034` and needs a rule about when a change has settled; deletion,
which is M2; and format rejection, which is `M1-ADD-VAL-024`. A file whose type
is unsupported is accepted by this module and rejected by that one — putting a
half-detector here would mean two answers to the same question.
"""

import asyncio
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import roots
from askwell.audit import Store, record
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

# Audit kinds. Adding material is a decision about what Askwell holds, which
# `docs/audit-log.md` §2 puts in the decisions store. A duplicate and a
# rejection are logged and are *not* decisions records: nothing changed, and a
# decisions store that also records non-events stops being a record of what the
# user did.
SOURCE_ADDED = "source_added"
DOCUMENT_ADDED = "document_added"

# The same cap the add-source screen applies to one drop (`web/lib/add-source.ts`
# MAX_FILES). Stated in both places because the browser cannot be the only thing
# enforcing it — the API is reachable without it.
MAX_FILES = 5000

# One mebibyte. Large enough that a 500 MB scan is a few hundred reads rather
# than a hundred thousand, small enough that hashing never holds a meaningful
# amount of a laptop's memory.
READ_CHUNK = 1024 * 1024

# How many times a file that is being written underneath us is re-hashed before
# Askwell gives up on it. Three, because the case this exists for is a file
# still arriving — a download, a sync client, a `Save As` in progress — and a
# fourth attempt on something genuinely mid-write is no more likely to catch a
# quiet moment than the third was.
HASH_ATTEMPTS = 3


class DocumentStatus(StrEnum):
    """Where a document actually is. Not a progress percentage.

    `QUEUED` is distinct from `INDEXING` on purpose. A queued document has a
    row and nothing looking at it, which on a laptop embedding a large corpus is
    where a document spends most of its life, and
    `docs/states-and-edge-cases.md` §3 requires that state be said plainly
    rather than shown as a bar that never moves.
    """

    QUEUED = "queued"
    INDEXING = "indexing"
    READY = "ready"
    ATTENTION = "attention"
    DELETED = "deleted"


# What may follow what. A document goes forward, and comes back only by being
# retried or re-indexed — both of which are real actions someone takes.
#
# Written down rather than left to callers because a status that can be set to
# anything reports whatever the last piece of code to run believed, and the one
# thing this column is for is being trusted.
TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.QUEUED: frozenset({DocumentStatus.INDEXING, DocumentStatus.ATTENTION}),
    DocumentStatus.INDEXING: frozenset({DocumentStatus.READY, DocumentStatus.ATTENTION}),
    # A re-index, and a retry after a failure. Neither is exotic: the first
    # happens when a chunking or embedding change lands, the second every time
    # somebody fixes whatever made extraction fail.
    DocumentStatus.READY: frozenset({DocumentStatus.QUEUED, DocumentStatus.INDEXING}),
    DocumentStatus.ATTENTION: frozenset({DocumentStatus.QUEUED, DocumentStatus.INDEXING}),
    # Deletion is M2 and is not reached from here. Present so that the table is
    # exhaustive: a missing key would read as "anything goes" at the one place
    # the rule is looked up.
    DocumentStatus.DELETED: frozenset(),
}


class Outcome(StrEnum):
    """What happened to one file. Three outcomes, and only one is a failure."""

    ADDED = "added"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class SourceRefused(ValueError):
    """The whole request cannot proceed. The message is shown to the user."""


class FileRefused(ValueError):
    """One file cannot be added. The message is shown to the user."""


class TransitionRefused(ValueError):
    """A status change that is not a stage this document could have reached."""


class DocumentNotFound(LookupError):
    """No live document with that identifier."""


# --- hashing ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Enough of a file's metadata to tell whether it changed under us.

    Not a substitute for the hash and never used as one — this is the check
    that the bytes just read were all from the same version of the file.
    `inode` is here because replacing a file is the *usual* way an editor saves:
    write a temporary file, rename it into place. Size and time alone would miss
    that entirely when the replacement happens to be the same length.
    """

    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int


def _fingerprint(status: os.stat_result) -> Fingerprint:
    return Fingerprint(
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
        ctime_ns=status.st_ctime_ns,
        inode=status.st_ino,
    )


def digest(path: str, attempts: int = HASH_ATTEMPTS) -> tuple[str, Fingerprint]:
    """The sha256 of a file's contents, and proof it held still while read.

    Blocking, and called through a thread. It is the only expensive thing this
    module does, and on a folder of scans it is minutes of disk.

    The file is fingerprinted from the open descriptor before and after reading,
    and against the path afterwards. A mismatch means the bytes hashed were not
    all one version of the file, so the hash identifies nothing — indexing on it
    would file the document under a content hash it does not have, and the
    duplicate check would then be wrong for as long as the row survives. So it
    is re-hashed rather than accepted.
    """
    for _ in range(attempts):
        try:
            found = os.stat(path)
        except FileNotFoundError:
            raise FileRefused(
                f"{path} is not there. If it was on a drive or a share, "
                "reconnect it and add it again — nothing was indexed and "
                "nothing was deleted."
            ) from None
        except PermissionError:
            raise FileRefused(
                f"Askwell is not allowed to read {path}. Check its permissions, "
                "and on a machine with SELinux that the bind mount is labelled "
                "so a container may traverse it."
            ) from None
        except OSError as error:
            raise FileRefused(f"{path} could not be read: {error.strerror}.") from None

        # Checked before anything is opened, and deliberately: opening a named
        # pipe blocks until somebody writes to it, which would hang the thread
        # this runs in rather than producing a refusal anyone can read.
        if not stat.S_ISREG(found.st_mode):
            raise FileRefused(
                f"{path} is not a file. Askwell indexes files; a folder is added "
                "by naming the folder, and a device or a pipe holds no document."
            )
        if found.st_size == 0:
            # Rejected rather than indexed as an empty document. A zero-byte
            # file produces no chunks, so it would sit in the library
            # permanently "ready" and never answer anything — and, worse, every
            # empty file shares one hash, so the second one would be reported as
            # a duplicate of the first, which is true of the bytes and
            # misleading about the documents.
            raise FileRefused(
                f"{path} is empty — 0 bytes. There is nothing in it to read, so "
                "nothing was added. If it should have content, whatever wrote "
                "it did not finish."
            )

        try:
            with open(path, "rb", buffering=0) as handle:
                opened = _fingerprint(os.fstat(handle.fileno()))
                content = hashlib.sha256()
                while chunk := handle.read(READ_CHUNK):
                    content.update(chunk)
                after = _fingerprint(os.fstat(handle.fileno()))
        except OSError as error:
            raise FileRefused(f"{path} could not be read: {error.strerror}.") from None

        try:
            on_disk = _fingerprint(os.stat(path))
        except OSError:
            # It went away while being read. Treated as a change rather than as
            # an absence: the next attempt reports whichever of the two it is.
            continue

        if opened == after == on_disk:
            return content.hexdigest(), after

    raise FileRefused(
        f"{path} kept changing while Askwell was reading it, so the copy it read "
        "was not one version of the file. It was not indexed. This usually means "
        "something is still writing it — a download, a sync client, or a save in "
        "progress. Add it again once it has settled."
    )


# --- what happened to each file ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Existing:
    """The live document a duplicate was recognised as."""

    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    path: str
    filename: str
    added_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "source_id": str(self.source_id),
            "source_name": self.source_name,
            "path": self.path,
            "filename": self.filename,
            "added_at": self.added_at.isoformat(),
        }


def duplicate_reason(path: str, existing: Existing) -> str:
    """Both paths, always.

    The user has the same file in more than one folder and is about to be told
    one of them was skipped. Which one is indexed is the entire question, and a
    message that says "already present" without saying where sends them looking
    through their own filing to work out what Askwell did.
    """
    same_name = os.path.basename(path) == existing.filename
    relation = (
        "the same file in another folder" if same_name else "the same content under another name"
    )
    return (
        f"Askwell already has this, byte for byte — {relation}. It is indexed as "
        f"{existing.path}, in {existing.source_name}, so {path} was not indexed "
        "again and answers will cite the copy that was. Nothing was deleted: "
        "both files are still where you put them."
    )


@dataclass(frozen=True, slots=True)
class FileOutcome:
    """One file's result. Everything the interface needs to render its row."""

    path: str
    filename: str
    outcome: Outcome
    reason: str | None = None
    document_id: uuid.UUID | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    mime: str | None = None
    status: DocumentStatus | None = None
    existing: Existing | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "outcome": str(self.outcome),
            "reason": self.reason,
            "document_id": str(self.document_id) if self.document_id else None,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "mime": self.mime,
            "status": str(self.status) if self.status else None,
            "existing": self.existing.as_dict() if self.existing else None,
        }


@dataclass(frozen=True, slots=True)
class Addition:
    """What one add did, in full.

    `source_id` is None when nothing was added — every file was already present
    or every file was refused. No empty source row is written in that case: a
    folder in the library with nothing in it is a thing the user has to work out
    the meaning of, and the meaning is "nothing happened".
    """

    root_path: str
    name: str
    source_id: uuid.UUID | None
    files: list[FileOutcome]

    def counted(self, outcome: Outcome) -> int:
        return sum(1 for item in self.files if item.outcome is outcome)

    def as_dict(self) -> dict[str, Any]:
        return {
            # Local counters, and the only analytics this feature has. Computed
            # here, read by the interface, and with no path off the machine to
            # take (C1).
            "added": self.counted(Outcome.ADDED),
            "duplicates": self.counted(Outcome.DUPLICATE),
            "rejected": self.counted(Outcome.REJECTED),
            "source": (
                None
                if self.source_id is None
                else {"id": str(self.source_id), "name": self.name, "root_path": self.root_path}
            ),
            "root_path": self.root_path,
            "files": [item.as_dict() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    """A file the caller offered, with its mime as the caller detected it."""

    path: str
    mime: str | None = None


# --- adding -----------------------------------------------------------------


def covered(root_paths: list[str], path: str) -> str | None:
    """The path in its stored form if a nominated root permits reading it.

    The rule is `roots.first_covering` and not a second copy of it. Two
    implementations of a permission check drift, and the one that drifts is the
    one nobody is reading when it does.
    """
    resolved = roots.literal_and_real(path)
    if resolved is None:
        return None
    literal, real = resolved
    return literal if roots.first_covering(root_paths, literal, real) is not None else None


def checked_digest(path: str, root_paths: list[str]) -> tuple[str, str, Fingerprint]:
    """Check the permission and hash the file, in one hop off the event loop.

    Returns the path in the form that will be stored, alongside the hash.

    Both halves touch the filesystem — `realpath` is a syscall per component and
    the hash reads every byte — so they are done together rather than in two
    thread hops per file. Order matters and is not an optimisation: nothing is
    opened until a nominated root has been found to cover it.
    """
    if not path.startswith("/"):
        raise FileRefused(
            f"Askwell needs the whole path, starting with a slash — {path!r} is "
            "relative to something, and Askwell and your file manager do not "
            "share a current directory."
        )
    literal = covered(root_paths, path)
    if literal is None:
        raise FileRefused(
            f"No folder you have nominated covers {path}, so Askwell will not "
            "read it. Nominate the folder it is in first — Askwell reads your "
            "files where they are, so it has to be told which folders it may "
            "open."
        )
    sha256, fingerprint = digest(literal)
    return literal, sha256, fingerprint


async def _live_document(session: AsyncSession, sha256: str) -> Existing | None:
    """The document this content already is, if Askwell has it.

    Global rather than per source: the ticket's user has the same contract in
    three folders, and three folders is three sources. Restricting the search to
    the source being added to would recognise nothing in exactly the case this
    exists for.

    Live means neither tombstoned nor superseded. A deleted document's row
    survives so old citations resolve, and matching against it would refuse to
    re-add a file the user deliberately removed and then changed their mind
    about. Oldest first, so the answer does not move about if the invariant
    ever fails to hold.
    """
    result = await session.execute(
        text(
            "SELECT d.id, d.source_id, d.path, d.filename, d.added_at, s.name AS source_name "
            "FROM documents d JOIN sources s ON s.id = d.source_id "
            "WHERE d.sha256 = :sha256 "
            "AND d.deleted_at IS NULL AND d.superseded_by IS NULL "
            "ORDER BY d.added_at, d.id LIMIT 1"
        ),
        {"sha256": sha256},
    )
    row = result.first()
    if row is None:
        return None
    return Existing(
        id=row.id,
        source_id=row.source_id,
        source_name=row.source_name,
        path=row.path,
        filename=row.filename,
        added_at=row.added_at,
    )


async def _create_source(session: AsyncSession, name: str, root_path: str) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, root_path, status) "
            "VALUES ('file', :name, :root_path, :status) RETURNING id"
        ),
        {"name": name, "root_path": root_path, "status": str(DocumentStatus.QUEUED)},
    )
    source_id: uuid.UUID = result.scalar_one()
    await record(
        session,
        Store.DECISIONS,
        SOURCE_ADDED,
        {"source_id": str(source_id), "kind": "file", "name": name, "root_path": root_path},
    )
    log.info("source_added", source_id=str(source_id), name=name, root_path=root_path)
    return source_id


async def _create_document(
    session: AsyncSession,
    source_id: uuid.UUID,
    candidate: Candidate,
    sha256: str,
    fingerprint: Fingerprint,
) -> uuid.UUID:
    filename = os.path.basename(candidate.path)
    result = await session.execute(
        text(
            "INSERT INTO documents (source_id, filename, path, mime, sha256, status) "
            "VALUES (:source_id, :filename, :path, :mime, :sha256, :status) RETURNING id"
        ),
        {
            "source_id": source_id,
            "filename": filename,
            "path": candidate.path,
            "mime": candidate.mime,
            "sha256": sha256,
            "status": str(DocumentStatus.QUEUED),
        },
    )
    document_id: uuid.UUID = result.scalar_one()

    # The path is in the record because that is what makes it answerable later:
    # "when did this contract enter Askwell, and from where" is the question the
    # decisions store exists for, and a bare identifier answers neither half.
    await record(
        session,
        Store.DECISIONS,
        DOCUMENT_ADDED,
        {
            "document_id": str(document_id),
            "source_id": str(source_id),
            "path": candidate.path,
            "filename": filename,
            "mime": candidate.mime,
            "sha256": sha256,
            "size_bytes": fingerprint.size,
        },
    )
    log.info("document_added", document_id=str(document_id), path=candidate.path, sha256=sha256)
    return document_id


def default_name(root_path: str) -> str:
    """What to call a source nobody named. The folder, as the user sees it."""
    return os.path.basename(root_path) or root_path


async def add(
    session: AsyncSession,
    root_path: str,
    candidates: list[Candidate],
    name: str | None = None,
) -> Addition:
    """Add files under a nominated folder. Recognise the ones already held.

    The source row is created lazily, on the first file that is actually added,
    so a drop of nothing but duplicates leaves the library exactly as it was
    rather than adding a folder with no contents.

    Files are handled one at a time rather than concurrently. The work is disk,
    and on the laptop this runs on — which is also running the user's browser —
    four threads reading four large scans at once is slower than one, not
    faster.
    """
    root = roots.normalise(root_path)
    if not candidates:
        raise SourceRefused("No files were named, so there was nothing to add.")
    if len(candidates) > MAX_FILES:
        raise SourceRefused(
            f"{len(candidates)} files were offered at once and Askwell takes "
            f"{MAX_FILES}. Add them in batches — nothing was added, so nothing "
            "is half-done."
        )

    # Read once for the whole batch. `roots.covering()` would re-read the
    # registry per file, which on a folder of five thousand documents is five
    # thousand queries answering the same question.
    nominated = await roots.active(session)
    root_paths = [item.path for item in nominated]
    if await asyncio.to_thread(covered, root_paths, root) is None:
        raise SourceRefused(
            f"No folder you have nominated covers {root}. Askwell reads your "
            "files where they are and never copies them, so it has to be told "
            "which folders it may open. Nominate this one first."
        )

    resolved_name = (name or "").strip() or default_name(root)
    source_id: uuid.UUID | None = None
    outcomes: list[FileOutcome] = []

    for candidate in candidates:
        try:
            path, sha256, fingerprint = await asyncio.to_thread(
                checked_digest, candidate.path, root_paths
            )
        except FileRefused as refusal:
            log.info("document_rejected", path=candidate.path, reason=str(refusal))
            outcomes.append(
                FileOutcome(
                    path=candidate.path,
                    filename=os.path.basename(candidate.path),
                    outcome=Outcome.REJECTED,
                    reason=str(refusal),
                )
            )
            continue

        filename = os.path.basename(path)
        # Within this batch as well as against the library: the two copies in
        # one drop are the ticket's own example, and they are only both visible
        # here because the earlier insert is in this same transaction.
        existing = await _live_document(session, sha256)
        if existing is not None:
            log.info("document_duplicate", path=path, existing=str(existing.id))
            outcomes.append(
                FileOutcome(
                    path=path,
                    filename=filename,
                    outcome=Outcome.DUPLICATE,
                    reason=duplicate_reason(path, existing),
                    document_id=existing.id,
                    sha256=sha256,
                    size_bytes=fingerprint.size,
                    existing=existing,
                )
            )
            continue

        if source_id is None:
            source_id = await _create_source(session, resolved_name, root)
        stored = Candidate(path=path, mime=candidate.mime)
        document_id = await _create_document(session, source_id, stored, sha256, fingerprint)
        outcomes.append(
            FileOutcome(
                path=path,
                filename=filename,
                outcome=Outcome.ADDED,
                document_id=document_id,
                sha256=sha256,
                size_bytes=fingerprint.size,
                mime=candidate.mime,
                status=DocumentStatus.QUEUED,
            )
        )

    return Addition(root_path=root, name=resolved_name, source_id=source_id, files=outcomes)


# --- stages -----------------------------------------------------------------


async def mark(
    session: AsyncSession, document_id: uuid.UUID, status: DocumentStatus
) -> DocumentStatus:
    """Move a document to the stage it has actually reached.

    Refuses a transition that is not one, rather than writing it. The status is
    what the library renders and what tells the user whether their question can
    be answered yet; a column that accepts anything reports whatever ran last,
    and the failure is silent and looks like a UI bug for weeks.
    """
    result = await session.execute(
        text("SELECT status FROM documents WHERE id = :id AND deleted_at IS NULL"),
        {"id": document_id},
    )
    row = result.first()
    if row is None:
        raise DocumentNotFound(str(document_id))

    current = DocumentStatus(row.status)
    if status is not current and status not in TRANSITIONS[current]:
        raise TransitionRefused(
            f"A document that is {current} does not become {status}. "
            f"From {current} it can become "
            f"{', '.join(sorted(str(item) for item in TRANSITIONS[current])) or 'nothing'}."
        )

    await session.execute(
        text("UPDATE documents SET status = :status WHERE id = :id"),
        {"status": str(status), "id": document_id},
    )
    log.info("document_status", document_id=str(document_id), was=str(current), now=str(status))
    return status


def rolled_up(counts: dict[str, int]) -> DocumentStatus | None:
    """A source's status, from its live documents. None when it has none.

    Attention wins, because one file that failed is the thing the user has to
    act on and averaging it away is how it never gets seen. Otherwise the source
    is as far along as its least finished document — with one exception: a
    source that is part queued and part ready is *in progress*, not queued, and
    `docs/ux/add-source.md` §5 has a state for exactly that.
    """
    if not sum(counts.values()):
        return None
    if counts.get(DocumentStatus.ATTENTION, 0):
        return DocumentStatus.ATTENTION
    if counts.get(DocumentStatus.INDEXING, 0):
        return DocumentStatus.INDEXING
    if counts.get(DocumentStatus.QUEUED, 0):
        if counts.get(DocumentStatus.READY, 0):
            return DocumentStatus.INDEXING
        return DocumentStatus.QUEUED
    return DocumentStatus.READY


async def refresh(session: AsyncSession, source_id: uuid.UUID) -> DocumentStatus | None:
    """Recompute a source's status from what its documents are actually doing.

    Derived rather than maintained. A source status written alongside each
    document change drifts the first time one of those writes is missed, and
    what it drifts into is a folder that says it is still indexing months after
    it finished — which the user cannot correct and has no reason to distrust.
    """
    result = await session.execute(
        text(
            "SELECT status, count(*) AS total FROM documents "
            "WHERE source_id = :id AND deleted_at IS NULL AND superseded_by IS NULL "
            "GROUP BY status"
        ),
        {"id": source_id},
    )
    counts = {row.status: int(row.total) for row in result}
    status = rolled_up(counts)
    if status is None:
        return None

    # Two statements rather than one with a CASE over the bound value. The
    # condition is known here, in Python, and writing it into the SQL instead
    # means Postgres inferring the type of a parameter compared against a bare
    # literal — which it cannot always do, and fails at run time rather than in
    # review.
    stamped = ", last_indexed_at = now()" if status is DocumentStatus.READY else ""
    await session.execute(
        text(
            f"UPDATE sources SET status = :status{stamped} "
            "WHERE id = :id AND status <> 'deleted'"
        ),
        {"status": str(status), "id": source_id},
    )
    return status


# --- the surface ------------------------------------------------------------


class FileRequest(BaseModel):
    """One file, as the caller found it.

    `mime` is what the *caller* detected from the file's first bytes — the
    add-source screen already does this, by content and not by extension
    (`web/lib/add-source.ts`). It is stored as given and is never guessed from
    the name here: a second detector in Python would be a second answer to the
    same question, and `M1-ADD-VAL-024` owns that question.
    """

    path: str = Field(min_length=1, max_length=4096)
    mime: str | None = Field(default=None, max_length=255)


class AddRequest(BaseModel):
    root_path: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=512)
    files: list[FileRequest] = Field(min_length=1)


def register_sources(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """Attach the sources surface. Register before the interface catch-all."""

    @app.post("/sources")
    async def add_source(body: AddRequest) -> JSONResponse:
        """Add files, and say what happened to each of them.

        Always one reply for the whole batch, never per file, and a duplicate
        or a refusal in it does not fail the request: one bad file must not
        reject the drop it arrived in.
        """
        candidates = [Candidate(path=item.path, mime=item.mime) for item in body.files]
        try:
            async with session_scope(factory) as db:
                result = await add(db, body.root_path, candidates, body.name)
        except (SourceRefused, roots.RootRefused) as refusal:
            # 400 rather than 422. The request is exactly the shape the
            # interface meant to send; what is wrong is the folder, and the
            # message is the whole answer.
            return JSONResponse(
                {"error": str(refusal), "root_path": body.root_path}, status_code=400
            )
        return JSONResponse(result.as_dict(), status_code=201 if result.source_id else 200)
