"""Parse a CSV, TSV or spreadsheet into typed columns before anything loads.

`docs/data-sources.md` §2: "A CSV has no types, no constraints and frequently
no usable header. Inferring and moving on is what produces confidently wrong
answers about numbers, which is the worst failure this product has." So
nothing here is applied silently. `infer_table` decides delimiter, encoding,
header and per-column type, always with a confidence, and hands back
`Candidate`s (`askwell.clarify`) for anything it cannot resolve on its own —
a missing or blank header, a column whose values do not agree on one type,
or (`M4-CSV-ING-093`) a date column whose values do not disambiguate
DD/MM from MM/DD. Loading the inferred table into the sandbox as a queryable
table (`M4-CSV-ING-094`) is out of this ticket's scope; this module only
parses, infers, detects and raises.

**`.csv`/`.tsv` and `.xlsx` both land here.** `docs/data-sources.md` §8 settled
multi-sheet and merged-header handling as "one sheet becomes one table, and
merged header cells raise a clarification rather than being guessed" — the
same "ask, never infer" rule the date format gets. `extract_xlsx.py`'s own
docstring names this module as where the *queryable* read of a workbook
belongs, distinct from its own document-style read of the same bytes.
"""

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import openpyxl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.audit import Store, record
from askwell.clarify import (
    Candidate,
    RaiseResult,
    column_distribution_evidence,
    get_clarification_cap,
)
from askwell.logging import get_logger

log = get_logger(__name__)

# The four separators Askwell recognises without asking. Anything else is
# still parsed if `csv.Sniffer` names it, but these are tried first and are
# what the confidence score is judged against.
_DELIMITER_CANDIDATES = (",", ";", "\t", "|")

# What `sniff_delimiter` reports for a file with exactly one column. Not a
# real separator — chosen so it can never appear in decoded text (`extract`'s
# own `looks_textual` already refuses any file containing a NUL byte), so
# `csv.reader` never splits a one-column row on it by accident.
SINGLE_COLUMN = "\x00"

# How many data rows are sampled to infer a column's type. A column of a
# million rows does not need a million rows read to know it is an integer;
# it needs enough that a genuine mix is not mistaken for one bad row.
MAX_TYPE_SAMPLE = 500

# How many malformed row numbers are named before the rest are folded into a
# count — the same bound `clarify.EVIDENCE_MAX_SAMPLES` uses, for the same
# reason: enough to be convincing, not the whole file.
MAX_MALFORMED_ROWS_NAMED = 10

_TRUE_VALUES = frozenset({"true", "t", "yes", "y", "1"})
_FALSE_VALUES = frozenset({"false", "f", "no", "n", "0"})

# Recognises that a value has the *shape* of a date, so a date-shaped column
# is typed "date" rather than "string". Three shapes: ISO (`2026-01-01`,
# unambiguous), a named month (`4 January 2026`, unambiguous), and a numeric
# `d[/-]d[/-]y` triple, which is the one `docs/data-sources.md` §2 warns
# about — `03/04/2025` is valid as either DD/MM or MM/DD and means a
# different month either way. `detect_date_format` below is what decides
# whether that numeric shape disambiguates itself; this pattern only says
# "date-shaped", never which format.
_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$|^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}$"
)
_NUMERIC_DATE_PATTERN = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_PLAIN_DECIMAL_PATTERN = re.compile(r"^[+-]?\d+\.\d+$")
_THOUSANDS_DECIMAL_PATTERN = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")

# A type has to win by more than a coin flip to be reported with any
# confidence. Below this, `infer_column_types` reports "string" and flags the
# column as ambiguous rather than picking the majority type and hiding how
# close the runner-up was.
_MIN_TYPE_CONFIDENCE = 0.8


class HeaderVerdict(StrEnum):
    """Whether the first row is names or data. `AMBIGUOUS` is the honest
    third answer — `docs/data-sources.md` §2's whole point is that guessing
    here is worse than asking."""

    PRESENT = "present"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


