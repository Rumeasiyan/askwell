"""The host-side hardware probe. `M7-PROBE-DEPLOY-137`.

`deploy/probe/askwell-probe` is standalone stdlib, for the same reason
`deploy/inference/askwell-inference` is — it must run on the host, and the
host's Python is not ours to choose. So it is loaded here by path, the same
way `test_model_fetch_host.py` exercises the inference supervisor's own
host-only logic, and the seam to `askwell.probe` is checked for drift the
same way `test_inference.py` checks the state vocabulary.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from askwell.probe import PROFILES

SUPERVISOR = Path(__file__).resolve().parents[2] / "deploy" / "probe" / "askwell-probe"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_loader(
        "askwell_probe_host",
        importlib.machinery.SourceFileLoader("askwell_probe_host", str(SUPERVISOR)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_probe_host"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host() -> ModuleType:
    return _load()


# --- the seam ---------------------------------------------------------------


def test_the_host_script_and_the_application_agree_on_the_profile_names() -> None:
    """The one test that earns its place here.

    The host script is standalone and cannot import `askwell.probe` — it
    defines the same four strings itself. Nothing but this catches them
    drifting, and the failure would be a profile the API silently does not
    recognise on a user's machine.
    """
    source = SUPERVISOR.read_text(encoding="utf-8")
    declared = set(re.findall(r'^([A-Z_]+) = "([a-z]+)"$', source, re.MULTILINE))
    names = {value for _, value in declared if value in PROFILES}
    assert names == set(PROFILES), "the host script's profile vocabulary has drifted from PROFILES"


# --- refusing to run in a container -----------------------------------------


def test_refuses_when_docker_marker_is_present(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host.Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert host.in_container() is True


def test_refuses_when_cgroup_names_a_container_runtime(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/docker/abc123\n", encoding="utf-8")
    monkeypatch.setattr(host.Path, "exists", lambda self: False)
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *a: object, **k: object) -> str:
        if str(self) == "/proc/1/cgroup":
            return original_read_text(cgroup, *a, **k)
        raise OSError("not found")

    monkeypatch.setattr(host.Path, "read_text", fake_read_text)
    assert host.in_container() is True


def test_a_bare_machine_is_not_a_container(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host.Path, "exists", lambda self: False)

    def fake_read_text(self: Path, *a: object, **k: object) -> str:
        raise OSError("no such file")

    monkeypatch.setattr(host.Path, "read_text", fake_read_text)
    assert host.in_container() is False


def test_main_refuses_and_writes_nothing_inside_a_container(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(host, "in_container", lambda: True)
    result_path = tmp_path / "probe.json"
    monkeypatch.setenv("ASKWELL_PROBE_RESULT_PATH", str(result_path))

    exit_code = host.main([])

    assert exit_code != 0
    assert not result_path.exists()


# --- profile selection -------------------------------------------------------


ABSENT = {"present": False, "kind": None, "vram_gb": None, "source": "not detected"}


def _accel(**over: object) -> dict[str, object]:
    return {**ABSENT, **over}


@pytest.mark.parametrize(
    ("ram_gb", "accelerator", "expected"),
    [
        (4.0, ABSENT, "light"),
        (7.9, ABSENT, "light"),
        (8.0, ABSENT, "light"),
        (15.9, ABSENT, "light"),
        (16.0, ABSENT, "standard"),
        (16.0, _accel(present=True, kind="nvidia", vram_gb=4.0), "standard"),
        (16.0, _accel(present=True, kind="nvidia", vram_gb=8.0), "accelerated"),
        (31.0, _accel(present=True, kind="nvidia", vram_gb=8.0), "accelerated"),
        (32.0, _accel(present=True, kind="nvidia", vram_gb=8.0), "accelerated"),
        (32.0, _accel(present=True, kind="nvidia", vram_gb=16.0), "workstation"),
        (32.0, _accel(present=True, kind="nvidia", vram_gb=15.9), "accelerated"),
        (16.0, _accel(present=True, kind="rocm", vram_gb=None), "accelerated"),
    ],
)
def test_profile_thresholds_match_architecture_md_section_6(
    host: ModuleType, ram_gb: float, accelerator: dict[str, object], expected: str
) -> None:
    profile, _reason, detection_failed = host.select_profile(ram_gb, accelerator)
    assert profile == expected
    assert detection_failed is False


def test_below_the_light_floor_is_still_light_but_warns(host: ModuleType) -> None:
    profile, reason, detection_failed = host.select_profile(4.0, ABSENT)
    assert profile == "light"
    assert detection_failed is False
    assert "below" in reason.lower()


def test_detection_failure_falls_back_to_standard_with_a_stated_reason(host: ModuleType) -> None:
    """`docs/architecture.md` §6: "Where detection fails, default to `standard`
    and say so." Distinct from a real reading under the floor, which stays
    `light` (above)."""
    profile, reason, detection_failed = host.select_profile(None, ABSENT)
    assert profile == "standard"
    assert detection_failed is True
    assert "could not be measured" in reason.lower()


def test_an_unrecognised_accelerator_is_treated_as_absent(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket's own edge case: an accelerator the probe does not
    recognise is absent, stated, and the user can override the profile
    (`M7-PROBE-FE-138`, out of scope here)."""
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    monkeypatch.setattr(host.platform, "system", lambda: "Linux")
    accelerator = host.detect_accelerator(ram_gb=64.0)
    assert accelerator == {
        "present": False,
        "kind": None,
        "vram_gb": None,
        "source": "not detected",
    }


