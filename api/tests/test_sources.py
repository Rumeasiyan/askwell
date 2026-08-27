"""Hashing, recognition wording and the stage machine, without a database.

What can be asserted here is everything that decides *whether* a file is a
duplicate and *what the user is told about it* — which is the whole ticket
apart from the rows. The rows need Postgres, and they are in
`test_sources_registry.py`.
"""

import hashlib
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from askwell import sources
from askwell.sources import (
    Candidate,
    DocumentStatus,
    Existing,
    FileOutcome,
    FileRefused,
    Outcome,
)

# --- the hash is over content, and only content -----------------------------


def test_the_hash_is_the_sha256_of_the_bytes(tmp_path: Path) -> None:
    document = tmp_path / "contract.pdf"
    document.write_bytes(b"%PDF-1.7 terms and conditions")

    sha256, fingerprint = sources.digest(str(document))

    assert sha256 == hashlib.sha256(b"%PDF-1.7 terms and conditions").hexdigest()
    assert fingerprint.size == 29


def test_the_same_content_under_two_names_hashes_the_same(tmp_path: Path) -> None:
    """The ticket's own example: `contract.pdf` and `contract copy.pdf`.

    Hashing anything but the bytes — the name, the size, the modification time —
    would make these two documents, which is the failure this whole feature
    exists to prevent.
    """
    original = tmp_path / "contract.pdf"
    copy = tmp_path / "contract copy.pdf"
    original.write_bytes(b"identical")
    copy.write_bytes(b"identical")
    os.utime(copy, (0, 0))

    assert sources.digest(str(original))[0] == sources.digest(str(copy))[0]


