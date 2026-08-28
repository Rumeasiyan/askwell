"""Fetching a model, which happens on the host. `M1-LIB-FE-052`, issue 192.

The download cannot run in a container: the application network is declared
internal and the egress proxy never forwards, so asking Hugging Face from
inside the API earns a 403 from Askwell's own proxy — C1 working, not a bug.
It runs beside `llama.cpp` on the host for the same reason inference does.

That puts the interesting logic — resume, checksum, cancel — in a standalone
stdlib script rather than in the package, so it is loaded here by path and
exercised directly. `urlopen` is stubbed; nothing reaches the network, which is
the whole point of the arrangement being tested.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SUPERVISOR = Path(__file__).resolve().parents[2] / "deploy" / "inference" / "askwell-inference"

_CONTENT = b"y" * 4096
_SHA = hashlib.sha256(_CONTENT).hexdigest()


def _load() -> ModuleType:
    """The supervisor as a module, despite having no .py extension."""
    spec = importlib.util.spec_from_loader(
        "askwell_inference_host",
        importlib.machinery.SourceFileLoader("askwell_inference_host", str(SUPERVISOR)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_inference_host"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host() -> ModuleType:
    return _load()


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status
        self._at = 0

    def read(self, size: int) -> bytes:
        chunk = self._body[self._at : self._at + size]
        self._at += len(chunk)
        return chunk

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _request(**over: Any) -> dict[str, Any]:
    return {
        "url": "https://example.invalid/model.gguf",
        "filename": "model.gguf",
        "sha256": _SHA,
        "size_bytes": len(_CONTENT),
        **over,
    }


def _progress(models: Path) -> dict[str, Any]:
    return dict(json.loads((models / "fetch-progress.json").read_text(encoding="utf-8")))


def test_a_verified_download_lands_and_reports_ready(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT))
    host._fetch_once(tmp_path, _request())

    assert (tmp_path / "model.gguf").read_bytes() == _CONTENT
    assert not (tmp_path / "model.gguf.part").exists()
    assert _progress(tmp_path)["status"] == "ready"


def test_a_file_that_fails_its_checksum_is_discarded(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept, it would fail later as bad answers rather than as a bad download —
    which is the expensive way to find out."""
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(b"z" * 4096))
    host._fetch_once(tmp_path, _request())

    assert not (tmp_path / "model.gguf").exists()
    assert not (tmp_path / "model.gguf.part").exists()
    reported = _progress(tmp_path)
    assert reported["status"] == "failed"
    assert "checksum" in reported["error"]


def test_a_partial_file_resumes_rather_than_starting_again(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "model.gguf.part").write_bytes(_CONTENT[:1000])
    seen: list[dict[str, str]] = []

    def urlopen(request: Any, **_k: Any) -> _Response:
        seen.append(dict(request.headers))
        return _Response(_CONTENT[1000:], status=206)

    monkeypatch.setattr(host.urllib.request, "urlopen", urlopen)
    host._fetch_once(tmp_path, _request())

    # Header names arrive capitalised through urllib's own normalisation.
    assert any("bytes=1000-" in value for header in seen for value in header.values())
    assert (tmp_path / "model.gguf").read_bytes() == _CONTENT


def test_a_server_ignoring_the_range_restarts_cleanly(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 to a Range request means the whole file is coming. Appending it to
    what is already there would produce a file of the right name, the wrong
    length and the wrong bytes."""
    (tmp_path / "model.gguf.part").write_bytes(_CONTENT[:1000])
    monkeypatch.setattr(
        host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT, status=200)
    )
    host._fetch_once(tmp_path, _request())

    assert (tmp_path / "model.gguf").read_bytes() == _CONTENT


def test_a_cancel_stops_it_and_keeps_what_arrived(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fetch-cancel").write_text("", encoding="utf-8")
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT))
    host._fetch_once(tmp_path, _request())

    assert _progress(tmp_path)["status"] == "paused"
    assert not (tmp_path / "model.gguf").exists()
    assert not (tmp_path / "fetch-cancel").exists(), "the flag is consumed, not left to fire again"


def test_a_download_that_dies_reports_it_rather_than_raising(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never raise: this runs inside the supervisor, and taking that down would
    stop inference because a download failed."""

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("the network went away")

    monkeypatch.setattr(host.urllib.request, "urlopen", boom)
    host._fetch_once(tmp_path, _request())

    reported = _progress(tmp_path)
    assert reported["status"] == "failed"
    assert "Nothing already downloaded was lost" in reported["error"]


def test_a_model_already_on_disk_is_not_fetched_again(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "model.gguf").write_bytes(_CONTENT)

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("it should not have asked for a file it already has")

    monkeypatch.setattr(host.urllib.request, "urlopen", refuse)
    host._fetch_once(tmp_path, _request())
    assert _progress(tmp_path)["status"] == "ready"
