"""`eval.grounded`'s own logic — citation matching and the fixture corpus
generator's output — without a database or a model.

Seeding the corpus and driving a real `ask` turn need real Postgres and a
running native inference process; that half is exercised by hand per
`eval/suites/grounded_qa.v1.json`'s own testing notes, not here (no network,
no database — same rule as every other unmarked test, `AGENTS.md` §6).
"""

from pathlib import Path

import docx
import openpyxl
from eval.fixtures.generate_corpus import (
    FIGURES_ROWS,
    HANDBOOK_A_PAGES,
    HANDBOOK_B_PAGES,
    NOTICE_SCAN_LINES,
    SPEC_SECTIONS,
    build_handbook_a,
    build_handbook_b,
    build_notice_scan,
)
from eval.grounded import FIXTURES_DIR, _citation_score
from eval.suite import Task


def _task(**overrides: object) -> Task:
    base = dict(
        id="t",
        prompt="hi",
        scorer="contains_all",
        expected="hi",
        timeout_seconds=1.0,
        expected_documents=("handbook_a.pdf",),
        expected_passages=("eleven paid holiday days",),
    )
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def _citation(filename: str, passage: str) -> dict[str, object]:
    return {"filename": filename, "passage": passage}


def test_citation_score_matches_document_and_passage() -> None:
    task = _task()
    citations = [
        _citation("handbook_a.pdf", "Meridian Loom employees accrue eleven paid holiday days.")
    ]
    assert _citation_score(task, citations) == 1.0


def test_citation_score_is_case_insensitive() -> None:
    task = _task()
    citations = [_citation("handbook_a.pdf", "ELEVEN PAID HOLIDAY DAYS accrue each year.")]
    assert _citation_score(task, citations) == 1.0


def test_citation_score_rejects_right_passage_wrong_document() -> None:
    task = _task()
    citations = [_citation("handbook_b.pdf", "eleven paid holiday days")]
    assert _citation_score(task, citations) == 0.0


def test_citation_score_rejects_right_document_wrong_passage() -> None:
    task = _task()
    citations = [_citation("handbook_a.pdf", "sixty-three days notice")]
    assert _citation_score(task, citations) == 0.0


def test_citation_score_accepts_either_of_two_expected_documents() -> None:
    """The "answer appears in two places" edge case: a duplicated fact in two
    fixture documents, either citation counts."""
    task = _task(expected_documents=("handbook_a.pdf", "notice_scan.pdf"))
    citations = [_citation("notice_scan.pdf", "eleven paid holiday days")]
    assert _citation_score(task, citations) == 1.0


def test_citation_score_with_no_citations_is_zero() -> None:
    assert _citation_score(_task(), []) == 0.0


