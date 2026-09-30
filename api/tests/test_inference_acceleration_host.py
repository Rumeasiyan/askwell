"""The host supervisor puts the model on a graphics card when llama.cpp can
use one, and says why when it does not. `M10-FIX-DEPLOY-222`.

Same arrangement as `test_model_swap_host.py`: the supervisor is a standalone
stdlib script, loaded by path. `llama-server --list-devices` is answered by a
small stand-in script, so what is under test is the parsing and the decision
on real process output, not a mock of `subprocess`. The load-log lines are
copied from llama.cpp build b10645 on the build host's RTX 3050.
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

VULKAN_LISTING = """\
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = NVIDIA GeForce RTX 3050 (NVIDIA) | uma: 0 | fp16: 1
Available devices:
  Vulkan0: NVIDIA GeForce RTX 3050 (8192 MiB, 7483 MiB free)
"""

CPU_LISTING = """\
Available devices:
  (none)
"""

FULL_OFFLOAD = [
    "0.03.665.866 I load_tensors: offloading output layer to GPU",
    "0.03.665.873 I load_tensors: offloading 31 repeating layers to GPU",
    "0.03.665.873 I load_tensors: offloaded 33/33 layers to GPU",
    "0.03.667.128 I load_tensors:      Vulkan0 model buffer size =  2603.50 MiB",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_loader(
        "askwell_inference_acceleration_host",
        importlib.machinery.SourceFileLoader(
            "askwell_inference_acceleration_host", str(SUPERVISOR)
        ),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_inference_acceleration_host"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("ASKWELL_INFERENCE_SOCKET", str(tmp_path / "run" / "inference.sock"))
    module = _load()
    # A checkout with builds fetched into deploy/inference/llama.cpp must not
    # change what these tests see; `_bundle` places one where a test wants it.
    monkeypatch.setattr(module, "BUNDLED", tmp_path / "no-bundled-llama.cpp")
    return module


def _binary(tmp_path: Path, listing: str) -> Path:
    """A `llama-server` that answers `--list-devices` the way a real build does."""
    listing_file = tmp_path / "listing.txt"
    listing_file.write_text(listing, encoding="utf-8")
    binary = tmp_path / "llama-server"
    binary.write_text(f'#!/bin/sh\ncat "{listing_file}"\n', encoding="utf-8")
    binary.chmod(0o755)
    return binary


def _supervisor(host: ModuleType, tmp_path: Path, listing: str) -> object:
    sup = host.Supervisor()
    sup.binary = str(_binary(tmp_path, listing))
    sup.model = tmp_path / "model.gguf"
    return sup


def _published(tmp_path: Path) -> dict[str, object]:
    payload = json.loads((tmp_path / "run" / "state.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


# --- which devices llama.cpp can use ------------------------------------------


def test_a_vulkan_build_lists_the_card(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    assert sup._list_devices() == [  # type: ignore[attr-defined]
        "Vulkan0: NVIDIA GeForce RTX 3050 (8192 MiB, 7483 MiB free)"
    ]


def test_a_cpu_build_lists_nothing(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, CPU_LISTING)
    assert sup._list_devices() == []  # type: ignore[attr-defined]


def test_backend_log_lines_are_not_devices(host: ModuleType, tmp_path: Path) -> None:
    """`ggml_vulkan: 0 = …` has a colon too; only the indented lines under
    the heading are devices, and the list ends where they do."""
    listing = VULKAN_LISTING + "llama_server: something else: after the list\n"
    sup = _supervisor(host, tmp_path, listing)
    assert sup._list_devices() == [  # type: ignore[attr-defined]
        "Vulkan0: NVIDIA GeForce RTX 3050 (8192 MiB, 7483 MiB free)"
    ]


def test_a_binary_that_cannot_run_lists_nothing(host: ModuleType, tmp_path: Path) -> None:
    sup = host.Supervisor()
    sup.binary = str(tmp_path / "not-there")
    assert sup._list_devices() == []


# --- the command --------------------------------------------------------------


def test_without_a_device_the_command_is_what_it_always_was(
    host: ModuleType, tmp_path: Path
) -> None:
    sup = _supervisor(host, tmp_path, CPU_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    assert sup.command() == [  # type: ignore[attr-defined]
        sup.binary,  # type: ignore[attr-defined]
        "--model",
        str(tmp_path / "model.gguf"),
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "--ctx-size",
        "8192",
        "--no-webui",
    ]


def test_with_a_device_the_layers_go_to_it(host: ModuleType, tmp_path: Path) -> None:
    """`auto`, not a number: llama.cpp's own fit decides how many layers the
    card's free memory holds, which is what makes a small card a partial
    offload rather than a failure."""
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    command = sup.command()  # type: ignore[attr-defined]
    assert command[command.index("--n-gpu-layers") + 1] == "auto"
    assert "--device" not in command


def test_after_the_card_failed_the_model_stays_off_it(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._gpu_failed = "Exited with 1 while loading."  # type: ignore[attr-defined]
    command = sup.command()  # type: ignore[attr-defined]
    assert command[command.index("--device") + 1] == "none"
    assert "--n-gpu-layers" not in command


# --- where the model actually went ---------------------------------------------


def test_the_whole_model_on_the_card_is_gpu_with_nothing_to_explain(
    host: ModuleType, tmp_path: Path
) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(FULL_OFFLOAD)  # type: ignore[attr-defined]
    assert sup.acceleration == "gpu"  # type: ignore[attr-defined]
    assert sup.acceleration_reason is None  # type: ignore[attr-defined]


def test_a_card_too_small_for_all_of_it_is_a_partial_offload_and_says_so(
    host: ModuleType, tmp_path: Path
) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(["I load_tensors: offloaded 20/33 layers to GPU"])  # type: ignore[attr-defined]
    assert sup.acceleration == "gpu"  # type: ignore[attr-defined]
    reason = sup.acceleration_reason  # type: ignore[attr-defined]
    assert "20 of 33 layers" in reason
    assert "NVIDIA GeForce RTX 3050" in reason


def test_a_card_that_holds_none_of_it_is_cpu_and_says_so(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(["I load_tensors: offloaded 0/33 layers to GPU"])  # type: ignore[attr-defined]
    assert sup.acceleration == "cpu"  # type: ignore[attr-defined]
    assert "none of the model" in sup.acceleration_reason  # type: ignore[attr-defined]


def test_no_device_is_cpu_and_names_the_build_or_the_driver(
    host: ModuleType, tmp_path: Path
) -> None:
    """A machine with a card whose driver is too old for the backend lists no
    device, the same as a CPU-only build — and the reason names both."""
    sup = _supervisor(host, tmp_path, CPU_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(["I srv  llama_server: model loaded"])  # type: ignore[attr-defined]
    assert sup.acceleration == "cpu"  # type: ignore[attr-defined]
    reason = sup.acceleration_reason  # type: ignore[attr-defined]
    assert "no GPU backend" in reason
    assert "driver is too old" in reason


def test_the_older_log_wording_still_reads_as_gpu(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(["llm_load_tensors: offloading 32 repeating layers to GPU"])  # type: ignore[attr-defined]
    assert sup.acceleration == "gpu"  # type: ignore[attr-defined]


def test_the_reason_is_published_only_while_ready(host: ModuleType, tmp_path: Path) -> None:
    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration(["I load_tensors: offloaded 20/33 layers to GPU"])  # type: ignore[attr-defined]
    sup._write(host.READY)  # type: ignore[attr-defined]
    ready = _published(tmp_path)
    assert ready["acceleration"] == "gpu"
    assert "20 of 33" in str(ready["acceleration_reason"])
    sup._write(host.STARTING)  # type: ignore[attr-defined]
    assert _published(tmp_path)["acceleration_reason"] is None


# --- a card that cannot load the model -----------------------------------------


class _FakeProcess:
    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self._exited = asyncio.Event()
        if returncode is not None:
            self._exited.set()

    def send_signal(self, _sig: int) -> None:
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.returncode = -9
        self._exited.set()

    async def wait(self) -> int | None:
        await self._exited.wait()
        return self.returncode


async def test_a_card_that_fails_to_load_falls_back_to_the_processor_at_once(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The driver-too-old case where the device is listed but loading on it
    fails: the next start is on the processor, straight away and not counted
    as a crash, and once ready the reason is published beside `cpu`."""
    commands: list[list[str]] = []

    async def fake_start_once(self: object) -> bool:
        commands.append(self.command())  # type: ignore[attr-defined]
        on_card = "--n-gpu-layers" in commands[-1]
        self.process = _FakeProcess(1 if on_card else None)  # type: ignore[attr-defined]
        return True

    async def fake_wait_until_ready(self: object) -> bool:
        if self.process.returncode is not None:  # type: ignore[attr-defined]
            self._last_failure = "ggml_vulkan: device lost"  # type: ignore[attr-defined]
            self._write(host.LOAD_FAILED, self._last_failure)  # type: ignore[attr-defined]
            return False
        self._detect_acceleration(["I srv  llama_server: model loaded"])  # type: ignore[attr-defined]
        self._write(host.READY)  # type: ignore[attr-defined]
        return True

    async def fake_drain(self: object) -> None:
        await self.process._exited.wait()  # type: ignore[attr-defined]

    monkeypatch.setattr(host.Supervisor, "start_once", fake_start_once)
    monkeypatch.setattr(host.Supervisor, "wait_until_ready", fake_wait_until_ready)
    monkeypatch.setattr(host.Supervisor, "drain", fake_drain)

    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    task = asyncio.create_task(sup.supervise())  # type: ignore[attr-defined]
    await asyncio.sleep(0.05)

    assert len(commands) == 2
    assert "--n-gpu-layers" in commands[0]
    assert commands[1][commands[1].index("--device") + 1] == "none"
    assert sup.consecutive == 0  # type: ignore[attr-defined]
    assert sup.restarts == 0  # type: ignore[attr-defined]
    published = _published(tmp_path)
    assert published["state"] == "ready"
    assert published["acceleration"] == "cpu"
    reason = str(published["acceleration_reason"])
    assert reason.startswith("NVIDIA GeForce RTX 3050 could not load the model")
    assert "ggml_vulkan: device lost" in reason

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- ready means loaded, not listening ------------------------------------------