def test_two_files_with_the_same_name_and_different_content_are_different(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a" / "report.pdf"
    second = tmp_path / "b" / "report.pdf"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    assert sources.digest(str(first))[0] != sources.digest(str(second))[0]


def test_a_file_larger_than_one_read_is_hashed_whole(tmp_path: Path) -> None:
    """Chunked reading must not stop at the first chunk."""
    content = bytes(range(256)) * (sources.READ_CHUNK // 128)
    document = tmp_path / "scan.pdf"
    document.write_bytes(content)

    assert sources.digest(str(document))[0] == hashlib.sha256(content).hexdigest()


# --- the refusals -----------------------------------------------------------


def test_a_zero_byte_file_is_rejected_with_the_reason(tmp_path: Path) -> None:
    """Rejected, not indexed as an empty document.

    Every empty file has the same hash, so accepting them would report the
    second one as a duplicate of the first — true of the bytes, and a confusing
    thing to say about two unrelated documents.
    """
    document = tmp_path / "empty.pdf"
    document.touch()

    with pytest.raises(FileRefused) as refusal:
        sources.digest(str(document))

    assert "0 bytes" in str(refusal.value)
    assert str(document) in str(refusal.value)


def test_a_missing_file_says_so_rather_than_raising_oserror(tmp_path: Path) -> None:
    with pytest.raises(FileRefused) as refusal:
        sources.digest(str(tmp_path / "gone.pdf"))
    assert "not there" in str(refusal.value)


def test_a_folder_is_not_a_document(tmp_path: Path) -> None:
    with pytest.raises(FileRefused) as refusal:
        sources.digest(str(tmp_path))
    assert "not a file" in str(refusal.value)


def test_a_named_pipe_is_refused_without_opening_it(tmp_path: Path) -> None:
    """Opening a fifo blocks until somebody writes to it.

    Which would hang the thread doing the hashing rather than producing a
    refusal, so the check has to happen before the open — and this test is the
    only thing that notices if it is ever moved after it.
    """
    pipe = tmp_path / "pipe"
    os.mkfifo(pipe)

    done = threading.Event()
    refused: list[str] = []

    def attempt() -> None:
        try:
            sources.digest(str(pipe))
        except FileRefused as error:
            refused.append(str(error))
        finally:
            done.set()

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    assert done.wait(timeout=5), "hashing a fifo blocked — the S_ISREG check must precede the open"
    assert refused and "not a file" in refused[0]


# --- a file that changes while it is being read -----------------------------


class RewritingHandle:
    """A handle that lets something else rewrite the file mid-read.

    Which is the situation being reproduced: a download or a sync client
    writing the file *between* the descriptor being opened and the last byte
    being read. The rewrite has to land after the opening fingerprint is taken
    or there is nothing for the check to catch, so it happens on the first
    `read` rather than at open.
    """

    def __init__(self, handle: Any, document: Path, content: bytes, writes: list[int]) -> None:
        self._handle = handle
        self._document = document
        self._content = content
        self._writes = writes
        self._written = False

    def read(self, size: int = -1) -> bytes:
        if not self._written:
            self._written = True
            self._writes.append(1)
            self._document.write_bytes(self._content)
        return bytes(self._handle.read(size))

    def fileno(self) -> int:
        return int(self._handle.fileno())

    def __enter__(self) -> "RewritingHandle":
        self._handle.__enter__()
        return self

    def __exit__(self, *details: object) -> None:
        self._handle.__exit__(*details)


def rewriting_open(document: Path, rewrites: list[bytes], writes: list[int]) -> Any:
    """`open`, for the first `len(rewrites)` attempts.

    Patched into the module rather than into `builtins`, so nothing outside
    `askwell.sources` sees a modified `open` — Python looks a module global up
    before it looks at builtins, which is what makes that possible.
    """
    real = open

    def opening(*args: Any, **kwargs: Any) -> Any:
        handle = real(*args, **kwargs)
        if len(writes) >= len(rewrites):
            return handle
        return RewritingHandle(handle, document, rewrites[len(writes)], writes)

    return opening


def test_a_file_that_changes_while_being_read_is_rehashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-hashed, not accepted.

    A hash computed over two different versions of a file identifies neither.
    Filing the document under it would make every later duplicate check wrong
    about this document, silently, for as long as the row survives.
    """
    document = tmp_path / "downloading.pdf"
    document.write_bytes(b"first version")
    settled = b"second version, a different length"

    writes: list[int] = []
    monkeypatch.setattr(sources, "open", rewriting_open(document, [settled], writes), raising=False)

    sha256, fingerprint = sources.digest(str(document))

    assert writes == [1], "the file was not rewritten under the first read"
    assert sha256 == hashlib.sha256(settled).hexdigest()
    assert fingerprint.size == len(settled)


def test_a_file_that_never_settles_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "syncing.pdf"
    document.write_bytes(b"start")

    writes: list[int] = []
    forever = [b"x" * (10 + step) for step in range(sources.HASH_ATTEMPTS)]
    monkeypatch.setattr(sources, "open", rewriting_open(document, forever, writes), raising=False)

    with pytest.raises(FileRefused) as refusal:
        sources.digest(str(document))

    assert len(writes) == sources.HASH_ATTEMPTS
    assert "kept changing" in str(refusal.value)
    assert "not indexed" in str(refusal.value)


# --- what the user is told about a duplicate --------------------------------


def an_existing(path: str, filename: str) -> Existing:
    return Existing(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        source_name="Client files",
        path=path,
        filename=filename,
        added_at=datetime.now(UTC),
    )


def test_a_duplicate_message_shows_both_paths() -> None:
    """The edge case the ticket names: the user must not have to guess.

    Which copy is indexed is the entire question — answers will cite it — and
    "already present" without a path sends someone through their own filing to
    find out what Askwell did.
    """
    existing = an_existing("/home/anna/clients/contract.pdf", "contract.pdf")

    message = sources.duplicate_reason("/home/anna/archive/contract copy.pdf", existing)

    assert "/home/anna/clients/contract.pdf" in message
    assert "/home/anna/archive/contract copy.pdf" in message


def test_the_same_content_under_another_name_is_described_as_such() -> None:
    existing = an_existing("/home/anna/clients/contract.pdf", "contract.pdf")
    message = sources.duplicate_reason("/home/anna/archive/contract copy.pdf", existing)
    assert "the same content under another name" in message


def test_the_same_name_in_another_folder_is_described_as_such() -> None:
    existing = an_existing("/home/anna/clients/contract.pdf", "contract.pdf")
    message = sources.duplicate_reason("/home/anna/archive/contract.pdf", existing)
    assert "the same file in another folder" in message


def test_a_duplicate_message_says_nothing_was_deleted() -> None:
    """Both copies are still on the user's disk, and they need telling.

    The same instinct as removing a root: someone being told a file was skipped
    has every reason to wonder whether it was skipped *because Askwell did
    something to it*.
    """
    existing = an_existing("/home/anna/clients/contract.pdf", "contract.pdf")
    message = sources.duplicate_reason("/home/anna/archive/contract.pdf", existing)
    assert "Nothing was deleted" in message


def test_a_duplicate_is_reported_as_recognised_not_as_an_error() -> None:
    """`docs/ux/add-source.md` §5: linked to the existing document, not rejected."""
    existing = an_existing("/home/anna/clients/contract.pdf", "contract.pdf")
    outcome = FileOutcome(
        path="/home/anna/archive/contract.pdf",
        filename="contract.pdf",
        outcome=Outcome.DUPLICATE,
        reason=sources.duplicate_reason("/home/anna/archive/contract.pdf", existing),
        document_id=existing.id,
        existing=existing,
    )

    rendered = outcome.as_dict()
    assert rendered["outcome"] == "duplicate"
    assert rendered["document_id"] == str(existing.id)
    assert rendered["existing"]["path"] == "/home/anna/clients/contract.pdf"


# --- stages -----------------------------------------------------------------


def test_queued_is_a_stage_of_its_own() -> None:
    """Not a shade of `indexing`.

    `docs/states-and-edge-cases.md` §3 requires "queued, nothing indexed yet" be
    said plainly rather than shown as a progress bar that never moves, and that
    sentence cannot be written from a status that also means "being read now".
    """
    from askwell.db.models import DOCUMENT_STATUSES, SOURCE_STATUSES

    assert "queued" in DOCUMENT_STATUSES
    assert "queued" in SOURCE_STATUSES
    assert DocumentStatus.QUEUED != DocumentStatus.INDEXING


@pytest.mark.parametrize(
    ("current", "wanted"),
    [
        (DocumentStatus.QUEUED, DocumentStatus.INDEXING),
        (DocumentStatus.QUEUED, DocumentStatus.ATTENTION),
        (DocumentStatus.INDEXING, DocumentStatus.READY),
        (DocumentStatus.INDEXING, DocumentStatus.ATTENTION),
        (DocumentStatus.ATTENTION, DocumentStatus.QUEUED),
        (DocumentStatus.READY, DocumentStatus.QUEUED),
    ],
)
def test_the_stages_a_document_really_passes_through(
    current: DocumentStatus, wanted: DocumentStatus
) -> None:
    assert wanted in sources.TRANSITIONS[current]


@pytest.mark.parametrize(
    ("current", "wanted"),
    [
        (DocumentStatus.QUEUED, DocumentStatus.READY),
        (DocumentStatus.READY, DocumentStatus.ATTENTION),
        (DocumentStatus.DELETED, DocumentStatus.READY),
    ],
)
def test_a_stage_that_was_never_reached_is_not_a_transition(
    current: DocumentStatus, wanted: DocumentStatus
) -> None:
    """`queued` to `ready` is the one that matters.

    It is what a bug that skips the work looks like: a document reported as
    searchable that was never read. The status is the only thing telling the
    user whether their question can be answered yet.
    """
    assert wanted not in sources.TRANSITIONS[current]


def test_every_status_has_a_transition_rule() -> None:
    """A missing key reads as "anything goes" at the place the rule is checked."""
    assert set(sources.TRANSITIONS) == set(DocumentStatus)


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({}, None),
        ({"queued": 3}, DocumentStatus.QUEUED),
        ({"queued": 2, "ready": 1}, DocumentStatus.INDEXING),
        ({"indexing": 1, "ready": 4}, DocumentStatus.INDEXING),
        ({"ready": 4}, DocumentStatus.READY),
        ({"ready": 9, "attention": 1}, DocumentStatus.ATTENTION),
        ({"queued": 5, "attention": 1}, DocumentStatus.ATTENTION),
    ],
)
def test_a_source_is_as_far_along_as_its_documents(
    counts: dict[str, int], expected: DocumentStatus | None
) -> None:
    """One failed file wins, because it is the one the user has to act on."""
    assert sources.rolled_up(counts) == expected


# --- naming -----------------------------------------------------------------


def test_a_source_nobody_named_is_called_after_its_folder() -> None:
    assert sources.default_name("/home/anna/clients") == "clients"


def test_a_candidate_carries_the_mime_the_caller_detected() -> None:
    """Stored as given, never guessed from the extension here.

    Detection by content belongs to `M1-ADD-VAL-024`; a second detector in this
    module would be a second answer to the same question, and the two would
    disagree on exactly the files where it matters.
    """
    assert Candidate(path="/x/a.pdf").mime is None
    assert Candidate(path="/x/a.pdf", mime="application/pdf").mime == "application/pdf"
