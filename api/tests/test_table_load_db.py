"""Loading and reloading a table into the real sandbox instance.
`M4-CSV-ING-094`. Same split as `test_dump_import.py`: pure-Python casting
and identifier logic is in `test_table_load.py`; everything here needs a
real, separate Postgres instance to prove.
"""

import hashlib
import io
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import openpyxl
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.dump_import import set_dump_size_cap_bytes
from askwell.filetypes import WORKBOOK_MIME
from askwell.review import answer_clarification
from askwell.table_load import (
    WORKBOOK_TABLES_FAILED,
    WORKBOOK_TABLES_LOADED,
    EmptyTable,
    TableCapExceeded,
    create_table_source,
    load_workbook_tables,
    process_table_source,
    reload_source,
    sweep_workbook_tables,
)

pytestmark = pytest.mark.requires_db

TABLES = (
    "sources, documents, clarifications, memory, schema_notes, reapply_jobs, "
    "audit_decisions, settings"
)


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


@pytest.fixture
def table_settings(sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password=os.environ["TEST_SANDBOX_OWNER_PASSWORD"],  # type: ignore[arg-type]
        sandbox_readonly_password=os.environ["TEST_SANDBOX_READONLY_PASSWORD"],  # type: ignore[arg-type]
    )


async def _make_source(
    factory: async_sessionmaker[AsyncSession], name: str, csv_path: Path
) -> uuid.UUID:
    async with factory() as session:
        source_id = await create_table_source(session, name, str(csv_path))
        await session.commit()
    return source_id


async def test_a_clean_csv_loads_as_a_real_table_with_confirmed_types(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("Name,Amount\nAnna,10\nBen,20\n")
    source_id = await _make_source(factory, "people", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))

    assert len(results) == 1
    result = results[0]
    assert result.row_count == 2
    assert result.failed_rows == []

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        assert row[0] == "ready"
        database = row[1]
        assert database is not None

        notes = (
            await session.execute(
                text(
                    "SELECT column_name FROM schema_notes WHERE source_id = :id "
                    "AND origin = 'inferred'"
                ),
                {"id": source_id},
            )
        ).all()
        # `M4-CSV-ING-092`'s own per-column notes, plus this ticket's
        # table-level note (`column_name IS NULL`).
        assert None in {row[0] for row in notes}

    admin_url = table_settings.sandbox_database_url.get_secret_value()
    import psycopg

    with psycopg.connect(admin_url.rsplit("/", 1)[0] + f"/{database}", autocommit=True) as conn:
        rows = conn.execute("SELECT name, amount FROM people_csv ORDER BY name").fetchall()
    assert rows == [("Anna", 10), ("Ben", 20)]


async def test_a_column_name_that_is_not_a_valid_identifier_is_normalised_and_recorded(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("Reference #,Amount\nA1,10\nA2,20\n")
    source_id = await _make_source(factory, "export", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))
    assert results[0].sql_table_name == "export_csv"

    async with factory() as session:
        note = (
            await session.execute(
                text(
                    "SELECT description FROM schema_notes WHERE source_id = :id "
                    "AND column_name = 'Reference #' AND description LIKE 'Loaded as column%'"
                ),
                {"id": source_id},
            )
        ).first()
        assert note is not None
        assert "reference" in note[0]
        assert "Reference #" in note[0]


async def test_malformed_rows_are_reported_by_row_number_not_dropped_silently(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    # Nine good integers and one `oops` — confident enough (9/10 = 90%,
    # over `_MIN_TYPE_CONFIDENCE`) that `table_infer` still calls the column
    # `integer` rather than falling back to an ambiguous `string`, so the
    # bad row only ever surfaces as a real cast failure during the load.
    good_rows = "\n".join(f"person{i},{i * 10}" for i in range(1, 10))
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(f"name,amount\n{good_rows}\nBen,oops\n")
    source_id = await _make_source(factory, "sales", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))

    result = results[0]
    assert result.row_count == 9
    assert len(result.failed_rows) == 1
    # Row 1 is the header, so the 10th data row ("Ben,oops") is row 11.
    assert result.failed_rows[0].row_number == 11
    assert "oops" in result.failed_rows[0].reason


