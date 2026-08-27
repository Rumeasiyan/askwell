"""What a file on disk actually is, decided by the server from its bytes.

There is a second copy of this in the browser (`web/lib/add-source.ts`) and the
duplication is deliberate rather than an oversight to be tidied away.

**The client's answer is a courtesy; this one is the boundary.** The browser is
the only place with the bytes before anything is sent, so it is where the user
is told what Askwell believes their files are — that is what makes a mislabelled
file honest rather than a failure three steps later. But a record built from a
client-declared type would send a renamed executable to a document extractor,
and the whole point of deciding by content is lost at exactly the step where it
would have had teeth. So nothing here reads what the client said. The file is
opened, its head is read, and the answer is recomputed from the bytes that are
actually on the user's disk at the moment Askwell looks.

The two copies are expected to agree, and where they disagree this one wins:
what it decides is what is stored, and its answer is what the user is shown for
a file that reached the server. `api/tests/test_filetypes.py` holds the cases
both are expected to answer identically; `web/lib/add-source.test.ts` holds the
same cases in the other language.

**One known divergence, and it is deliberate.** The browser routes a `.md` or
`.txt` file whose first line carries two commas to the table route, and one
containing a line beginning `CREATE` to the dump route — which since
`M1-ADD-VAL-024` means the file is not queued at all and the user is told their
plain-text note arrives in M4. This module refuses to take a file away from the
files route on a heuristic when its own extension claims that route (see
`detect`). Fixing it here does not fix it for the user, because the client is
what decides whether a file is sent at all; the client-side half is recorded as
an open item in `docs/BRAIN.md` and is not this ticket's to change.

Everything here is pure — bytes and a name in, a description out. No filesystem,
no clock, no session. Reading the head is the caller's job (`askwell.sources`),
which is what keeps this testable with a literal.
"""

from dataclasses import dataclass
from enum import StrEnum

# How much of a file is read to decide what it is. The same 4 KB the browser
# reads: enough for every signature below plus a run of text to judge, and small
# enough that doing it for several thousand files is not the same as reading
# several thousand files.
HEAD_BYTES = 4096


class Route(StrEnum):
    """Which of the four add routes a file belongs to."""

    FILES = "files"
    TABLE = "table"
    DUMP = "dump"
    CONNECTION = "connection"


class Verdict(StrEnum):
    """What Askwell will do with it, which is three things and not two.

    A CSV is not unsupported, it is unsupported *yet*, and collapsing those into
    one flag either enrols it in a queue that will never take it or tells the
    user their spreadsheets have no home here. Both are false, and they are
    false in opposite directions.
    """

    SUPPORTED = "supported"
    LATER = "later"
    REFUSED = "refused"


# When each route starts working. Written once, here, so that when M4 lands the
# only change is a `None` and every CSV already detected becomes supported.
ARRIVES: dict[Route, str | None] = {
    Route.FILES: None,
    Route.TABLE: "M4",
    Route.DUMP: "M4",
    Route.CONNECTION: "M4",
}


@dataclass(frozen=True, slots=True)
class Detection:
    """What the bytes said, and what follows from it."""

    format: str
    route: Route
    verdict: Verdict
    # The milestone the route arrives in. Set only when the verdict is `later`.
    arrives: str | None
    # A media type for `documents.mime`, or None when the bytes did not settle
    # one. None means "not established", never `application/octet-stream` —
    # an invented value here is a claim nothing checked, and the extractor in
    # `M1-ADD-ING-025` is the next thing that will read it.
    mime: str | None
    # Set when the bytes and the name disagree. Content is what was believed.
    mismatch: str | None
    # Why it was refused, when it was. Never a bare rejection.
    refusal: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "route": str(self.route),
            "verdict": str(self.verdict),
            "arrives": self.arrives,
            "mime": self.mime,
            "mismatch": self.mismatch,
            "refusal": self.refusal,
        }


REFUSED_PROGRAM = (
    "Askwell indexes documents, and this is a program. Nothing has been run and "
    "nothing has been read past its first few bytes."
)

REFUSED_ARCHIVE = (
    "Askwell does not open archives. Unpack it and add what is inside — that way "
    "each document keeps its own name in your citations."
)

REFUSED_EMPTY = "There is nothing in this file to index. Nothing was changed on disk."

REFUSED_UNKNOWN = "Askwell could not tell what this file is from its contents."