class MalformedTable(ValueError):
    """A file whose rows do not agree on a column count.

    Raised rather than silently padded or truncated — the ticket's own edge
    case. `row_numbers` is 1-indexed against the file as the user would count
    it (the header, if any, is row 1), bounded to
    `MAX_MALFORMED_ROWS_NAMED` with `total` carrying the real count.
    """

    def __init__(self, row_numbers: list[int], total: int, expected: int) -> None:
        self.row_numbers = row_numbers
        self.total = total
        self.expected = expected
        shown = ", ".join(str(n) for n in row_numbers)
        more = f" and {total - len(row_numbers)} more" if total > len(row_numbers) else ""
        super().__init__(f"{total} row(s) do not have {expected} column(s): row(s) {shown}{more}.")


@dataclass(frozen=True, slots=True)
class EncodingDetection:
    encoding: str
    confidence: float
    # What decoding a document without any detection would have assumed —
    # named so the review surface can say "detected windows-1252, not the
    # UTF-8 Askwell defaults to" rather than just naming the winner.
    default_assumed: str = "utf-8"

    def as_dict(self) -> dict[str, object]:
        return {
            "encoding": self.encoding,
            "confidence": self.confidence,
            "default_assumed": self.default_assumed,
        }


@dataclass(frozen=True, slots=True)
class DelimiterDetection:
    delimiter: str
    confidence: float

    def as_dict(self) -> dict[str, object]:
        label = {
            ",": "comma",
            ";": "semicolon",
            "\t": "tab",
            "|": "pipe",
            SINGLE_COLUMN: "single column (no delimiter)",
        }.get(self.delimiter, self.delimiter)
        return {"delimiter": label, "confidence": self.confidence}


@dataclass(frozen=True, slots=True)
class HeaderDetection:
    verdict: HeaderVerdict
    confidence: float
    names: list[str]
    reason: str


class DateFormatVerdict(StrEnum):
    """Whether a date-shaped column's numeric `d/d/y` values disambiguate
    day-first from month-first. `NOT_APPLICABLE` covers a column with no
    numeric-slash-or-dash values at all (ISO, named-month, or not a date
    column) — nothing to disambiguate, so nothing is asked or recorded."""

    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"
    AMBIGUOUS = "ambiguous"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class DateFormatDetection:
    verdict: DateFormatVerdict
    # The disambiguating value and why, present only for DAY_FIRST/MONTH_FIRST
    # — the evidence `raise_table_inference` records the inference with.
    evidence_value: str | None = None
    evidence_reason: str | None = None


def detect_date_format(values: list[str]) -> DateFormatDetection:
    """Never guesses: a numeric date column only gets a verdict other than
    `AMBIGUOUS` when a value's own shape rules one format out — one of the
    two `d/d` positions holding something above 12, which cannot be a month.

    Rows that decide the format in *opposite* directions (one value only
    valid as day-first, another only valid as month-first) mean the column
    itself is inconsistent — `MIXED`, the edge case
    `docs/build-plan.md`'s M4-CSV-ING-093 calls out as "reported as malformed
    rather than asked about as if it were consistent": offering a single
    DD/MM-or-MM/DD choice would be wrong when no one answer fits every row.
    """
    day_first_evidence: tuple[str, str] | None = None
    month_first_evidence: tuple[str, str] | None = None
    saw_numeric_date = False

    for raw_value in values:
        match = _NUMERIC_DATE_PATTERN.match(raw_value.strip())
        if not match:
            continue
        saw_numeric_date = True
        first, second, _year = int(match.group(1)), int(match.group(2)), match.group(3)
        if first > 12 and second > 12:
            # Neither position can be a month — not a real date under either
            # format. Noise, not evidence either way.
            continue
        if first > 12 and day_first_evidence is None:
            day_first_evidence = (raw_value, f"the first value, {first}, cannot be a month")
        elif second > 12 and month_first_evidence is None:
            month_first_evidence = (raw_value, f"the second value, {second}, cannot be a month")

    if not saw_numeric_date:
        return DateFormatDetection(DateFormatVerdict.NOT_APPLICABLE)
    if day_first_evidence and month_first_evidence:
        return DateFormatDetection(DateFormatVerdict.MIXED)
    if day_first_evidence:
        return DateFormatDetection(DateFormatVerdict.DAY_FIRST, *day_first_evidence)
    if month_first_evidence:
        return DateFormatDetection(DateFormatVerdict.MONTH_FIRST, *month_first_evidence)
    return DateFormatDetection(DateFormatVerdict.AMBIGUOUS)