async def test_an_empty_file_is_refused_with_the_reason(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("")
    source_id = await _make_source(factory, "empty", csv_path)

    with pytest.raises(EmptyTable):
        await process_table_source(factory, table_settings, source_id, str(csv_path))

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        # Never reached the sandbox at all — nothing to create, nothing to drop.
        assert row[1] is None


async def test_the_size_cap_aborts_the_load_and_drops_the_database(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "big.csv"
    csv_path.write_text("name\n" + "\n".join(f"row{i}" for i in range(500)) + "\n")
    source_id = await _make_source(factory, "big", csv_path)

    async with factory() as session:
        await set_dump_size_cap_bytes(session, 1024)
        await session.commit()

    with pytest.raises(TableCapExceeded) as exc_info:
        await process_table_source(factory, table_settings, source_id, str(csv_path))
    assert exc_info.value.cap == "size"

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        assert row[0] == "attention"
        assert row[1] is None
        assert "size cap" in row[2]


async def test_answering_a_date_format_clarification_reloads_the_column_as_a_real_date(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    # Both parts of each value are `<= 12`, so neither disambiguates itself
    # (`table_infer.detect_date_format` returns `AMBIGUOUS`) and the column
    # loads as `text` until the clarification it raises is answered.
    csv_path = tmp_path / "registrations.csv"
    csv_path.write_text("name,registered\nAnna,03/04/2026\nBen,05/06/2026\n")
    source_id = await _make_source(factory, "registrations", csv_path)

    await process_table_source(factory, table_settings, source_id, str(csv_path))

    async with factory() as session:
        database = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).scalar_one()

    import psycopg

    admin_url = table_settings.sandbox_database_url.get_secret_value()
    dsn = admin_url.rsplit("/", 1)[0] + f"/{database}"

    # Before the clarification is answered, an undecided date column loads
    # as text, verbatim — never guessed.
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
        ).fetchall()
    assert rows[0][0] == "text"

    async with factory() as session:
        clarification = (
            await session.execute(
                text(
                    "SELECT id, options FROM clarifications WHERE source_id = :id "
                    "AND evidence->>'trigger' = 'date_format'"
                ),
                {"id": source_id},
            )
        ).one()
        clarification_id, options = clarification
        await answer_clarification(session, clarification_id, options[0])
        await session.commit()

    await reload_source(factory, table_settings, source_id)

    with psycopg.connect(dsn, autocommit=True) as conn:
        column = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
        ).fetchall()
        values = conn.execute(
            "SELECT name, registered FROM registrations_csv ORDER BY name"
        ).fetchall()
    assert column[0][0] == "date"
    # Day-first: `03/04/2026` -> 3 April, `05/06/2026` -> 5 June.
    assert values[0][1].isoformat() == "2026-04-03"
    assert values[1][1].isoformat() == "2026-06-05"


