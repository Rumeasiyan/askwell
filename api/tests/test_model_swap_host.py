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


# --- the watcher: the file-signal seam with the API --------------------------


async def test_watch_for_swap_requests_reads_swaps_and_reports(
    host: ModuleType, tmp_path: Path
) -> None:
    class _FakeSupervisor:
        async def swap_model(self, new_model: Path) -> tuple[bool, str | None]:
            return True, None

    model_path = tmp_path / "m.gguf"
    (tmp_path / host.SWAP_REQUEST).write_text(
        json.dumps({"model_path": str(model_path)}), encoding="utf-8"
    )

    stopping = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stopping.set()

    stopper = asyncio.create_task(stop_soon())
    await host.watch_for_swap_requests(_FakeSupervisor(), tmp_path, stopping)  # type: ignore[arg-type]
    await stopper

    assert not (tmp_path / host.SWAP_REQUEST).exists()
    result = json.loads((tmp_path / host.SWAP_RESULT).read_text(encoding="utf-8"))
    assert result == {
        "model_path": str(model_path),
        "ok": True,
        "reason": None,
        "updated_at": result["updated_at"],
    }