@dataclass(frozen=True, slots=True)
class ColumnInference:
    name: str
    inferred_type: str
    confidence: float
    sample_values: list[str]
    ambiguous: bool
    ambiguity_reason: str | None = None
    # Set only for a `date`-typed column: `NOT_APPLICABLE` when nothing
    # needed disambiguating, `AMBIGUOUS`/`MIXED` when `ambiguous` is also
    # True for this column, `DAY_FIRST`/`MONTH_FIRST` when the format was
    # inferred (`ambiguous` stays False — this is a recorded inference, not
    # an open question).
    date_format: DateFormatDetection | None = None


@dataclass(frozen=True, slots=True)
class TableInference:
    table_name: str
    sheet: str | None
    encoding: EncodingDetection | None
    delimiter: DelimiterDetection | None
    header: HeaderDetection
    columns: list[ColumnInference]
    row_count: int
    merged_header: bool = False
    candidates: list[Candidate] = field(default_factory=list)
    # The data rows themselves (header already stripped, if one was detected).
    # `M4-CSV-ING-094` (`askwell.table_load`) is what actually loads them into
    # the sandbox — carried here rather than re-parsed a second time from the
    # raw bytes, which would duplicate this module's own delimiter/encoding/
    # header logic in a second place.
    rows: list[list[str]] = field(default_factory=list)


# --- encoding -----------------------------------------------------------


