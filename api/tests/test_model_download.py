"""The model acquisition step's mechanics. `M1-LIB-FE-052`, issue 192.

The download itself does not happen here and cannot: the egress proxy never
forwards and the application network is declared internal, so a container
asking Hugging Face for a model is refused by Askwell's own proxy — C1 working
as designed. The fetch runs on the host, beside `llama.cpp`, for the same
reason. `test_model_fetch_host.py` covers the fetching; what is under test here
is the half that stayed: disk space refused before anything starts, the request
the host is given, the progress the host reports being preferred over this
process's own memory, a cancel that reaches across the boundary, and a manually
placed file being verified rather than trusted by name.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from askwell.model_download import (
    FETCH_PROGRESS,
    FETCH_REQUEST,
    DownloadStatus,
    ModelDownloadManager,
    NoDiskSpace,
)
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


def _manager(tmp_path: Path) -> ModelDownloadManager:
    return ModelDownloadManager(tmp_path / "model.gguf")


def _host_says(tmp_path: Path, **payload: object) -> None:
    """Stand in for the host supervisor having written progress."""
    (tmp_path / FETCH_PROGRESS).write_text(
        json.dumps({"filename": "model.gguf", **payload}), encoding="utf-8"
    )


async def test_starting_asks_the_host_rather_than_opening_a_socket(tmp_path: Path) -> None:
    """The heart of issue 192: this process must not try to reach the network.

    It has no route — the application network is internal and the egress proxy
    never forwards — so an attempt is not merely refused, it is refused by
    Askwell's own proxy and logged as a C1 violation that never should have
    been made. What start() does is leave a request where the host supervisor
    will find it.
    """
    manager = _manager(tmp_path)
    progress = await manager.start("light")
    assert progress.status == DownloadStatus.DOWNLOADING

    request = json.loads((tmp_path / FETCH_REQUEST).read_text(encoding="utf-8"))
    assert request["url"] == _SPEC.url
    assert request["filename"] == "model.gguf"
    # The checksum travels with the request. A fetcher deciding for itself what
    # "correct" means would be no check at all.
    assert request["sha256"] == _SPEC.sha256
    assert request["size_bytes"] == _SPEC.size_bytes


async def test_the_hosts_progress_wins_over_this_process_s_memory(tmp_path: Path) -> None:
    """The host is the one actually downloading.

    Preferring the local value would freeze the progress bar whenever the API
    restarted, over a download that never paused.
    """
    manager = _manager(tmp_path)
    await manager.start("light")
    _host_says(tmp_path, status="downloading", downloaded_bytes=2048, error=None)

    snapshot = manager.snapshot("light")
    assert snapshot.status == DownloadStatus.DOWNLOADING
    assert snapshot.downloaded_bytes == 2048


async def test_a_failure_the_host_reports_reaches_the_screen(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _host_says(
        tmp_path,
        status="failed",
        downloaded_bytes=0,
        error="The downloaded file did not match its published checksum.",
    )
    snapshot = manager.snapshot("light")
    assert snapshot.status == DownloadStatus.FAILED
    assert snapshot.error is not None
    assert "checksum" in snapshot.error


async def test_progress_for_a_different_model_is_ignored(tmp_path: Path) -> None:
    """Two tiers share a directory. A stale file from the other one must not be
    read as this one's progress — the screen would show a bar for a download
    nobody started."""
    manager = _manager(tmp_path)
    (tmp_path / FETCH_PROGRESS).write_text(
        json.dumps(
            {"filename": "someone-else.gguf", "status": "downloading", "downloaded_bytes": 9}
        ),
        encoding="utf-8",
    )
    assert manager.snapshot("light").status == DownloadStatus.IDLE


async def test_unreadable_progress_is_no_progress_rather_than_an_error(tmp_path: Path) -> None:
    # Written by another process, so it can be truncated mid-write or absent.
    manager = _manager(tmp_path)
    (tmp_path / FETCH_PROGRESS).write_text("{ not json", encoding="utf-8")
    assert manager.snapshot("light").status == DownloadStatus.IDLE


async def test_cancel_reaches_across_the_container_boundary(tmp_path: Path) -> None:
    """The fetch is in another process, so the stop has to be something both
    can see. The pending request is withdrawn too, or the host would start the
    download that was just cancelled."""
    manager = _manager(tmp_path)
    await manager.start("light")
    assert (tmp_path / FETCH_REQUEST).exists()

    await manager.cancel("light")
    assert (tmp_path / "fetch-cancel").exists()
    assert not (tmp_path / FETCH_REQUEST).exists()


async def test_no_disk_space_refuses_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
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
    manager = _manager(tmp_path)

    result = manager.verify_manual("light")
    assert result.status == DownloadStatus.READY


def test_verify_manual_refuses_a_wrong_file_by_name_alone(tmp_path: Path) -> None:
    target = tmp_path / "model.gguf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not the right model at all")
    manager = _manager(tmp_path)

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
    manager = _manager(tmp_path)

    manager.verify_manual("light")
    assert manager.snapshot("light").status == DownloadStatus.READY


def test_verify_manual_with_no_file_says_where_to_put_it(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    result = manager.verify_manual("light")
    assert result.status == DownloadStatus.IDLE
    # Names the actual configured target path, not the catalog's own
    # upstream filename — the two can differ (`docs/decisions.md`), and a
    # user placing a file by the wrong name would never satisfy this check.
    assert "model.gguf" in (result.error or "")
