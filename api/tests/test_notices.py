"""`M7-DOC-DOC-163` — the model-licence inventory and its disallow check.

Only the static table and the pure matching function: the full inventory
(every installed Python and pnpm dependency) is real I/O against the built
image and belongs to `scripts/generate_notices.py` and the release gate
(`docs/release-procedure.md`), not the no-network unit suite.
"""

from askwell.notices import DISALLOWED_LICENSES, MODEL_NOTICES, disallowed_tokens


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


def test_disallowed_tokens_matches_plain_gpl_and_agpl() -> None:
    assert disallowed_tokens("GPL-3.0-or-later") == ["GPL-3.0-OR-LATER"]
    assert disallowed_tokens("AGPL-3.0-only") == ["AGPL-3.0-ONLY"]


def test_disallowed_tokens_never_flags_lgpl_via_substring() -> None:
    # A naive substring search for "GPL-3.0" inside "LGPL-3.0-or-later" would
    # wrongly flag it. Whole-token matching must not.
    assert disallowed_tokens("LGPL-3.0-or-later") == []
    assert disallowed_tokens("LGPL-3.0-only") == []


def test_disallowed_tokens_matches_within_a_compound_expression() -> None:
    assert disallowed_tokens("MIT AND GPL-2.0-only") == ["GPL-2.0-ONLY"]
    assert disallowed_tokens("Apache-2.0 OR MIT") == []


def test_disallowed_tokens_empty_licence_is_not_itself_disallowed() -> None:
    assert disallowed_tokens("") == []
    assert disallowed_tokens("   ") == []


def test_disallowed_licenses_are_spdx_shaped() -> None:
    for token in DISALLOWED_LICENSES:
        assert token == token.upper()
        assert " " not in token