def test_fixture_corpus_is_committed_and_reproducible() -> None:
    """The committed bytes under `eval/fixtures/corpus/` match a fresh build
    from the same fact strings — the ticket's own "fixture corpus is
    committed and reproducible" acceptance criterion.

    Byte-for-byte for the PDFs, built from scratch with no embedded
    timestamp. `.docx`/`.xlsx` are zip containers python-docx/openpyxl stamp
    with the current time on every save, so those two are compared by
    content instead — still reproducible, just not byte-identical.
    """
    assert (FIXTURES_DIR / "handbook_a.pdf").read_bytes() == build_handbook_a()
    assert (FIXTURES_DIR / "handbook_b.pdf").read_bytes() == build_handbook_b()
    assert (FIXTURES_DIR / "notice_scan.pdf").read_bytes() == build_notice_scan()

    document = docx.Document(str(FIXTURES_DIR / "spec.docx"))
    facts = [p.text for p in document.paragraphs if p.text in dict(SPEC_SECTIONS).values()]
    assert facts == [fact for _heading, fact in SPEC_SECTIONS]

    workbook = openpyxl.load_workbook(FIXTURES_DIR / "figures.xlsx")
    sheet = workbook.active
    rows = [tuple(row) for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert rows == FIGURES_ROWS


def test_fixture_corpus_covers_the_ticket_scope() -> None:
    """Digital PDFs, a scan, an Office document and a table — the ticket's
    own scope list, `M2-EVAL-TEST-064`. `conflict_*.pdf`/`store_hours_*.pdf`
    are `M2-EVAL-TEST-066`'s own additions, seeded through this same
    corpus (`eval.conflict.seed_corpus` reuses this module's `seed_corpus`
    unchanged)."""
    names = {p.name for p in Path(FIXTURES_DIR).iterdir()}
    assert names == {
        "handbook_a.pdf",
        "handbook_b.pdf",
        "notice_scan.pdf",
        "spec.docx",
        "figures.xlsx",
        "conflict_2025.pdf",
        "conflict_2026.pdf",
        "store_hours_2025.pdf",
        "store_hours_2026.pdf",
    }
    assert len(HANDBOOK_A_PAGES) == 8
    assert len(HANDBOOK_B_PAGES) == 8
    assert len(NOTICE_SCAN_LINES) == 5
    assert len(SPEC_SECTIONS) == 6
    assert len(FIGURES_ROWS) == 5


def test_a_failed_turn_is_an_error_not_an_empty_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """#769: the inference process went away 28 runs into the first
    `abstention.v1` measurement, every later turn ended `failed` with empty
    text, and the harness scored that text as an answer that did not
    abstain — with no error recorded anywhere. Raised as `InferenceFailed`,
    every suite's existing handler records it as the error it is."""
    import asyncio
    from contextlib import asynccontextmanager

    import pytest
    from eval import grounded

    from askwell.inference.client import InferenceFailed

    class _Db:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

    @asynccontextmanager
    async def _scope(_factory: object):  # type: ignore[no-untyped-def]
        yield _Db()

    async def _failing_generate(_settings, _factory, turn, _question, _source_id) -> None:  # type: ignore[no-untyped-def]
        turn.status = "failed"
        turn.emit("done", {"status": "failed", "reason": "The assistant is unavailable."})

    monkeypatch.setattr(grounded, "session_scope", _scope)
    monkeypatch.setattr(grounded.ask_module, "_generate", _failing_generate)

    with pytest.raises(InferenceFailed, match="The assistant is unavailable"):
        asyncio.run(grounded._ask_one(None, None, "Who is the CEO?"))  # type: ignore[arg-type]


# --- M11-FIX-TEST-232: pending clarifications skipped after seeding --------
#
# #859: ingesting the corpus raises a clarification, and the first question
# retrieving from that source pauses in `askwell.ask._await_clarification`
# for an answer the harness never gives — on a fresh database the suite
# never finishes. `seed_corpus` now reports which sources hold the corpus,
# and `skip_pending_clarifications` skips what is pending on them through
# `askwell.review.skip_clarification`, the product's own skip path.


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_Rows":
        return self

    def all(self) -> list[object]:
        return self._rows


class _PendingDb:
    """Answers the one `SELECT id FROM clarifications ...` with `pending`."""

    def __init__(self, pending: list[object]) -> None:
        self.pending = pending
        self.params: list[object] = []

    async def execute(self, _statement: object, params: object = None) -> _Rows:
        self.params.append(params)
        return _Rows(self.pending)


def _patch_scope(monkeypatch, db: object) -> None:  # type: ignore[no-untyped-def]
    from contextlib import asynccontextmanager

    from eval import grounded

    @asynccontextmanager
    async def _scope(_factory: object):  # type: ignore[no-untyped-def]
        yield db

    monkeypatch.setattr(grounded, "session_scope", _scope)


def test_every_pending_clarification_on_the_corpus_is_skipped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    import uuid

    from eval import grounded

    pending = [uuid.uuid4(), uuid.uuid4()]
    source_id = uuid.uuid4()
    db = _PendingDb(pending)
    _patch_scope(monkeypatch, db)
    skipped: list[object] = []

    async def _skip(_session: object, clarification_id: object) -> None:
        skipped.append(clarification_id)

    monkeypatch.setattr(grounded.review, "skip_clarification", _skip)

    count = asyncio.run(grounded.skip_pending_clarifications(None, {source_id}))  # type: ignore[arg-type]

    assert count == 2
    assert skipped == pending
    assert db.params == [{"source_ids": [source_id]}]


def test_a_corpus_that_raises_no_clarification_skips_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The ticket's first edge case — and the re-run on an already-seeded
    database, where everything came back `DUPLICATE` and nothing is
    pending: zero, with no skip call."""
    import asyncio
    import uuid

    from eval import grounded

    _patch_scope(monkeypatch, _PendingDb([]))

    async def _skip(_session: object, _clarification_id: object) -> None:
        raise AssertionError("nothing was pending")

    monkeypatch.setattr(grounded.review, "skip_clarification", _skip)

    assert asyncio.run(grounded.skip_pending_clarifications(None, {uuid.uuid4()})) == 0  # type: ignore[arg-type]


def test_no_corpus_sources_means_no_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    from eval import grounded

    db = _PendingDb([])
    _patch_scope(monkeypatch, db)

    assert asyncio.run(grounded.skip_pending_clarifications(None, set())) == 0  # type: ignore[arg-type]
    assert db.params == []


def test_seed_corpus_names_the_sources_holding_the_corpus(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Added files report the new source; duplicates report the source the
    existing copy lives in — that is the source retrieval will read, and the
    one a clarification would be pending on after a re-run."""
    import asyncio
    import uuid

    from eval import grounded

    from askwell.sources import AddResult, Existing, FileResult, Outcome

    new_source = uuid.uuid4()
    old_source = uuid.uuid4()
    added_document = uuid.uuid4()
    result = AddResult(
        files=[
            FileResult(
                relative_path="handbook_a.pdf",
                path="/x/handbook_a.pdf",
                filename="handbook_a.pdf",
                outcome=Outcome.ADDED,
                document_id=added_document,
            ),
            FileResult(
                relative_path="spec.docx",
                path="/x/spec.docx",
                filename="spec.docx",
                outcome=Outcome.DUPLICATE,
                existing=Existing(
                    id=uuid.uuid4(), path="/y/spec.docx", filename="spec.docx", source_id=old_source
                ),
            ),
        ],
        source_id=new_source,
    )
    _patch_scope(monkeypatch, _PendingDb([]))

    async def _add(_db: object, _root: str, _filenames: list[str]) -> AddResult:
        return result

    processed: list[object] = []

    async def _process(_factory: object, _settings: object, document_id: object) -> str:
        processed.append(document_id)
        return "done"

    async def _ensure_root(_db: object, _path: str) -> None:
        return None

    monkeypatch.setattr(grounded, "add_source", _add)
    monkeypatch.setattr(grounded, "_ensure_root", _ensure_root)
    monkeypatch.setattr(grounded.ingest, "process", _process)

    sources = asyncio.run(grounded.seed_corpus(None, None))  # type: ignore[arg-type]

    assert sources == {new_source, old_source}
    assert processed == [added_document]


def test_the_grounded_run_skips_after_seeding_and_records_the_count(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    import uuid
    from types import SimpleNamespace

    from eval import grounded
    from eval.suite import Suite

    order: list[str] = []
    corpus_source = uuid.uuid4()

    class _Engine:
        async def dispose(self) -> None:
            order.append("dispose")

    async def _seed(_factory: object, _settings: object) -> set[uuid.UUID]:
        order.append("seed")
        return {corpus_source}

    async def _skip(_factory: object, source_ids: set[uuid.UUID]) -> int:
        assert source_ids == {corpus_source}
        order.append("skip")
        return 3

    async def _run_task(_factory: object, _settings: object, task: Task) -> object:
        order.append("task")
        from eval.results import RunResult, TaskResult

        return TaskResult(task_id=task.id, prompt=task.prompt, runs=(RunResult(1.0, "a", None),))

    monkeypatch.setattr(grounded, "build_engine", lambda _settings: _Engine())
    monkeypatch.setattr(grounded, "session_factory", lambda _engine: None)
    monkeypatch.setattr(grounded, "seed_corpus", _seed)
    monkeypatch.setattr(grounded, "skip_pending_clarifications", _skip)
    monkeypatch.setattr(grounded, "_run_grounded_task", _run_task)
    monkeypatch.setattr(grounded, "current_model_name", lambda _settings: "m")

    suite = Suite(
        name="grounded_qa.v1",
        category="grounded",
        pass_bar=0.85,
        tasks=(_task(),),
        mode="grounded",
    )
    settings = SimpleNamespace(profile=SimpleNamespace(value="standard"))
    report = asyncio.run(grounded.run_grounded_suite(settings, suite))  # type: ignore[arg-type]

    assert order == ["seed", "skip", "task", "dispose"]
    assert report.clarifications_skipped == 3
    assert report.to_dict()["clarifications_skipped"] == 3
