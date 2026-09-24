"""A document's own date, and where it came from. `M7-FIX-BE-170a`.

Until this module, the only date Askwell held for a document was `added_at` —
when it was ingested. Two versions of a handbook added in the same minute got
the same date, and a 2024 file added after a 2026 one looked newer. The
conflicting-sources state (`docs/ux/ask.md` §5) has to show which of two
documents is current, and ingest order is exactly the wrong evidence for that.

**Three columns, never one.** `documents.document_date` is the date;
`document_date_precision` (`day` | `month` | `year`) says how much of it is
real, because `store_hours_2026.pdf` carries a year and rendering it as
"1 January 2026" is a wrong fact presented as a right one. The stored value is
the first day of the period; `as_iso` is what leaves the API, truncated to the
precision, so a caller cannot render the padding even by accident.
`document_date_source` (`metadata` | `filename`) says where it came from,
because file metadata is a *claimed* date — a PDF re-exported in 2026 from a
2019 original says 2026 — and the interface must be able to say so rather
than present it as authoritative.

**Order: format metadata, then the filename, then nothing.** Metadata first
because `Handbook.pdf` with a correct `/ModDate` is the common real case;
the filename second because the fixture corpus (`store_hours_2025.pdf`,
`store_hours_2026.pdf`) carries no `/Info` dictionary at all. Null means
unknown. **`added_at` is never a fallback, on any path** — nothing here reads
it, and the write in `record` always sets all three columns, including back
to null, so a re-index cannot leave a stale date behind.

**Modified before created.** "Which of these is newer" is a question about
the content's last revision. The usual way a second version comes to exist is
opening the first and saving it again, which keeps the original's creation
date and moves only the modification date — so `/CreationDate` or
`dcterms:created` alone would date the 2026 handbook to 2025. Created is used
when modified is absent, unparseable, implausible or in the future.

**OOXML core properties are read from the zip directly, not through
`python-docx`, `python-pptx` or `openpyxl`.** All three fill in a missing
core-properties part with defaults, and `openpyxl`'s default `created` is the
moment the file was opened — the ingest time again, wearing a metadata label.
Reading `docProps/core.xml` ourselves means an absent value stays absent.
The part is size-capped before parsing, and parsed with the standard library's
`ElementTree`, which resolves no external entities; the bundled expat
(≥ 2.4) refuses entity-expansion bombs.

**Conservative on purpose.** The filename pattern recognises only `YYYY`,
`YYYY-MM` and `YYYY-MM-DD` (with `-` or `_`, used consistently), as a whole
digit run — `invoice_20500` and `2025-26` are not dates here. Two candidates:
the more specific wins; two equally specific and different: null, not a
guess. A date after today, from either source, is ignored — a document cannot
have been written in the future, and a clock set wrong is the likelier story.
Any failure reading metadata falls through to the filename and never fails
the ingest: a date is a nicety, the document's text is the point.
"""

import re
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePath
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text

from askwell.db.engine import session_scope
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Work

log = get_logger(__name__)

Precision = Literal["day", "month", "year"]
Source = Literal["metadata", "filename"]

PRECISIONS: tuple[Precision, ...] = ("day", "month", "year")
SOURCES: tuple[Source, ...] = ("metadata", "filename")

_RANK: dict[Precision, int] = {"year": 0, "month": 1, "day": 2}

# PDF is 1993 and OOXML 2006: a metadata date before 1990 is a zeroed or
# defaulted clock (the DOS epoch, OLE's 1899-12-30), not a real one. A
# filename is typed by a person and may legitimately name an older year —
# `minutes_1965.pdf` is a scan of something real.
METADATA_MIN_YEAR = 1990
FILENAME_MIN_YEAR = 1900

# `docProps/core.xml` is a few hundred bytes in practice. The cap is what stops
# a hostile zip entry from inflating to gigabytes before anything parses it.
_CORE_XML_MAX_BYTES = 1 << 20
_CORE_XML = "docProps/core.xml"
_DCTERMS = "{http://purl.org/dc/terms/}"

# `D:YYYYMMDDHHmmSS...` — ISO 32000-1 §7.9.4. Everything after the year is
# optional, and a missing month or day is a real, lower precision.
_PDF_DATE = re.compile(r"(?:D:)?(\d{4})(\d{2})?(\d{2})?")
# W3CDTF, which `dcterms:created`/`modified` use: `YYYY`, `YYYY-MM`,
# `YYYY-MM-DD`, optionally followed by a time.
_W3C_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?:T.*)?")
# A maximal run of digits joined by `-`/`_`, then judged whole.
_DIGIT_RUN = re.compile(r"\d+(?:[-_]\d+)*")
_FILENAME_DATE = re.compile(r"(\d{4})(?:([-_])(\d{2})(?:\2(\d{2}))?)?")


@dataclass(frozen=True, slots=True)
class DocumentDate:
    """A document's own date: the first day of the period, how much of it is
    meaningful, and where it was read from."""

    value: date
    precision: Precision
    source: Source

    def as_iso(self) -> str:
        """`2026`, `2026-03` or `2026-03-15` — never more than is known."""
        return iso_for(self.value, self.precision)


