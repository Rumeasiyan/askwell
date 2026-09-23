"""The host supervisor's live model swap, for the generation role.
`M7-SET-BE-145a`.

Same arrangement as `test_model_fetch_host.py`: the supervisor is a
standalone stdlib script, loaded here by path and exercised directly.
`start_once`/`wait_until_ready`/`drain` are faked per test so nothing spawns
a real `llama-server` or opens a real socket — what is under test is the
orchestration in `Supervisor.supervise`/`swap_model`, not `llama.cpp` itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SUPERVISOR = Path(__file__).resolve().parents[2] / "deploy" / "inference" / "askwell-inference"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_loader(
        "askwell_inference_swap_host",
        importlib.machinery.SourceFileLoader("askwell_inference_swap_host", str(SUPERVISOR)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_inference_swap_host"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host() -> ModuleType:
    return _load()


class _FakeProcess:
    """Enough of `asyncio.subprocess.Process` for `swap_model`'s own
    terminate-then-wait to observe an exit without a real child process."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self._exited = asyncio.Event()

    def send_signal(self, _sig: int) -> None:
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.returncode = -9
        self._exited.set()

    async def wait(self) -> int | None:
        await self._exited.wait()
        return self.returncode


def _fake_supervisor_methods(
    monkeypatch: pytest.MonkeyPatch, host: ModuleType, *, fails_for: Path | None = None
) -> None:
    async def fake_start_once(self: object) -> bool:
        self.process = _FakeProcess()  # type: ignore[attr-defined]
        return True

    async def fake_wait_until_ready(self: object) -> bool:
        return self.model != fails_for  # type: ignore[attr-defined]

    async def fake_drain(self: object) -> None:
        await self.process._exited.wait()  # type: ignore[attr-defined]

    monkeypatch.setattr(host.Supervisor, "start_once", fake_start_once)
    monkeypatch.setattr(host.Supervisor, "wait_until_ready", fake_wait_until_ready)
    monkeypatch.setattr(host.Supervisor, "drain", fake_drain)


async def _running(host: ModuleType, sup: object) -> asyncio.Task[None]:
    task = asyncio.create_task(sup.supervise())  # type: ignore[attr-defined]
    # Enough for `supervise()` to reach `start_once` -> `wait_until_ready` ->
    # `drain` and settle there, waiting on the fake process's own exit event.
    await asyncio.sleep(0.05)
    return task


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- swap_model: the guards, before anything is touched ---------------------


async def test_swap_when_the_role_is_not_supervised_at_all(
    host: ModuleType, tmp_path: Path
) -> None:
    sup = host.Supervisor()
    ok, reason = await sup.swap_model(tmp_path / "x.gguf")
    assert ok is False
    assert "not running this role" in reason
    assert "scripts/dev.sh inference" in reason


async def test_swap_when_no_process_is_currently_answering(
    host: ModuleType, tmp_path: Path
) -> None:
    sup = host.Supervisor()
    sup._supervising = True  # e.g. still starting, or backing off after a crash
    ok, reason = await sup.swap_model(tmp_path / "x.gguf")
    assert ok is False
    assert "not currently answering" in reason


async def test_swap_rejects_a_path_that_is_not_a_file(host: ModuleType, tmp_path: Path) -> None:
    sup = host.Supervisor()
    sup._supervising = True
    sup.process = _FakeProcess()
    ok, reason = await sup.swap_model(tmp_path / "missing.gguf")
    assert ok is False
    assert "No file at" in reason


# --- swap_model, driven through a real supervise() loop ---------------------


