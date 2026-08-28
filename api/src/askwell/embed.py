"""Embedding, in bounded batches, with retry and a document that only
becomes ready when every one of its chunks has a vector. `M1-INDEX-ING-032`.

The pipeline's own guarantee, stated in `docs/build-plan.md` and `AGENTS.md`
§3 C4/C5: an answer is only as good as what it can retrieve, and a chunk with
no embedding is invisible to retrieval without anyone being told so. **A
document is marked indexed only when every one of its chunks has an
embedding** — this stage either embeds all of them or leaves the document
exactly as un-indexed as it was, never something in between that `ready`
would misrepresent.

**A batch, not the whole document, is the unit of work and of retry.**
`Settings.embedding_batch_size` bounds how many passages go into one call to
the native inference process — unbounded would send a nine-hundred-passage
scientific paper in a single request and make the machine unusable for
whatever else it is doing, the same reasoning `ingest_concurrency` already
carries. Within one batch, a transient failure — the inference process
restarting mid-import, a request that timed out — retries with a short linear
backoff before this stage gives up on it; only once that is exhausted does
the document fail and the outer job-level retry (`askwell.ingest`,
`MAX_ATTEMPTS`) take over, which re-runs the whole pipeline rather than
resuming mid-batch — chunking is cheap and idempotent
(`chunk.run` deletes and reinserts), so there is nothing worth resuming.

**An empty chunk is a second line of defence, not a real possibility.**
`askwell.chunk` guarantees every chunk it writes has content; this stage
checks anyway, because a defect discovered by refusing to embed an empty
passage is a much better bug than a citation pointing at nothing.

**The embedding dimension is checked once, at worker startup, never per
batch.** `askwell.worker.startup` calls `check_dimension` before any document
is claimed — a mismatch is a fact about how the machine is configured, not
about the file being embedded, and checking it while a batch is already
in flight would mean an import fails midway through rather than the worker
refusing to start at all.
"""

import asyncio
import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from askwell.ingest import Report, Work

log = get_logger(__name__)

# How many times one batch is retried before this stage gives up on the whole
# document and lets the outer, per-document retry (`askwell.ingest.MAX_ATTEMPTS`)
# take over. Three, for the same reason every other retry ceiling in this
# pipeline is three: a genuinely transient cause clears within one or two
# attempts, and anything that survives three is a fact about the machine or
# the model right now, not bad luck.
EMBED_BATCH_MAX_ATTEMPTS = 3

# Linear, not exponential, and short: the inference client's own timeout
# (`DEFAULT_TIMEOUT_SECONDS`, 300s) is already generous, so a batch that fails
# has usually failed fast, and there is no benefit in waiting long between
# attempts on a machine with nothing else contending for the socket.
EMBED_BATCH_RETRY_DELAY_SECONDS = 2.0

_VECTOR_DIMENSION = re.compile(r"vector\((\d+)\)")


class EmptyChunk(Exception):
    """A chunk with no content reached the embedding stage.

    `askwell.chunk` guarantees this cannot happen — every fragment it writes
    is stripped and checked non-empty before the insert. This exists as a
    second line, per the ticket's own edge case, so that a defect upstream
    surfaces as a named, retryable failure rather than an embedding call sent
    for an empty string, or a citation with nothing behind it.
    """


class EmbeddingDimensionMismatch(RuntimeError):
    """`chunks.embedding` was created at a different width than configuration
    now asks for.

    The migration fixes the column's dimension from `Settings.embedding_dimensions`
    at the time it runs (`docs/decisions.md`, 2026-08-27). Changing
    `ASKWELL_EMBEDDING_DIMENSIONS` afterwards — a different embedding model,
    say — without re-running the migration leaves the column at the old width.
    pgvector would refuse the first insert with its own opaque error; this
    names the actual cause before any document is even claimed.
    """