async def test_date_format_answers_are_read_from_evidence_and_from_the_old_subject_shape(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # #361 moved the table out of the subject and into the evidence. A sheet
    # name contains a colon (`data.xlsx:North`), which the old subject parse
    # split in the wrong place. An answer recorded before the change still
    # carries `"{table}: {column}"` and is still honoured.
    from askwell.table_load import _date_format_overrides

    csv_path = tmp_path / "registrations.csv"
    csv_path.write_text("name\nAnna\n")
    source_id = await _make_source(factory, "registrations", csv_path)
    options = json.dumps(["DD/MM/YYYY (day first)", "MM/DD/YYYY (month first)"])
    async with factory() as session:
        for subject, evidence, answer in (
            (
                "registered",
                {"trigger": "date_format", "table_name": "data.xlsx:North"},
                "DD/MM/YYYY (day first)",
            ),
            ("old.csv: joined", {"trigger": "date_format"}, "MM/DD/YYYY (month first)"),
            ("data.xlsx:South: left", {"trigger": "date_format"}, "DD/MM/YYYY (day first)"),
        ):
            await session.execute(
                text(
                    "INSERT INTO clarifications "
                    "(id, source_id, subject, question, options, evidence, status, answer) "
                    "VALUES (:id, :source_id, :subject, 'which?', CAST(:options AS jsonb), "
                    "CAST(:evidence AS jsonb), 'answered', :answer)"
                ),
                {
                    "id": uuid.uuid4(),
                    "source_id": source_id,
                    "subject": subject,
                    "options": options,
                    "evidence": json.dumps(evidence),
                    "answer": answer,
                },
            )
        await session.commit()

        overrides = await _date_format_overrides(session, source_id)

    assert overrides == {
        ("data.xlsx:North", "registered"): True,
        ("old.csv", "joined"): False,
        ("data.xlsx:South", "left"): True,
    }


async def test_the_reapply_job_for_a_date_format_answer_reloads_the_column_itself(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    # #361: the compound subject matched no schema note, so answering queued
    # no job and nothing reloaded unless `reload_source` was called by hand.
    from askwell import reapply

    csv_path = tmp_path / "registrations.csv"
    csv_path.write_text("name,registered\nAnna,03/04/2026\nBen,05/06/2026\n")
    source_id = await _make_source(factory, "registrations", csv_path)
    await process_table_source(factory, table_settings, source_id, str(csv_path))

    async with factory() as session:
        clarification_id, options, database = (
            await session.execute(
                text(
                    "SELECT c.id, c.options, s.sandbox_db FROM clarifications c "
                    "JOIN sources s ON s.id = c.source_id WHERE c.source_id = :id "
                    "AND c.evidence->>'trigger' = 'date_format'"
                ),
                {"id": source_id},
            )
        ).one()
        outcome = await answer_clarification(session, clarification_id, options[0])
        await session.commit()
    assert outcome.reapply_job_id is not None

    await reapply.run_job(factory, table_settings, outcome.reapply_job_id)

    import psycopg

    admin_url = table_settings.sandbox_database_url.get_secret_value()
    dsn = admin_url.rsplit("/", 1)[0] + f"/{database}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        column = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
        ).fetchall()
    assert column[0][0] == "date"

    async with factory() as session:
        note = (
            await session.execute(
                text(
                    "SELECT origin, description FROM schema_notes WHERE source_id = :id "
                    "AND column_name = 'registered' AND superseded_by IS NULL"
                ),
                {"id": source_id},
            )
        ).one()
    assert note == ("user", options[0])


# --- a workbook's sheets, loaded alongside its document (`M11-FIX-ING-224`) ---


_FIGURES: list[list[object]] = [
    ["Department", "Q1 Revenue", "Headcount", "Avg Tenure Years"],
    ["Textiles", 482000, 34, 4.1],
    ["Logistics", 215000, 19, 2.7],
    ["Research", 903000, 27, 5.6],
]


def _write_workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    workbook = openpyxl.Workbook()
    first = True
    for title, rows in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet()
        assert sheet is not None
        sheet.title = title
        for row in rows:
            sheet.append(row)
        first = False
    buffer = io.BytesIO()
    workbook.save(buffer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


async def _folder_source(factory: async_sessionmaker[AsyncSession], root: Path) -> uuid.UUID:
    async with factory() as session:
        source_id = (
            await session.execute(
                text(
                    "INSERT INTO sources (kind, name, root_path, status) "
                    "VALUES ('file', :name, :root, 'ready') RETURNING id"
                ),
                {"name": root.name, "root": str(root)},
            )
        ).scalar_one()
        await session.commit()
    return uuid.UUID(str(source_id))


async def _workbook_document(
    factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID, path: Path
) -> uuid.UUID:
    async with factory() as session:
        document_id = (
            await session.execute(
                text(
                    "INSERT INTO documents "
                    "(source_id, filename, path, mime, sha256, version, status) "
                    "VALUES (:source_id, :filename, :path, :mime, :sha256, 1, 'indexing') "
                    "RETURNING id"
                ),
                {
                    "source_id": source_id,
                    "filename": path.name,
                    "path": str(path),
                    "mime": WORKBOOK_MIME,
                    "sha256": hashlib.sha256(str(path).encode() + os.urandom(8)).hexdigest(),
                },
            )
        ).scalar_one()
        await session.commit()
    return uuid.UUID(str(document_id))


def _sandbox_tables(settings: Settings, database: str) -> dict[str, str | None]:
    admin_url = settings.sandbox_database_url.get_secret_value()
    with psycopg.connect(admin_url.rsplit("/", 1)[0] + f"/{database}", autocommit=True) as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r'"
        ).fetchall()
    return {str(name): comment for name, comment in rows}


async def _source_row(
    factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> tuple[str, str | None]:
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
    return row[0], row[1]


async def _audit(factory: async_sessionmaker[AsyncSession], kind: str) -> list[dict[str, object]]:
    async with factory() as session:
        rows = await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY id"),
            {"kind": kind},
        )
        return [dict(row[0]) for row in rows]


async def test_each_headed_sheet_of_a_workbook_loads_as_a_table_in_its_folders_sandbox(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    workbook = root / "figures.xlsx"
    _write_workbook(
        workbook,
        {
            "Quarterly Department Figures": _FIGURES,
            "Raw": [[1, 2], [3, 4], [5, 6]],
            "Blank": [],
        },
    )
    source_id = await _folder_source(factory, root)
    document_id = await _workbook_document(factory, source_id, workbook)

    outcome = await load_workbook_tables(factory, table_settings, source_id, document_id)

    assert outcome.failure is None
    assert [result.sql_table_name for result in outcome.tables] == [
        "figures_xlsx_quarterly_department_figures"
    ]
    assert outcome.tables[0].row_count == 3
    assert {sheet for sheet, _ in outcome.skipped} == {"Raw", "Blank"}

    # The folder is still the folder: its status is the documents', and the
    # sandbox database is the one C3 requires, not Askwell's own.
    status, database = await _source_row(factory, source_id)
    assert status == "ready"
    assert database is not None
    tables = _sandbox_tables(table_settings, database)
    assert tables == {"figures_xlsx_quarterly_department_figures": "askwell workbook: figures.xlsx"}
    admin_url = table_settings.sandbox_database_url.get_secret_value()
    with psycopg.connect(admin_url.rsplit("/", 1)[0] + f"/{database}", autocommit=True) as conn:
        headcount = conn.execute(
            "SELECT headcount FROM figures_xlsx_quarterly_department_figures "
            "WHERE department = 'Logistics'"
        ).fetchone()
    assert headcount == (19,)

    async with factory() as session:
        notes = (
            await session.execute(
                text(
                    "SELECT table_name, column_name, description FROM schema_notes "
                    "WHERE source_id = :id AND superseded_by IS NULL"
                ),
                {"id": source_id},
            )
        ).all()
        # Nothing asked: a folder's clarifications are its documents' (#851).
        clarifications = (
            await session.execute(
                text("SELECT count(*) FROM clarifications WHERE source_id = :id"),
                {"id": source_id},
            )
        ).scalar_one()
    assert clarifications == 0
    assert {table for table, _, _ in notes} == {"figures.xlsx:Quarterly Department Figures"}
    assert {column for _, column, _ in notes} >= {None, "Headcount", "Q1 Revenue"}
    table_note = next(description for _, column, description in notes if column is None)
    assert "figures_xlsx_quarterly_department_figures" in table_note

    [loaded] = await _audit(factory, WORKBOOK_TABLES_LOADED)
    assert loaded["source_id"] == str(source_id)
    assert loaded["document_id"] == str(document_id)
    assert loaded["tables"] == ["figures_xlsx_quarterly_department_figures"]
    assert {entry["sheet"] for entry in loaded["skipped"]} == {"Raw", "Blank"}  # type: ignore[union-attr]


async def test_two_sheets_with_the_same_headers_become_two_tables(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    workbook = root / "regions.xlsx"
    _write_workbook(workbook, {"North": _FIGURES, "South": _FIGURES[:2]})
    source_id = await _folder_source(factory, root)
    document_id = await _workbook_document(factory, source_id, workbook)

    outcome = await load_workbook_tables(factory, table_settings, source_id, document_id)

    assert [(r.sql_table_name, r.row_count) for r in outcome.tables] == [
        ("regions_xlsx_north", 3),
        ("regions_xlsx_south", 1),
    ]


async def test_reloading_one_workbook_replaces_its_own_tables_and_leaves_anothers_alone(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    # Two names that normalise to the same identifier.
    first, second = root / "a b.xlsx", root / "a_b.xlsx"
    _write_workbook(first, {"Data": _FIGURES})
    _write_workbook(second, {"Data": _FIGURES[:2]})
    source_id = await _folder_source(factory, root)
    first_id = await _workbook_document(factory, source_id, first)
    second_id = await _workbook_document(factory, source_id, second)

    await load_workbook_tables(factory, table_settings, source_id, first_id)
    await load_workbook_tables(factory, table_settings, source_id, second_id)
    # The file changed on disk and was ingested again.
    _write_workbook(first, {"Renamed": _FIGURES})
    await load_workbook_tables(factory, table_settings, source_id, first_id)

    _, database = await _source_row(factory, source_id)
    assert database is not None
    assert _sandbox_tables(table_settings, database) == {
        "a_b_xlsx_data_2": "askwell workbook: a_b.xlsx",
        "a_b_xlsx_renamed": "askwell workbook: a b.xlsx",
    }
    async with factory() as session:
        tables = set(
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT table_name FROM schema_notes "
                        "WHERE source_id = :id AND superseded_by IS NULL"
                    ),
                    {"id": source_id},
                )
            ).scalars()
        )
    assert tables == {"a b.xlsx:Renamed", "a_b.xlsx:Data"}


async def test_a_sheet_over_the_size_cap_fails_without_failing_the_document(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    workbook = root / "big.xlsx"
    _write_workbook(workbook, {"Big": [["name", "amount"]] + [[f"row{i}", i] for i in range(500)]})
    source_id = await _folder_source(factory, root)
    document_id = await _workbook_document(factory, source_id, workbook)
    async with factory() as session:
        await set_dump_size_cap_bytes(session, 1024)
        await session.commit()

    outcome = await load_workbook_tables(factory, table_settings, source_id, document_id)

    assert outcome.tables == []
    assert outcome.failure is not None
    assert "size cap" in outcome.failure
    # Nothing half-loaded is left to answer from, and the folder is untouched.
    status, database = await _source_row(factory, source_id)
    assert status == "ready"
    assert database is None
    [failed] = await _audit(factory, WORKBOOK_TABLES_FAILED)
    assert failed["source_id"] == str(source_id)
    assert failed["cap"] == "size"


async def test_a_100k_row_sheet_is_stopped_by_the_time_cap_without_failing_the_document(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    """The ticket's large-sheet edge case, at its real size: the load is
    bounded by the same time cap a CSV's is. A sheet this size does not load
    within the default cap on the build host (rows go in one at a time, the
    CSV loader's own path, #862), so the cap is lowered here to keep the
    test short; what is asserted is that the load stops, cleans up after
    itself, and records why."""
    from askwell.dump_import import set_dump_time_cap_seconds

    root = tmp_path / "work"
    workbook = root / "large.xlsx"
    _write_workbook(
        workbook, {"Ledger": [["name", "amount"]] + [[f"row{i}", i] for i in range(100_000)]}
    )
    source_id = await _folder_source(factory, root)
    document_id = await _workbook_document(factory, source_id, workbook)
    async with factory() as session:
        await set_dump_time_cap_seconds(session, 2.0)
        await session.commit()

    outcome = await load_workbook_tables(factory, table_settings, source_id, document_id)

    assert outcome.tables == []
    assert outcome.failure is not None
    assert "time cap" in outcome.failure
    status, database = await _source_row(factory, source_id)
    assert status == "ready"
    assert database is None
    [failed] = await _audit(factory, WORKBOOK_TABLES_FAILED)
    assert failed["source_id"] == str(source_id)
    assert failed["cap"] == "time"


async def test_deleting_a_workbook_takes_its_tables_out_of_every_answer_then_drops_them(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    """#852. The notes go with the delete — they are all SQL generation and
    routing ever see — and the tables go at the next sweep. Another
    workbook in the same folder is untouched."""
    from askwell.sources import delete_document

    root = tmp_path / "work"
    gone, kept = root / "gone.xlsx", root / "kept.xlsx"
    _write_workbook(gone, {"Data": _FIGURES})
    _write_workbook(kept, {"Data": _FIGURES})
    source_id = await _folder_source(factory, root)
    gone_id = await _workbook_document(factory, source_id, gone)
    kept_id = await _workbook_document(factory, source_id, kept)
    await load_workbook_tables(factory, table_settings, source_id, gone_id)
    await load_workbook_tables(factory, table_settings, source_id, kept_id)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO schema_notes (id, source_id, table_name, column_name, description, "
                "origin, confidence) VALUES (:id, :source_id, 'gone.xlsx:Data', 'Headcount', "
                "'People on the payroll.', 'user', 1.0)"
            ),
            {"id": uuid.uuid4(), "source_id": source_id},
        )
        assert await delete_document(session, gone_id, None, 0.6, table_settings)
        await session.commit()

        notes = (
            await session.execute(
                text(
                    "SELECT table_name, origin, stale FROM schema_notes "
                    "WHERE source_id = :id AND left(table_name, 10) = 'gone.xlsx:'"
                ),
                {"id": source_id},
            )
        ).all()
    assert notes == [("gone.xlsx:Data", "user", True)]

    assert await sweep_workbook_tables(factory, table_settings) == 1
    _, database = await _source_row(factory, source_id)
    assert database is not None
    assert _sandbox_tables(table_settings, database) == {
        "kept_xlsx_data": "askwell workbook: kept.xlsx"
    }
    # Nothing left to drop, and the owner's grant is not reopened for it.
    assert await sweep_workbook_tables(factory, table_settings) == 0


async def test_deleting_an_older_version_leaves_the_newer_ones_tables(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    from askwell.table_load import forget_deleted_workbook

    root = tmp_path / "work"
    workbook = root / "figures.xlsx"
    _write_workbook(workbook, {"Data": _FIGURES})
    source_id = await _folder_source(factory, root)
    older = await _workbook_document(factory, source_id, workbook)
    newer = await _workbook_document(factory, source_id, workbook)
    await load_workbook_tables(factory, table_settings, source_id, newer)

    async with factory() as session:
        await session.execute(
            text("UPDATE documents SET deleted_at = now(), status = 'deleted' WHERE id = :id"),
            {"id": older},
        )
        await forget_deleted_workbook(session, older)
        await session.commit()
        remaining = (
            await session.execute(
                text("SELECT count(*) FROM schema_notes WHERE source_id = :id AND NOT stale"),
                {"id": source_id},
            )
        ).scalar_one()
    assert remaining > 0
    assert await sweep_workbook_tables(factory, table_settings) == 0


async def test_a_sheets_inferred_notes_stay_out_of_a_document_answer_and_in_sql_generation(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    """#857. The same workbook is also passages, which carry the same numbers
    with a citation. A note Askwell inferred about a sheet column ("Loaded
    as column `q1_revenue`") is for writing SQL; in a document answer it
    competes with the passage and gets cited in its place. What a person
    said about a sheet is memory, and still applies."""
    from askwell.memory import retrieve_relevant_facts

    root = tmp_path / "work"
    workbook = root / "figures.xlsx"
    _write_workbook(workbook, {"Figures": _FIGURES})
    source_id = await _folder_source(factory, root)
    document_id = await _workbook_document(factory, source_id, workbook)
    await load_workbook_tables(factory, table_settings, source_id, document_id)
    question = "What was the Q1 revenue of the Research department, per the figures?"

    async with factory() as session:
        for_sql = await retrieve_relevant_facts(session, question=question, source_id=source_id)
        for_documents = await retrieve_relevant_facts(
            session, question=question, include_inferred_sheet_notes=False
        )
    assert {note.origin for note in for_sql.notes} == {"inferred"}
    assert for_documents.notes == []

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO schema_notes (id, source_id, table_name, column_name, description, "
                "origin, confidence) VALUES (:id, :source_id, 'figures.xlsx:Figures', "
                "'Q1 Revenue', 'Q1 revenue is in US dollars.', 'user', 1.0)"
            ),
            {"id": uuid.uuid4(), "source_id": source_id},
        )
        await session.commit()
        for_documents = await retrieve_relevant_facts(
            session, question=question, include_inferred_sheet_notes=False
        )
    assert [(note.origin, note.description) for note in for_documents.notes] == [
        ("user", "Q1 revenue is in US dollars.")
    ]
