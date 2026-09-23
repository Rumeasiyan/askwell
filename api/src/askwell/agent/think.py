"""Drop a reasoning model's `<think>` block before anything downstream sees it.

The shipped generation model (`Qwen3.5-4B-Q4_K_M.gguf`) wraps its chain of
thought in `<think>…</think>` and only then writes the answer. Until this
existed the raw stream went straight into `turn.text`, which meant the
reasoning was stored as `messages.content`, shown to the reader, and — the
part that actually breaks a guarantee — segmented for citations. The model
rehearses lines like `Not covered: termination notice period.` several times
while drafting, so `split_partial_answer` counted one uncovered aspect three
times, and `[index]` markers inside a draft became claims that were never
asserted. That is a crack in C4, not a cosmetic one (issue #220).

Stripping happens at the single point where tokens are consumed, so claims
segmentation, citation resolution and the stored answer all see the same
text the reader does.

Deliberately conservative about what counts as a think block: output that
does not begin with `<think>` is passed through untouched, so a model that
does not reason this way — or one whose answer merely mentions the word —
is unaffected. The cost of guessing wrong is swallowing a real answer
whole, which is worse than the bug being fixed.
"""

from __future__ import annotations

from enum import Enum

_OPEN = "<think>"
_CLOSE = "</think>"


class _State(Enum):
    DECIDING = "deciding"
    THINKING = "thinking"
    PASSING = "passing"


class ThinkStripper:
    """Feed it stream chunks, get back only what the reader should see.

    Stateful because both tags can be split across two chunks — `</thi` then
    `nk>` is ordinary, and a naive per-chunk `str.replace` never sees it.
    """

    __slots__ = ("_buffer", "_state")

    def __init__(self) -> None:
        self._buffer = ""
        self._state = _State.DECIDING

    @property
    def thinking(self) -> bool:
        """Still inside a block that has not closed."""
        return self._state is _State.THINKING

    def feed(self, text: str) -> str:
        if not text:
            return ""
        if self._state is _State.PASSING:
            return text

        self._buffer += text

        if self._state is _State.DECIDING:
            stripped = self._buffer.lstrip()
            if not stripped:
                # Only whitespace so far; it belongs to whichever branch wins.
                return ""
            if stripped.startswith(_OPEN):
                self._state = _State.THINKING
                self._buffer = stripped[len(_OPEN) :]
            elif _OPEN.startswith(stripped):
                # A prefix of the tag — `<thi` — so the decision is not made
                # yet. Wait rather than emit half a tag we may need to eat.
                return ""
            else:
                self._state = _State.PASSING
                out, self._buffer = self._buffer, ""
                return out

        if self._state is _State.THINKING:
            end = self._buffer.find(_CLOSE)
            if end == -1:
                # Keep only enough to recognise a close tag split across
                # chunks; the reasoning itself is never needed again.
                self._buffer = self._buffer[-(len(_CLOSE) - 1) :]
                return ""
            self._state = _State.PASSING
            out = self._buffer[end + len(_CLOSE) :]
            self._buffer = ""
            return out.lstrip()

        return ""

    def flush(self) -> str:
        """What is left once the stream ends.

        An unclosed block yields nothing: the model spent its whole budget
        reasoning and never wrote an answer, and showing the reasoning
        instead would be presenting a draft as an answer. The caller's own
        empty-answer handling is the honest outcome.
        """
        if self._state is _State.PASSING:
            out, self._buffer = self._buffer, ""
            return out
        if self._state is _State.DECIDING:
            # Never enough text to decide — whatever arrived is the answer.
            out, self._buffer = self._buffer, ""
            self._state = _State.PASSING
            return out
        self._buffer = ""
        return ""
