"""Claim segmentation: splitting a streamed answer into factual claims and
locating the source text each one rests on. `M1-CITE-BE-042`.

The model is asked (`prompts/answer_composition.v1.md`) to place one or more
`[index]` markers immediately before the sentence-ending punctuation of every
factual sentence, and to leave a sentence that is not a factual claim — a
restatement of the question, a transition — unmarked. `segment_claims` reads
that convention back out of the growing answer text: a sentence with no
marker is not a claim at all, never an uncited one, matching the ticket's own
edge case. This is prompt-driven and imperfect by construction — the eval
suite that measures its miss/over-flag rate is `M2`, and the counter-metric
that would catch a regression here is `M1-CITE-TEST-045`.

`segment_claims` is pure and re-run against the whole answer text seen so
far, rather than tracking a stream cursor itself. Only complete sentences
(ending in `.`, `!` or `?`) match, so calling it again after more tokens have
arrived naturally reveals only newly completed claims — the caller compares
against how many it has already emitted (`ask.py`), the same "recompute
against a growing prefix" approach `askwell.ask._tail` already uses for
events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A claim is a sentence, and its citation markers sit immediately before the
# terminating punctuation: "...forty-five days [1][2]." not "...days. [1][2]"
# — established by `test_a_question_streams_steps_then_tokens_then_a_citation_then_done`
# before this ticket and kept rather than moved, since moving it would change
# the wire format for no benefit.
_CLAIM_RE = re.compile(r"(?P<body>[^.!?]*?)(?P<markers>(?:\s*\[\d+\])+)?[.!?]")
_MARKER_RE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True, slots=True)
class Claim:
    """One factual sentence and the candidate indices it cites."""

    ordinal: int  # 1-based, counts only claims that carry a marker
    text: str  # the sentence, markers and terminating punctuation stripped
    indices: tuple[int, ...]  # de-duplicated, in the order they appeared


def segment_claims(text: str) -> list[Claim]:
    """Every complete, marked sentence in `text`, in order.

    A sentence with no marker is skipped entirely — it is not a claim, so it
    is never counted and never produces a citation. A marker referencing an
    index that turns out not to exist among the candidates is the caller's
    concern (`ask.py` already only resolves indices in range); this function
    does not know how many candidates there were.
    """
    claims: list[Claim] = []
    ordinal = 0
    for match in _CLAIM_RE.finditer(text):
        body = match.group("body").strip()
        markers = match.group("markers")
        if not body or not markers:
            continue
        indices = tuple(dict.fromkeys(int(i) for i in _MARKER_RE.findall(markers)))
        if not indices:
            continue
        ordinal += 1
        claims.append(Claim(ordinal=ordinal, text=body, indices=indices))
    return claims


def locate_quoted_span(claim_text: str, chunk_content: str) -> str | None:
    """The exact substring of `chunk_content` the claim's own words came
    from, if it is there verbatim (case-insensitive). `None` — never a
    dropped citation — when it is not: the edge case is the citation
    resolving to the chunk without a span, not resolving to nothing.
    """
    claim_text = claim_text.strip()
    if not claim_text:
        return None
    index = chunk_content.lower().find(claim_text.lower())
    if index == -1:
        return None
    return chunk_content[index : index + len(claim_text)]