async def _serve(status: bytes) -> tuple[asyncio.Server, int]:
    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_a_port_answering_loading_model_is_not_ready(
    host: ModuleType, tmp_path: Path
) -> None:
    """`llama-server` binds its port before loading and answers 503 until the
    model is in — ready then was published seconds early, before the load
    log said where the model went."""
    server, port = await _serve(b"503 Service Unavailable")
    async with server:
        sup = host.Supervisor()
        sup.upstream_port = port
        assert await sup._answers() is False


async def test_a_port_answering_200_is_ready(host: ModuleType, tmp_path: Path) -> None:
    server, port = await _serve(b"200 OK")
    async with server:
        sup = host.Supervisor()
        sup.upstream_port = port
        assert await sup._answers() is True


async def test_nothing_listening_is_not_ready(host: ModuleType, tmp_path: Path) -> None:
    server, port = await _serve(b"200 OK")
    server.close()
    await server.wait_closed()
    sup = host.Supervisor()
    sup.upstream_port = port
    assert await sup._answers() is False


async def test_an_offload_line_after_ready_is_published_when_it_arrives(
    host: ModuleType, tmp_path: Path
) -> None:
    class _Output:
        def __init__(self, lines: list[str]) -> None:
            self._lines = [line.encode() + b"\n" for line in lines]

        async def readline(self) -> bytes:
            return self._lines.pop(0) if self._lines else b""

    class _Running:
        stdout = _Output(["I srv  update_slots: all slots are idle", FULL_OFFLOAD[2]])

    sup = _supervisor(host, tmp_path, VULKAN_LISTING)
    sup.devices = sup._list_devices()  # type: ignore[attr-defined]
    sup._detect_acceleration([])  # type: ignore[attr-defined]
    assert sup.acceleration == "cpu"  # type: ignore[attr-defined]

    sup.process = _Running()  # type: ignore[attr-defined]
    await sup.drain()  # type: ignore[attr-defined]

    published = _published(tmp_path)
    assert published["acceleration"] == "gpu"
    assert published["acceleration_reason"] is None


