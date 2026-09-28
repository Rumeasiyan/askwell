"""Remove what leaks from the prompt into an answer. `M9-FIX-BE-215`, #769.

The first run of `abstention.v1` (2026-09-28) found three leaks in the
shipped 4B model's answers:

- **Prompt delimiters.** A `<retrieved-content index="1" chunk_id="…">`
  block copied out of the prompt, passage text and all. That is C7's boundary
  shown to the user as if it were the answer.
- **Repeated `Not covered:` lines.** The same aspect named four, ten, twenty
  times, sometimes bolded (`**Not covered:** …`) rather than written the way
  the prompt asks.
- **Citation markers with no claim.** `[1]` … `[15]`, one per line, after a
  sentence that cites nothing. The reader renders a marker outside a claim
  as literal text (`web/lib/claims.ts`).

`AnswerScrubber` removes all three at the one point tokens are consumed,
beside `ThinkStripper` and `PlaceholderStripper`, and for the same reason:
the stored answer, `segment_claims`, the partial parser and the reader all
see one text, so claim ordinals cannot drift between server and browser.
`scrub_answer` runs the same streamers over a complete text, for the paths
that do not stream (the tool loop).

**Delimiters.** A block is an opening tag at the start of a line that ends
the line — the only way `askwell.agent.compose` ever writes one. Everything
from there to its closing tag is dropped, or to the end of the answer if it
never closes (generation hit its budget mid-block). A tag anywhere else —
the model writing "no `<memory-fact>` block was provided" — loses the tag
and keeps the sentence: dropping everything after an inline mention would
swallow the rest of a real answer.

**Markers.** A marker is kept only where `askwell.agent.claims` would count
it: immediately before a sentence's terminating punctuation, in a sentence
with text of its own. The rule mirrors `_CLAIM_RE` rather than inventing a
second one, so a kept marker is always a citation and a dropped one never
was.

**`Not covered` lines.** Written back in the form the prompt asks for,
`Not covered: <aspect>.`, and each aspect kept once. Only the line's own
form is matched, never prose that mentions coverage.
"""

from __future__ import annotations

import re

# Every delimiter a prompt in `prompts/` wraps untrusted or scaffolding text
# in (`askwell.agent.compose`, `askwell.agent.conflict`,
# `askwell.agent.sql_generate`). Longest first, so `schema-notes` is tried
# before `schema` and `memory-facts` before `memory-fact`.
DELIMITER_TAGS = (
    "retrieved-content",
    "memory-facts",
    "schema-notes",
    "memory-fact",
    "tool-result",
    "web-content",
    "schema",
)

# An opening or closing delimiter tag, complete. The name must be followed by
# whitespace, `>` or `/`, so `<schema` never matches `<schema-notes` and
# `<memory-fact` never matches `<memory-facts`.
_TAG_RE = re.compile(
    r"<(?P<close>/)?(?P<name>" + "|".join(DELIMITER_TAGS) + r")(?=[\s/>])[^<>\n]*>"
)
# The candidates a held `<…` might still grow into.
_TAG_OPENERS = tuple(f"<{name}" for name in DELIMITER_TAGS) + tuple(
    f"</{name}" for name in DELIMITER_TAGS
)
# Beyond this an unterminated `<retrieved-content …` is not a tag the prompt
# wrote (the longest, with a UUID attribute, is under 100 characters).
_MAX_TAG = 300


