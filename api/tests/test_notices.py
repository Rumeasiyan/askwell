"""`M7-DOC-DOC-163` — the model-licence inventory and its disallow check;
`M8-FIX-DOC-179` — the rule it applies is GPLv3 compatibility.

The static table, the pure matching functions, and the generator's `check()`
fed fabricated inventories: the full inventory (every installed Python and
pnpm dependency) is real I/O against the built image and belongs to
`scripts/generate_notices.py` and the release gate
(`docs/release-procedure.md`), not the no-network unit suite. The generator
is loaded by path, the way `test_probe_host.py` loads the host probe.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tomllib
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from askwell.notices import (
    DISALLOWED_LICENSES,
    MODEL_NOTICES,
    ModelNotice,
    disallowed_tokens,
    unclear_tokens,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_notices.py"


@pytest.fixture
def generator() -> ModuleType:
    spec = importlib.util.spec_from_loader(
        "askwell_generate_notices",
        importlib.machinery.SourceFileLoader("askwell_generate_notices", str(GENERATOR)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_generate_notices"] = module
    spec.loader.exec_module(module)
    return module


def _runtime(generator: ModuleType, name: str, license_expression: str) -> Any:
    return generator.DependencyNotice(
        name=name, version="1.0.0", license=license_expression, scope="runtime"
    )


def test_every_model_notice_has_a_licence_and_a_source() -> None:
    for notice in MODEL_NOTICES:
        assert notice.license.strip(), notice.name
        assert notice.source.strip(), notice.name
        assert notice.verified.strip(), notice.name


def test_no_bundled_model_carries_a_disallowed_licence() -> None:
    for notice in MODEL_NOTICES:
        assert not disallowed_tokens(notice.license), (
            f"{notice.name} ({notice.role}) is licensed {notice.license!r}, "
            "which C9 does not permit bundling"
        )


def test_model_notices_cover_every_bundled_role() -> None:
    roles = {n.role for n in MODEL_NOTICES}
    for expected in (
        "Embedding",
        "Reranker",
        "Transcription",
        "Voice activity detection",
        "Synthesis",
    ):
        assert expected in roles


def test_gplv3_and_gpl_2_or_later_are_allowed() -> None:
    # Askwell is GPL-3.0-or-later (docs/decisions.md, 2026-09-25): every GPL
    # that can be taken under v3 is compatible, and none of it is unclear.
    for expression in (
        "GPL-3.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0",
        "GPL-3.0+",
        "GPL-2.0-or-later",
        "GPL-2.0+",
    ):
        assert disallowed_tokens(expression) == [], expression
        assert unclear_tokens(expression) == [], expression


def test_gpl_2_only_agpl_and_sspl_stay_disallowed() -> None:
    # GPL-2.0-only cannot be relicensed to v3; "GPL-2.0" is SPDX's deprecated
    # spelling of the same thing. AGPL and SSPL add network obligations.
    assert disallowed_tokens("GPL-2.0-only") == ["GPL-2.0-ONLY"]
    assert disallowed_tokens("GPL-2.0") == ["GPL-2.0"]
    assert disallowed_tokens("GPL-1.0-only") == ["GPL-1.0-ONLY"]
    assert disallowed_tokens("AGPL-3.0-only") == ["AGPL-3.0-ONLY"]
    assert disallowed_tokens("AGPL-3.0-or-later") == ["AGPL-3.0-OR-LATER"]
    assert disallowed_tokens("SSPL-1.0") == ["SSPL-1.0"]


def test_non_commercial_no_derivatives_and_unlicensed_stay_disallowed() -> None:
    for token in ("CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", "UNLICENSED"):
        assert disallowed_tokens(token) == [token], token


def test_gpl_without_a_version_is_unclear_not_allowed() -> None:
    # The ticket's edge case: "GPL" alone could be GPL-2.0-only (refused) or
    # GPL-2.0-or-later (allowed). It is not waved through.
    assert unclear_tokens("GPL") == ["GPL"]
    assert unclear_tokens("gpl") == ["GPL"]
    assert unclear_tokens("GNU GPL") == ["GNU GPL"]
    assert unclear_tokens("GPLv2") == ["GPLV2"]
    assert unclear_tokens("MIT OR GPL") == ["GPL"]
    assert disallowed_tokens("GPL") == []


def test_no_licence_at_all_is_unclear() -> None:
    assert unclear_tokens("") == ["UNVERIFIED"]
    assert unclear_tokens("UNVERIFIED") == ["UNVERIFIED"]
    assert unclear_tokens("UNVERIFIED (raw metadata: 'see LICENSE / COPYING')") == ["UNVERIFIED"]


def test_permissive_and_weak_copyleft_are_neither_disallowed_nor_unclear() -> None:
    for expression in ("MIT", "Apache-2.0", "BSD-3-Clause", "LGPL-3.0-only", "MPL-2.0"):
        assert disallowed_tokens(expression) == [], expression
        assert unclear_tokens(expression) == [], expression


def test_disallowed_tokens_never_flags_lgpl_via_substring() -> None:
    # A naive substring search for "GPL-3.0" inside "LGPL-3.0-or-later" would
    # wrongly flag it. Whole-token matching must not.
    assert disallowed_tokens("LGPL-3.0-or-later") == []
    assert disallowed_tokens("LGPL-3.0-only") == []


def test_disallowed_tokens_matches_within_a_compound_expression() -> None:
    assert disallowed_tokens("MIT AND GPL-2.0-only") == ["GPL-2.0-ONLY"]
    assert disallowed_tokens("Apache-2.0 OR MIT") == []


def test_disallowed_tokens_empty_licence_is_not_itself_disallowed() -> None:
    # Unclear instead — `test_no_licence_at_all_is_unclear`.
    assert disallowed_tokens("") == []
    assert disallowed_tokens("   ") == []


def test_disallowed_licenses_are_spdx_shaped() -> None:
    for token in DISALLOWED_LICENSES:
        assert token == token.upper()
        assert " " not in token


def test_gate_accepts_a_gplv3_dependency(generator: ModuleType) -> None:
    # phonemizer's real licence, the one #619 was about. The rule accepts it;
    # nothing names it.
    deps = [_runtime(generator, "phonemizer", "GPL-3.0-or-later")]
    assert generator.check(deps, []) == []


def test_gate_still_fails_on_a_gpl_2_only_dependency(generator: ModuleType) -> None:
    deps = [_runtime(generator, "fake-gpl2-only", "GPL-2.0-only")]
    problems = generator.check(deps, [])
    assert len(problems) == 1
    assert "fake-gpl2-only" in problems[0]
    assert "disallowed licence GPL-2.0-ONLY" in problems[0]


def test_gate_still_fails_on_an_agpl_dependency(generator: ModuleType) -> None:
    web = [_runtime(generator, "fake-agpl", "AGPL-3.0-or-later")]
    problems = generator.check([], web)
    assert len(problems) == 1
    assert "disallowed licence AGPL-3.0-OR-LATER" in problems[0]


def test_gate_fails_on_a_versionless_gpl_dependency(generator: ModuleType) -> None:
    deps = [_runtime(generator, "fake-bare-gpl", "GPL")]
    problems = generator.check(deps, [])
    assert len(problems) == 1
    assert "unclear licence GPL" in problems[0]


def test_gate_fails_on_a_dependency_with_no_readable_licence(generator: ModuleType) -> None:
    deps = [_runtime(generator, "fake-unverified", "UNVERIFIED")]
    assert len(generator.check(deps, [])) == 1


def test_gate_ignores_dev_only_tooling(generator: ModuleType) -> None:
    dev = generator.DependencyNotice(
        name="fake-dev-gpl2", version="1.0.0", license="GPL-2.0-only", scope="dev-only"
    )
    assert generator.check([dev], []) == []


def test_gate_still_refuses_a_non_commercial_model(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = ModelNotice(
        role="Synthesis",
        name="fake-nc-voice",
        source="example/fake-nc-voice",
        license="CC-BY-NC-4.0",
        verified="2026-09-25",
    )
    monkeypatch.setattr(generator, "MODEL_NOTICES", (*MODEL_NOTICES, fake))
    problems = generator.check([], [])
    assert len(problems) == 1
    assert "fake-nc-voice" in problems[0]
    assert "disallowed licence CC-BY-NC-4.0" in problems[0]


class _FakeDistribution:
    def __init__(self, name: str, classifiers: list[str]) -> None:
        self.metadata = Message()
        self.metadata["Name"] = name
        for classifier in classifiers:
            self.metadata["Classifier"] = classifier


def test_versioned_gpl_classifier_wins_over_the_bare_one(generator: ModuleType) -> None:
    dist = _FakeDistribution(
        "fake-gpl",
        [
            "License :: OSI Approved :: GNU General Public License (GPL)",
            "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        ],
    )
    assert generator._python_license(dist) == "GPL-2.0-or-later"


def test_bare_gpl_classifier_alone_reads_as_unclear(generator: ModuleType) -> None:
    dist = _FakeDistribution(
        "fake-gpl", ["License :: OSI Approved :: GNU General Public License (GPL)"]
    )
    license_expression = generator._python_license(dist)
    assert unclear_tokens(license_expression) == ["GPL"]


def test_askwell_states_gplv3_everywhere_it_declares_a_licence() -> None:
    # The places a tool reads Askwell's own licence from. The prose ones
    # (README, PRD, About screen) are checked by their own reviews.
    license_text = (REPO_ROOT / "LICENSE").read_text()
    assert license_text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in license_text
    pyproject = tomllib.loads((REPO_ROOT / "api" / "pyproject.toml").read_text())
    assert pyproject["project"]["license"] == "GPL-3.0-or-later"
    package = json.loads((REPO_ROOT / "web" / "package.json").read_text())
    assert package["license"] == "GPL-3.0-or-later"