def sniff_encoding(raw: bytes) -> EncodingDetection:
    """Byte-order marks settle it outright; everything else is a fallback
    ladder, tried in the order a mis-decode would be most visible.

    `windows-1252` almost never raises on decode (only five byte values in
    it are undefined), so it cannot be reached by "did it decode" alone —
    it is tried before the always-succeeding `latin-1` specifically so a
    file that is genuinely Windows-authored is named as such rather than
    reported as the technically-correct but practically-useless `latin-1`.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return EncodingDetection("utf-8-sig", 1.0)
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return EncodingDetection("utf-32", 1.0)
    if raw.startswith(b"\xff\xfe"):
        return EncodingDetection("utf-16-le", 1.0)
    if raw.startswith(b"\xfe\xff"):
        return EncodingDetection("utf-16-be", 1.0)

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        confidence = 1.0 if all(byte < 0x80 for byte in raw) else 0.9
        return EncodingDetection("utf-8", confidence)

    try:
        raw.decode("windows-1252")
    except UnicodeDecodeError:
        pass
    else:
        return EncodingDetection("windows-1252", 0.6)

    # `latin-1` maps every byte to a code point and cannot fail. Confidence
    # is low on purpose: this is the "nothing else worked" answer, not a
    # positive identification.
    return EncodingDetection("latin-1", 0.3)


# --- delimiter and parsing ------------------------------------------------


def sniff_delimiter(sample: str) -> DelimiterDetection:
    """Prefer `csv.Sniffer`, which reads more of the sample than one line;
    fall back to counting candidate separators across several lines when the
    sniffer has too little structure to go on.

    Judged on *consistency* across lines, not on which candidate appears
    most often — a single-column file of numbers formatted with a thousands
    separator (`1,200.00`) has a comma in most data rows and none in a
    one-word header, and a plain frequency count would misread that comma as
    the column separator and then fail every row as malformed, since the
    comma's position (and so its count per row) varies with each number's
    size. A real delimiter appears the *same number of times* on nearly
    every line; `1,200.00` does not repeat that pattern reliably (`12,000`
    has one comma, `1,200,000` has two, `500` has none) so it never reaches
    the consistency bar below. When no candidate clears it, the file is one
    column, and the delimiter returned is `SINGLE_COLUMN` — a character
    chosen so it cannot appear in decoded text, so `parse_rows` never
    accidentally splits a one-column row on it.
    """
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITER_CANDIDATES))
        if dialect.delimiter in _DELIMITER_CANDIDATES:
            return DelimiterDetection(dialect.delimiter, 0.9)
    except csv.Error:
        pass

    lines = [line for line in sample.splitlines() if line][:20]
    if not lines:
        return DelimiterDetection(SINGLE_COLUMN, 0.5)

    best_delimiter: str | None = None
    best_consistency = 0.0
    for candidate in _DELIMITER_CANDIDATES:
        counts = [line.count(candidate) for line in lines]
        nonzero = [count for count in counts if count]
        if not nonzero:
            continue
        mode_count = max(set(nonzero), key=nonzero.count)
        consistency = sum(1 for count in counts if count == mode_count) / len(counts)
        if consistency > best_consistency:
            best_consistency = consistency
            best_delimiter = candidate

    if best_delimiter is None or best_consistency < 0.6:
        return DelimiterDetection(SINGLE_COLUMN, 1 - best_consistency)
    return DelimiterDetection(best_delimiter, best_consistency)


def parse_rows(text_content: str, delimiter: str) -> list[list[str]]:
    """Every row, same length or `MalformedTable`. The expected width is the
    modal row length — more forgiving of one short first row than "whatever
    the first row happens to be", and still exact about what disagrees with
    it."""
    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
    rows = [row for row in reader if row]
    if not rows:
        return []

    lengths: dict[int, int] = {}
    for row in rows:
        lengths[len(row)] = lengths.get(len(row), 0) + 1
    expected = max(lengths, key=lambda length: lengths[length])

    bad = [i + 1 for i, row in enumerate(rows) if len(row) != expected]
    if bad:
        raise MalformedTable(bad[:MAX_MALFORMED_ROWS_NAMED], len(bad), expected)
    return rows


# --- header detection ------------------------------------------------------


def _looks_typed(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return bool(
        _INTEGER_PATTERN.match(value)
        or _PLAIN_DECIMAL_PATTERN.match(value)
        or _THOUSANDS_DECIMAL_PATTERN.match(value)
        or _DATE_PATTERN.match(value)
        or value.lower() in _TRUE_VALUES
        or value.lower() in _FALSE_VALUES
    )


def detect_header(rows: list[list[str]]) -> HeaderDetection:
    """First row against the rest, column by column: if a column's data rows
    are mostly typed values and the first row's own cell there is not, that
    column votes "header present". The fraction of columns voting that way
    is the confidence, in both directions — the honest middle ground is
    `AMBIGUOUS`, not a coin flip dressed up as a decision.
    """
    if not rows:
        return HeaderDetection(HeaderVerdict.ABSENT, 0.0, [], "the file is empty")

    first, rest = rows[0], rows[1:]
    if not rest:
        # One row only: nothing to compare it against. Treated as data, not
        # names, because assuming a lone row is a header with no data behind
        # it is a bigger leap than the reverse.
        return HeaderDetection(
            HeaderVerdict.ABSENT,
            0.3,
            [f"Column {i + 1}" for i in range(len(first))],
            "only one row — nothing to compare it against",
        )

    # A column votes only when its data actually says something: if the data
    # beneath it settles on one non-string type (integer, decimal, boolean,
    # date), the first cell either matches that type too (a vote *against* a
    # header — it looks like one more data row) or does not (a vote *for*
    # one — it reads as a label). A column whose data is itself all text
    # (names, free-form notes) gives no signal either way and is excluded
    # from both the vote and the denominator, rather than counted as a "no".
    votes_present = 0
    signal_columns = 0
    width = len(first)
    for column in range(width):
        data_values = [row[column] for row in rest if column < len(row) and row[column].strip()]
        if not data_values:
            continue
        kinds: dict[str, int] = {}
        for value in data_values:
            kind = _classify(value)
            if kind is not None:
                kinds[kind] = kinds.get(kind, 0) + 1
        majority_kind, majority_count = max(kinds.items(), key=lambda item: item[1])
        if majority_kind == "string" or majority_count / len(data_values) < 0.7:
            continue
        signal_columns += 1
        if _classify(first[column]) != majority_kind:
            votes_present += 1
    confidence = votes_present / signal_columns if signal_columns else 0.5

    if signal_columns == 0:
        return HeaderDetection(
            HeaderVerdict.AMBIGUOUS,
            0.5,
            [cell.strip() for cell in first],
            "every column is free-form text — the data gives no typed signal either way",
        )

    if confidence >= 0.7:
        return HeaderDetection(
            HeaderVerdict.PRESENT,
            confidence,
            [cell.strip() for cell in first],
            "first row reads as names, the rest as typed data",
        )
    if confidence <= 0.3:
        return HeaderDetection(
            HeaderVerdict.ABSENT,
            1 - confidence,
            [f"Column {i + 1}" for i in range(width)],
            "the first row has the same shape as the data beneath it",
        )
    return HeaderDetection(
        HeaderVerdict.AMBIGUOUS,
        confidence,
        [cell.strip() for cell in first],
        "some columns read as headed, some do not — not enough to decide",
    )


# --- column type inference --------------------------------------------------


def _classify(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.lower() in _TRUE_VALUES or value.lower() in _FALSE_VALUES:
        return "boolean"
    if _INTEGER_PATTERN.match(value):
        return "integer"
    if _PLAIN_DECIMAL_PATTERN.match(value) or _THOUSANDS_DECIMAL_PATTERN.match(value):
        return "decimal"
    if _DATE_PATTERN.match(value):
        return "date"
    return "string"


def _mixed_number_format(values: list[str]) -> bool:
    """`amount` mixing `1,200.00` and `1200.5` — `docs/data-sources.md` §2's
    own example. Not "does it parse", since both forms parse fine on their
    own; it is that *both shapes appear in the same column*, which is exactly
    the case Askwell must not silently pick a side on."""
    has_thousands = any(_THOUSANDS_DECIMAL_PATTERN.match(v.strip()) for v in values)
    has_plain = any(_PLAIN_DECIMAL_PATTERN.match(v.strip()) for v in values)
    return has_thousands and has_plain


def infer_column_types(rows: list[list[str]], column_names: list[str]) -> list[ColumnInference]:
    """One `ColumnInference` per header name, judged over up to
    `MAX_TYPE_SAMPLE` data rows. A column where no single type reaches
    `_MIN_TYPE_CONFIDENCE` is reported as `string` and `ambiguous=True` —
    never silently coerced to whichever type happened to win a bare
    plurality."""
    sample = rows[:MAX_TYPE_SAMPLE]
    columns = []
    for index, name in enumerate(column_names):
        values = [row[index] for row in sample if index < len(row) and row[index].strip()]
        if not values:
            columns.append(
                ColumnInference(name, "string", 0.0, [], True, "column is entirely empty")
            )
            continue

        counts: dict[str, int] = {}
        for value in values:
            kind = _classify(value)
            if kind is not None:
                counts[kind] = counts.get(kind, 0) + 1
        best_type, best_count = max(counts.items(), key=lambda item: item[1])
        confidence = best_count / len(values)
        samples = values[:5]

        if best_type == "decimal" and _mixed_number_format(values):
            columns.append(
                ColumnInference(
                    name,
                    "string",
                    confidence,
                    samples,
                    True,
                    "mixes a thousands separator with a plain decimal — units and "
                    "format are ambiguous",
                )
            )
            continue

        if confidence < _MIN_TYPE_CONFIDENCE:
            columns.append(
                ColumnInference(
                    name,
                    "string",
                    confidence,
                    samples,
                    True,
                    f"no single type reaches {_MIN_TYPE_CONFIDENCE:.0%} agreement "
                    f"(best: {best_type} at {confidence:.0%})",
                )
            )
            continue

        if best_type == "date":
            date_format = detect_date_format(values)
            if date_format.verdict is DateFormatVerdict.MIXED:
                columns.append(
                    ColumnInference(
                        name,
                        "string",
                        confidence,
                        samples,
                        True,
                        "mixes date formats inconsistently — some values are only valid "
                        "day-first, others only valid month-first, so no single format fits "
                        "every row; reported as malformed rather than asked about as one format",
                        date_format,
                    )
                )
                continue
            if date_format.verdict is DateFormatVerdict.AMBIGUOUS:
                columns.append(
                    ColumnInference(
                        name,
                        best_type,
                        confidence,
                        samples,
                        True,
                        "is a date column whose values do not disambiguate between "
                        "day-first (DD/MM) and month-first (MM/DD)",
                        date_format,
                    )
                )
                continue
            columns.append(
                ColumnInference(name, best_type, confidence, samples, False, None, date_format)
            )
            continue

        columns.append(ColumnInference(name, best_type, confidence, samples, False))
    return columns


# --- candidates: what cannot be inferred ------------------------------------


def _column_evidence(values: list[str], row_count: int) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return column_distribution_evidence(sorted(counts.items()), row_count)


def build_candidates(
    table_name: str,
    header: HeaderDetection,
    columns: list[ColumnInference],
    rows: list[list[str]],
) -> list[Candidate]:
    """Everything `infer_table` could not resolve on its own, as
    `askwell.clarify.Candidate`s — the same shape M3's triggers produce, so
    the review surface (`docs/ux/clarifications.md` §3) needs no
    table-specific rendering."""
    candidates: list[Candidate] = []

    if header.verdict is HeaderVerdict.AMBIGUOUS:
        preview_rows = rows[:3]
        candidates.append(
            Candidate(
                trigger="table_header",
                subject=f"{table_name}: header row",
                question=(
                    f"Does *{table_name}* have a header row? First row: {', '.join(header.names)}."
                ),
                passes=True,
                reason="header presence could not be determined from the data",
                options=["Yes, it's a header", "No, it's data"],
                evidence={
                    "kind": "table_preview",
                    "rows": preview_rows,
                    "reason": header.reason,
                },
            )
        )
    elif header.verdict is HeaderVerdict.ABSENT:
        candidates.append(
            Candidate(
                trigger="table_header",
                subject=f"{table_name}: header row",
                question=(
                    f"*{table_name}* has no header row. What should its "
                    f"{len(header.names)} column(s) be called?"
                ),
                passes=True,
                reason="no header row detected",
                evidence={
                    "kind": "table_preview",
                    "rows": rows[:3],
                    "reason": header.reason,
                },
            )
        )

    for index, name in enumerate(header.names):
        if header.verdict is HeaderVerdict.PRESENT and not name.strip():
            values = [row[index] for row in rows if index < len(row) and row[index].strip()]
            candidates.append(
                Candidate(
                    trigger="table_column",
                    subject=f"{table_name}: column {index + 1}",
                    question=f"Column {index + 1} of *{table_name}* has no header. What is it?",
                    passes=True,
                    reason="header cell is blank",
                    evidence=_column_evidence(values, len(rows)),
                )
            )

    for column in columns:
        if not column.ambiguous or not column.name.strip():
            continue
        column_is_ambiguous_date = (
            column.date_format is not None
            and column.date_format.verdict is DateFormatVerdict.AMBIGUOUS
        )
        if column_is_ambiguous_date:
            candidates.append(
                Candidate(
                    trigger="date_format",
                    subject=f"{table_name}: {column.name}",
                    question=(
                        f"*{column.name}* looks like a date in DD/MM/YYYY or MM/DD/YYYY — "
                        f"which is it? For example: {', '.join(column.sample_values[:3])}."
                    ),
                    passes=True,
                    reason=column.ambiguity_reason or "date format could not be determined",
                    options=["DD/MM/YYYY (day first)", "MM/DD/YYYY (month first)"],
                    evidence=_column_evidence(column.sample_values, len(rows)),
                )
            )
            continue
        candidates.append(
            Candidate(
                trigger="table_column",
                subject=f"{table_name}: {column.name}",
                question=(
                    f"*{column.name}* {column.ambiguity_reason}. Same currency, same units?"
                    if "thousands" in (column.ambiguity_reason or "")
                    else f"*{column.name}* {column.ambiguity_reason}. What is it?"
                ),
                passes=True,
                reason=column.ambiguity_reason or "type could not be determined",
                evidence=_column_evidence(column.sample_values, len(rows)),
            )
        )

    return candidates


# --- entry points ------------------------------------------------------


def infer_csv(table_name: str, raw: bytes) -> TableInference:
    """Parse and infer a `.csv`/`.tsv` file end to end. Raises
    `MalformedTable` rather than returning a result when row widths
    disagree — that is reported, not silently padded."""
    encoding = sniff_encoding(raw)
    text_content = raw.decode(encoding.encoding, errors="replace")
    delimiter = sniff_delimiter(text_content[:4096])
    rows = parse_rows(text_content, delimiter.delimiter)

    if not rows:
        header = HeaderDetection(HeaderVerdict.ABSENT, 0.0, [], "the file is empty")
        return TableInference(table_name, None, encoding, delimiter, header, [], 0, False, [])

    header = detect_header(rows)
    data_rows = rows[1:] if header.verdict is HeaderVerdict.PRESENT else rows
    names = header.names if header.names else [f"Column {i + 1}" for i in range(len(rows[0]))]
    columns = infer_column_types(data_rows, names)
    candidates = build_candidates(table_name, header, columns, data_rows)

    return TableInference(
        table_name=table_name,
        sheet=None,
        encoding=encoding,
        delimiter=delimiter,
        header=header,
        columns=columns,
        row_count=len(data_rows),
        candidates=candidates,
        rows=data_rows,
    )


def infer_xlsx(filename: str, raw: bytes) -> list[TableInference]:
    """One `TableInference` per sheet — `docs/data-sources.md` §8's settled
    default. A sheet whose header row has a merged cell is flagged rather
    than guessed at (the same section: "merged headers ... raise a
    clarification rather than being guessed"), and its columns are still
    inferred from the data beneath — the merge affects only whether the
    label can be trusted, not whether the data can be typed.

    Not `read_only` — `ReadOnlyWorksheet` has no `merged_cells`, and merged
    ranges are exactly what this function has to see.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=False)
    results: list[TableInference] = []
    try:
        for sheet in workbook.worksheets:
            table_name = f"{filename}:{sheet.title}"
            rows = [
                [("" if cell is None else str(cell)) for cell in row]
                for row in sheet.iter_rows(values_only=True)
                if any(cell is not None for cell in row)
            ]
            if not rows:
                header = HeaderDetection(HeaderVerdict.ABSENT, 0.0, [], "the sheet is empty")
                results.append(
                    TableInference(table_name, sheet.title, None, None, header, [], 0, False, [])
                )
                continue

            merged_header = any(merged.min_row == 1 for merged in sheet.merged_cells.ranges)
            header = detect_header(rows)
            data_rows = rows[1:] if header.verdict is HeaderVerdict.PRESENT else rows
            names = (
                header.names if header.names else [f"Column {i + 1}" for i in range(len(rows[0]))]
            )
            columns = infer_column_types(data_rows, names)
            candidates = build_candidates(table_name, header, columns, data_rows)
            if merged_header:
                candidates.append(
                    Candidate(
                        trigger="table_header",
                        subject=f"{table_name}: merged header",
                        question=(
                            f"The header row of *{table_name}* has merged cells. "
                            "What should the columns under it be called?"
                        ),
                        passes=True,
                        reason="a merged header cell cannot be split into per-column names",
                        evidence={"kind": "table_preview", "rows": rows[:3]},
                    )
                )

            results.append(
                TableInference(
                    table_name=table_name,
                    sheet=sheet.title,
                    encoding=None,
                    delimiter=None,
                    header=header,
                    columns=columns,
                    row_count=len(data_rows),
                    merged_header=merged_header,
                    candidates=candidates,
                    rows=data_rows,
                )
            )
    finally:
        workbook.close()
    return results


