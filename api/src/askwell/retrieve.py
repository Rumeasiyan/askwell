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

**The threshold is captured, not applied.** Deciding whether a score clears
it is the abstention decision, `M2`'s scope and explicitly out of this
ticket's. `RetrievalResult.threshold` is `Settings.retrieval_score_threshold`
as configured at the moment of this call, so a trace written today still
reads correctly after the setting changes tomorrow.

**Superseded and deleted documents are excluded at the query, not filtered
after.** A tombstoned document already has its chunk content and embedding
cleared (`docs/architecture.md` §7 standing notes), so excluding it here is
belt-and-braces for content that survives some other way; a superseded
document's chunks are otherwise untouched and would rank normally without
this join.

**No deduplication by content.** Two chunks with identical text from two
different documents are two different citations, and collapsing them would
point one citation at the wrong source — the ticket's own edge case.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.config import Settings
from askwell.inference.client import InferenceClient
from askwell.logging import get_logger

log = get_logger(__name__)

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


@dataclass(frozen=True, slots=True)
class Candidate:
    """One fused result, with both source rankings' own scores retained."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    score: float  # the fused RRF score this candidate was ranked by
    dense_score: float | None  # cosine similarity, as measured; null if dense search missed it
    lexical_score: float | None  # ts_rank, as measured; null if lexical search missed it


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    candidates: list[Candidate]
    threshold: float  # Settings.retrieval_score_threshold, in force at this call


@dataclass(slots=True)
class _FusionEntry:
    """Mutable accumulator while the two ranked lists are being merged."""

    document_id: uuid.UUID
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    rrf: float
    dense_score: float | None
    lexical_score: float | None


_Row = tuple[uuid.UUID, uuid.UUID, str, str | None, int | None, int | None, float]


async def _dense_search(
    session: AsyncSession,
    settings: Settings,
    query_vector: list[float],
    source_id: uuid.UUID | None,
) -> list[_Row]:
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.document_id, c.content, c.heading, c.page_from, c.page_to, "
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
    return [(row[0], row[1], row[2], row[3], row[4], row[5], float(row[6])) for row in rows]


async def _lexical_search(
    session: AsyncSession,
    settings: Settings,
    query: str,
    source_id: uuid.UUID | None,
) -> list[_Row]:
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.document_id, c.content, c.heading, c.page_from, c.page_to, "
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
    return [(row[0], row[1], row[2], row[3], row[4], row[5], float(row[6])) for row in rows]


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
        chunk_id, document_id, content, heading, page_from, page_to, score = row
        fused[chunk_id] = _FusionEntry(
            document_id=document_id,
            content=content,
            heading=heading,
            page_from=page_from,
            page_to=page_to,
            rrf=1.0 / (RRF_K + rank),
            dense_score=score,
            lexical_score=None,
        )

    for rank, row in enumerate(lexical_rows, start=1):
        chunk_id, document_id, content, heading, page_from, page_to, score = row
        entry = fused.get(chunk_id)
        if entry is None:
            fused[chunk_id] = _FusionEntry(
                document_id=document_id,
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

    log.info(
        "retrieve_completed",
        query_length=len(query),
        source_id=str(source_id) if source_id else None,
        dense_hits=len(dense_rows),
        lexical_hits=len(lexical_rows),
        fused=len(candidates),
    )

    return RetrievalResult(candidates=candidates, threshold=settings.retrieval_score_threshold)
