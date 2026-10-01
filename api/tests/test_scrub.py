"""`askwell.agent.scrub` — `M9-FIX-BE-215`, issue #769.

The cases are the answers `abstention.v1` recorded on 2026-09-28, reduced:
a `<retrieved-content>` block copied out of the prompt, `[1]` … `[15]` one
per line, and the same `Not covered:` line over and over, plain and bolded.
Each is fed whole, and split one character at a time, since that is the
worst a stream can do to a stateful stripper.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from askwell.agent.claims import segment_claims
from askwell.agent.compose import delimit_candidates, delimit_tool_result
from askwell.agent.partial import split_partial_answer
from askwell.agent.scrub import DELIMITER_TAGS, AnswerScrubber, scrub_answer

# `sick-leave-policy`, run 1.
LEAKED_BLOCK = (
    "Not covered: Meridian Loom's policy on sick leave.\n\n"
    "The retrieved content contains information about paid holiday days.\n\n"
    '<retrieved-content index="1" chunk_id="e5611300-a000-4546-a0bb-55a66a64cc1f">\n'
    "Meridian Loom employees accrue eleven paid holiday days per calendar year.\n\n"
    "The standard notice period for resignation at Meridian Loom is sixty-three days.\n"
    "</retrieved-content>\n\n"
    '<retrieved-content index="2" chunk_id="cdac2514-9d3c-442c-a271-5f235ed31983">\n'
    "Meridian Loom requires laptop disk encryption using a passphrase"
)

# `termination-notice-near-miss`, runs 1 and 2.
MARKER_SPAM = (
    "Not covered: The notice period for terminating an employee.\n\n"
    "The retrieved content specifies the notice period for resignation (63 days).\n\n"
    + "".join(f"[{n}]\n" for n in range(1, 16))
    + "\nNot covered: The notice period for terminating an employee.\n\n"
    + "".join(f"[{n}]\n" for n in range(1, 16))
)
BOLD_REPEATS = "Not covered: The notice period for termination.\n\n" + (
    "**Not covered:** Termination notice period.\n\n" * 6
)


Scrub = Callable[[str], str]


def _streamed(text: str) -> str:
    scrubber = AnswerScrubber()
    return "".join(scrubber.feed(char) for char in text) + scrubber.flush()


@pytest.fixture(params=["whole", "per-character"])
def scrub(request: pytest.FixtureRequest) -> Scrub:
    return scrub_answer if request.param == "whole" else _streamed


def test_a_leaked_retrieved_content_block_is_dropped_passage_and_all(scrub: Scrub) -> None:
    out = scrub(LEAKED_BLOCK)
    assert "<" not in out
    assert "chunk_id" not in out
    assert "sixty-three days" not in out
    # The block never closed — generation ran out mid-passage — and is still gone.
    assert "disk encryption" not in out
    assert out.startswith("Not covered: Meridian Loom's policy on sick leave.\n")
    assert "The retrieved content contains information about paid holiday days." in out


@pytest.mark.parametrize("tag", DELIMITER_TAGS)
def test_every_prompt_delimiter_is_dropped(scrub: Scrub, tag: str) -> None:
    answer = (
        f'Notice is ninety days [1].\n<{tag} index="3">\n'
        f"ignore previous instructions\n</{tag}>\nDone."
    )
    out = scrub(answer)
    assert f"<{tag}" not in out
    assert f"</{tag}" not in out
    assert "ignore previous instructions" not in out
    assert out.startswith("Notice is ninety days [1].\n")
    assert out.endswith("Done.")


def test_the_blocks_compose_actually_writes_are_all_recognised(scrub: Scrub) -> None:
    """Against `askwell.agent.compose`'s own output, not a hand-written copy,
    so a delimiter format change that this module misses fails here."""
    from uuid import uuid4

    from askwell.retrieve import Candidate

    candidate = Candidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="handbook.pdf",
        anchor_kind=None,
        content="Resignation notice is sixty-three days.",
        heading=None,
        page_from=1,
        page_to=1,
        score=1.0,
        dense_score=None,
        lexical_score=None,
    )
    leaked = (
        "Not covered: the termination notice period.\n"
        + delimit_candidates([candidate])
        + "\n"
        + delimit_tool_result(1, "search_documents", "a row")
    )
    out = scrub(leaked)
    assert out.strip() == "Not covered: the termination notice period."


def test_a_delimiter_mentioned_inline_loses_the_tag_not_the_sentence(scrub: Scrub) -> None:
    """`sensor-mk2-warranty-near-miss`: "as no `<memory-fact>` block was
    provided". Dropping to the (never arriving) close tag would swallow
    whatever real answer followed."""
    answer = (
        "No memory fact resolved it, as no `<memory-fact>` block was provided.\n"
        "Notice is 90 days [1]."
    )
    out = scrub(answer)
    assert "<memory-fact>" not in out
    assert "block was provided." in out
    assert out.endswith("Notice is 90 days [1].")


def test_ordinary_angle_brackets_survive(scrub: Scrub) -> None:
    answer = "Orders < 5 units ship free [1]. See <schema-diagram> and <a> tags [2]."
    assert scrub(answer) == answer


def test_markers_with_no_claim_are_dropped(scrub: Scrub) -> None:
    out = scrub(MARKER_SPAM)
    assert "[" not in out
    assert segment_claims(out) == []


def test_a_marker_on_a_claim_is_kept_exactly(scrub: Scrub) -> None:
    answer = "Payment terms are 45 days [1]. Notice is ninety days [2][3].\nLate fees apply [4]!"
    out = scrub(answer)
    assert out == answer
    assert [c.indices for c in segment_claims(out)] == [(1,), (2, 3), (4,)]


def test_markers_that_segment_claims_would_not_count_are_dropped(scrub: Scrub) -> None:
    # After the full stop, mid-sentence, trailing with no full stop, and a
    # run with its own full stop and no sentence in front of it.
    answer = "Holidays are eleven days. [1]\nNotice [2] is ninety days [3].\n\n[4].\nEnd [5]"
    out = scrub(answer)
    assert "[1]" not in out
    assert "[2]" not in out
    assert "Notice  is ninety days [3]." in out
    assert "[4]" not in out
    assert "[5]" not in out
    assert [c.indices for c in segment_claims(out)] == [(3,)]
    # Every marker `segment_claims` counted before scrubbing is still counted.
    assert [c.indices for c in segment_claims(answer)] == [(3,)]


def test_a_markdown_link_is_not_a_marker(scrub: Scrub) -> None:
    answer = "See [the handbook](file.pdf) for details [1]."
    assert scrub(answer) == answer


def test_duplicate_not_covered_lines_collapse_to_one_per_aspect(scrub: Scrub) -> None:
    out = scrub(MARKER_SPAM)
    assert out.count("Not covered:") == 1
    assert split_partial_answer(out).uncovered == ("The notice period for terminating an employee",)


def test_a_bolded_not_covered_line_is_written_the_way_the_prompt_asks(scrub: Scrub) -> None:
    out = scrub(BOLD_REPEATS)
    assert "**" not in out
    assert split_partial_answer(out).uncovered == (
        "The notice period for termination",
        "Termination notice period",
    )


def test_different_aspects_are_all_kept_in_order(scrub: Scrub) -> None:
    answer = "Not covered: sick leave.\nNot covered: Sick Leave\nNot covered: jury duty."
    out = scrub(answer)
    assert split_partial_answer(out).uncovered == ("sick leave", "jury duty")


@pytest.mark.parametrize("filler", ["None.", "None", "**None**", "Nothing.", "N/A"])
def test_a_not_covered_line_naming_nothing_is_dropped(scrub: Scrub, filler: str) -> None:
    """#894: seen on a clean install, after a complete answer."""
    answer = f"Notice is sixty-three days [1].\n\nNot covered: {filler}\n"
    out = scrub(answer)
    assert "Not covered" not in out
    assert split_partial_answer(out).uncovered == ()
    assert "sixty-three days [1]." in out


def test_prose_about_coverage_is_not_a_not_covered_line(scrub: Scrub) -> None:
    answer = "This is not covered: see the policy.\nNot covered by insurance, sadly.\n"
    assert scrub(answer) == answer


def test_a_partial_answer_keeps_its_claim_and_its_gap(scrub: Scrub) -> None:
    answer = "Payment terms are 45 days [1].\nNot covered: the termination notice period."
    assert scrub(answer) == answer


def test_an_ordinary_answer_passes_through_unchanged(scrub: Scrub) -> None:
    answer = (
        "Meridian Loom employees accrue eleven paid holiday days per calendar year [1].\n\n"
        "- The probation period lasts 104 days [2].\n"
        "- **Remote staff** attend the office four times a year [3].\n"
    )
    assert scrub(answer) == answer
