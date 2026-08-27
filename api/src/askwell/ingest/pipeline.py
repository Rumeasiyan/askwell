"""What happens to one document, in order, and what it is allowed to claim.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-025`.

A pipeline is an ordered list of stages. Each stage is given one document, a
database session and a way to say how far it has got; it either finishes, or
raises `StageFailed` with a sentence the user will read.

Three ideas carry this module, and the third is the one that keeps the product
honest while it is half-built.

**Progress is per byte, not per file.** A folder of two hundred contracts and a
single 4 GB scan are both ordinary, and a bar that only moves when a file
finishes looks identical to a hang for as long as the scan takes. So the read
reports as it goes, and the interface has something to move even when the queue
has one item in it.

**A stage that cannot open the file says so in a sentence, not a traceback.**
Every failure here has a fix attached — the file moved, the folder was
un-nominated, something is still writing to it — and the difference between
those is the difference between the user knowing what to do and filing a bug.

**A pipeline cannot claim more than its stages can do.** `produces_index` is
declared per stage, and a document only becomes `ready` if some stage in the
pipeline that ran actually makes it retrievable. Today no stage does: extraction
is `M1-EXTRACT-ING-026`, chunking is `M1-INDEX-ING-031`, and neither exists. So
this pipeline reads and verifies every file and then leaves it **queued**, which
is exactly true — recorded, checked, waiting for a capability that has not
shipped. Marking those documents `ready` would be a lie the size of the product:
the library would report a corpus that answers nothing, and C5's abstention
would look like a bug rather than the truth.

`SIGNATURE` is what makes that state self-correcting. It names the stages that
ran, it is stored on the document, and a document is re-queued whenever its
recorded signature differs from the current one. Add the extraction stage and
every waiting document becomes work again on the next sweep — no migration, no
repair script, and no possibility of a corpus silently missing the stage that
arrived after it was added.
"""

import asyncio
import hashlib
import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from askwell import roots
from askwell.logging import get_logger

log = get_logger(__name__)

# How much is read at a time. Larger than the add-time hash chunk deliberately:
# nothing is waiting on this read, and a 4 GB scan at one megabyte a time is
# four thousand thread hops for no benefit.
READ_CHUNK = 4 * 1024 * 1024


class Outcome(StrEnum):
    """How a document came out of the pipeline. Three answers, no silence."""

    INDEXED = "indexed"
    """Every stage ran and one of them made the document retrievable."""

    WAITING = "waiting"
    """Every stage that exists ran. Nothing here can make it searchable yet."""

    FAILED = "failed"
    """A stage refused, with a reason the user can act on."""


class StageFailed(Exception):
    """This document cannot go further, and here is what to tell the user.

    The message is shown verbatim. It is not a log line with a user-facing
    paraphrase somewhere else — a second copy of a sentence is a second copy to
    keep true.
    """


@dataclass(frozen=True, slots=True)
class DocumentJob:
    """The document a stage is working on, read once before it starts."""

    id: uuid.UUID
    source_id: uuid.UUID
    path: str
    filename: str
    mime: str | None
    sha256: str
    size_bytes: int | None