# --- signatures -------------------------------------------------------------

_IMAGES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "a PNG image", "image/png"),
    (b"\xff\xd8\xff", "a JPEG image", "image/jpeg"),
    (b"GIF8", "a GIF image", "image/gif"),
    (b"II*\x00", "a TIFF image", "image/tiff"),
    (b"MM\x00*", "a TIFF image", "image/tiff"),
    (b"BM", "a BMP image", "image/bmp"),
)

# A program, not a document. Named as such rather than as "unsupported": the
# user learns which of their files is an executable, and learns that Askwell did
# not run it.
_EXECUTABLES: tuple[tuple[bytes, str], ...] = (
    (b"\x7fELF", "a Linux program"),
    (b"MZ", "a Windows program"),
    (b"\xca\xfe\xba\xbe", "a macOS program"),
    (b"\xcf\xfa\xed\xfe", "a macOS program"),
    (b"#!", "a script"),
)


@dataclass(frozen=True, slots=True)
class _Content:
    """What the signature table found. No verdict: the route decides that."""

    format: str
    route: Route
    mime: str | None = None
    refusal: str | None = None
    # The zip and OLE containers hold four different things each; the name is
    # the only cheap way to tell them apart, so it is consulted here and only
    # here.
    container: str | None = None


def _from_bytes(head: bytes) -> _Content | None:
    if head.startswith(b"%PDF-"):
        return _Content("a PDF document", Route.FILES, "application/pdf")
    if head.startswith(b"PGDMP"):
        return _Content("a PostgreSQL dump", Route.DUMP, "application/octet-stream")
    for signature, name, mime in _IMAGES:
        if head.startswith(signature):
            return _Content(name, Route.FILES, mime)
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return _Content("a WebP image", Route.FILES, "image/webp")
    for signature, name in _EXECUTABLES:
        if head.startswith(signature):
            return _Content(name, Route.FILES, refusal=REFUSED_PROGRAM)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _Content("an older Microsoft Office file", Route.FILES, container="ole")
    if head.startswith(b"PK\x03\x04"):
        return _Content("a zip archive", Route.FILES, container="ooxml")
    if head.startswith(b"\x1f\x8b"):
        return _Content("a gzip archive", Route.FILES, refusal=REFUSED_ARCHIVE)
    return None


def looks_textual(head: bytes) -> bool:
    """Whether the head reads as text.

    A NUL byte settles it: no text encoding Askwell supports produces one, and
    every binary format that got past the signatures above has them early. The
    printable ratio catches the rest. Both are judged on the head alone, so a
    text file with a stray control character deep inside is still text.
    """
    if not head:
        return False
    printable = sum(1 for byte in head if byte >= 0x20 or byte in (0x09, 0x0A, 0x0D))
    return not any(byte == 0 for byte in head) and printable / len(head) > 0.9


def _decode(head: bytes) -> str:
    """Latin-1, deliberately: every byte maps and nothing raises.

    UTF-8 with `errors="replace"` would be the obvious choice and is worse here
    — the head is a *slice*, so it routinely ends mid-character, and the marker
    checks below only ever look at ASCII. Decoding byte-for-byte keeps the
    offsets honest and cannot fail on somebody's Latin-1 contract.
    """
    return head.decode("latin-1")


def _html_at_the_top(text: str) -> bool:
    """HTML judged on its opening rather than on its name.

    There is no byte signature for HTML — it is text — so this is the content
    check for it, and it runs *before* the delimiter and SQL checks because a
    saved page full of tables would otherwise read as a CSV. A byte-order mark
    is skipped in both forms: `_decode` reads bytes one at a time, so a UTF-8
    BOM arrives as three separate characters rather than as U+FEFF.

    Matched with `startswith` on a stripped prefix rather than with a regular
    expression. This runs over every text file in a several-thousand-file drop,
    and the input is whatever happened to be on disk.
    """
    stripped = text.lstrip("﻿").lstrip("ï»¿").lstrip()
    lowered = stripped[:64].lower()
    if lowered.startswith("<!doctype") and "html" in lowered:
        return True
    return lowered.startswith(("<html>", "<html ", "<head>", "<head "))