def test_apple_silicon_is_reported_as_unified_memory(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    monkeypatch.setattr(host.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(host.platform, "machine", lambda: "arm64")
    accelerator = host.detect_accelerator(ram_gb=36.0)
    assert accelerator["present"] is True
    assert accelerator["kind"] == "apple-silicon"
    assert accelerator["vram_gb"] == 36.0


# --- a virtual machine's dishonest memory figure ----------------------------


def test_a_vm_reported_value_is_used_and_the_source_is_stated(
    host: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket's own edge case: a VM reporting the host's memory
    dishonestly is not detected or corrected — the value is used as given,
    and where it came from is on the record."""
    monkeypatch.setattr(host.platform, "system", lambda: "Linux")
    meminfo = "MemTotal:       999999999 kB\nMemFree:        1000 kB\n"
    monkeypatch.setattr(host, "open", lambda *_a, **_k: io.StringIO(meminfo), raising=False)
    ram_gb, source = host.detect_memory()
    assert ram_gb == pytest.approx(999999999 / (1024 * 1024))
    assert source == "/proc/meminfo"


# --- publishing --------------------------------------------------------------


def test_probe_once_writes_atomically_and_reads_back(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "detect_memory", lambda: (16.0, "test"))
    monkeypatch.setattr(host, "detect_accelerator", lambda ram_gb: ABSENT)
    monkeypatch.setattr(
        host, "detect_cpu", lambda: {"processor": "test", "machine": "x", "cores": 4}
    )
    monkeypatch.setattr(host, "detect_disk", lambda path: 100.0)

    result = host.probe_once(tmp_path)
    result_path = tmp_path / "probe.json"
    host._write(result_path, result)

    read_back = json.loads(result_path.read_text(encoding="utf-8"))
    assert read_back["profile"] == "standard"
    assert not result_path.with_suffix(".partial").exists()


def test_watch_mode_reprobes_on_request_and_clears_the_flag(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "in_container", lambda: False)
    monkeypatch.setattr(host, "detect_memory", lambda: (16.0, "test"))
    monkeypatch.setattr(host, "detect_accelerator", lambda ram_gb: ABSENT)
    monkeypatch.setattr(
        host, "detect_cpu", lambda: {"processor": "test", "machine": "x", "cores": 4}
    )
    monkeypatch.setattr(host, "detect_disk", lambda path: 100.0)

    result_path = tmp_path / "probe.json"
    request_path = tmp_path / host.REQUEST_FLAG
    monkeypatch.setenv("ASKWELL_PROBE_RESULT_PATH", str(result_path))
    monkeypatch.setenv("ASKWELL_PROBE_DISK_PATH", str(tmp_path))

    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            request_path.write_text("", encoding="utf-8")
        elif calls["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(host.time, "sleep", fake_sleep)

    exit_code = host.main(["--watch"])

    assert exit_code == 0
    assert not request_path.exists(), "the flag is consumed, not left to fire again"
    assert json.loads(result_path.read_text(encoding="utf-8"))["profile"] == "standard"
