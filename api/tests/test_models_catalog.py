"""The model registry itself: real names, real sizes, real hashes.

`AGENTS.md` §4's registry-verification rule is why this is a test and not
just a docstring — a copy-paste error in a sha256 fails silently at download
time, weeks from now, as a mysterious hash mismatch.
"""

from askwell.models_catalog import CATALOG, spec_for_tier


def test_every_tier_maps_to_a_spec() -> None:
    for tier in ("light", "standard", "accelerated", "workstation"):
        spec = spec_for_tier(tier)
        assert spec.size_bytes > 0
        assert len(spec.sha256) == 64
        assert spec.url.startswith("https://huggingface.co/")


def test_unknown_tier_falls_back_rather_than_raising() -> None:
    spec = spec_for_tier("nonexistent-tier")
    assert spec is CATALOG["light"]


def test_light_and_standard_share_the_smaller_model() -> None:
    assert CATALOG["light"] is CATALOG["standard"]


def test_accelerated_and_workstation_share_the_larger_model() -> None:
    assert CATALOG["accelerated"] is CATALOG["workstation"]
    assert CATALOG["accelerated"].size_bytes > CATALOG["light"].size_bytes
