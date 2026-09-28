"""`askwell.agent.placeholders` — issue #663, `M9-FIX-BE-202`.

The live failure: the 4B model copied `Not covered: <the specific thing that
was asked and not found>.` and `Resolved by memory: <the fact that was in
conflict>.` out of the prompt, and both rendered as answer content. The
cases below are that output, placeholders split across stream chunks the way
tokens actually arrive, and the things that look similar and must survive:
tags, comparisons, and every `[n]` citation marker (C4).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from askwell.agent.claims import segment_claims
from askwell.agent.conflict import split_conflict_answer
from askwell.agent.partial import split_partial_answer
from askwell.agent.placeholders import PlaceholderStripper, strip_placeholders

PROMPTS = Path(__file__).resolve().parents[1] / "src" / "askwell" / "agent" / "prompts"

# The answer seen on 2026-09-23 against the conflict corpus, reduced.
LIVE_ECHO = (
    "The return window is 30 days [1]. The 2026 policy says 45 days [2].\n\n"
    "Not covered: <the specific thing that was asked and not found>.\n"
    "Not covered: <the specific thing that was asked and not found>.\n"
    "Not covered: <the\n"
    "Resolved by memory: <the fact that was in conflict>."
)


def _stream(chunks: list[str]) -> str:
    stripper = PlaceholderStripper()
    return "".join(stripper.feed(c) for c in chunks) + stripper.flush()


def _tokens(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def test_the_live_echo_leaves_no_placeholder_behind() -> None:
    assert "<" not in strip_placeholders(LIVE_ECHO)


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 13, 1000])
def test_streaming_matches_the_whole_text_at_every_chunk_size(size: int) -> None:
    assert _stream(_tokens(LIVE_ECHO, size)) == strip_placeholders(LIVE_ECHO)


def test_an_echoed_not_covered_line_is_not_an_uncovered_aspect() -> None:
    assert split_partial_answer(strip_placeholders(LIVE_ECHO)).uncovered == ()


def test_an_echoed_resolution_line_claims_no_memory_fact() -> None:
    assert split_conflict_answer(strip_placeholders(LIVE_ECHO)).resolved_by_memory is None


def test_a_real_not_covered_line_is_still_read() -> None:
    text = "Hours are 9 to 5 [1].\n\nNot covered: <the fee>.\nNot covered: the 2026 express fee."
    assert split_partial_answer(strip_placeholders(text)).uncovered == ("the 2026 express fee",)


def test_a_real_resolution_line_is_still_read() -> None:
    text = "It is 45 days [2].\n\nResolved by memory: the 2026 policy is current."
    assert split_conflict_answer(strip_placeholders(text)).resolved_by_memory == (
        "the 2026 policy is current"
    )


def test_an_echoed_conflict_topic_still_reads_as_a_conflict_with_no_topic() -> None:
    text = (
        "Conflicting sources on <the specific fact being asked about>:\n\n"
        "One says 30 days [1]. The other says 45 days [2]."
    )
    conflict = split_conflict_answer(strip_placeholders(text))
    assert conflict.is_conflict
    assert conflict.topic == ""


def test_a_template_inside_a_real_sentence_removes_only_the_template() -> None:
    text = "The window is <the fact that was in conflict> 30 days [1]."
    assert strip_placeholders(text) == "The window is 30 days [1]."


def test_no_citation_marker_is_ever_removed() -> None:
    text = "A is 1 <the thing [1]> [2]. B is <your answer> 2 [3][4]."
    stripped = strip_placeholders(text)
    for marker in ("[1]", "[2]", "[3]", "[4]"):
        assert marker in stripped


def test_claims_and_their_indices_survive_stripping() -> None:
    text = "A is 1 [1]. B is <the fact that was in conflict> 2 [2]. C is 3 [3]."
    before = [c.indices for c in segment_claims(text)]
    after = [c.indices for c in segment_claims(strip_placeholders(text))]
    assert after == before


@pytest.mark.parametrize(
    "text",
    [
        "<think>",
        '<retrieved-content index="1">',
        '<a href="x">link</a>',
        "if x < 5 and y > 3 then",
        "a<b and c>d",
        "The <theory of change> section",
        "Use <b>bold</b> sparingly.",
        "A <thesis> is due.",
    ],
)
def test_things_that_are_not_placeholders_are_untouched(text: str) -> None:
    assert strip_placeholders(text) == text
    assert _stream(_tokens(text, 1)) == text


def test_every_placeholder_in_the_prompts_is_recognised() -> None:
    # A new prompt placeholder in a shape this module does not know would
    # silently start leaking again; this is the tripwire. `=` marks a tag
    # with attributes (`<schema engine="...">`), which is not a placeholder.
    found = {
        m
        for path in PROMPTS.glob("*.md")
        for m in re.findall(r"<[a-z][a-z]* [^<>=\n]*>", path.read_text(encoding="utf-8"))
    }
    assert found, "expected at least the Not covered placeholder"
    for placeholder in found:
        assert strip_placeholders(f"x {placeholder} y") == "x y", placeholder


def test_an_unclosed_placeholder_at_the_end_of_the_stream_is_dropped() -> None:
    assert _stream(["Not covered: <", "the spec", "ific"]) == "Not covered:"


def test_ordinary_text_is_not_held_back_once_it_is_decided() -> None:
    stripper = PlaceholderStripper()
    assert stripper.feed("Hours are 9 to 5 [1].") == "Hours are 9 to 5 [1]."
