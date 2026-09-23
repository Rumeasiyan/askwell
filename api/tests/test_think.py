"""`ThinkStripper` — issue #220.

The cases that matter are the ones a naive `str.replace` on each chunk gets
wrong: a tag split across two chunks, and output that never opens a block at
all (where swallowing everything would be far worse than the bug).
"""

from __future__ import annotations

from askwell.agent.think import ThinkStripper


def _run(chunks: list[str]) -> str:
    s = ThinkStripper()
    return "".join(s.feed(c) for c in chunks) + s.flush()


def test_a_think_block_in_one_chunk_is_dropped() -> None:
    assert _run(["<think>drafting</think>The hours are 9 to 5 [1]."]) == "The hours are 9 to 5 [1]."


def test_output_with_no_think_block_is_untouched() -> None:
    assert _run(["The hours are 9 to 5 [1]."]) == "The hours are 9 to 5 [1]."


def test_an_opening_tag_split_across_chunks_is_still_recognised() -> None:
    assert _run(["<thi", "nk>drafting</think>Answer."]) == "Answer."


def test_a_closing_tag_split_across_chunks_is_still_recognised() -> None:
    assert _run(["<think>drafting</thi", "nk>Answer."]) == "Answer."


def test_a_closing_tag_split_across_three_chunks_is_still_recognised() -> None:
    assert _run(["<think>drafting<", "/think", ">Answer."]) == "Answer."


def test_a_rehearsed_line_inside_the_block_never_reaches_the_answer() -> None:
    # The live failure in #220: the model wrote this line three times while
    # drafting and once for real, and all four were counted.
    raw = (
        "<think>Not covered: termination notice period. "
        "Not covered: termination notice period.</think>"
        "The term is three years [1].\nNot covered: termination notice period."
    )
    out = _run([raw])
    assert out.count("Not covered: termination notice period.") == 1


def test_an_unclosed_block_yields_nothing_rather_than_a_draft() -> None:
    s = ThinkStripper()
    assert s.feed("<think>still reasoning and out of budget") == ""
    assert s.thinking is True
    assert s.flush() == ""


def test_leading_whitespace_before_the_tag_is_handled() -> None:
    assert _run(["\n\n<think>x</think>Answer."]) == "Answer."


def test_text_merely_mentioning_the_word_think_is_passed_through() -> None:
    assert _run(["I think the answer is 9 to 5 [1]."]) == "I think the answer is 9 to 5 [1]."


def test_a_late_think_tag_is_not_treated_as_a_block() -> None:
    # Only a block the output *opens with* is reasoning. A tag appearing
    # mid-answer is content, and eating the rest of the answer would be the
    # worse failure.
    assert _run(["Answer. <think>x</think> more."]) == "Answer. <think>x</think> more."


def test_chunks_after_the_block_stream_through_one_at_a_time() -> None:
    s = ThinkStripper()
    assert s.feed("<think>x</think>The hours") == "The hours"
    assert s.feed(" are 9 to 5") == " are 9 to 5"
    assert s.feed(" [1].") == " [1]."
    assert s.flush() == ""