# Matched as whole words at the start of a line, never as a prefix. `CREATE`
# as a prefix also matches "Created by Anna, 2026" — which is a line in
# somebody's notes, not a dump, and mistaking it costs them the file.
_SQL_LEADS_ONE = frozenset({"create", "copy", "set"})
_SQL_LEADS_TWO = frozenset({"insert into", "alter table", "drop table"})


def _looks_like_a_dump(text: str) -> bool:
    """A SQL dump, judged on a preamble line rather than on any DDL keyword.

    Deliberately narrower than a keyword search anywhere in the head. Since
    `M1-ADD-VAL-024` a non-`files` route means the file is **not queued at all**
    — so a note documenting a schema, misread as a dump, is not a cosmetic
    mislabel any more: the user is told their plain-text note arrives in M4,
    which is false about a format Askwell reads today.
    """
    if "postgresql database dump" in text.lower():
        return True
    for line in text.splitlines():
        words = line.strip().lower().split()
        if not words:
            continue
        if words[0] in _SQL_LEADS_ONE or " ".join(words[:2]) in _SQL_LEADS_TWO:
            return True
    return False


def _looks_delimited(text: str) -> bool:
    """Comma or tab separated, judged on the first line having repeated separators."""
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if not first:
        return False
    return first.count(",") >= 2 or first.count("\t") >= 2


# --- extensions -------------------------------------------------------------

_BY_EXTENSION: dict[str, tuple[str, Route]] = {
    "pdf": ("a PDF document", Route.FILES),
    "doc": ("a Word document", Route.FILES),
    "docx": ("a Word document", Route.FILES),
    "xls": ("an Excel workbook", Route.FILES),
    "xlsx": ("an Excel workbook", Route.FILES),
    "ppt": ("a PowerPoint deck", Route.FILES),
    "pptx": ("a PowerPoint deck", Route.FILES),
    "txt": ("plain text", Route.FILES),
    "md": ("a Markdown document", Route.FILES),
    "markdown": ("a Markdown document", Route.FILES),
    "html": ("an HTML page", Route.FILES),
    "htm": ("an HTML page", Route.FILES),
    "csv": ("a CSV file", Route.TABLE),
    "tsv": ("a tab-separated file", Route.TABLE),
    "sql": ("a SQL dump", Route.DUMP),
    "dump": ("a database dump", Route.DUMP),
    "backup": ("a database dump", Route.DUMP),
    "png": ("a PNG image", Route.FILES),
    "jpg": ("a JPEG image", Route.FILES),
    "jpeg": ("a JPEG image", Route.FILES),
    "gif": ("a GIF image", Route.FILES),
    "webp": ("a WebP image", Route.FILES),
    "tif": ("a TIFF image", Route.FILES),
    "tiff": ("a TIFF image", Route.FILES),
    "bmp": ("a BMP image", Route.FILES),
}

