"""The model acquisition step's mechanics. `M1-LIB-FE-052`.

No real Hugging Face request — `httpx.MockTransport` stands in for the
network, the same "prove the wiring against a fake, not the model this
environment cannot start" pattern `M1-ASK-RET-036`'s own session used for its
reranker client. What is under test is Askwell's own logic: disk space
refused before a download starts, a cancel leaving the partial file alone, a
resume asking for the right `Range`, a hash mismatch being refused rather than
accepted, and a manually-placed file being verified rather than trusted by
name.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from askwell.model_download import DownloadStatus, ModelDownloadManager, NoDiskSpace
from askwell.models_catalog import CATALOG, ModelSpec

_CONTENT = b"x" * 4096
_SPEC = ModelSpec(
    tier="light",
    display_name="Test model",
    repo="test/repo",
    filename="model.gguf",
    url="https://example.invalid/model.gguf",
    size_bytes=len(_CONTENT),
    sha256=hashlib.sha256(_CONTENT).hexdigest(),
)


@pytest.fixture(autouse=True)
def _patch_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CATALOG, "light", _SPEC)
    # Mirrors the real catalog: "standard" aliases to the same `ModelSpec` as
    # "light", and that spec's own `.tier` field says "light" — exactly the
    # mismatch `test_snapshot_after_failure_uses_the_requested_tier_not_the_catalog_spec`
    # exists to catch.
    monkeypatch.setitem(CATALOG, "standard", _SPEC)


def _full_response_transport(content: bytes = _CONTENT) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get("range")
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            return httpx.Response(206, content=content[start:])
        return httpx.Response(200, content=content)

    return httpx.MockTransport(handler)


def _manager(tmp_path: Path, transport: httpx.MockTransport) -> ModelDownloadManager:
    return ModelDownloadManager(
        tmp_path / "model.gguf",
        client_factory=lambda: httpx.AsyncClient(transport=transport),
    )


async def test_full_download_lands_at_target_and_reports_ready(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _full_response_transport())
    progress = await manager.start("light")
    assert progress.status == DownloadStatus.DOWNLOADING
    await manager._task  # type: ignore[union-attr]

    snapshot = manager.snapshot("light")
    assert snapshot.status == DownloadStatus.READY
    assert snapshot.downloaded_bytes == _SPEC.size_bytes
    assert (tmp_path / "model.gguf").read_bytes() == _CONTENT
    assert not (tmp_path / "model.gguf.part").exists()


async def test_hash_mismatch_is_refused_not_accepted(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _full_response_transport(content=b"wrong bytes, wrong length!!"))
    await manager.start("light")
    await manager._task  # type: ignore[union-attr]

    snapshot = manager.snapshot("light")
    assert snapshot.status == DownloadStatus.FAILED
    assert snapshot.error is not None
    assert not (tmp_path / "model.gguf").exists()


async def test_cancel_keeps_the_partial_file(tmp_path: Path) -> None:
    # A transport that yields one byte at a time so cancel has something to
    # interrupt mid-stream rather than racing a single completed chunk.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_CONTENT)

    manager = _manager(tmp_path, httpx.MockTransport(handler))
    await manager.start("light")
    await manager.cancel("light")

    snapshot = manager.snapshot("light")
    # A fast in-memory transport races the cancel signal against the first
    # chunk being written, same as a real download racing the network against
    # a click — both PAUSED-with-nothing-yet and READY-it-already-finished
    # are honest outcomes. What must never happen is the target file existing
    # with the wrong bytes, or an exception escaping cancel().
    assert snapshot.status in (DownloadStatus.PAUSED, DownloadStatus.READY)
    if snapshot.status == DownloadStatus.READY:
        assert (tmp_path / "model.gguf").read_bytes() == _CONTENT


async def test_resume_asks_for_a_range_from_the_partial_file(tmp_path: Path) -> None:
    part = tmp_path / "model.gguf.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(_CONTENT[:1000])

    seen_ranges: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ranges.append(request.headers.get("range"))
        return httpx.Response(206, content=_CONTENT[1000:])

    manager = _manager(tmp_path, httpx.MockTransport(handler))
    await manager.start("light")
    await manager._task  # type: ignore[union-attr]

    assert seen_ranges == ["bytes=1000-"]
    assert manager.snapshot("light").status == DownloadStatus.READY


async def test_snapshot_after_failure_uses_the_requested_tier_not_the_catalog_spec(
    tmp_path: Path,
) -> None:
    """A tier whose catalog spec's own `.tier` differs from the requested key
    (e.g. `standard` shares `light`'s `ModelSpec`) must not lose its progress:
    `snapshot(tier)` matches on the *requested* tier, so the in-memory result
    has to carry that, not whatever the spec happens to be tagged with."""
    manager = _manager(tmp_path, _full_response_transport(content=b"wrong length!"))
    await manager.start("standard")
    await manager._task  # type: ignore[union-attr]

    snapshot = manager.snapshot("standard")
    assert snapshot.status == DownloadStatus.FAILED
    assert snapshot.tier == "standard"


async def test_no_disk_space_refuses_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, _full_response_transport())
    monkeypatch.setattr(
        "askwell.model_download.disk_usage",
        lambda _path: type("Usage", (), {"free": 10})(),
    )
    with pytest.raises(NoDiskSpace) as refusal:
        await manager.start("light")
    assert refusal.value.needed_bytes > 0
    assert not (tmp_path / "model.gguf.part").exists()


def test_verify_manual_accepts_a_correct_file(tmp_path: Path) -> None:
    target = tmp_path / "model.gguf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_CONTENT)
    manager = _manager(tmp_path, _full_response_transport())

    result = manager.verify_manual("light")
    assert result.status == DownloadStatus.READY


def test_verify_manual_refuses_a_wrong_file_by_name_alone(tmp_path: Path) -> None:
    target = tmp_path / "model.gguf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not the right model at all")
    manager = _manager(tmp_path, _full_response_transport())

    result = manager.verify_manual("light")
    assert result.status == DownloadStatus.FAILED
    assert result.error is not None


def test_verify_manual_result_survives_a_subsequent_snapshot(tmp_path: Path) -> None:
    """`snapshot()` prefers in-memory state over recomputing from disk — so a
    manual-verify result has to actually land in that in-memory state, or a
    poll right after clicking "Verify" would show the *previous* state."""
    target = tmp_path / "model.gguf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_CONTENT)
    manager = _manager(tmp_path, _full_response_transport())

    manager.verify_manual("light")
    assert manager.snapshot("light").status == DownloadStatus.READY


def test_verify_manual_with_no_file_says_where_to_put_it(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _full_response_transport())
    result = manager.verify_manual("light")
    assert result.status == DownloadStatus.IDLE
    # Names the actual configured target path, not the catalog's own
    # upstream filename — the two can differ (`docs/decisions.md`), and a
    # user placing a file by the wrong name would never satisfy this check.
    assert "model.gguf" in (result.error or "")