class _DelimiterStripper:
    __slots__ = ("_block", "_buffer", "_line_start")

    def __init__(self) -> None:
        self._buffer = ""
        self._block: str | None = None  # the tag whose content is being dropped
        self._line_start = True

    def _emit(self, text: str) -> str:
        if text:
            self._line_start = text.endswith("\n")
        return text

    def feed(self, text: str, *, final: bool = False) -> str:
        self._buffer += text
        out: list[str] = []
        while self._buffer:
            if self._block is not None:
                close = f"</{self._block}>"
                end = self._buffer.find(close)
                if end == -1:
                    # Keep only enough to recognise a close tag split across chunks.
                    self._buffer = "" if final else self._buffer[-(len(close) - 1) :]
                    break
                self._buffer = self._buffer[end + len(close) :]
                self._block = None
                continue

            start = self._buffer.find("<")
            if start == -1:
                out.append(self._emit(self._buffer))
                self._buffer = ""
                break
            if start:
                out.append(self._emit(self._buffer[:start]))
                self._buffer = self._buffer[start:]

            match = _TAG_RE.match(self._buffer)
            if match is None:
                pending = len(self._buffer) < _MAX_TAG and "\n" not in self._buffer
                could_be = any(
                    opener.startswith(self._buffer)
                    or (
                        self._buffer.startswith(opener)
                        and self._buffer[len(opener) : len(opener) + 1] in ("", " ", "\t", "/", ">")
                    )
                    for opener in _TAG_OPENERS
                )
                if could_be and pending and not final:
                    break  # a tag may still be arriving
                out.append(self._emit("<"))
                self._buffer = self._buffer[1:]
                continue

            rest = self._buffer[match.end() :]
            opens_block = match.group("close") is None and self._line_start
            if opens_block and not rest and not final:
                break  # whether the tag ends its line decides what it is
            self._buffer = rest
            if opens_block and rest.startswith("\n"):
                self._block = match.group("name")
                self._buffer = rest[1:]
            elif opens_block and not rest:
                # The answer ended on an opening tag: nothing followed it.
                self._block = match.group("name")
            # Otherwise a tag mentioned inline, or a stray closing tag: the tag
            # goes, the sentence around it stays.
        return "".join(out)

    def flush(self) -> str:
        out = self.feed("", final=True)
        self._buffer = ""
        return out


# The prompts' own convention (`prompts/partial_answer.v1.md`), plus the
# bolded variants the model writes instead: `**Not covered:** x`,
# `**Not covered: x**`, `**Not covered**: x`.
_UNCOVERED_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:\*\*)?Not covered(?:\*\*)?:(?:\*\*)?\s*(?P<aspect>.*?)\s*$"
)
_UNCOVERED_OPENERS = ("Not covered:", "**Not covered:**", "**Not covered**:", "**Not covered:")


def _aspect_key(aspect: str) -> str:
    return aspect.strip().strip("*").strip().rstrip(".").strip().casefold()


class _UncoveredLineFilter:
    __slots__ = ("_buffer", "_holding", "_line_start", "_seen")

    def __init__(self) -> None:
        self._buffer = ""
        self._line_start = True
        self._holding = False  # the current line is a `Not covered` line
        self._seen: set[str] = set()

    def _settle(self, line: str, newline: str) -> str:
        match = _UNCOVERED_LINE_RE.match(line)
        if match is None:
            return line + newline
        aspect = match.group("aspect").strip().strip("*").strip()
        key = _aspect_key(aspect)
        if key and key in self._seen:
            return ""
        if key:
            self._seen.add(key)
        body = aspect if aspect.endswith((".", "!", "?")) or not aspect else f"{aspect}."
        return f"{match.group('indent')}Not covered: {body}".rstrip() + newline

    def feed(self, text: str, *, final: bool = False) -> str:
        self._buffer += text
        out: list[str] = []
        while self._buffer:
            if self._holding:
                end = self._buffer.find("\n")
                if end == -1:
                    if final:
                        out.append(self._settle(self._buffer, ""))
                        self._buffer = ""
                    break
                out.append(self._settle(self._buffer[:end], "\n"))
                self._buffer = self._buffer[end + 1 :]
                self._holding = False
                self._line_start = True
                continue

            if self._line_start:
                stripped = self._buffer.lstrip(" \t")
                if any(stripped.startswith(opener) for opener in _UNCOVERED_OPENERS):
                    self._holding = True
                    continue
                undecided = any(opener.startswith(stripped) for opener in _UNCOVERED_OPENERS)
                if undecided and "\n" not in stripped and not final:
                    break
                self._line_start = False

            end = self._buffer.find("\n")
            if end == -1:
                out.append(self._buffer)
                self._buffer = ""
                break
            out.append(self._buffer[: end + 1])
            self._buffer = self._buffer[end + 1 :]
            self._line_start = True
        return "".join(out)

    def flush(self) -> str:
        out = self.feed("", final=True)
        self._buffer = ""
        return out


