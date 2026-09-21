"""Hybrid retrieval: dense search and lexical search, fused with Reciprocal
Rank Fusion. `M1-ASK-RET-035`.

`docs/architecture.md` §8: dense-only fails on exactly what people search for
— reference numbers, codes, proper nouns — and lexical-only fails on a
paraphrase that shares no wording with the passage that answers it. Neither
list is trusted alone; both run, and Reciprocal Rank Fusion combines their
*rankings* rather than their scores, which is what lets a cosine similarity
and a `ts_rank` value — different units, not comparable — contribute to one
result without either being renormalised into the other's scale.

**Every candidate's own scores are retained, never just the fused one.**
`docs/architecture.md` §7.1: the abstention explanation this feeds shows the
near-miss — "the right passage scored 0.61 under a 0.65 threshold" — and that
sentence needs the real dense or lexical score, not a rank-fusion number with
no natural units. A candidate found by only one of the two searches carries a
null score for the other, which is a fact about that candidate, not a missing
value to paper over with a zero.

**The threshold is captured here, applied by the caller.** `RetrievalResult.threshold`
is `get_retrieval_threshold()`'s value as of the moment of this call — the
user's own stored override (`M5-TRACE-FE-122`) if one exists, else
`Settings.retrieval_score_threshold` — so a trace written today still reads
correctly after the setting changes tomorrow. Deciding whether a candidate
clears it — the abstention
decision itself, `candidate_score()` below and `askwell.ask`'s use of it,
`M2-ABSTAIN-RET-053` — stays out of this function: `retrieve()` runs the same
way for every question, and an empty or all-below-threshold candidate list is
`askwell.ask`'s to act on, not this module's.

**Superseded and deleted documents are excluded at the query, not filtered
after.** A tombstoned document already has its chunk content and embedding
cleared (`docs/architecture.md` §7 standing notes), so excluding it here is
belt-and-braces for content that survives some other way; a superseded
document's chunks are otherwise untouched and would rank normally without
this join.

**No deduplication by content.** Two chunks with identical text from two
different documents are two different citations, and collapsing them would
point one citation at the wrong source — the ticket's own edge case.

**Reranking, `M1-ASK-RET-036`.** A cross-encoder pass over the top fused
candidates, served by the same native process as embedding — one more reason
`InferenceClient` is the seam `M1-ASK-RET-035`'s own decision log named. Only
the top `Settings.rerank_candidate_count` fused candidates are sent; the rest
of the fused list is appended after them, unreordered, so a corpus with fewer
candidates than the window needs no padding and nothing beyond the window is
silently dropped. The reranker's score is kept *alongside* the fused score,
never in place of it — the two are never mixed, matching `docs/architecture.md`
§8's cross-encoder pass and the ticket's own validation rule. If the reranker
is unavailable or times out, `retrieve()` returns fusion order unchanged and
says so on `RetrievalResult`, rather than silently pretending reranking ran.
"""

import math
import time
import uuid
from dataclasses import dataclass, replace

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import crypto, passphrase
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

# `docs/ux/trace.md` §4 / `docs/ux/settings.md` §2: the threshold is
# adjustable at runtime, per install — a deployment-time `Settings` field
# cannot be that, since changing it means editing `.env` and restarting. The
# generic `settings` table (`get_clarification_cap`'s own precedent,
# `askwell.clarify`) holds the override; `Settings.retrieval_score_threshold`
# stays the shipped default a fresh install starts from and the floor a
# corrupted or missing override falls back to.
RETRIEVAL_THRESHOLD_KEY = "retrieval_score_threshold"
RETRIEVAL_THRESHOLD_CHANGED = "retrieval_threshold_changed"

# Matches `chunks.content_tsv`'s own generated expression (`c7e2f814a5b3`).
# Query-side text gets the identical hyphen-to-space substitution before
# `plainto_tsquery` sees it, or a search for a reference number would produce
# the signed lexemes the column itself was changed to avoid.
TEXT_SEARCH_CONFIG = "english"

# The standard constant from Cormack, Clarke & Buettcher's reciprocal rank
# fusion paper. It damps the influence of a rank-1 hit just enough that one
# search's single best guess cannot alone outrank several moderate agreements
# between both searches — the entire point of fusing two rankings instead of
# trusting either alone.
RRF_K = 60