async def test_a_successful_swap_ends_up_on_the_new_model(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_supervisor_methods(monkeypatch, host)
    sup = host.Supervisor()
    sup.model = tmp_path / "shipped.gguf"
    task = await _running(host, sup)

    new_model = tmp_path / "custom.gguf"
    new_model.write_bytes(b"GGUF")
    ok, reason = await sup.swap_model(new_model)

    assert ok is True
    assert reason is None
    assert sup.model == new_model
    assert sup.consecutive == 0  # a deliberate swap is never counted as a crash

    await _stop(task)


async def test_a_failed_swap_restores_the_previous_model_and_names_it(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"GGUF")
    good = tmp_path / "good.gguf"

    _fake_supervisor_methods(monkeypatch, host, fails_for=bad)
    sup = host.Supervisor()
    sup.model = good
    task = await _running(host, sup)

    ok, reason = await sup.swap_model(bad)

    assert ok is False
    assert "Could not load bad.gguf" in reason
    assert "good.gguf" in reason
    assert sup.model == good  # restored, still answering
    assert sup.consecutive == 0  # the restore succeeded; this is not a crash either

    await _stop(task)


@pytest.mark.parametrize("fails", [False, True])
async def test_a_swap_starts_exactly_one_process_per_model_it_loads(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    """Regression, found running `M7-SET-FE-146` against the real stack:
    after a swap the loop started a second `llama-server` on the same port,
    which could not bind and exited 1 — a crash loop behind a model that
    was answering. One start for the original, one for the swap target, one
    more only if the target fails and the original is restored."""
    target = tmp_path / "target.gguf"
    target.write_bytes(b"GGUF")
    _fake_supervisor_methods(monkeypatch, host, fails_for=target if fails else None)
    starts: list[Path] = []
    fake_start = host.Supervisor.start_once

    async def counting_start(self: object) -> bool:
        starts.append(self.model)  # type: ignore[attr-defined]
        return bool(await fake_start(self))

    monkeypatch.setattr(host.Supervisor, "start_once", counting_start)
    sup = host.Supervisor()
    original = tmp_path / "original.gguf"
    sup.model = original
    task = await _running(host, sup)

    await sup.swap_model(target)
    await asyncio.sleep(0.1)  # time for a stray extra start to happen, if any

    assert starts == ([original, target, original] if fails else [original, target])
    await _stop(task)


# --- the watcher: the file-signal seam with the API --------------------------


async def _watch_once(host: ModuleType, supervisor: object, tmp_path: Path, models: Path) -> None:
    stopping = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stopping.set()

    stopper = asyncio.create_task(stop_soon())
    await host.watch_for_swap_requests(supervisor, tmp_path, stopping, models)
    await stopper


async def test_watch_for_swap_requests_resolves_a_file_name_in_the_models_dir(
    host: ModuleType, tmp_path: Path
) -> None:
    """`M7-SET-FE-146`, issue #660: the API names a file, never a path — it
    sees the models directory at `/models`, which is not where it is on the
    host. The supervisor resolves the name against its own view of it."""
    swapped_to: list[Path] = []

    class _FakeSupervisor:
        async def swap_model(self, new_model: Path) -> tuple[bool, str | None]:
            swapped_to.append(new_model)
            return True, None

    models = tmp_path / "models"
    (tmp_path / host.SWAP_REQUEST).write_text(
        json.dumps({"model_file": "m.gguf"}), encoding="utf-8"
    )

    await _watch_once(host, _FakeSupervisor(), tmp_path, models)

    assert swapped_to == [models / "m.gguf"]
    assert not (tmp_path / host.SWAP_REQUEST).exists()
    result = json.loads((tmp_path / host.SWAP_RESULT).read_text(encoding="utf-8"))
    assert result == {
        "model_file": "m.gguf",
        "ok": True,
        "reason": None,
        "updated_at": result["updated_at"],
    }


@pytest.mark.parametrize("name", ["../elsewhere.gguf", "/etc/passwd", "sub/m.gguf", "..", ""])
async def test_watch_for_swap_requests_refuses_anything_but_a_bare_file_name(
    host: ModuleType, tmp_path: Path, name: str
) -> None:
    """A request file must not be able to point `llama-server` outside the
    models directory."""

    class _FakeSupervisor:
        async def swap_model(self, new_model: Path) -> tuple[bool, str | None]:
            raise AssertionError(f"swapped to {new_model}")

    (tmp_path / host.SWAP_REQUEST).write_text(json.dumps({"model_file": name}), encoding="utf-8")

    await _watch_once(host, _FakeSupervisor(), tmp_path, tmp_path / "models")

    result = json.loads((tmp_path / host.SWAP_RESULT).read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "not a file name" in result["reason"]


# --- memory footprint ----------------------------------------------------


def test_memory_is_the_running_processes_resident_size(host: ModuleType) -> None:
    """`M7-SET-FE-146`: a measured figure. This test's own process stands in
    for `llama-server` — any live pid has a resident size to read."""
    import os

    supervisor = host.Supervisor()

    class _Live:
        pid = os.getpid()
        returncode = None

    supervisor.process = _Live()
    measured = supervisor._memory_bytes()
    assert isinstance(measured, int) and measured > 0


def test_memory_is_unmeasured_with_no_process(host: ModuleType) -> None:
    supervisor = host.Supervisor()
    supervisor.process = None
    assert supervisor._memory_bytes() is None


def test_publishing_state_never_measures_memory_on_the_event_loop(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Issue #671: `_write` runs on the supervisor's one event loop, and on
    macOS measuring means running `ps`. It publishes the last measured figure
    and nothing else; `_measure_memory` does the measuring, in a thread."""
    monkeypatch.setenv("ASKWELL_INFERENCE_SOCKET", str(tmp_path / "inference.sock"))
    supervisor = host.Supervisor()

    def must_not_run() -> int:
        raise AssertionError("_write measured memory itself")

    monkeypatch.setattr(supervisor, "_memory_bytes", lambda: 4096)
    asyncio.run(supervisor._measure_memory())
    monkeypatch.setattr(supervisor, "_memory_bytes", must_not_run)

    supervisor._write(host.READY)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["memory_bytes"] == 4096

    # A stopped process's figure is not carried over to the next one.
    supervisor._write(host.STOPPED)
    supervisor._write(host.READY)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["memory_bytes"] is None