# --- persistence: schema notes and clarifications --------------------------

TABLE_SCHEMA_NOTE_RAISED = "table_schema_note_recorded"
TABLE_CLARIFICATION_RAISED = "table_clarification_raised"


async def raise_table_inference(
    session: AsyncSession, source_id: uuid.UUID, inference: TableInference
) -> RaiseResult:
    """Write what was inferred, but never as fact: every column lands in
    `schema_notes` as `origin='inferred'` with its confidence attached
    (`AGENTS.md` §3 C4 — an unreviewed guess is not a citation-worthy claim),
    and every candidate `infer_table` produced becomes a real row in
    `clarifications`, capped and ranked the same way `askwell.clarify` caps
    document-derived candidates — a table that raised 12 ambiguous columns
    must not ask 12 questions any more than a document source may.

    Idempotent per source, the same guard `clarify.raise_candidates` uses:
    a source that already has a clarification row is not re-scanned.
    """
    already = await session.execute(
        text("SELECT 1 FROM clarifications WHERE source_id = :id LIMIT 1"),
        {"id": source_id},
    )
    already_raised = already.first() is not None

    for column in inference.columns:
        description = f"Inferred type: {column.inferred_type} ({column.confidence:.0%} confidence)."
        if column.ambiguous and column.ambiguity_reason:
            description += f" {column.ambiguity_reason}."
        if column.date_format is not None and column.date_format.verdict in (
            DateFormatVerdict.DAY_FIRST,
            DateFormatVerdict.MONTH_FIRST,
        ):
            is_day_first = column.date_format.verdict is DateFormatVerdict.DAY_FIRST
            label = "DD/MM/YYYY" if is_day_first else "MM/DD/YYYY"
            description += (
                f" Date format inferred: {label} — disambiguated by "
                f"'{column.date_format.evidence_value}' ({column.date_format.evidence_reason})."
            )
        await session.execute(
            text(
                "INSERT INTO schema_notes "
                "(id, source_id, table_name, column_name, description, origin, confidence) "
                "VALUES (:id, :source_id, :table_name, :column_name, :description, "
                "'inferred', :confidence)"
            ),
            {
                "id": uuid.uuid4(),
                "source_id": source_id,
                "table_name": inference.table_name,
                "column_name": column.name,
                "description": description,
                "confidence": column.confidence,
            },
        )
        await record(
            session,
            Store.DECISIONS,
            TABLE_SCHEMA_NOTE_RAISED,
            {
                "source_id": str(source_id),
                "table_name": inference.table_name,
                "column_name": column.name,
                "inferred_type": column.inferred_type,
                # A string, not a float — `audit.compute_hash` refuses floats
                # outright, since they do not round-trip identically through
                # jsonb and would make every later verification report
                # tampering that never happened.
                "confidence": f"{column.confidence:.3f}",
            },
        )

    raised = 0
    capped = 0
    if not already_raised and inference.candidates:
        cap = await get_clarification_cap(session)
        to_raise, to_cap = inference.candidates[:cap], inference.candidates[cap:]

        for rank, candidate in enumerate(to_raise, start=1):
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
                    "evidence": json.dumps({**candidate.evidence, "trigger": candidate.trigger}),
                    "rank": rank,
                },
            )
            await record(
                session,
                Store.DECISIONS,
                TABLE_CLARIFICATION_RAISED,
                {
                    "source_id": str(source_id),
                    "trigger": candidate.trigger,
                    "subject": candidate.subject,
                    "rank": rank,
                },
            )
            raised += 1

        for offset, candidate in enumerate(to_cap, start=1):
            capped += 1
            await record(
                session,
                Store.DECISIONS,
                "clarification_capped",
                {
                    "source_id": str(source_id),
                    "trigger": candidate.trigger,
                    "subject": candidate.subject,
                    "rank": cap + offset,
                    "cap": cap,
                },
            )

    log.info(
        "table_inferred",
        source_id=str(source_id),
        table_name=inference.table_name,
        columns=len(inference.columns),
        raised=raised,
        capped=capped,
    )
    return RaiseResult(raised=raised, inferred=0, dropped=0, capped=capped)
