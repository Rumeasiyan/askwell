"""Ambiguity detection: the three tests before Askwell asks a question.

`docs/memory-and-clarification.md` §1. A candidate is raised only when all
three hold: Askwell genuinely cannot determine the answer, the answer
materially changes future results, and the user plausibly knows it. Anything
that fails one of the three is inferred instead — when there is a defensible
guess to make — and recorded as a low-confidence fact rather than surfaced as
a question. When there is nothing safe to guess (an abbreviation's actual
meaning, which side of a real contradiction is right), nothing is recorded:
inventing an answer there is exactly the failure C5 exists to prevent, and a
memory fact is retrieved and injected into prompts the same way a document
chunk is (`docs/memory-and-clarification.md` §5) — a wrong one is not inert.

Four triggers, ticket's own scope: abbreviations, unreadable scans,
ambiguous document identity, contradictions between sources. Column and date
triggers arrive with M4's data sources and reuse this same filter.

Detection is heuristic, not a model call — `M3-RAISE-BE-068`'s own
Assumption says trigger detection must be cheap enough not to slow ingestion
materially, and it runs once per source (`askwell.clarify.raise_candidates`,
called from `askwell.ingest.refresh_source` once a source has nothing left
outstanding) rather than per document, so a large import is scanned once
rather than once per file landing. It will both miss real ambiguity and
raise on things that turn out to be fine — the cap and the dismissal signal
(`M3-RAISE-BE-069`) are the designed safeguard, not this module.

`M3-RAISE-BE-071`: every raised candidate's `evidence` is real data pulled
from the source at raise time, never a paraphrase — a passage with its
document and page, a contradiction's two passages with their dates, or a
poor scan's extracted text. `raise_candidates` merges `candidate.inferred_fact`
into that dict as `current_inference` for every kind, so a raised question
also carries what Askwell would have guessed had it not been material enough
to ask. `column_distribution_evidence` is the one exception: no trigger in
this module raises a column question yet (that is M4's own data source), so
it exists only as the shared shape M4 needs to fill in with a query.

`M7-FIX-BE-172`: a term-definition candidate must clear a floor before it
is queued — see `_detect_abbreviations`. Against the fixture corpus the only
question used to be what "PM" means, cited from two lines that say "8 PM"
and "9 PM", while the closing-time conflict between those same two lines
went unasked because no fact pattern here could see it (`_TIME_FACT_PATTERN`).
"""

import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto, passphrase
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

CANDIDATE_RAISED = "clarification_raised"
CANDIDATE_DROPPED = "clarification_dropped"
CANDIDATE_CAPPED = "clarification_capped"
CANDIDATE_SUPPRESSED = "clarification_suppressed"
CAP_CHANGED = "clarification_cap_changed"

# `docs/memory-and-clarification.md` §8: "cap of 5 questions per source,
# user-adjustable". Stored under this key in the generic `settings` table
# rather than `Settings` (`config.py`) because it is a per-install user
# preference changed at runtime, not a deployment-time value.
CLARIFICATION_CAP_KEY = "clarification_cap"
DEFAULT_CLARIFICATION_CAP = 5

# A guess this uncertain is exactly what `origin = 'inferred'` exists to mark
# — visible, correctable, never confused with something the user actually
# said (`docs/memory-and-clarification.md` §3).
LOW_CONFIDENCE = 0.3

# All-caps tokens that are common general knowledge rather than something
# only this user's material could explain. Short and deliberately so — an
# over-eager stoplist silently launders a real domain abbreviation into
# "already known", and that is the more expensive mistake of the two: a
# skipped question moves no one, and a good stoplist entry can always be
# added when it is caught.
_COMMON_ABBREVIATIONS = frozenset(
    {"PDF", "HTML", "HTTP", "HTTPS", "URL", "USA", "UK", "OK", "ID", "FAQ", "TV", "CEO", "USD"}
)
_ABBREVIATION = re.compile(r"\b[A-Z]{2,6}\b")
# Counted over *unresolved* occurrences only (`M7-FIX-BE-172`): two uses the
# surrounding text already explains do not make a term worth a question.
_MIN_ABBREVIATION_OCCURRENCES = 2