async def test_a_model_that_never_finishes_loading_is_stopped(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness now waits for the model, so the timeout is reachable; a
    process left running there would be waited on forever."""

    class _Silent:
        async def readline(self) -> bytes:
            await asyncio.sleep(3600)
            return b""

    class _Loading(_FakeProcess):
        stdout = _Silent()

    async def never(self: object) -> bool:
        return False

    monkeypatch.setattr(host, "READY_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(host.Supervisor, "_answers", never)
    sup = _supervisor(host, tmp_path, CPU_LISTING)
    sup.process = _Loading(None)  # type: ignore[attr-defined]

    assert await sup.wait_until_ready() is False  # type: ignore[attr-defined]
    assert sup.process.returncode == -9  # type: ignore[attr-defined]
    assert _published(tmp_path)["state"] == host.LOAD_FAILED


# --- the builds a release installs beside the supervisor ------------------------


def _bundle(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **builds: str
) -> Path:
    """A `llama.cpp/` beside the supervisor, one stand-in per build, each
    answering `--list-devices` with its listing."""
    bundled = tmp_path / "llama.cpp"
    for variant, listing in builds.items():
        (bundled / variant).mkdir(parents=True)
        listing_file = bundled / variant / "listing.txt"
        listing_file.write_text(listing, encoding="utf-8")
        binary = bundled / variant / host.EXECUTABLE
        binary.write_text(f'#!/bin/sh\ncat "{listing_file}"\n', encoding="utf-8")
        binary.chmod(0o755)
    monkeypatch.setattr(host, "BUNDLED", bundled)
    return bundled


def test_a_configured_binary_is_used_as_it_is(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bundle(host, tmp_path, monkeypatch, gpu=VULKAN_LISTING, cpu=CPU_LISTING)
    assert host._binaries("/opt/my/llama-server") == ("/opt/my/llama-server", None, None)


def test_without_a_bundle_the_default_is_llama_server_on_path(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source checkout: the command is what it always was."""
    monkeypatch.setattr(host, "BUNDLED", tmp_path / "absent")
    assert host._binaries("llama-server") == ("llama-server", None, None)


def test_with_a_bundle_the_default_name_means_the_bundle(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every installed `.env` carries `ASKWELL_INFERENCE_BINARY=llama-server`
    from `.env.example`, and the shell passes it through, so that value must
    not hide the builds the installer placed."""
    bundled = _bundle(host, tmp_path, monkeypatch, gpu=VULKAN_LISTING, cpu=CPU_LISTING)
    gpu = str(bundled / "gpu" / host.EXECUTABLE)
    cpu = str(bundled / "cpu" / host.EXECUTABLE)
    assert host._binaries("llama-server") == (gpu, gpu, cpu)
    monkeypatch.delenv("ASKWELL_INFERENCE_BINARY", raising=False)
    sup = host.Supervisor()
    assert (sup.binary, sup.gpu_binary, sup.cpu_binary) == (gpu, gpu, cpu)


async def _started_command(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, list[str]]:
    started: list[str] = []

    async def fake_exec(*argv: str, **_kwargs: object) -> object:
        started.extend(argv)
        return _FakeProcess(None)

    monkeypatch.setattr(host.asyncio, "create_subprocess_exec", fake_exec)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"gguf")
    monkeypatch.setenv("ASKWELL_INFERENCE_MODEL_PATH", str(model))
    monkeypatch.delenv("ASKWELL_INFERENCE_BINARY", raising=False)
    sup = host.Supervisor()
    assert await sup.start_once() is True
    return sup, started


async def test_a_machine_with_a_card_starts_the_gpu_build_with_offload(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = _bundle(host, tmp_path, monkeypatch, gpu=VULKAN_LISTING, cpu=CPU_LISTING)
    _sup, command = await _started_command(host, tmp_path, monkeypatch)
    assert command[0] == str(bundled / "gpu" / host.EXECUTABLE)
    assert command[command.index("--n-gpu-layers") + 1] == "auto"


async def test_a_machine_without_one_starts_the_cpu_build_unchanged(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No device — no card, or a driver too old for Vulkan — and the CPU
    build runs with exactly the flags it always had."""
    bundled = _bundle(host, tmp_path, monkeypatch, gpu=CPU_LISTING, cpu=CPU_LISTING)
    sup, command = await _started_command(host, tmp_path, monkeypatch)
    assert command[0] == str(bundled / "cpu" / host.EXECUTABLE)
    assert "--n-gpu-layers" not in command and "--device" not in command
    sup._detect_acceleration(["I srv  llama_server: model loaded"])  # type: ignore[attr-defined]
    assert sup.acceleration == "cpu"  # type: ignore[attr-defined]
    assert "driver is too old" in sup.acceleration_reason  # type: ignore[attr-defined]


async def test_a_gpu_build_that_cannot_even_list_devices_leaves_the_cpu_build(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A driver that crashes the Vulkan backend fails at `--list-devices`,
    before any model is loaded — and the machine answers on the CPU build."""
    bundled = _bundle(host, tmp_path, monkeypatch, gpu=VULKAN_LISTING, cpu=CPU_LISTING)
    (bundled / "gpu" / host.EXECUTABLE).write_text("#!/bin/sh\nkill -SEGV $$\n", encoding="utf-8")
    _sup, command = await _started_command(host, tmp_path, monkeypatch)
    assert command[0] == str(bundled / "cpu" / host.EXECUTABLE)
    assert "--n-gpu-layers" not in command


async def test_a_card_that_fails_to_load_falls_back_to_the_cpu_build(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = _bundle(host, tmp_path, monkeypatch, gpu=VULKAN_LISTING, cpu=CPU_LISTING)
    commands: list[list[str]] = []

    async def fake_start_once(self: object) -> bool:
        if self.devices is None:  # type: ignore[attr-defined]
            self.devices = self._list_devices()  # type: ignore[attr-defined]
        commands.append(self.command())  # type: ignore[attr-defined]
        on_card = "--n-gpu-layers" in commands[-1]
        self.process = _FakeProcess(1 if on_card else None)  # type: ignore[attr-defined]
        return True

    async def fake_wait_until_ready(self: object) -> bool:
        if self.process.returncode is not None:  # type: ignore[attr-defined]
            self._last_failure = "ggml_vulkan: device lost"  # type: ignore[attr-defined]
            return False
        self._detect_acceleration([])  # type: ignore[attr-defined]
        self._write(host.READY)  # type: ignore[attr-defined]
        return True

    async def fake_drain(self: object) -> None:
        await self.process._exited.wait()  # type: ignore[attr-defined]

    monkeypatch.setattr(host.Supervisor, "start_once", fake_start_once)
    monkeypatch.setattr(host.Supervisor, "wait_until_ready", fake_wait_until_ready)
    monkeypatch.setattr(host.Supervisor, "drain", fake_drain)
    monkeypatch.delenv("ASKWELL_INFERENCE_BINARY", raising=False)

    sup = host.Supervisor()
    task = asyncio.create_task(sup.supervise())
    await asyncio.sleep(0.05)

    assert commands[0][0] == str(bundled / "gpu" / host.EXECUTABLE)
    assert commands[1][0] == str(bundled / "cpu" / host.EXECUTABLE)
    assert "--device" not in commands[1] and "--n-gpu-layers" not in commands[1]
    assert sup.restarts == 0
    assert "could not load the model" in str(_published(tmp_path)["acceleration_reason"])

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- generation takes the card first (#841) --------------------------------------


async def test_the_other_roles_wait_for_generation_to_settle(host: ModuleType) -> None:
    settled = asyncio.Event()
    ran: list[str] = []

    async def work() -> None:
        ran.append("embedding")

    waiting = asyncio.create_task(host.after(settled, work))
    await asyncio.sleep(0.01)
    assert ran == []
    settled.set()
    await waiting
    assert ran == ["embedding"]


async def test_generation_settles_when_ready(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_start_once(self: object) -> bool:
        self.process = _FakeProcess(None)  # type: ignore[attr-defined]
        return True

    async def ready(self: object) -> bool:
        return True

    async def fake_drain(self: object) -> None:
        await self.process._exited.wait()  # type: ignore[attr-defined]

    monkeypatch.setattr(host.Supervisor, "start_once", fake_start_once)
    monkeypatch.setattr(host.Supervisor, "wait_until_ready", ready)
    monkeypatch.setattr(host.Supervisor, "drain", fake_drain)
    sup = host.Supervisor()
    task = asyncio.create_task(sup.supervise())
    async with asyncio.timeout(1):
        await sup.settled.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_generation_with_no_model_settles_so_the_others_still_start(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing generation model must not hold retrieval back.

    Since `M11-FIX-BE-235` the role no longer returns: it settles, then waits
    for the file to arrive, so a download finishing later starts it."""
    monkeypatch.setenv("ASKWELL_INFERENCE_MODEL_PATH", str(tmp_path / "absent.gguf"))
    sup = host.Supervisor()
    task = asyncio.create_task(sup.supervise())
    await asyncio.wait_for(sup.settled.wait(), timeout=5)
    assert not task.done()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_a_crashing_generation_settles_before_its_backoff(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_start_once(self: object) -> bool:
        self.process = _FakeProcess(1)  # type: ignore[attr-defined]
        return True

    async def not_ready(self: object) -> bool:
        return False

    monkeypatch.setattr(host.Supervisor, "start_once", fake_start_once)
    monkeypatch.setattr(host.Supervisor, "wait_until_ready", not_ready)
    monkeypatch.setattr(host, "BACKOFF_SECONDS", (60,))
    sup = host.Supervisor()
    sup.binary = "llama-server"
    sup.devices = []
    task = asyncio.create_task(sup.supervise())
    async with asyncio.timeout(1):
        await sup.settled.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