async def get_retrieval_threshold(session: AsyncSession, settings: Settings) -> float:
    """The threshold in force right now: the stored override if a person has
    ever set one, else the shipped default. Never recomputed from anything
    else — this is the one place `retrieve()` and the settings/trace routes
    below both read from, so they cannot disagree."""
    stored = await get_setting(session, RETRIEVAL_THRESHOLD_KEY)
    return settings.retrieval_score_threshold if stored is None else float(stored)


class InvalidThreshold(ValueError):
    """Outside `[0, 1]` — the same bound `Settings.retrieval_score_threshold`
    itself enforces at deploy time, kept here too since a runtime override
    bypasses that `Field(ge=0, le=1)` validator entirely."""


async def set_retrieval_threshold(session: AsyncSession, settings: Settings, value: float) -> float:
    """The only way the threshold changes. `docs/ux/trace.md` §4 / `M5-TRACE-
    FE-122`'s own Validation Rule: never automatic, never a side effect —
    every change, raised or lowered, is a decisions record with the old and
    new values, the same shape `set_clarification_cap` already established
    for a per-install preference change. Returns the new effective value.
    """
    if not (0.0 <= value <= 1.0):
        raise InvalidThreshold("retrieval threshold must be between 0 and 1")
    previous = await get_retrieval_threshold(session, settings)
    await set_setting(session, RETRIEVAL_THRESHOLD_KEY, str(value))
    # Strings, not floats: `canonical_payload` refuses a float outright (a
    # `jsonb` round trip does not preserve one identically, which would make
    # every later verification report tampering that never happened).
    await record(
        session,
        Store.DECISIONS,
        RETRIEVAL_THRESHOLD_CHANGED,
        {"previous": str(previous), "new": str(value)},
    )
    return value


