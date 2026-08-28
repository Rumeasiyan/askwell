"""Suggested questions for an empty Ask screen, without a model call.

`M1-LIB-FE-051`. The Ask screen's own empty state, with sources present, is
supposed to name up to three real things from the corpus rather than show a
generic prompt — but generating that with the model is the wrong moment to
ask it for anything: this is exactly when the machine is most likely still
indexing (`../ux/ask.md` §5, `../ux/first-run.md` §6, both settled the same
way). So this is plain SQL and a small heuristic in Python instead.

**A heading beats a term.** `askwell.chunk` only records a heading when
chunking actually found a structural one (`db/models.py`'s `Chunk.heading`
docstring), so a document that has one gives a sharper question than a term
picked out of running prose. A document with no heading anywhere falls back
to its first chunk's most distinctive word — "distinctive" meaning "not on
a short stopword list", not anything smarter; there is no tokenizer or
term-frequency utility elsewhere in this codebase to reuse; and this is
cheap on purpose. A document with neither a heading nor readable content
falls back to naming just the file.

Only `documents.status = 'ready'` is read from — an `indexing` or
`attention` document has nothing safe to promise a question about yet, and
that is the caller's job to notice (`GET /ingest`'s `askable` already says
so) before calling this at all.
"""

import re
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.db.engine import session_scope

MAX_SUGGESTIONS = 3

# Not a linguistic stopword list — a short list of words common enough in
# English prose that picking one out as "the distinctive term" in a document
# would name nothing. Good enough for a heuristic that exists to be cheap,
# not to be right every time.
_STOPWORDS = frozenset(
    """
    the a an and or but if then else for of to in on at by with from as is
    are was were be been being this that these those it its it's he she they
    we you your our their his her them him us not no do does did done have
    has had can could will would should may might must into over under
    about above below between among per via than also such only more most
    other same each any all both few some such only own so too very just
    """.split()
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")


def _distinctive_term(content: str) -> str | None:
    counts: dict[str, int] = {}
    for match in _WORD.finditer(content):
        word = match.group(0).lower()
        if word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    if not counts:
        return None
    # Most frequent first; ties broken by first appearance order, which
    # `dict` already preserves from the scan above.
    return max(counts, key=lambda word: counts[word])


def _question_for(filename: str, heading: str | None, content: str | None) -> str:
    if heading is not None and heading.strip() != "":
        return f"What does {filename} say about {heading.strip()}?"
    term = _distinctive_term(content) if content is not None else None
    if term is not None:
        return f"What does {filename} mention about {term}?"
    return f"What is in {filename}?"


async def suggested_questions(session: AsyncSession) -> list[dict[str, Any]]:
    """Up to `MAX_SUGGESTIONS`, one per document, most recently added first.

    Two bounded queries rather than one per document: the same "cheap even
    while the machine is busy" reasoning `askwell.ingest.snapshot` already
    follows for the same surface class.
    """
    documents = (
        await session.execute(
            text(
                "SELECT d.id, d.filename FROM documents d "
                "JOIN sources s ON s.id = d.source_id "
                "WHERE d.status = 'ready' AND d.deleted_at IS NULL "
                "AND s.status <> 'deleted' "
                "ORDER BY d.id DESC LIMIT :limit"
            ),
            {"limit": MAX_SUGGESTIONS},
        )
    ).all()
    if not documents:
        return []

    document_ids = [row[0] for row in documents]
    filenames = {row[0]: row[1] for row in documents}

    first_chunks = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (document_id) document_id, heading, content "
                "FROM chunks WHERE document_id = ANY(:ids) "
                "ORDER BY document_id, ordinal"
            ),
            {"ids": document_ids},
        )
    ).all()
    by_document = {row[0]: (row[1], row[2]) for row in first_chunks}

    suggestions = []
    for document_id in document_ids:
        heading, content = by_document.get(document_id, (None, None))
        suggestions.append(
            {
                "question": _question_for(filenames[document_id], heading, content),
                "filename": filenames[document_id],
            }
        )
    return suggestions


def register_suggestions(app: FastAPI, sessions: async_sessionmaker[AsyncSession]) -> None:
    @app.get("/suggestions")
    async def suggestions() -> JSONResponse:
        async with session_scope(sessions) as db:
            return JSONResponse({"suggestions": await suggested_questions(db)})
