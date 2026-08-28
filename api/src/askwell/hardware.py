"""A basic hardware profile, run at first launch. `M1-LIB-FE-052`.

The full hardware probe is `M7-PROBE` and runs on the host, not in a
container (`docs/architecture.md` §6) — a container sees the cgroup's or the
VM's view of memory, which is not the machine's. This module reads the same
`/proc/meminfo` a container-level probe would still see correctly (memory
accounting is per-cgroup on Linux, but the *total* a cgroup-unconstrained
container reports is the host's), so it is honest enough to show on the
welcome screen without waiting for M7 — the ticket's own assumption is
exactly this: "the probe exists in a basic form by M1 or the sequence falls
back to the standard profile with a stated reason."

GPU presence is a coarse yes/no from whether `nvidia-smi` is on `PATH` and
answers, not a verified VRAM figure — good enough to distinguish "definitely
CPU-only" from "has an NVIDIA GPU worth trying", not to size a model against.
No AMD/ROCm detection: `rocm-smi` is checked as well, but its VRAM query
format is not parsed, so a ROCm machine reports GPU presence without a VRAM
number and is treated the same as an undetermined-VRAM NVIDIA machine.

**Copy needing human review** (ticket's own requirement): `_EXPECTATION` below
renders directly onto the welcome screen's machine-check step.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

_MEMINFO = "/proc/meminfo"
_LIGHT_FLOOR_GB = 8.0
_STANDARD_FLOOR_GB = 16.0
_WORKSTATION_FLOOR_GB = 32.0
_ACCELERATED_VRAM_FLOOR_GB = 8.0
_WORKSTATION_VRAM_FLOOR_GB = 16.0

# Human review required before this ships (ticket's own "Human review: copy").
_EXPECTATION = {
    "below_floor": "Below what Askwell expects (8 GB). It will run, but slowly, "
    "and voice will likely not work.",
    "light": "{ram:.0f} GB, CPU only. Answers may take up to a minute. Voice will be limited.",
    "standard": "{ram:.0f} GB, no GPU. Answers in about 15 seconds. Voice will work.",
    "accelerated": "{ram:.0f} GB with a GPU. Answers in a few seconds. Full voice.",
    "workstation": "{ram:.0f} GB with a capable GPU. Fast answers, full capability.",
}


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    tier: str
    ram_gb: float
    gpu_detected: bool
    vram_gb: float | None
    floor_met: bool
    expectation: str
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "ram_gb": round(self.ram_gb, 1),
            "gpu_detected": self.gpu_detected,
            "vram_gb": self.vram_gb,
            "floor_met": self.floor_met,
            "expectation": self.expectation,
            "source": self.source,
        }


def _total_ram_gb() -> float | None:
    try:
        with open(_MEMINFO, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    kib = int(line.split()[1])
                    return kib / (1024 * 1024)
    except OSError:
        return None
    return None


def _nvidia_vram_gb() -> float | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    try:
        return int(first_line.strip()) / 1024
    except ValueError:
        return None


def _gpu_present() -> bool:
    if shutil.which("nvidia-smi") is not None:
        return True
    return shutil.which("rocm-smi") is not None


def probe() -> HardwareProfile:
    """Read what this machine can tell us right now, no installer needed.

    Falls back to `standard` with the reason stated, as the ticket's own
    Assumptions line requires, when memory cannot be read at all (a
    non-Linux host, a locked-down container) — never refuses.
    """
    ram_gb = _total_ram_gb()
    if ram_gb is None:
        return HardwareProfile(
            tier="standard",
            ram_gb=16.0,
            gpu_detected=False,
            vram_gb=None,
            floor_met=True,
            expectation=_EXPECTATION["standard"].format(ram=16.0)
            + " (Memory could not be read on this machine; assuming the standard profile.)",
            source="fallback",
        )

    gpu = _gpu_present()
    vram_gb = _nvidia_vram_gb() if gpu else None

    if ram_gb < _LIGHT_FLOOR_GB:
        tier = "light"
        floor_met = False
        expectation = _EXPECTATION["below_floor"]
    elif (
        ram_gb >= _WORKSTATION_FLOOR_GB
        and vram_gb is not None
        and vram_gb >= _WORKSTATION_VRAM_FLOOR_GB
    ):
        tier = "workstation"
        floor_met = True
        expectation = _EXPECTATION["workstation"].format(ram=ram_gb)
    elif (
        ram_gb >= _STANDARD_FLOOR_GB
        and gpu
        and (vram_gb is None or vram_gb >= _ACCELERATED_VRAM_FLOOR_GB)
    ):
        tier = "accelerated"
        floor_met = True
        expectation = _EXPECTATION["accelerated"].format(ram=ram_gb)
    elif ram_gb >= _STANDARD_FLOOR_GB:
        tier = "standard"
        floor_met = True
        expectation = _EXPECTATION["standard"].format(ram=ram_gb)
    else:
        tier = "light"
        floor_met = True
        expectation = _EXPECTATION["light"].format(ram=ram_gb)

    return HardwareProfile(
        tier=tier,
        ram_gb=ram_gb,
        gpu_detected=gpu,
        vram_gb=vram_gb,
        floor_met=floor_met,
        expectation=expectation,
        source="basic-probe",
    )