@dataclass(frozen=True, slots=True)
class Candidate:
    """One fused result, with both source rankings' own scores retained."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    anchor_kind: str | None
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    score: float  # the fused RRF score this candidate was ranked by
    dense_score: float | None  # cosine similarity, as measured; null if dense search missed it
    lexical_score: float | None  # ts_rank, as measured; null if lexical search missed it
    rerank_score: float | None = None  # raw cross-encoder logit; null unless reranking ran on it


def candidate_score(candidate: Candidate) -> float:
    """The one comparable, 0..1 score `M2-ABSTAIN-RET-053`'s threshold decision
    is made against.

    None of `Candidate`'s four scores are directly comparable to a configured
    threshold on their own: the fused RRF score (`.score`) has no natural
    ceiling near 1 (`1 / (RRF_K + 1)` at best) and exists to order candidates,
    not to be read as a confidence; a raw cross-encoder logit
    (`InferenceClient.rerank`'s own docstring) is unbounded and can be
    negative. Reranking, when it ran, is still the most informative signal
    available, so its logit is passed through a sigmoid — the transform a
    cross-encoder is trained to be read through — to get a 0..1 relevance
    probability that a `[0, 1]`-bounded `Settings.retrieval_score_threshold`
    can actually mean something against.

    When this candidate was never sent to the reranker (reranking unavailable
    entirely, or the candidate fell outside `rerank_candidate_count`'s
    window), the real dense similarity is used instead — already a comparable
    0..1 cosine, and the score `docs/architecture.md` §7.1's own abstention
    example ("the right passage scored 0.61") is written in terms of. Lexical
    `ts_rank` is the last resort, for a candidate dense search never found.
    """
    if candidate.rerank_score is not None:
        return 1.0 / (1.0 + math.exp(-candidate.rerank_score))
    if candidate.dense_score is not None:
        return candidate.dense_score
    if candidate.lexical_score is not None:
        return candidate.lexical_score
    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    candidates: list[Candidate]
    threshold: float  # Settings.retrieval_score_threshold, in force at this call
    reranked: bool  # whether `candidates`' order is the reranker's, not fusion's
    rerank_duration_ms: float | None  # None when reranking did not run
    rerank_skipped_reason: str | None  # None when `reranked` is True


@dataclass(slots=True)
class _FusionEntry:
    """Mutable accumulator while the two ranked lists are being merged."""

    document_id: uuid.UUID
    filename: str
    anchor_kind: str | None
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    rrf: float
    dense_score: float | None
    lexical_score: float | None


_Row = tuple[uuid.UUID, uuid.UUID, str, str | None, str, str | None, int | None, int | None, float]


async def _decrypt(session: AsyncSession, settings: Settings, content: str, encrypted: bool) -> str:
    """A candidate's content, as stored may be a Fernet token
    (`c.content_encrypted`, `M7-SEC-BE-152`) — decrypted here, once per row,
    so every caller downstream of `_dense_search`/`_lexical_search` (fusion,
    reranking, citations, composition) sees plaintext exactly as it did
    before encryption existed. `CredentialsLocked` (no passphrase, or this
    process not unlocked yet) propagates — a locked retrieval cannot
    silently return ciphertext as if it were an answer."""
    if not encrypted:
        return content
    key = await passphrase.current_key(session, settings)
    return crypto.decrypt(content.encode("ascii"), key).decode("utf-8")


async def _dense_search(
    session: AsyncSession,
    settings: Settings,
    query_vector: list[float],
    source_id: uuid.UUID | None,
) -> list[_Row]:
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.document_id, d.filename, d.anchor_kind, c.content, "
                "c.content_encrypted, c.heading, "
                "c.page_from, c.page_to, "
                "1 - (c.embedding <=> CAST(:qvec AS vector)) AS score "
                "FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.embedding IS NOT NULL "
                "AND d.deleted_at IS NULL AND d.superseded_by IS NULL "
                "AND (CAST(:source_id AS uuid) IS NULL OR d.source_id = CAST(:source_id AS uuid)) "
                "ORDER BY c.embedding <=> CAST(:qvec AS vector) "
                "LIMIT :limit"
            ),
            {
                "qvec": str(query_vector),
                "source_id": str(source_id) if source_id else None,
                "limit": settings.retrieval_candidate_count,
            },
        )
    ).all()
    return [
        (
            row[0],
            row[1],
            row[2],
            row[3],
            await _decrypt(session, settings, row[4], row[5]),
            row[6],
            row[7],
            row[8],
            float(row[9]),
        )
        for row in rows
    ]


async def _lexical_search(
    session: AsyncSession,
    settings: Settings,
    query: str,
    source_id: uuid.UUID | None,
) -> list[_Row]:
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.document_id, d.filename, d.anchor_kind, c.content, "
                "c.content_encrypted, c.heading, "
                "c.page_from, c.page_to, "
                "ts_rank(c.content_tsv, "
                "plainto_tsquery(:cfg, regexp_replace(:query, '-', ' ', 'g'))) AS score "
                "FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.content_tsv "
                "@@ plainto_tsquery(:cfg, regexp_replace(:query, '-', ' ', 'g')) "
                "AND d.deleted_at IS NULL AND d.superseded_by IS NULL "
                "AND (CAST(:source_id AS uuid) IS NULL OR d.source_id = CAST(:source_id AS uuid)) "
                "ORDER BY score DESC "
                "LIMIT :limit"
            ),
            {
                "cfg": TEXT_SEARCH_CONFIG,
                "query": query,
                "source_id": str(source_id) if source_id else None,
                "limit": settings.retrieval_candidate_count,
            },
        )
    ).all()
    return [
        (
            row[0],
            row[1],
            row[2],
            row[3],
            await _decrypt(session, settings, row[4], row[5]),
            row[6],
            row[7],
            row[8],
            float(row[9]),
        )
        for row in rows
    ]


def _fuse(
    dense_rows: list[_Row], lexical_rows: list[_Row], candidate_count: int
) -> list[Candidate]:
    """Reciprocal rank fusion over two already-ranked, already-limited lists.

    Pure and synchronous on purpose — every acceptance criterion about
    ordering, missing scores and no-dedup is a fact about this function alone
    and is tested against it directly, with no database involved.
    """
    fused: dict[uuid.UUID, _FusionEntry] = {}

    for rank, row in enumerate(dense_rows, start=1):
        (
            chunk_id,
            document_id,
            filename,
            anchor_kind,
            content,
            heading,
            page_from,
            page_to,
            score,
        ) = row
        fused[chunk_id] = _FusionEntry(
            document_id=document_id,
            filename=filename,
            anchor_kind=anchor_kind,
            content=content,
            heading=heading,
            page_from=page_from,
            page_to=page_to,
            rrf=1.0 / (RRF_K + rank),
            dense_score=score,
            lexical_score=None,
        )

    for rank, row in enumerate(lexical_rows, start=1):
        (
            chunk_id,
            document_id,
            filename,
            anchor_kind,
            content,
            heading,
            page_from,
            page_to,
            score,
        ) = row
        entry = fused.get(chunk_id)
        if entry is None:
            fused[chunk_id] = _FusionEntry(
                document_id=document_id,
                filename=filename,
                anchor_kind=anchor_kind,
                content=content,
                heading=heading,
                page_from=page_from,
                page_to=page_to,
                rrf=1.0 / (RRF_K + rank),
                dense_score=None,
                lexical_score=score,
            )
        else:
            entry.rrf += 1.0 / (RRF_K + rank)
            entry.lexical_score = score

    ordered = sorted(fused.items(), key=lambda item: item[1].rrf, reverse=True)
    ordered = ordered[:candidate_count]

    return [
        Candidate(
            chunk_id=chunk_id,
            document_id=entry.document_id,
            filename=entry.filename,
            anchor_kind=entry.anchor_kind,
            content=entry.content,
            heading=entry.heading,
            page_from=entry.page_from,
            page_to=entry.page_to,
            score=entry.rrf,
            dense_score=entry.dense_score,
            lexical_score=entry.lexical_score,
        )
        for chunk_id, entry in ordered
    ]


async def _rerank(
    client: InferenceClient,
    settings: Settings,
    query: str,
    candidates: list[Candidate],
) -> tuple[list[Candidate], bool, float | None, str | None]:
    """Reorder the top fused candidates by cross-encoder score.

    Only `settings.rerank_candidate_count` candidates are sent — the reranker
    scores each one individually, so the window is what keeps this bounded on
    a light profile. The remainder of `candidates` (if any) is appended
    unreordered: it was never sent to be scored, so claiming it was reranked
    would be exactly the "silently pretending" the ticket forbids.

    Returns the fused list unchanged, with a reason, if the reranker is
    unavailable or the call fails or times out — reranking is a quality
    improvement, not a dependency retrieval can fail on.
    """
    if not candidates:
        return candidates, False, None, None

    window = candidates[: settings.rerank_candidate_count]
    started = time.monotonic()
    try:
        scored = await client.rerank(
            query,
            [candidate.content for candidate in window],
            timeout_seconds=settings.rerank_timeout_seconds,
        )
    except InferenceUnavailable as error:
        log.info("rerank_skipped", reason="unavailable", detail=str(error))
        return candidates, False, None, f"reranker unavailable: {error}"
    except InferenceFailed as error:
        log.warning("rerank_failed", detail=str(error))
        return candidates, False, None, f"reranker failed: {error}"

    duration_ms = (time.monotonic() - started) * 1000

    # `scored` is already sorted best-first by `InferenceClient.rerank`, and
    # that sort is stable, so two near-identical scores keep the order they
    # arrived in (their fused rank) rather than moving between runs.
    reranked_window = [replace(window[index], rerank_score=score) for index, score in scored]
    return reranked_window + candidates[len(window) :], True, duration_ms, None


async def retrieve(
    session: AsyncSession,
    client: InferenceClient,
    settings: Settings,
    query: str,
    *,
    source_id: uuid.UUID | None = None,
) -> RetrievalResult:
    """Dense and lexical search over the live corpus, fused by RRF.

    `source_id` scopes both searches to one source — the ticket's own "asked
    from a source context" case — and is otherwise `None`, searching
    everything live. An empty corpus, or a query neither search matches,
    returns an empty candidate list rather than raising: abstention (`M2`)
    is what turns that into an answer, not this function.
    """
    vectors = await client.embed([query])
    dense_rows = await _dense_search(session, settings, vectors[0], source_id) if vectors else []
    lexical_rows = await _lexical_search(session, settings, query, source_id)

    candidates = _fuse(dense_rows, lexical_rows, settings.retrieval_candidate_count)
    candidates, reranked, rerank_duration_ms, rerank_skipped_reason = await _rerank(
        client, settings, query, candidates
    )

    log.info(
        "retrieve_completed",
        query_length=len(query),
        source_id=str(source_id) if source_id else None,
        dense_hits=len(dense_rows),
        lexical_hits=len(lexical_rows),
        fused=len(candidates),
        reranked=reranked,
        rerank_duration_ms=rerank_duration_ms,
    )

    return RetrievalResult(
        candidates=candidates,
        threshold=await get_retrieval_threshold(session, settings),
        reranked=reranked,
        rerank_duration_ms=rerank_duration_ms,
        rerank_skipped_reason=rerank_skipped_reason,
    )


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Retrieval alone, with no composition and no threshold decision — the
    degraded-assistant surface `M2-FAIL-FE-060` and any future non-chat entry
    point that wants passages rather than an answer."""

    candidates: list[Candidate]
    keyword_only: bool  # dense search did not run; every score is lexical


async def search(
    session: AsyncSession,
    client: InferenceClient,
    settings: Settings,
    query: str,
    *,
    source_id: uuid.UUID | None = None,
) -> SearchResult:
    """Dense and lexical search, degrading to lexical alone when the model is
    not there to embed the query.

    `retrieve()` calls `client.embed()` unguarded because `askwell.ask` wants
    exactly that: an unavailable assistant should fail the whole turn, which
    it already reports plainly (`docs/ux/ask.md` §5). This function exists for
    the opposite case — the moment the assistant is *not* available and the
    product still has to answer "does anything I have mention this" — so the
    same exceptions that would fail a question here mean only "skip dense,
    lexical still works," matching `InferenceClient`'s own stated distinction
    between the assistant being absent and a request failing.
    """
    try:
        vectors = await client.embed([query])
        keyword_only = False
    except (InferenceUnavailable, InferenceFailed):
        vectors = []
        keyword_only = True

    dense_rows = await _dense_search(session, settings, vectors[0], source_id) if vectors else []
    lexical_rows = await _lexical_search(session, settings, query, source_id)
    candidates = _fuse(dense_rows, lexical_rows, settings.retrieval_candidate_count)
    # Reranking already degrades gracefully on its own (`_rerank` catches both
    # of `InferenceClient`'s exceptions and returns fusion order unchanged),
    # so it is safe to attempt here even when the embed call above just showed
    # the assistant is down — it will skip itself the same way.
    candidates, _reranked, _duration_ms, _skip_reason = await _rerank(
        client, settings, query, candidates
    )

    log.info(
        "search_completed",
        query_length=len(query),
        source_id=str(source_id) if source_id else None,
        keyword_only=keyword_only,
        hits=len(candidates),
    )

    return SearchResult(candidates=candidates, keyword_only=keyword_only)


class SetThresholdRequest(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)


def register_retrieval_threshold(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The one read/write pair for the retrieval threshold — reached from
    the abstention trace's near-miss control (`docs/ux/trace.md` §4) and
    from the settings screen (`docs/ux/settings.md` §2), both against this
    same endpoint so the two surfaces cannot drift apart (`M5-TRACE-FE-122`).
    """

    @app.get("/settings/retrieval-threshold")
    async def get_threshold() -> JSONResponse:
        async with session_scope(factory) as db:
            value = await get_retrieval_threshold(db, settings)
        return JSONResponse({"threshold": value})

    @app.post("/settings/retrieval-threshold")
    async def set_threshold(body: SetThresholdRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            value = await set_retrieval_threshold(db, settings, body.threshold)
        return JSONResponse({"threshold": value})


def register_search(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the degraded-assistant search surface. `M2-FAIL-FE-060`.

    Deliberately separate from `askwell.ask`: nothing here writes to
    `messages` or `citations` — there is no turn, no composition and nothing
    to persist. It is retrieval read back directly for the moment there is no
    assistant to ask through.
    """

    @app.get("/search")
    async def search_endpoint(q: str, source_id: uuid.UUID | None = None) -> JSONResponse:
        trimmed = q.strip()
        if trimmed == "":
            return JSONResponse({"keyword_only": False, "results": []})

        client = InferenceClient(settings)
        async with session_scope(factory) as db:
            result = await search(db, client, settings, trimmed, source_id=source_id)

        return JSONResponse(
            {
                "keyword_only": result.keyword_only,
                "results": [
                    {
                        "chunk_id": str(candidate.chunk_id),
                        "document_id": str(candidate.document_id),
                        "filename": candidate.filename,
                        "anchor_kind": candidate.anchor_kind,
                        "heading": candidate.heading,
                        "page_from": candidate.page_from,
                        "page_to": candidate.page_to,
                        "passage": candidate.content,
                    }
                    for candidate in result.candidates
                ],
            }
        )