# A run of markers as `_CLAIM_RE` reads one: `[1]`, `[1][2]`, `[1] [2]`.
_RUN_RE = re.compile(r"\[\d+\](?:\s*\[\d+\])*")
# What a held run might still grow into.
_HOLD_RUN_RE = re.compile(r"\[\d*|\[\d+\](?:\s*\[\d+\])*\s*(?:\[\d*)?")
_TERMINATORS = ".!?"
_MAX_RUN = 200


class _MarkerStripper:
    __slots__ = ("_buffer", "_has_text")

    def __init__(self) -> None:
        self._buffer = ""
        # Whether the sentence under way has any text of its own yet — the
        # non-empty `body` `segment_claims` requires of a claim.
        self._has_text = False

    def _pass(self, text: str) -> str:
        for char in text:
            if char in _TERMINATORS:
                self._has_text = False
            elif not char.isspace():
                self._has_text = True
        return text

    def feed(self, text: str, *, final: bool = False) -> str:
        self._buffer += text
        out: list[str] = []
        while self._buffer:
            start = self._buffer.find("[")
            if start == -1:
                out.append(self._pass(self._buffer))
                self._buffer = ""
                break
            if start:
                out.append(self._pass(self._buffer[:start]))
                self._buffer = self._buffer[start:]

            if (
                not final
                and len(self._buffer) < _MAX_RUN
                and _HOLD_RUN_RE.fullmatch(self._buffer) is not None
            ):
                break  # the run, or what follows it, is still arriving

            run = _RUN_RE.match(self._buffer)
            if run is None:
                out.append(self._pass("["))
                self._buffer = self._buffer[1:]
                continue
            after = self._buffer[run.end() : run.end() + 1]
            if after and after in _TERMINATORS and self._has_text:
                out.append(self._pass(run.group()))
                self._buffer = self._buffer[run.end() :]
            elif after and after in _TERMINATORS:
                # A run and its full stop with no sentence in front of them:
                # both go, rather than leaving a lone `.` on its own line.
                self._buffer = self._buffer[run.end() + 1 :]
            else:
                self._buffer = self._buffer[run.end() :]
        return "".join(out)

    def flush(self) -> str:
        out = self.feed("", final=True)
        self._buffer = ""
        return out


class AnswerScrubber:
    """Feed it stream chunks, get back the answer without the prompt's leaks.

    Stateful for the same reason as `PlaceholderStripper`: a delimiter, a
    `Not covered` line and a marker run all arrive over several chunks.
    """

    __slots__ = ("_delimiters", "_markers", "_uncovered")

    def __init__(self) -> None:
        self._delimiters = _DelimiterStripper()
        self._uncovered = _UncoveredLineFilter()
        self._markers = _MarkerStripper()

    def feed(self, text: str) -> str:
        if not text:
            return ""
        return self._markers.feed(self._uncovered.feed(self._delimiters.feed(text)))

    def flush(self) -> str:
        """What is left once the stream ends. An unclosed block, an
        unfinished `Not covered` line's duplicate and a trailing marker run
        are all decided here."""
        text = self._uncovered.feed(self._delimiters.flush())
        text = self._markers.feed(text + self._uncovered.flush())
        return text + self._markers.flush()


def scrub_answer(text: str) -> str:
    """`AnswerScrubber` over a complete answer."""
    scrubber = AnswerScrubber()
    return scrubber.feed(text) + scrubber.flush()
