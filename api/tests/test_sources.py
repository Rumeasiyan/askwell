"""Hashing a file, and deciding whether Askwell may open it at all.

Everything here runs without a database and without a network. What it covers
is the part of `M1-ADD-BE-023` that is about the filesystem rather than about
rows: the hash is over content and nothing else, a file that moves under the
read is caught, and a path that climbs out of the folder the user named is
refused before anything opens it.
"""

import hashlib
import os
import threading
from pathlib import Path

import pytest

from askwell.sources import (
    FileUnsettled,
    _outside_reason,
    _resolve,
    _uncovered_reason,
    fingerprint,
)

BODY = b"Either party may terminate on ninety days written notice.\n"


def written(directory: Path, name: str, body: bytes = BODY) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_the_hash_is_over_the_content_and_nothing_else(tmp_path: Path) -> None:
    """The whole duplicate rule rests on this.

    Two names, two folders, two modification times, one hash. Hashing anything
    else — the name, the size, the mtime — would make `contract.pdf` and
    `contract copy.pdf` two different documents, which is the exact failure the
    ticket exists to prevent.
    """
    first = written(tmp_path / "clients", "contract.pdf")
    second = written(tmp_path / "archive", "contract copy.pdf")
    os.utime(second, (1_600_000_000, 1_600_000_000))

    assert fingerprint(str(first)).sha256 == fingerprint(str(second)).sha256
    assert fingerprint(str(first)).sha256 == hashlib.sha256(BODY).hexdigest()


def test_one_pass_yields_the_head_the_size_and_the_hash(tmp_path: Path) -> None:
    """Opening the file twice is two chances for it to change between them.

    The head decides the file's *type* and the hash decides its *identity*, so
    reading them separately could type one version of a file and record another.
    """
    body = b"%PDF-1.7\n" + b"x" * 9000
    path = written(tmp_path, "big.pdf", body)

    stamp = fingerprint(str(path))
    assert stamp.size == len(body)
    assert stamp.head.startswith(b"%PDF-")
    assert len(stamp.head) == 4096
    assert stamp.sha256 == hashlib.sha256(body).hexdigest()


def test_an_empty_file_hashes_rather_than_failing(tmp_path: Path) -> None:
    """Refusing it is `detect`'s job, on the size. This must not raise first."""
    path = written(tmp_path, "empty.pdf", b"")
    stamp = fingerprint(str(path))
    assert stamp.size == 0
    assert stamp.head == b""


def test_a_file_that_changes_under_the_read_is_re_read(tmp_path: Path) -> None:
    """The ticket's edge case: detected and re-hashed, not recorded inconsistently.

    The file is rewritten once, from another thread, while the first pass is in
    flight. The second pass sees a settled file and its hash is the one stored —
    a hash of bytes that no longer exist would name a document nobody can open.
    """
    path = written(tmp_path, "growing.txt", b"first\n")
    started = threading.Event()
    rewritten = threading.Event()

    real_open = open
    passes = 0

    def counting_open(*args: object, **kwargs: object) -> object:
        nonlocal passes
        passes += 1
        if passes == 1:
            started.set()
            rewritten.wait(timeout=5)
        return real_open(*args, **kwargs)  # type: ignore[arg-type, call-overload]

    def rewrite() -> None:
        started.wait(timeout=5)
        path.write_bytes(b"second, and longer\n")
        os.utime(path, (1_600_000_000, 1_600_000_000))
        rewritten.set()

    writer = threading.Thread(target=rewrite)
    writer.start()
    try:
        import askwell.sources as module

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(module, "open", counting_open, raising=False)
            stamp = fingerprint(str(path))
    finally:
        writer.join()

    assert stamp.sha256 == hashlib.sha256(b"second, and longer\n").hexdigest()
    assert passes >= 2, "the first pass saw a file that had changed and must have re-read it"


def test_a_file_that_never_settles_is_refused_rather_than_hashed_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file something else is appending to continuously never settles.

    Hashing it until it does is how a drop of sixty contracts never finishes,
    so the attempts are bounded and the file is reported rather than stored.
    """
    path = written(tmp_path, "log.txt", b"one\n")
    counter = {"n": 0}

    def moving(_path: str) -> tuple[int, int, int, int]:
        counter["n"] += 1
        return (1, 1, counter["n"], counter["n"])

    monkeypatch.setattr("askwell.sources._identity", moving)

    with pytest.raises(FileUnsettled):
        fingerprint(str(path), attempts=2)


def test_a_missing_file_raises_rather_than_hashing_nothing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fingerprint(str(tmp_path / "gone.pdf"))


# --- what may be opened -----------------------------------------------------


def test_a_relative_path_cannot_climb_out_of_the_folder_it_was_given(tmp_path: Path) -> None:
    """A string a client can send, whatever today's client happens to send.

    The browser builds these paths from a folder the user typed and names it
    reports, so `../../etc/shadow` is not what the interface would produce — and
    that is a property of the interface, not of this endpoint.
    """
    folder = str(tmp_path / "clients")
    path, filename, refusal = _resolve(folder, "../../etc/shadow", [folder])
    assert refusal == _outside_reason(folder)
    assert filename == "shadow"
    assert not path.startswith(folder)


def test_a_path_no_nominated_root_covers_is_refused_with_what_to_do(tmp_path: Path) -> None:
    folder = str(tmp_path / "clients")
    (tmp_path / "clients").mkdir()
    path, _filename, refusal = _resolve(folder, "contract.pdf", [])
    assert refusal == _uncovered_reason(path)
    assert "nominate" in (refusal or "").lower()


def test_a_covered_path_resolves_to_the_file_and_its_name(tmp_path: Path) -> None:
    folder = str(tmp_path / "clients")
    written(tmp_path / "clients" / "2026", "contract.pdf")
    path, filename, refusal = _resolve(folder, "2026/contract.pdf", [str(tmp_path)])
    assert refusal is None
    assert filename == "contract.pdf"
    assert path == str(tmp_path / "clients" / "2026" / "contract.pdf")


def test_a_symlink_inside_the_folder_cannot_reach_outside_it(tmp_path: Path) -> None:
    """The same rule `askwell.roots` enforces, applied where files are opened.

    Covering the link but not its target would let one symlink inside a
    nominated folder stand in for the whole disk, which is precisely the
    permission the user declined to give.
    """
    nominated = tmp_path / "clients"
    nominated.mkdir()
    outside = written(tmp_path / "private", "diary.txt")
    (nominated / "escape.txt").symlink_to(outside)

    _path, _filename, refusal = _resolve(str(nominated), "escape.txt", [str(nominated)])
    assert refusal is not None, "a symlink out of a nominated folder must not be readable"