def iso_for(value: date, precision: str) -> str:
    if precision == "year":
        return f"{value.year:04d}"
    if precision == "month":
        return f"{value.year:04d}-{value.month:02d}"
    return value.isoformat()


def _today() -> date:
    return datetime.now(UTC).date()


def _build(
    year: str,
    month: str | None,
    day: str | None,
    *,
    source: Source,
    min_year: int,
    today: date,
) -> DocumentDate | None:
    """A validated date, or `None` if any part is impossible or it is later
    than today at its own precision."""
    precision: Precision = "day" if day else "month" if month else "year"
    try:
        value = date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    if value.year < min_year:
        return None
    if precision == "year" and value.year > today.year:
        return None
    if precision == "month" and (value.year, value.month) > (today.year, today.month):
        return None
    if precision == "day" and value > today:
        return None
    return DocumentDate(value, precision, source)


def _first_plausible(
    raws: Iterable[str | None], parse: Callable[[str, date], DocumentDate | None], today: date
) -> DocumentDate | None:
    for raw in raws:
        if not raw:
            continue
        found = parse(raw.strip(), today)
        if found is not None:
            return found
    return None


def _parse_pdf_date(raw: str, today: date) -> DocumentDate | None:
    match = _PDF_DATE.match(raw)
    if match is None:
        return None
    year, month, day = match.groups()
    return _build(year, month, day, source="metadata", min_year=METADATA_MIN_YEAR, today=today)


def _parse_w3c_date(raw: str, today: date) -> DocumentDate | None:
    match = _W3C_DATE.fullmatch(raw)
    if match is None:
        return None
    year, month, day = match.groups()
    return _build(year, month, day, source="metadata", min_year=METADATA_MIN_YEAR, today=today)


def from_pdf_metadata(
    metadata: Mapping[str, str], *, today: date | None = None
) -> DocumentDate | None:
    """From a PDF `/Info` dictionary as `pypdfium2.PdfDocument.get_metadata_dict`
    returns it — `ModDate`, then `CreationDate`."""
    return _first_plausible(
        (metadata.get("ModDate"), metadata.get("CreationDate")),
        _parse_pdf_date,
        today or _today(),
    )


def from_ooxml(path: str, *, today: date | None = None) -> DocumentDate | None:
    """From an OOXML package's `docProps/core.xml` — `dcterms:modified`, then
    `dcterms:created`. `None` if the part is missing, oversized or malformed:
    the caller falls through to the filename."""
    try:
        with zipfile.ZipFile(path) as package:
            try:
                info = package.getinfo(_CORE_XML)
            except KeyError:
                return None
            if info.file_size > _CORE_XML_MAX_BYTES:
                return None
            with package.open(info) as part:
                body = part.read(_CORE_XML_MAX_BYTES + 1)
        if len(body) > _CORE_XML_MAX_BYTES:
            return None
        root = ElementTree.fromstring(body)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as error:
        log.warning("document_date_metadata_unreadable", error=type(error).__name__)
        return None
    return _first_plausible(
        (root.findtext(f"{_DCTERMS}modified"), root.findtext(f"{_DCTERMS}created")),
        _parse_w3c_date,
        today or _today(),
    )


def from_filename(filename: str, *, today: date | None = None) -> DocumentDate | None:
    """A date written into the file's name, or `None` if there is none or it
    is ambiguous."""
    today = today or _today()
    candidates: set[DocumentDate] = set()
    for run in _DIGIT_RUN.findall(PurePath(filename).stem):
        match = _FILENAME_DATE.fullmatch(run)
        if match is None:
            continue
        year, _separator, month, day = match.groups()
        found = _build(year, month, day, source="filename", min_year=FILENAME_MIN_YEAR, today=today)
        if found is not None:
            candidates.add(found)
    if not candidates:
        return None
    best = max(_RANK[candidate.precision] for candidate in candidates)
    most_specific = [c for c in candidates if _RANK[c.precision] == best]
    return most_specific[0] if len(most_specific) == 1 else None


def resolve(
    metadata: DocumentDate | None, filename: str, *, today: date | None = None
) -> DocumentDate | None:
    return metadata or from_filename(filename, today=today)


async def record(
    factory: "async_sessionmaker[AsyncSession]",
    work: "Work",
    metadata: DocumentDate | None,
) -> DocumentDate | None:
    """Resolve and write all three columns — to null as well, so a re-index
    that no longer finds a date does not leave the previous one standing."""
    found = resolve(metadata, work.filename)
    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE documents SET document_date = :value, "
                "document_date_precision = :precision, document_date_source = :source "
                "WHERE id = :id"
            ),
            {
                "value": found.value if found else None,
                "precision": found.precision if found else None,
                "source": found.source if found else None,
                "id": work.document_id,
            },
        )
    log.info(
        "document_date_recorded",
        document_id=str(work.document_id),
        precision=found.precision if found else None,
        source=found.source if found else None,
    )
    return found
