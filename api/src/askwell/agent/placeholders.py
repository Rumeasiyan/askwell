"""Drop prompt-template placeholders the model copies into its answer.

Three prompts show the model the fixed lines it should write with an
angle-bracket placeholder where the content goes —
`Not covered: <the specific thing that was asked and not found>.`,
`Resolved by memory: <the fact that was in conflict>.`,
`Conflicting sources on <the specific fact being asked about>:`. The shipped
4B model sometimes copies the placeholder instead of filling it in, and until
this existed the Ask screen rendered it as answer content: a "Not covered by
your files" block listing `<the specific thing…>` twice, and "Resolved using
what you told Askwell: <the fact that was in conflict>" on a turn where no
memory fact existed at all — an invented claim about the user's own material
in the one place they look to see why a source won (issue #663, C4).

Stripping happens where `ThinkStripper` strips, at the single point tokens
are consumed, for the same reason: the stored answer, `segment_claims`, the
partial/conflict parsers and the reader all see one text, so no claim ordinal
can drift between server and browser.

What counts as a placeholder is deliberately narrow: `<`, then a determiner
(`the`, `a`, `your`, …) and at least one more word, then `>` — the shape of
every placeholder in `prompts/`, and not the shape of a tag (`<think>`,
`<retrieved-content>`, `<a href="…">`) or a comparison (`x < 5`). It can never
span a `[n]` citation marker, so removing one never removes a citation. A
placeholder the model started and never closed (`<the` at the end of a line,
seen live when generation hit its token budget) is dropped too.
"""

from __future__ import annotations

import re

_DETERMINERS = ("the", "a", "an", "one", "your", "some", "each", "any")
_DET = "(?:" + "|".join(_DETERMINERS) + ")"
# No brackets (a placeholder never swallows a `[n]` marker, C4), no `=` or `"`
# (attributes mean a tag, not a placeholder), no newline (a placeholder is
# always on one line).
_BODY = r"[^<>\[\]=\"\n]"
# The longest placeholder in `prompts/` is under 60 characters; beyond this
# an unclosed `<the …` is ordinary text and is not held back from the reader.
_MAX_BODY = 120

# The optional horizontal whitespace in front goes with it, so
# "is <the fact> 30 days" reads "is 30 days" rather than "is  30 days".
_CLOSED_RE = re.compile(rf"[ \t]*<{_DET}[ \t]{_BODY}{{0,{_MAX_BODY}}}>", re.IGNORECASE)
_UNCLOSED_BEFORE_NEWLINE_RE = re.compile(
    rf"[ \t]*<{_DET}(?:[ \t]{_BODY}{{0,{_MAX_BODY}}})?(?=\n)", re.IGNORECASE
)
_UNCLOSED_AT_END_RE = re.compile(
    rf"[ \t]*<{_DET}(?:[ \t]{_BODY}{{0,{_MAX_BODY}}})?\Z", re.IGNORECASE
)

# What a stream chunk might end partway through: trailing whitespace, a bare
# `<`, part of a determiner, or an unclosed placeholder. Held back until the
# next chunk decides it, the same way `ThinkStripper` holds `<thi`.
_DET_PREFIXES = sorted(
    {det[:n] for det in _DETERMINERS for n in range(1, len(det) + 1)}, key=len, reverse=True
)
_HOLD_RE = re.compile(
    rf"[ \t]*(?:<(?:{_DET}[ \t]{_BODY}{{0,{_MAX_BODY}}}|" + "|".join(_DET_PREFIXES) + r")?)?\Z",
    re.IGNORECASE,
)

# A parsed annotation payload with nothing a reader could use in it — what
# `Not covered: <the …>.` leaves once the placeholder is gone.
_HAS_CONTENT_RE = re.compile(r"[^\W_]")


def strip_placeholders(text: str) -> str:
    """Remove every placeholder from a complete answer, including one left
    unclosed at the very end."""
    text = _CLOSED_RE.sub("", text)
    text = _UNCLOSED_BEFORE_NEWLINE_RE.sub("", text)
    return _UNCLOSED_AT_END_RE.sub("", text)


def has_content(payload: str) -> bool:
    """Whether an annotation line's payload names anything at all."""
    return _HAS_CONTENT_RE.search(payload) is not None


class PlaceholderStripper:
    """Feed it stream chunks, get back the text with placeholders removed.

    Stateful because a placeholder is several tokens long: `Not covered: <`,
    `the specific`, ` thing…>` arrive separately, and none of them alone is
    recognisable.
    """

    __slots__ = ("_buffer",)

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        match = _HOLD_RE.search(self._buffer)
        hold = match.start() if match is not None else len(self._buffer)
        settled, self._buffer = self._buffer[:hold], self._buffer[hold:]
        # Everything settled is decided: any `<` in it is closed, ended by a
        # newline, or too long to be a placeholder.
        text = _CLOSED_RE.sub("", settled)
        return _UNCLOSED_BEFORE_NEWLINE_RE.sub("", text)

    def flush(self) -> str:
        """What is left once the stream ends; an unclosed placeholder is
        dropped rather than shown."""
        out, self._buffer = self._buffer, ""
        return strip_placeholders(out)