# What the zipped and OLE Office containers hold, from the name alone.
_OOXML: dict[str, tuple[str, str]] = {
    "docx": (
        "a Word document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": (
        "an Excel workbook",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "pptx": (
        "a PowerPoint deck",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "odt": ("an OpenDocument text file", "application/vnd.oasis.opendocument.text"),
    "ods": ("an OpenDocument spreadsheet", "application/vnd.oasis.opendocument.spreadsheet"),
    "odp": ("an OpenDocument presentation", "application/vnd.oasis.opendocument.presentation"),
}

_OLE: dict[str, tuple[str, str]] = {
    "doc": ("a Word document", "application/msword"),
    "xls": ("an Excel workbook", "application/vnd.ms-excel"),
    "ppt": ("a PowerPoint deck", "application/vnd.ms-powerpoint"),
}

# The names of text formats that go to the files route today. A file with one of
# these extensions is never routed to `table` or `dump` on a heuristic — see
# `detect`.
_TEXT_FILE_EXTENSIONS = frozenset({"md", "markdown", "txt", "html", "htm"})


def extension_of(name: str) -> str:
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()


def _on_route(format_: str, route: Route, mime: str | None, mismatch: str | None) -> Detection:
    arrives = ARRIVES[route]
    return Detection(
        format=format_,
        route=route,
        verdict=Verdict.SUPPORTED if arrives is None else Verdict.LATER,
        arrives=arrives,
        mime=mime,
        mismatch=mismatch,
        refusal=None,
    )


def _disagreement(claimed: str | None, actual: str, extension: str) -> str | None:
    """The sentence for a file whose name and contents disagree.

    Said plainly and in the user's own terms — they named it `.pdf`, so the
    message starts there. Silence is the dishonest option: the file would be
    indexed as what it really is and the user would never learn that one of
    their documents is not what its name says.
    """
    if claimed is None or extension == "" or claimed == actual:
        return None
    return f"Named .{extension}, but the contents are {actual}. Askwell goes by the contents."


def detect(name: str, head: bytes, size: int) -> Detection:
    """Decide what a file is from its first bytes and its name.

    `size` is separate from `len(head)` because the head is a slice: a 400 MB
    PDF and a 4 KB one have the same head, and an empty file is the only case
    where the difference matters.
    """
    extension = extension_of(name)
    claimed = _BY_EXTENSION.get(extension)

    if size == 0:
        return Detection(
            format="an empty file",
            route=claimed[1] if claimed else Route.FILES,
            verdict=Verdict.REFUSED,
            arrives=None,
            mime=None,
            mismatch=None,
            refusal=REFUSED_EMPTY,
        )

    content = _from_bytes(head)

    if content is not None and content.container == "ooxml":
        named = _OOXML.get(extension)
        if named is None:
            # A zip that is not one of the Office formats is an archive, and the
            # refusal names the way out rather than the rule.
            return Detection(
                format="a zip archive",
                route=Route.FILES,
                verdict=Verdict.REFUSED,
                arrives=None,
                mime="application/zip",
                mismatch=None,
                refusal=REFUSED_ARCHIVE,
            )
        return _on_route(named[0], Route.FILES, named[1], None)

    if content is not None and content.container == "ole":
        named = _OLE.get(extension)
        if named is None:
            return _on_route(content.format, Route.FILES, "application/x-ole-storage", None)
        return _on_route(named[0], Route.FILES, named[1], None)

    if content is not None:
        mismatch = _disagreement(claimed[0] if claimed else None, content.format, extension)
        if content.refusal is not None:
            return Detection(
                format=content.format,
                route=content.route,
                verdict=Verdict.REFUSED,
                arrives=None,
                mime=content.mime,
                mismatch=mismatch,
                refusal=content.refusal,
            )
        return _on_route(content.format, content.route, content.mime, mismatch)

    if looks_textual(head):
        text = _decode(head)
        # HTML first: a saved page is full of rows and would otherwise read as a
        # CSV, and one of those two routes works today while the other does not.
        if extension in ("html", "htm") or _html_at_the_top(text):
            mismatch = _disagreement(claimed[0] if claimed else None, "an HTML page", extension)
            return _on_route("an HTML page", Route.FILES, "text/html", mismatch)

        # A file the user named `.md`, `.txt` or `.html` is never taken away
        # from the files route by a heuristic. Prose is full of commas and a
        # note about a schema is full of `CREATE TABLE`, and since
        # `M1-ADD-VAL-024` a non-files route means the file is not queued at
        # all — so a misread here withholds a document Askwell can read today
        # and tells the user it arrives in M4. Content still decides everything
        # the extension claims nothing about.
        named_text = extension in _TEXT_FILE_EXTENSIONS

        if not named_text and (extension in ("sql", "dump", "backup") or _looks_like_a_dump(text)):
            return _on_route("a SQL dump", Route.DUMP, "application/sql", None)

        if not named_text and (extension in ("csv", "tsv") or _looks_delimited(text)):
            if extension == "tsv":
                return _on_route(
                    "a tab-separated file", Route.TABLE, "text/tab-separated-values", None
                )
            return _on_route("a CSV file", Route.TABLE, "text/csv", None)

        # Markdown is plain text with conventions and no byte distinguishes it,
        # so the name decides — the one place the extension is better evidence.
        # Getting it wrong costs nothing: both go to the same extractor.
        format_ = "a Markdown document" if extension in ("md", "markdown") else "plain text"
        mime = "text/markdown" if extension in ("md", "markdown") else "text/plain"
        mismatch = _disagreement(claimed[0] if claimed else None, format_, extension)
        return _on_route(format_, Route.FILES, mime, mismatch)

    return Detection(
        format="an unrecognised file",
        route=claimed[1] if claimed else Route.FILES,
        verdict=Verdict.REFUSED,
        arrives=None,
        mime=None,
        mismatch=None,
        refusal=REFUSED_UNKNOWN,
    )