# `M7-FIX-BE-172`'s floor, first half: a common-English reading the passage
# itself proves. "PM" right after a clock time is a time of day, and asking
# what it means spends the user's attention on something a competent tool
# should already know. Keyed per token rather than a stoplist on purpose — the
# same "PM" with no clock time in front of it ("the PM signs off") is a domain
# term in context and still asked; a stoplist would silence both.
_CONTEXT_READINGS: dict[str, re.Pattern[str]] = {
    "AM": re.compile(r"\b\d{1,2}(?::\d{2})?\s+AM\b"),
    "PM": re.compile(r"\b\d{1,2}(?::\d{2})?\s+PM\b"),
}
# `\s+`, not `\s*`: "8PM" is never counted as a use by `_ABBREVIATION` (no
# word boundary between "8" and "P"), so counting it as a resolved one would
# cancel out a genuine jargon "PM" elsewhere in the same passage.
# Second half: the source defines the term itself — "Request for Quotation
# (RFQ)", "RFQ (Request for Quotation)", "RFQ stands for ...". The expansion
# is found by initials, not a dictionary, so it only counts as a definition
# when the words next to the term actually spell it.
_DEFINITION_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")

# `<subject> is|are|shall be|must be|will be <number> <unit>` — a narrow net,
# deliberately: it is aimed at the kind of sentence the worked example in
# `docs/memory-and-clarification.md` §1 gives ("the 2024 handbook says 30
# days, the 2025 policy says 45"), not at prose contradiction in general,
# which needs reading for meaning and is exactly what `askwell.agent.conflict`
# already does at answer time over retrieved passages.
_FACT_PATTERN = re.compile(
    r"\b([a-z][a-z ]{5,40}?)\s+(?:is|are|shall be|must be|will be)\s+(\d{1,5})\s*([a-z%$]*)",
    re.IGNORECASE,
)
# `<subject> at|by|until <clock time> AM|PM` — `M7-FIX-BE-172`. A closing
# time is exactly the kind of fact two sources disagree on and only the user
# can settle, and `_FACT_PATTERN`'s `is <number>` shape never sees it ("stores
# close at 8 PM"). Same narrow net, same subject rules.
_TIME_FACT_PATTERN = re.compile(
    r"\b([a-z][a-z ]{5,40}?)\s+(?:at|by|until)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)\b",
    re.IGNORECASE,
)
_MIN_SUBJECT_WORDS = 2
_STOPWORDS = frozenset({"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "it"})

# Strips version-ish tokens from a filename stem so `contract-v1`,
# `contract-v2-FINAL` and `contract (copy)` all normalise to `contract`.
# `(2)` sits outside the `\b...\b` group deliberately. A word boundary needs a
# word character on one side, and in `contract (2)` the character before the
# bracket is a space — so inside the group that alternative could never match,
# and `contract (2).docx` normalised to `contract (2)` while every other form
# normalised to `contract`. Two copies of one document then read as two
# different documents, which is the thing this function exists to prevent.
_VERSION_TOKEN = re.compile(
    r"[\s_.\-]*(?:\b(?:v\d+|version ?\d*|final|draft|copy|rev ?\d*)\b|\(\d+\))[\s_.\-]*",
    re.IGNORECASE,
)

# Below this fraction of a flagged document's pages, a poor scan is not
# material enough to interrupt the user — "index as-is" is the sensible
# default `docs/memory-and-clarification.md` §1 says a preference with one
# does not need asking about, and it is exactly what happens anyway.
_MIN_SCAN_MATERIALITY_FRACTION = 0.05

# --- evidence: real data, bounded, so a clarification record stays small ----

EVIDENCE_KIND_PASSAGE = "passage"
EVIDENCE_KIND_CONTRADICTION = "contradiction"
EVIDENCE_KIND_POOR_SCAN = "poor_scan"
EVIDENCE_KIND_COLUMN_DISTRIBUTION = "column_distribution"
EVIDENCE_KIND_UNAVAILABLE = "unavailable"

# A passage this long already makes the point; the rest is what "open the
# source" (`docs/ux/clarifications.md` §3) is for, not more inline text.
EVIDENCE_PASSAGE_MAX_CHARS = 500
# How many sample locations one abbreviation or poor-scan question carries —
# enough to be convincing, not the whole document.
EVIDENCE_MAX_SAMPLES = 2
# `docs/backlog/M3-it-learns-my-material.md`'s own edge case: a column with
# thousands of distinct values shows the top ones plus a remainder count,
# never everything.
EVIDENCE_MAX_COLUMN_VALUES = 10


def _bound_text(value: str, max_chars: int = EVIDENCE_PASSAGE_MAX_CHARS) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _unavailable_evidence(reason: str) -> dict[str, Any]:
    """The edge case named by the ticket: evidence that cannot be captured
    still raises the question, with this in place of a paraphrase."""
    return {"kind": EVIDENCE_KIND_UNAVAILABLE, "reason": reason}


def column_distribution_evidence(values: list[tuple[str, int]], row_count: int) -> dict[str, Any]:
    """The shape a `M4` column-ambiguity trigger will produce — no trigger in
    this module calls it yet, since no data source exposes a column here
    before `M4`. `values` is `(value, count)` for a column's distinct values;
    only the top `EVIDENCE_MAX_COLUMN_VALUES` are kept, with the rest folded
    into `remainder_count` rather than stored in full.
    """
    top = sorted(values, key=lambda item: item[1], reverse=True)[:EVIDENCE_MAX_COLUMN_VALUES]
    remainder = row_count - sum(count for _value, count in top)
    return {
        "kind": EVIDENCE_KIND_COLUMN_DISTRIBUTION,
        "row_count": row_count,
        "values": [{"value": value, "count": count} for value, count in top],
        "remainder_count": max(remainder, 0),
    }


@dataclass(frozen=True, slots=True)
class Candidate:
    """One thing a trigger noticed, before the three tests decide its fate."""

    trigger: str
    subject: str
    question: str
    passes: bool
    reason: str
    options: list[str] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    # What to remember if this is not asked. `None` means there is nothing
    # safe to guess — the candidate is simply dropped, not inferred.
    inferred_fact: str | None = None
    inferred_confidence: float = LOW_CONFIDENCE


@dataclass(frozen=True, slots=True)
class RaiseResult:
    raised: int
    inferred: int
    dropped: int
    # Of `inferred`, how many were not asked solely because the source
    # produced more passing candidates than the cap — as opposed to failing
    # one of the three tests. `docs/ux/clarifications.md` §5's capped state
    # needs this number to say what it inferred rather than asked.
    capped: int = 0
    # Never became a candidate for a question at all — a current fact for
    # the same subject already existed in `memory` or `schema_notes`, from
    # this source or an earlier one. `M3-RAISE-BE-070`'s own Analytics Event:
    # a local counter, never transmitted (C1).
    suppressed: int = 0


# Ranking order, `docs/memory-and-clarification.md` §8: contradictions first,
# then date-format ambiguity, then unguessable columns, then abbreviations,
# then low-confidence scans. `date_format` is `M4-CSV-ING-093`'s own trigger
# and now occupies its documented slot, second only to contradictions.
# Column triggers (`table_column`) are M4's own too but not yet placed here —
# `M4-CSV-ING-092` raised them without a priority entry, so they fall to the
# default (below `unreadable_scan`) until that gap is closed.
# `document_identity` is `M3-RAISE-BE-069`'s own trigger and is not named in
# the canonical list at all — it is ranked just below date-format, ahead of
# abbreviations: an unresolved "which file is current" question has the same
# shape of consequence as a contradiction (the wrong document's facts get
# treated as current) rather than the shape of a vocabulary gap.
# `docs/decisions.md` has the reasoning.
_TRIGGER_PRIORITY = {
    "contradiction": 0,
    "date_format": 1,
    "document_identity": 2,
    "abbreviation": 3,
    "unreadable_scan": 4,
}


def _rank_weight(candidate: Candidate) -> float:
    """Volume behind a candidate, used to order within its own tier.

    Abbreviations rank "by corpus frequency" — occurrence count. Scans rank
    "weighted by document size" — page count. Contradictions and document
    identity have no documented weighting rule; the count of documents
    involved is the closest available proxy to "how much is at stake".
    """
    if candidate.trigger == "abbreviation":
        return float(candidate.evidence.get("occurrences", 0))
    if candidate.trigger == "unreadable_scan":
        return float(candidate.evidence.get("total_pages", 0))
    if candidate.trigger == "document_identity":
        return float(len(candidate.options or []))
    if candidate.trigger == "contradiction":
        return float(len(candidate.evidence.get("passages", [])))
    if candidate.trigger == "date_format":
        return float(candidate.evidence.get("row_count", 0))
    return 0.0


def _rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Highest priority first. Deterministic: two runs over the same source
    produce the same order, since the sort key is built only from stored,
    reproducible data (trigger, evidence counts, subject) — never from
    insertion order or anything that varies run to run."""
    return sorted(
        candidates,
        key=lambda c: (
            _TRIGGER_PRIORITY.get(c.trigger, len(_TRIGGER_PRIORITY)),
            -_rank_weight(c),
            c.subject,
        ),
    )


async def get_clarification_cap(session: AsyncSession) -> int:
    value = await get_setting(session, CLARIFICATION_CAP_KEY)
    return DEFAULT_CLARIFICATION_CAP if value is None else int(value)


async def set_clarification_cap(session: AsyncSession, cap: int) -> None:
    """The only way the cap is changed. `docs/build-plan.md` M3-RAISE-BE-069's
    own Validation Rule: "never raised silently" — so every change, in either
    direction, is a decision record, not just a settings write."""
    if cap < 1:
        raise ValueError("clarification cap must be at least 1")
    previous = await get_clarification_cap(session)
    await set_setting(session, CLARIFICATION_CAP_KEY, str(cap))
    await record(session, Store.DECISIONS, CAP_CHANGED, {"previous": previous, "new": cap})


def _evaluate(*, cannot_determine: bool, material: bool, user_knows: bool) -> str | None:
    """The filter. `None` means all three held and the candidate is asked."""
    failed = [
        name
        for name, held in (
            ("cannot_determine", cannot_determine),
            ("material", material),
            ("user_knows", user_knows),
        )
        if not held
    ]
    return None if not failed else f"failed: {', '.join(failed)}"


def _normalize_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = _VERSION_TOKEN.sub(" ", stem)
    return re.sub(r"[\s_\-]+", " ", stem).strip().lower()


def _spells(term: str, words: list[str]) -> bool:
    """Whether `words`, starting with the term's own first letter, carry the
    term's letters in order as initials — "Request for Quotation" spells
    RFQ, "Project Manager" spells PM, "the price" spells nothing."""
    if not words or words[0][0].upper() != term[0]:
        return False
    initials = iter(word[0].upper() for word in words)
    return all(letter in initials for letter in term)


def _defined_inline(term: str, content: str) -> bool:
    """The passage itself says what `term` means, in one of three shapes:
    an expansion before it in brackets, an expansion after it in brackets,
    or "stands for / is short for / means". Anything looser — a sentence
    that merely uses the term near some words — is not a definition, and
    treating it as one would silence the question the loop exists for."""
    escaped = re.escape(term)
    reach = 2 * len(term) + 2
    for match in re.finditer(rf"\(\s*{escaped}\s*\)", content):
        before = content[max(0, match.start() - 200) : match.start()]
        words = _DEFINITION_WORD.findall(before)[-reach:]
        if any(_spells(term, words[start:]) for start in range(len(words))):
            return True
    for pattern in (
        rf"\b{escaped}\s*\(([^()]+)\)",
        rf"\b{escaped}\s+(?:stands for|is short for|means)\s+(.{{1,120}})",
    ):
        for match in re.finditer(pattern, content):
            if _spells(term, _DEFINITION_WORD.findall(match.group(1))[:reach]):
                return True
    return False


def _unresolved_occurrences(term: str, content: str) -> int:
    """Occurrences of `term` in `content` that the text around them does not
    already settle — see `_CONTEXT_READINGS`."""
    total = sum(1 for found in _ABBREVIATION.findall(content) if found == term)
    reading = _CONTEXT_READINGS.get(term)
    resolved = len(reading.findall(content)) if reading is not None else 0
    return max(total - resolved, 0)


async def _detect_abbreviations(
    session: AsyncSession, source_id: uuid.UUID, settings: Settings
) -> list[Candidate]:
    """One candidate per all-caps token, behind `M7-FIX-BE-172`'s floor.

    A token is dropped — not deferred to the cap, since that would still
    record it as a question worth asking — when the source already answers
    it: every occurrence carries a common-English reading its own passage
    proves (`_CONTEXT_READINGS`), or some passage defines it
    (`_defined_inline`). The samples cited as evidence are taken only from
    passages with an unresolved occurrence, so a question never cites the
    very line that answers it. Materiality counts unresolved occurrences
    only: two explained uses do not change any answer.
    """
    rows = await session.execute(
        text(
            "SELECT c.content, c.content_encrypted, d.filename, c.page_from FROM chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "WHERE d.source_id = :source_id AND d.deleted_at IS NULL "
            "AND d.superseded_by IS NULL AND d.status = 'ready'"
        ),
        {"source_id": source_id},
    )
    counts: Counter[str] = Counter()
    samples: dict[str, list[tuple[str, int | None, str]]] = defaultdict(list)
    defined: set[str] = set()
    key: bytes | None = None
    for content, content_encrypted, filename, page_from in rows:
        if not content:
            continue
        if content_encrypted:
            if key is None:
                key = await passphrase.current_key(session, settings)
            content = crypto.decrypt(content.encode("ascii"), key).decode("utf-8")
        for abbreviation in dict.fromkeys(_ABBREVIATION.findall(content)):
            if abbreviation in _COMMON_ABBREVIATIONS:
                continue
            if _defined_inline(abbreviation, content):
                defined.add(abbreviation)
            unresolved = _unresolved_occurrences(abbreviation, content)
            # Zero is still recorded, so a token whose every use is
            # explained is dropped visibly rather than never seen at all.
            counts[abbreviation] += unresolved
            if unresolved and len(samples[abbreviation]) < EVIDENCE_MAX_SAMPLES:
                samples[abbreviation].append((filename, page_from, content))
    if not counts:
        return []

    candidates = []
    for abbreviation, occurrences in sorted(counts.items()):
        cannot_determine = abbreviation not in defined and occurrences > 0
        material = occurrences >= _MIN_ABBREVIATION_OCCURRENCES
        reason = _evaluate(cannot_determine=cannot_determine, material=material, user_knows=True)
        if not cannot_determine:
            reason = (
                f"{reason} (defined in the source)"
                if abbreviation in defined
                else f"{reason} (every occurrence is explained by its own passage)"
            )
        found_samples = samples.get(abbreviation, [])
        evidence: dict[str, Any] = (
            {
                "kind": EVIDENCE_KIND_PASSAGE,
                "occurrences": occurrences,
                "samples": [
                    {"document": filename, "page": page_from, "text": _bound_text(content)}
                    for filename, page_from, content in found_samples
                ],
            }
            if found_samples
            else _unavailable_evidence(f"no locatable passage for '{abbreviation}'")
        )
        candidates.append(
            Candidate(
                trigger="abbreviation",
                subject=abbreviation,
                question=f"'{abbreviation}' appears throughout. What does it mean?",
                passes=reason is None,
                reason=reason or "all three tests held",
                evidence=evidence,
                # There is no safe guess at what an unexplained abbreviation
                # means — a wrong one is worse than no note at all, since a
                # memory fact is fed straight into future prompts.
                inferred_fact=None,
            )
        )
    return candidates


async def _detect_unreadable_scans(
    session: AsyncSession, source_id: uuid.UUID, ocr_confidence_threshold: float
) -> list[Candidate]:
    rows = await session.execute(
        text(
            "SELECT d.id, d.filename, "
            "count(*) FILTER (WHERE dp.ocr_confidence < :threshold) AS low_count, "
            "count(*) AS total_count, "
            "array_agg(dp.page_number ORDER BY dp.page_number) "
            "  FILTER (WHERE dp.ocr_confidence < :threshold) AS low_pages "
            "FROM documents d JOIN document_pages dp ON dp.document_id = d.id "
            "WHERE d.source_id = :source_id AND d.deleted_at IS NULL "
            "AND d.superseded_by IS NULL AND d.status = 'ready' "
            # Only documents the aggregate OCR flag (`M1-EXTRACT-ING-029`)
            # already named `attention` for — that flag is the pre-existing
            # materiality bar the product already committed to; this trigger
            # turns it into a question rather than re-deriving its own.
            "AND d.ocr_confidence IS NOT NULL AND d.ocr_confidence < :threshold "
            "GROUP BY d.id, d.filename"
        ),
        {"source_id": source_id, "threshold": ocr_confidence_threshold},
    )
    scanned_documents = rows.all()

    candidates = []
    for document_id, filename, low_count, total_count, low_pages in scanned_documents:
        low_pages = sorted(low_pages or [])
        fraction = (low_count / total_count) if total_count else 0.0
        material = fraction >= _MIN_SCAN_MATERIALITY_FRACTION
        reason = _evaluate(cannot_determine=True, material=material, user_knows=True)
        lo, hi = low_pages[0], low_pages[-1]
        pages_label = f"Page {lo}" if lo == hi else f"Pages {lo}-{hi}"

        extracted_rows = await session.execute(
            text(
                "SELECT page_number, text FROM document_pages "
                "WHERE document_id = :document_id AND page_number = ANY(:pages) "
                "ORDER BY page_number LIMIT :limit"
            ),
            {"document_id": document_id, "pages": low_pages, "limit": EVIDENCE_MAX_SAMPLES},
        )
        extracted = [
            {"page": page_number, "text": _bound_text(page_text)}
            for page_number, page_text in extracted_rows
            if page_text and page_text.strip()
        ]
        # `docs/architecture.md` names no page-image capture anywhere in the
        # pipeline yet — stated rather than silently omitted, per the
        # ticket's own edge case for evidence that cannot be captured.
        evidence: dict[str, Any] = (
            {
                "kind": EVIDENCE_KIND_POOR_SCAN,
                "pages": low_pages,
                "total_pages": total_count,
                "extracted_text": extracted,
                "page_images": "not available",
            }
            if extracted
            else _unavailable_evidence(
                f"no text extracted from {pages_label.lower()} of '{filename}'"
            )
        )

        candidates.append(
            Candidate(
                trigger="unreadable_scan",
                subject=filename,
                question=(
                    f"{pages_label} of *{filename}* scanned poorly and produced "
                    "little text. Re-scan, or index as-is?"
                ),
                passes=reason is None,
                reason=reason or "all three tests held",
                options=["Re-scan", "Index as-is"],
                evidence=evidence,
                inferred_fact=(
                    f"{filename}: indexed as-is. {low_count} of {total_count} page(s) "
                    "scanned poorly, below the materiality threshold to ask about."
                ),
            )
        )
    return candidates


async def _document_first_passage(
    session: AsyncSession, document_id: uuid.UUID
) -> tuple[int, str] | None:
    row = (
        await session.execute(
            text(
                "SELECT page_number, text FROM document_pages "
                "WHERE document_id = :document_id AND text IS NOT NULL "
                "ORDER BY page_number LIMIT 1"
            ),
            {"document_id": document_id},
        )
    ).first()
    if row is None or not row[1] or not row[1].strip():
        return None
    return row[0], row[1]


async def _detect_document_identity(session: AsyncSession, source_id: uuid.UUID) -> list[Candidate]:
    rows = await session.execute(
        text(
            "SELECT id, filename, added_at FROM documents "
            "WHERE source_id = :source_id AND deleted_at IS NULL "
            "AND superseded_by IS NULL AND status = 'ready'"
        ),
        {"source_id": source_id},
    )
    clusters: dict[str, list[tuple[uuid.UUID, str, Any]]] = defaultdict(list)
    for document_id, filename, added_at in rows:
        clusters[_normalize_filename(filename)].append((document_id, filename, added_at))

    candidates = []
    for stem, members in clusters.items():
        if len(members) < 2:
            # One file per normalised stem is not ambiguous — nothing to
            # infer either, since there was never a question here.
            continue
        members = sorted(members, key=lambda member: member[2])
        newest_id, newest, _added_at = members[-1]
        names = ", ".join(f"*{filename}*" for _id, filename, _added_at in members)

        passage = await _document_first_passage(session, newest_id)
        evidence: dict[str, Any] = (
            {
                "kind": EVIDENCE_KIND_PASSAGE,
                "samples": [
                    {"document": newest, "page": passage[0], "text": _bound_text(passage[1])}
                ],
            }
            if passage is not None
            else _unavailable_evidence(f"no extracted text available for '{newest}'")
        )

        candidates.append(
            Candidate(
                trigger="document_identity",
                subject=stem,
                question=(
                    f"{len(members)} files look like versions of the same document "
                    f"({names}). Is *{newest}* the current one?"
                ),
                passes=True,
                reason="all three tests held",
                options=[filename for _id, filename, _added_at in members],
                evidence=evidence,
            )
        )
    return candidates


async def _detect_contradictions(session: AsyncSession, source_id: uuid.UUID) -> list[Candidate]:
    rows = await session.execute(
        text(
            "SELECT d.filename, d.added_at, dp.page_number, dp.text FROM document_pages dp "
            "JOIN documents d ON d.id = dp.document_id "
            "WHERE d.source_id = :source_id AND d.deleted_at IS NULL "
            # A superseded version is excluded here, not filtered afterwards
            # — a contradiction against a document that no longer represents
            # anything current is not a contradiction at all
            # (`docs/backlog/M3-it-learns-my-material.md`'s own edge case).
            "AND d.superseded_by IS NULL AND d.status = 'ready' AND dp.text IS NOT NULL"
        ),
        {"source_id": source_id},
    )
    # Keyed by subject, then by (filename, number, unit) — the first match
    # for a given document/value pair carries its own page, date and a
    # bounded passage around the match, which is the real evidence a
    # contradiction question needs (`M3-RAISE-BE-071`).
    facts: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)
    for filename, added_at, page_number, page_text in rows:
        matches = [
            *_FACT_PATTERN.finditer(page_text),
            *_TIME_FACT_PATTERN.finditer(page_text),
        ]
        for match in matches:
            subject_raw, number, unit = match.group(1), match.group(2), match.group(3)
            subject = " ".join(subject_raw.lower().split())
            if match.re is _TIME_FACT_PATTERN:
                # "8 pm" and "8 PM" are one value, not a disagreement.
                unit = unit.upper()
            key = (filename, number.strip(), unit.strip())
            if key in facts[subject]:
                continue
            window = page_text[max(0, match.start() - 100) : match.end() + 100]
            facts[subject][key] = {
                "page": page_number,
                "date": added_at.date().isoformat() if added_at else None,
                "text": _bound_text(window),
            }

    candidates = []
    for subject, occurrences in sorted(facts.items()):
        by_document = {filename for filename, _number, _unit in occurrences}
        distinct_values = {(number, unit) for _filename, number, unit in occurrences}
        if len(by_document) < 2 or len(distinct_values) < 2:
            continue

        words = subject.split()
        material = len(words) >= _MIN_SUBJECT_WORDS and not all(w in _STOPWORDS for w in words)
        reason = _evaluate(cannot_determine=True, material=material, user_knows=True)
        described = "; ".join(
            f"*{filename}* says {number} {unit}".rstrip()
            for filename, number, unit in sorted(occurrences)
        )
        candidates.append(
            Candidate(
                trigger="contradiction",
                subject=subject,
                question=f"Sources disagree on {subject}: {described}. Which is current?",
                passes=reason is None,
                reason=reason or "all three tests held",
                options=sorted(by_document),
                evidence={
                    "kind": EVIDENCE_KIND_CONTRADICTION,
                    "passages": [
                        {
                            "document": filename,
                            "value": f"{number} {unit}".rstrip(),
                            **occurrences[(filename, number, unit)],
                        }
                        for filename, number, unit in sorted(occurrences)
                    ],
                },
                # A real, unresolved contradiction is never silently resolved
                # to one side (`docs/memory-and-clarification.md` §8, ranking
                # rule 1) — the model already presents both, uncollapsed, at
                # answer time (`askwell.agent.conflict`). Inventing a winner
                # here just because the question was not material enough to
                # ask would be exactly the confidently-wrong answer the whole
                # feature exists to prevent.
                inferred_fact=None,
            )
        )
    return candidates


async def _known_facts(session: AsyncSession, subjects: list[str]) -> dict[str, str]:
    """Current fact text for each subject already covered, from `memory` or
    `schema_notes` — whichever has it. `M3-RAISE-BE-070`: checked before any
    candidate becomes a question, so the same subject is never asked twice,
    whether the earlier answer came from this source or an earlier one.

    Exact match only (`docs/backlog/M3-it-learns-my-material.md`'s own
    Assumption for this ticket) — a near-match subject that is not the same
    thing must not suppress a real question, and fuzzy matching is how that
    would happen. `superseded_by IS NULL` on both tables is the same
    "current, not stale" filter used everywhere else in this module: a
    superseded fact must not resurrect a suppressed question with retired
    wording, and the fact applied is always the current one.

    A `memory` row of any confidence counts, including a low-confidence
    inference nobody has reviewed yet — asking about the user's own material
    twice is the failure this exists to prevent, and that holds even when
    the existing answer is only a guess (it still surfaces in Memory for
    review, which is a different problem from asking about it again).
    """
    if not subjects:
        return {}
    memory_rows = await session.execute(
        text(
            "SELECT subject, fact FROM memory "
            "WHERE subject = ANY(:subjects) AND superseded_by IS NULL"
        ),
        {"subjects": subjects},
    )
    known: dict[str, str] = {subject: fact for subject, fact in memory_rows}

    remaining = [subject for subject in subjects if subject not in known]
    if remaining:
        schema_rows = await session.execute(
            text(
                "SELECT COALESCE(column_name, table_name), description FROM schema_notes "
                "WHERE (table_name = ANY(:subjects) OR column_name = ANY(:subjects)) "
                "AND superseded_by IS NULL"
            ),
            {"subjects": remaining},
        )
        for subject, description in schema_rows:
            known.setdefault(subject, description)
    return known


async def raise_candidates(
    session: AsyncSession, source_id: uuid.UUID, ocr_confidence_threshold: float, settings: Settings
) -> RaiseResult:
    """Run every M3 trigger for one source, once.

    Idempotent per source: a source that already has a clarification row —
    asked, answered, skipped or dismissed, it does not matter which — is
    never re-scanned. Newly added documents landing in an already-scanned
    source, and a late-arriving high-ranking candidate displacing an
    already-raised but unanswered one, are incremental re-ingestion's
    concern and remain open — see the tracker issue this ticket filed for it
    (`docs/BRAIN.md`). Scanning here happens exactly once, when a source
    first finishes with nothing left outstanding, and the cap
    (`M3-RAISE-BE-069`) is applied to everything found in that one pass.
    """
    already = await session.execute(
        text("SELECT 1 FROM clarifications WHERE source_id = :id LIMIT 1"),
        {"id": source_id},
    )
    if already.first() is not None:
        return RaiseResult(raised=0, inferred=0, dropped=0)

    all_candidates = [
        *await _detect_abbreviations(session, source_id, settings),
        *await _detect_unreadable_scans(session, source_id, ocr_confidence_threshold),
        *await _detect_document_identity(session, source_id),
        *await _detect_contradictions(session, source_id),
    ]

    # `M3-RAISE-BE-070`: memory and schema notes are checked before any
    # candidate becomes a question. A subject already covered — by this
    # source or an earlier one — never reaches the pass/fail tests at all;
    # the existing fact applies instead, and nothing new is inferred over it.
    known = await _known_facts(session, sorted({c.subject for c in all_candidates}))
    suppressed_candidates = [c for c in all_candidates if c.subject in known]
    candidates = [c for c in all_candidates if c.subject not in known]

    cap = await get_clarification_cap(session)
    ranked = _rank_candidates([c for c in candidates if c.passes])
    to_raise, to_cap = ranked[:cap], ranked[cap:]
    failing = [c for c in candidates if not c.passes]

    raised = inferred = dropped = capped = 0
    for rank, candidate in enumerate(to_raise, start=1):
        # `current_inference` rides alongside the kind-specific evidence so
        # the answer field can prefill with what Askwell would have guessed
        # had this not been material enough to ask (`docs/ux/clarifications.md`
        # §3) — `None` where there is nothing safe to guess. `trigger` is
        # what `askwell.inline_clarify.find_blocking` (`M3-INLINE-FE-085`)
        # reads to tell a contradiction or document-identity question apart
        # from an abbreviation or scan note without re-deriving it from the
        # evidence's own shape.
        evidence = {
            **candidate.evidence,
            "current_inference": candidate.inferred_fact,
            "trigger": candidate.trigger,
        }
        await session.execute(
            text(
                "INSERT INTO clarifications "
                "(id, source_id, subject, question, options, evidence, rank, status) "
                "VALUES (:id, :source_id, :subject, :question, "
                "CAST(:options AS jsonb), CAST(:evidence AS jsonb), :rank, 'pending')"
            ),
            {
                "id": uuid.uuid4(),
                "source_id": source_id,
                "subject": candidate.subject,
                "question": candidate.question,
                "options": json.dumps(candidate.options) if candidate.options else None,
                "evidence": json.dumps(evidence),
                "rank": rank,
            },
        )
        await record(
            session,
            Store.DECISIONS,
            CANDIDATE_RAISED,
            {
                "source_id": str(source_id),
                "trigger": candidate.trigger,
                "subject": candidate.subject,
                "reason": candidate.reason,
                "rank": rank,
            },
        )
        raised += 1

    for offset, candidate in enumerate(to_cap, start=1):
        rank = cap + offset
        # Passed all three tests but the source already had `cap` better
        # candidates — not a case of "nothing safe to guess"
        # (`Candidate.inferred_fact`'s own docstring), since nothing about
        # the answer is invented here. Only that it was flagged and ranked
        # below the cap, which is itself never a guess.
        await session.execute(
            text(
                "INSERT INTO memory (id, subject, fact, origin, confidence) "
                "VALUES (:id, :subject, :fact, 'inferred', :confidence)"
            ),
            {
                "id": uuid.uuid4(),
                "subject": candidate.subject,
                "fact": (
                    f"{candidate.question} Not asked — ranked {rank} of "
                    f"{len(ranked)} for this source, below the cap of {cap}."
                ),
                "confidence": LOW_CONFIDENCE,
            },
        )
        await record(
            session,
            Store.DECISIONS,
            CANDIDATE_CAPPED,
            {
                "source_id": str(source_id),
                "trigger": candidate.trigger,
                "subject": candidate.subject,
                "rank": rank,
                "cap": cap,
            },
        )
        inferred += 1
        capped += 1

    for candidate in failing:
        if candidate.inferred_fact is not None:
            await session.execute(
                text(
                    "INSERT INTO memory (id, subject, fact, origin, confidence) "
                    "VALUES (:id, :subject, :fact, 'inferred', :confidence)"
                ),
                {
                    "id": uuid.uuid4(),
                    "subject": candidate.subject,
                    "fact": candidate.inferred_fact,
                    "confidence": candidate.inferred_confidence,
                },
            )
            inferred += 1
        else:
            dropped += 1
        await record(
            session,
            Store.DECISIONS,
            CANDIDATE_DROPPED,
            {
                "source_id": str(source_id),
                "trigger": candidate.trigger,
                "subject": candidate.subject,
                "reason": candidate.reason,
                "inferred": candidate.inferred_fact is not None,
            },
        )

    suppressed = 0
    for candidate in suppressed_candidates:
        await record(
            session,
            Store.DECISIONS,
            CANDIDATE_SUPPRESSED,
            {
                "source_id": str(source_id),
                "trigger": candidate.trigger,
                "subject": candidate.subject,
                "applied_fact": known[candidate.subject],
            },
        )
        suppressed += 1

    log.info(
        "clarifications_raised",
        source_id=str(source_id),
        raised=raised,
        inferred=inferred,
        dropped=dropped,
        capped=capped,
        suppressed=suppressed,
    )
    return RaiseResult(
        raised=raised, inferred=inferred, dropped=dropped, capped=capped, suppressed=suppressed
    )