async def check_dimension(session: AsyncSession, settings: Settings) -> None:
    """Refuse to embed anything if the schema and configuration disagree.

    Called once, at worker startup — never per batch. A dimension mismatch is
    a fact about how this install is configured, true for every document
    equally; discovering it midway through a large import, one failed batch
    at a time, would be strictly worse than refusing to start at all.
    """
    row = (
        await session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'chunks' AND a.attname = 'embedding' "
                "AND NOT a.attisdropped"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        # The table is not migrated yet. Not this function's concern —
        # whatever runs next against this database will fail for that reason
        # and say so.
        return

    match = _VECTOR_DIMENSION.search(str(row))
    if match is None:
        return
    deployed = int(match.group(1))
    if deployed != settings.embedding_dimensions:
        raise EmbeddingDimensionMismatch(
            f"ASKWELL_EMBEDDING_DIMENSIONS is {settings.embedding_dimensions}, but "
            f"chunks.embedding was created at {deployed} dimensions. Embedding would "
            f"fail on the first batch and every one after it. Run the migration for "
            f"the model actually configured (`scripts/dev.sh db upgrade head`) before "
            f"starting the worker again."
        )


def _batches(rows: list[tuple[uuid.UUID, str]], size: int) -> list[list[tuple[uuid.UUID, str]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


async def _embed_batch(client: InferenceClient, texts: list[str]) -> list[list[float]]:
    """One batch, retried with backoff before this stage gives up on it.

    Catches both of the client's exceptions, deliberately: the ticket's own
    edge case is the inference process going down *mid-batch*, and from here
    that looks identical to a request that merely failed — both are worth one
    more try before the whole document is reported failed.
    """
    last: Exception = InferenceUnavailable("never attempted")
    for attempt in range(1, EMBED_BATCH_MAX_ATTEMPTS + 1):
        try:
            return await client.embed(texts)
        except (InferenceFailed, InferenceUnavailable) as error:
            last = error
            log.warning(
                "embed_batch_retrying",
                attempt=attempt,
                max_attempts=EMBED_BATCH_MAX_ATTEMPTS,
                size=len(texts),
                error=f"{type(error).__name__}: {error}",
            )
            if attempt < EMBED_BATCH_MAX_ATTEMPTS:
                await asyncio.sleep(EMBED_BATCH_RETRY_DELAY_SECONDS * attempt)
    raise last


async def run(
    work: "Work",
    report: "Report",
    factory: "async_sessionmaker[AsyncSession]",
    settings: Settings,
) -> None:
    async with session_scope(factory) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, content FROM chunks WHERE document_id = :id "
                    "AND embedding IS NULL ORDER BY ordinal"
                ),
                {"id": work.document_id},
            )
        ).all()

    if not rows:
        # Nothing to do: either `chunk` produced nothing (it would have
        # raised rather than let that happen) or a retry finds every chunk
        # already embedded from a previous attempt that failed after this
        # point. Either way, there is no batch to send.
        return

    pending = [(row[0], row[1]) for row in rows]
    for chunk_id, content in pending:
        if content is None or not content.strip():
            raise EmptyChunk(
                f"Askwell found an empty passage in {work.filename} (chunk {chunk_id}). "
                "This should never happen after chunking — indexing it would leave a "
                "citation pointing at nothing."
            )

    client = InferenceClient(settings)
    batches = _batches(pending, settings.embedding_batch_size)
    done = 0

    for batch in batches:
        vectors = await _embed_batch(client, [content for _chunk_id, content in batch])
        async with session_scope(factory) as session:
            for (chunk_id, _content), vector in zip(batch, vectors, strict=True):
                await session.execute(
                    text("UPDATE chunks SET embedding = :embedding WHERE id = :id"),
                    {"embedding": str(vector), "id": chunk_id},
                )
        done += len(batch)
        await report(done, len(pending))

    log.info(
        "embed_completed",
        document_id=str(work.document_id),
        filename=work.filename,
        chunks=len(pending),
        batches=len(batches),
    )
