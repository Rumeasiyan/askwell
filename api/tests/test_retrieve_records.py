"""Hybrid retrieval, against a real Postgres. `M1-ASK-RET-035`.

Chunks and their embeddings are inserted directly rather than run through the
whole `extract`/`chunk`/`embed` pipeline — what is under test here is the
dense-plus-lexical query and its fusion, not ingestion, which
`test_chunk_records.py`/`test_embed_records.py` already cover. `content_tsv`
is still the real generated column, and `<=>` is still the real pgvector
operator; nothing about the search itself is a stand-in.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import retrieve as retrieve_module
from askwell.config import Settings

from .test_ingest_records import TABLES

pytestmark = pytest.mark.requires_db

DIMENSIONS = Settings.model_fields["embedding_dimensions"].default


class _FakeClient:
    """Stands in for `InferenceClient`: hands back whatever vector the test
    asked to be returned for the query, instead of talking to a real
    embedding model this suite has no need to start.

    `rerank` defaults to identity — same order, descending scores by
    position — so the ten `M1-ASK-RET-035` tests above, none of which care
    about reranking, keep asserting on fused order unchanged. A test that
    does care passes `rerank_scores` explicitly.
    """

    def __init__(self, vector: list[float], rerank_scores: dict[str, float] | None = None) -> None:
        self.vector = vector
        self.rerank_scores = rerank_scores
        self.calls: list[list[str]] = []
        self.rerank_calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self.vector for _text in texts]

    async def rerank(
        self, query: str, documents: list[str], *, timeout_seconds: float = 0.0
    ) -> list[tuple[int, float]]:
        self.rerank_calls.append(documents)
        if self.rerank_scores is None:
            scored = [(index, float(len(documents) - index)) for index in range(len(documents))]
        else:
            scored = [
                (index, self.rerank_scores.get(document, 0.0))
                for index, document in enumerate(documents)
            ]
        return sorted(scored, key=lambda pair: pair[1], reverse=True)


def _vector(lead: float) -> list[float]:
    """A unit-ish vector distinguishable by its first component, cheap
    to reason about under cosine distance without needing real embeddings."""
    return [lead] + [0.01] * (DIMENSIONS - 1)


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


async def _source(session: AsyncSession, kind: str = "file") -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, :kind, 'a source')"),
        {"id": source_id, "kind": kind},
    )
    return source_id


async def _document(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    sha256: str | None = None,
    superseded_by: uuid.UUID | None = None,
    deleted_at_now: bool = False,
) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents "
            "(id, source_id, filename, path, sha256, superseded_by, deleted_at) "
            "VALUES (:id, :source_id, 'file.txt', :path, :sha256, :superseded_by, "
            "CASE WHEN :deleted THEN now() ELSE NULL END)"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "path": f"/tmp/{document_id}.txt",
            "sha256": sha256 or uuid.uuid4().hex.ljust(64, "0")[:64],
            "superseded_by": superseded_by,
            "deleted": deleted_at_now,
        },
    )
    return document_id


async def _chunk(
    session: AsyncSession,
    document_id: uuid.UUID,
    content: str,
    embedding: list[float] | None,
    *,
    heading: str | None = None,
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, heading, embedding) "
            "VALUES (:id, :document_id, 0, :content, :heading, :embedding)"
        ),
        {
            "id": chunk_id,
            "document_id": document_id,
            "content": content,
            "heading": heading,
            "embedding": str(embedding) if embedding is not None else None,
        },
    )
    return chunk_id


async def _committed(session: AsyncSession) -> None:
    await session.commit()


# --- the acceptance criteria --------------------------------------------------


async def test_a_reference_number_retrieves_the_chunk_that_contains_it(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    target = await _chunk(session, document_id, "Invoice INV-2024-0917 is overdue.", _vector(0.0))
    await _chunk(session, document_id, "Unrelated supplier onboarding notes.", _vector(0.0))
    await _committed(session)

    result = await retrieve_module.retrieve(session, _FakeClient(_vector(0.0)), settings, "0917")

    assert target in [candidate.chunk_id for candidate in result.candidates]
    hit = next(candidate for candidate in result.candidates if candidate.chunk_id == target)
    assert hit.lexical_score is not None and hit.lexical_score > 0


async def test_a_paraphrase_retrieves_the_semantically_matching_chunk(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    target = await _chunk(
        session,
        document_id,
        "Either party may terminate this agreement on ninety days written notice.",
        _vector(1.0),
    )
    await _chunk(session, document_id, "The quarterly picnic is on Friday.", _vector(-1.0))
    await _committed(session)

    # A query embedding pointed exactly at the target's own vector: no shared
    # wording with the chunk at all, so only dense search can find this.
    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), settings, "when can we end the contract early"
    )

    assert result.candidates
    assert result.candidates[0].chunk_id == target
    assert result.candidates[0].dense_score is not None
    assert result.candidates[0].dense_score > 0.9


async def test_scores_and_threshold_are_captured_for_the_trace(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    await _chunk(session, document_id, "renewal terms and conditions", _vector(1.0))
    await _committed(session)

    configured = settings.model_copy(update={"retrieval_score_threshold": 0.42})
    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), configured, "renewal terms"
    )

    assert result.threshold == 0.42
    assert result.candidates
    assert result.candidates[0].score > 0


async def test_superseded_and_deleted_documents_are_excluded(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    live_document = await _document(session, source_id)
    live_chunk = await _chunk(session, live_document, "shared wording here", _vector(1.0))

    newer = await _document(session, source_id)
    superseded_document = await _document(session, source_id, superseded_by=newer)
    await _chunk(session, superseded_document, "shared wording here", _vector(1.0))

    deleted_document = await _document(session, source_id, deleted_at_now=True)
    await _chunk(session, deleted_document, "shared wording here", _vector(1.0))

    await _committed(session)

    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), settings, "shared wording"
    )

    ids = {candidate.chunk_id for candidate in result.candidates}
    assert ids == {live_chunk}


async def test_an_empty_corpus_returns_nothing_cleanly(
    session: AsyncSession, settings: Settings
) -> None:
    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(0.0)), settings, "anything at all"
    )
    assert result.candidates == []


async def test_a_query_shorter_than_a_word_does_not_error(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    await _chunk(session, document_id, "some ordinary passage", _vector(0.0))
    await _committed(session)

    result = await retrieve_module.retrieve(session, _FakeClient(_vector(0.0)), settings, "a")
    assert isinstance(result.candidates, list)


async def test_a_corpus_of_one_document_still_fuses(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    chunk_id = await _chunk(session, document_id, "the only passage that exists", _vector(1.0))
    await _committed(session)

    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), settings, "the only passage"
    )

    assert [candidate.chunk_id for candidate in result.candidates] == [chunk_id]
    assert result.candidates[0].dense_score is not None
    assert result.candidates[0].lexical_score is not None


async def test_identical_content_from_different_documents_is_not_deduplicated(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    first_document = await _document(session, source_id)
    second_document = await _document(session, source_id)
    first_chunk = await _chunk(session, first_document, "identical clause text", _vector(1.0))
    second_chunk = await _chunk(session, second_document, "identical clause text", _vector(1.0))
    await _committed(session)

    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), settings, "identical clause"
    )

    ids = {candidate.chunk_id for candidate in result.candidates}
    assert ids == {first_chunk, second_chunk}


async def test_scoping_to_a_source_excludes_a_matching_chunk_in_another_source(
    session: AsyncSession, settings: Settings
) -> None:
    wanted_source = await _source(session)
    other_source = await _source(session)
    wanted_document = await _document(session, wanted_source)
    other_document = await _document(session, other_source)
    wanted_chunk = await _chunk(session, wanted_document, "matching text here", _vector(1.0))
    await _chunk(session, other_document, "matching text here", _vector(1.0))
    await _committed(session)

    result = await retrieve_module.retrieve(
        session, _FakeClient(_vector(1.0)), settings, "matching text", source_id=wanted_source
    )

    assert [candidate.chunk_id for candidate in result.candidates] == [wanted_chunk]


# --- reranking, `M1-ASK-RET-036` ---------------------------------------------


async def test_the_right_passage_is_promoted_above_four_wrong_ones(
    session: AsyncSession, settings: Settings
) -> None:
    """The ticket's own Real-World Example Scenario: on a corpus of similar
    contracts, the passage from the right supplier is promoted above four
    passages from the wrong ones. All five score equally under fusion — same
    vector, same words — so only reranking can tell them apart."""
    source_id = await _source(session)
    right = "Meridian Supplies: payment terms are net 30 from invoice date."
    wrong = [
        "Acme Corp: payment terms are net 30 from invoice date.",
        "Bolt Industries: payment terms are net 30 from invoice date.",
        "Crestview Ltd: payment terms are net 30 from invoice date.",
        "Delta Partners: payment terms are net 30 from invoice date.",
    ]
    document_id = await _document(session, source_id)
    right_chunk = await _chunk(session, document_id, right, _vector(1.0))
    for text_ in wrong:
        await _chunk(session, document_id, text_, _vector(1.0))
    await _committed(session)

    client = _FakeClient(_vector(1.0), rerank_scores={right: 9.0})
    result = await retrieve_module.retrieve(
        session, client, settings, "what are Meridian's payment terms"
    )

    assert result.reranked is True
    assert result.candidates[0].chunk_id == right_chunk
    assert result.candidates[0].rerank_score == 9.0


async def test_reranker_unavailable_still_returns_fusion_ordered_results(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    """An answer still comes back with the reranker off — degradation, not
    failure — and the result says reranking did not run."""
    from askwell.inference.client import InferenceClient

    source_id = await _source(session)
    document_id = await _document(session, source_id)
    await _chunk(session, document_id, "renewal terms and conditions", _vector(1.0))
    await _committed(session)

    absent = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "no-such.sock"})
    )
    # `InferenceClient.embed` needs the assistant too, so retrieve() would
    # abstain before ever reaching reranking; a fake client that can embed
    # but whose `rerank` behaves like the real client when nothing is
    # listening is what isolates the reranking degradation path.

    class _EmbedsButNoReranker(_FakeClient):
        async def rerank(
            self, query: str, documents: list[str], *, timeout_seconds: float = 0.0
        ) -> list[tuple[int, float]]:
            return await absent.rerank(query, documents, timeout_seconds=timeout_seconds)

    result = await retrieve_module.retrieve(
        session, _EmbedsButNoReranker(_vector(1.0)), settings, "renewal terms"
    )

    assert result.candidates
    assert result.reranked is False
    assert result.rerank_skipped_reason is not None
    assert "unavailable" in result.rerank_skipped_reason
    assert all(candidate.rerank_score is None for candidate in result.candidates)