# How a stage says how far it has got. Bytes, because that is the only unit in
# which a 4 GB file and a two-page letter can be compared, and because it is the
# only one that moves *within* a file.
Report = Callable[[str, int, int | None], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class StageContext:
    """Everything a stage is given."""

    document: DocumentJob
    session: AsyncSession
    report: Report


class StageRun(Protocol):
    async def __call__(self, ctx: StageContext) -> None: ...


@dataclass(frozen=True, slots=True)
class Stage:
    """One step, and whether finishing it means anything is searchable."""

    name: str
    run: StageRun

    produces_index: bool = False
    """Whether this stage is what makes the document retrievable.

    Declared rather than inferred, because the alternative is a pipeline that
    reports `ready` for whatever set of stages happens to be registered. The
    day someone adds a stage that renames files, `ready` must not start meaning
    "renamed".
    """


# --- reasons ----------------------------------------------------------------
# Each one names the fix. A failure the user cannot act on is a failure they
# will read as Askwell being broken.

MISSING = (
    "Askwell could not find this file when it came to read it. It has been "
    "moved, renamed or deleted since it was added. Nothing on disk was changed "
    "— add it again from wherever it is now."
)

UNREADABLE = (
    "Askwell is not allowed to read this file. Check its permissions — and on a "
    "machine with SELinux, that the folder's bind mount is labelled so a "
    "container may traverse it."
)

CHANGED = (
    "This file is not the one Askwell recorded — its contents have changed "
    "since it was added. Nothing was indexed from it, because indexing a file "
    "under the record of a different one is how a citation ends up pointing at "
    "text that is not there. Add it again to index the current version."
)


def uncovered(path: str) -> str:
    return (
        f"No folder you have nominated covers {path} any more, so Askwell will "
        f"not open it. Nothing has been deleted — nominate that folder again in "
        f"Settings and retry this file."
    )


def unreachable(folder: str) -> str:
    return (
        f"Askwell cannot reach {folder}. A drive or a network share that was "
        f"connected when this file was added is not connected now. Nothing has "
        f"been deleted and nothing needs re-indexing — reconnect it and retry."
    )


# --- the read stage ---------------------------------------------------------


def _stat(path: str) -> os.stat_result:
    return os.stat(path)


async def read(ctx: StageContext) -> None:
    """Open the file, prove it is the one that was recorded, report as it goes.

    This is real work rather than a placeholder for extraction, and it is the
    work every later stage depends on being true. Askwell indexes in place: a
    document row is a claim about a file on somebody's disk, made at add time,
    and by the time the queue reaches it — which on a large import is hours
    later — the file may have moved, the drive may have been unplugged, the
    folder may have been un-nominated, or the file may have been edited. Each of
    those is a different sentence with a different fix, and finding out here is
    the difference between a clear message and an extractor failing on bytes it
    should never have been handed.

    The permission check is re-run rather than trusted from add time for the
    same reason. `roots` is a permission, and a permission that is checked once
    and then held for the duration of a queue is not a permission.
    """
    document = ctx.document

    nominated = [item.path for item in await roots.active(ctx.session)]
    real = await asyncio.to_thread(os.path.realpath, document.path)
    if roots.first_covering(nominated, document.path, real) is None:
        raise StageFailed(uncovered(document.path))

    try:
        stat = await asyncio.to_thread(_stat, document.path)
    except FileNotFoundError:
        # A whole folder being absent is not this file having been deleted, and
        # saying "deleted" about an unplugged drive is the error
        # `docs/ux/add-source.md` §7 names explicitly.
        folder = os.path.dirname(document.path)
        if not await asyncio.to_thread(os.path.isdir, folder):
            raise StageFailed(unreachable(folder)) from None
        raise StageFailed(MISSING) from None
    except PermissionError:
        raise StageFailed(UNREADABLE) from None
    except OSError as error:
        raise StageFailed(f"Askwell could not read this file: {error.strerror}.") from None

    total = stat.st_size
    digest = hashlib.sha256()
    done = 0

    try:
        handle = await asyncio.to_thread(open, document.path, "rb")
    except PermissionError:
        raise StageFailed(UNREADABLE) from None
    except OSError as error:
        raise StageFailed(f"Askwell could not read this file: {error.strerror}.") from None

    try:
        while True:
            try:
                block = await asyncio.to_thread(handle.read, READ_CHUNK)
            except OSError as error:
                raise StageFailed(
                    f"Askwell stopped being able to read this file part way "
                    f"through: {error.strerror}."
                ) from None
            if not block:
                break
            digest.update(block)
            done += len(block)
            await ctx.report("read", done, total)
    finally:
        await asyncio.to_thread(handle.close)

    if digest.hexdigest() != document.sha256:
        raise StageFailed(CHANGED)

    await ctx.report("read", done, total)


READ = Stage(name="read", run=read, produces_index=False)

# The pipeline, in order. Extraction (`M1-EXTRACT-ING-026`), OCR
# (`M1-EXTRACT-ING-028`), chunking (`M1-INDEX-ING-031`) and embedding
# (`M1-INDEX-ING-032`) each add a stage here, and each of the last two sets
# `produces_index`. Until one does, no document can become `ready` — see the
# module docstring.
STAGES: tuple[Stage, ...] = (READ,)


def signature(stages: Sequence[Stage] = STAGES) -> str:
    """Which pipeline processed a document, as one storable string.

    Names joined, in order. Adding, removing or reordering a stage changes it,
    which is what makes both the estimate and the backlog sweep correct across a
    product that is still growing stages: measurements from a different pipeline
    are excluded, and documents processed by a different pipeline are re-queued.

    A stage whose *behaviour* changes materially without changing its name is
    the one case this cannot see. Rename it — `extract` to `extract2` — rather
    than leaving the old measurements in the average.
    """
    return "|".join(stage.name for stage in stages)


SIGNATURE = signature()


async def run(
    ctx_document: DocumentJob,
    session: AsyncSession,
    report: Report,
    stages: Sequence[Stage] = STAGES,
) -> Outcome:
    """Run every stage over one document and say what came of it.

    Returns `WAITING` rather than `INDEXED` when no stage that ran was able to
    make the document retrievable. That is not a failure and must never be
    rendered as one: the file has been read and verified, and what is missing is
    a capability Askwell has not shipped yet.
    """
    for stage in stages:
        await stage.run(StageContext(document=ctx_document, session=session, report=report))

    return Outcome.INDEXED if any(stage.produces_index for stage in stages) else Outcome.WAITING


WAITING_NOTE = (
    "Askwell has read this file and checked it is the one you added. Reading "
    "the text out of it is the next piece of work and has not shipped yet."
)
