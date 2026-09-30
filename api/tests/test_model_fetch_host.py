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

import asyncio
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


# --- M9-FIX-DEPLOY-211, issue #668: signals in the run directory ------------
#
# The API sees the models directory read-only, so the request, the progress
# and the cancel flag are exchanged through the run directory. The model file
# itself still lands in the models directory.


def test_signals_go_through_the_run_directory_and_the_model_through_models(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    run = tmp_path / "run"
    models.mkdir()
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT))

    host._fetch_once(models, _request(), run)

    assert (models / "model.gguf").read_bytes() == _CONTENT
    assert _progress(run)["status"] == "ready"
    assert not (models / "fetch-progress.json").exists()


def test_a_cancel_in_the_run_directory_stops_the_fetch(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    run = tmp_path / "run"
    models.mkdir()
    run.mkdir()
    (run / "fetch-cancel").write_text("", encoding="utf-8")
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT))

    host._fetch_once(models, _request(), run)

    assert _progress(run)["status"] == "paused"
    assert not (models / "model.gguf").exists()
    assert not (run / "fetch-cancel").exists()


async def test_the_watcher_takes_its_request_from_the_run_directory(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request left in the models directory is not the contract any more —
    the API cannot write there — so only the run directory's is acted on."""
    models = tmp_path / "models"
    run = tmp_path / "run"
    models.mkdir()
    run.mkdir()
    (run / "fetch-request.json").write_text(json.dumps(_request()), encoding="utf-8")
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *_a, **_k: _Response(_CONTENT))
    monkeypatch.setattr(host, "FETCH_POLL_SECONDS", 0.01)

    stopping = asyncio.Event()
    watcher = asyncio.create_task(host.watch_for_fetch_requests(models, run, stopping))
    for _ in range(200):
        if (models / "model.gguf").exists():
            break
        await asyncio.sleep(0.01)
    stopping.set()
    await watcher

    assert (models / "model.gguf").read_bytes() == _CONTENT
    assert not (run / "fetch-request.json").exists()
    assert _progress(run)["status"] == "ready"


# --- M11-FIX-BE-235: one Download fetches every model a tier needs -------------

_EMBED = b"e" * 1024
_RERANK = b"r" * 2048


def _companion(name: str, body: bytes) -> dict[str, Any]:
    return {
        "url": f"https://example.invalid/{name}",
        "filename": name,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def test_companions_are_fetched_after_the_model_as_one_download(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bodies = {"model.gguf": _CONTENT, "embed.gguf": _EMBED, "rerank.gguf": _RERANK}
    asked: list[str] = []

    def fake_urlopen(req: Any, timeout: float) -> _Response:
        name = req.full_url.rsplit("/", 1)[1]
        asked.append(name)
        return _Response(bodies[name])

    monkeypatch.setattr(host.urllib.request, "urlopen", fake_urlopen)
    request = _request(
        companions=[_companion("embed.gguf", _EMBED), _companion("rerank.gguf", _RERANK)]
    )
    host._fetch_once(tmp_path, request, tmp_path)

    assert asked == ["model.gguf", "embed.gguf", "rerank.gguf"]
    for name, body in bodies.items():
        assert (tmp_path / name).read_bytes() == body
    progress = _progress(tmp_path)
    # One download on the screen: the generation model's name, every byte.
    assert progress["status"] == "ready"
    assert progress["filename"] == "model.gguf"
    assert progress["total_bytes"] == len(_CONTENT) + len(_EMBED) + len(_RERANK)
    assert progress["downloaded_bytes"] == progress["total_bytes"]


def test_a_companion_already_in_place_is_not_fetched_again(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "embed.gguf").write_bytes(_EMBED)
    asked: list[str] = []

    def fake_urlopen(req: Any, timeout: float) -> _Response:
        asked.append(req.full_url.rsplit("/", 1)[1])
        return _Response(_CONTENT)

    monkeypatch.setattr(host.urllib.request, "urlopen", fake_urlopen)
    host._fetch_once(tmp_path, _request(companions=[_companion("embed.gguf", _EMBED)]), tmp_path)
    assert asked == ["model.gguf"]
    assert _progress(tmp_path)["status"] == "ready"


def test_a_companion_with_a_bad_checksum_fails_the_download(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _Response:
        name = req.full_url.rsplit("/", 1)[1]
        return _Response(_CONTENT if name == "model.gguf" else b"not the embedding")

    monkeypatch.setattr(host.urllib.request, "urlopen", fake_urlopen)
    host._fetch_once(tmp_path, _request(companions=[_companion("embed.gguf", _EMBED)]), tmp_path)
    progress = _progress(tmp_path)
    assert progress["status"] == "failed"
    assert "embed.gguf" in progress["error"]
    assert not (tmp_path / "embed.gguf").exists()


def test_a_companion_name_with_a_directory_is_refused(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host.urllib.request, "urlopen", lambda req, timeout: _Response(_CONTENT))
    bad = _companion("../outside.gguf", _EMBED)
    host._fetch_once(tmp_path, _request(companions=[bad]), tmp_path)
    assert _progress(tmp_path)["status"] == "failed"
    assert not (tmp_path.parent / "outside.gguf").exists()


def test_a_role_whose_model_is_missing_starts_once_the_file_arrives(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a clean Ubuntu VM the roles reported `model_missing` at start and
    never looked again, so a finished download changed nothing."""
    model = tmp_path / "model.gguf"
    monkeypatch.setattr(host, "MODEL_RECHECK_SECONDS", 0.01)

    class _Role:
        def __init__(self) -> None:
            self.model = model

    role = _Role()
    waited = host.Supervisor.wait_for_model

    async def scenario() -> None:
        task = asyncio.create_task(waited(role))
        await asyncio.sleep(0.05)
        assert not task.done()
        model.write_bytes(b"model")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
