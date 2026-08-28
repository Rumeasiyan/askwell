"""The basic machine-check probe. `M1-LIB-FE-052`.

No network, no subprocess mocked out to a real binary — `_total_ram_gb` and
`_gpu_present`/`_nvidia_vram_gb` are monkeypatched so the tier logic itself is
what is under test, not whatever hardware happens to run CI.
"""

import pytest

from askwell import hardware


def test_below_the_light_floor_warns_and_still_returns_a_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 4.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: False)
    result = hardware.probe()
    assert result.tier == "light"
    assert result.floor_met is False
    assert "Below" in result.expectation


def test_light_floor_met_no_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 10.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: False)
    result = hardware.probe()
    assert result.tier == "light"
    assert result.floor_met is True


def test_standard_no_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: False)
    result = hardware.probe()
    assert result.tier == "standard"
    assert result.gpu_detected is False


def test_accelerated_with_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: True)
    monkeypatch.setattr(hardware, "_nvidia_vram_gb", lambda: 8.0)
    result = hardware.probe()
    assert result.tier == "accelerated"
    assert result.gpu_detected is True
    assert result.vram_gb == 8.0


def test_workstation_needs_both_ram_and_vram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 32.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: True)
    monkeypatch.setattr(hardware, "_nvidia_vram_gb", lambda: 16.0)
    result = hardware.probe()
    assert result.tier == "workstation"


def test_high_ram_thin_vram_gpu_falls_back_to_standard(monkeypatch: pytest.MonkeyPatch) -> None:
    """32 GB RAM with a GPU too small to trust for `accelerated` (< 8 GB VRAM)
    is `standard`, not `accelerated` — the VRAM floor is a real gate, not
    "any GPU counts"."""
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: 32.0)
    monkeypatch.setattr(hardware, "_gpu_present", lambda: True)
    monkeypatch.setattr(hardware, "_nvidia_vram_gb", lambda: 4.0)
    result = hardware.probe()
    assert result.tier == "standard"


def test_unreadable_meminfo_falls_back_to_standard_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardware, "_total_ram_gb", lambda: None)
    result = hardware.probe()
    assert result.tier == "standard"
    assert result.source == "fallback"
    assert "could not be read" in result.expectation
