"""Plain text, Markdown and HTML extraction. `M1-EXTRACT-ING-027`.

Three formats, one extractor, because all three reduce to the same shape once
their format-specific chrome is gone: a stream of text, optionally broken into
heading-anchored sections. HTML is converted into that stream first —
`_html_to_headed_text` mutates each heading tag's own text to carry a Markdown
`#` prefix in place, so `BeautifulSoup.get_text()` afterwards returns exactly
the same shape a `.md` file already has, in document order, with no separate
pass needed to avoid reading a heading's text twice.

**Front matter is metadata, not prose.** A `.md` file opening with a
`---`-delimited YAML block is stripped before sectioning — the ticket's edge
case says so explicitly — rather than parsed into fields nothing here stores
yet; the honest scope is "excluded", not "read".

**Navigation chrome is discarded, not just hidden.** `<script>`, `<style>`
and `<nav>` are removed from the tree before any text is read, so a saved
page's menu never lands in a citation next to the paragraph it decorates.

**No heading at all is one section, not zero.** A plain `.txt` file has no
headings by definition; a `.md` or `.html` file might not either. Both still
need one `document_pages` row to be indexed at all — the whole document, page
1, no label, honest that there was nothing more specific to anchor to.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from askwell.extract_common import Anchor, write_anchors
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Report, Work

log = get_logger(__name__)

ANCHOR_KIND = "heading"

_HTML_MIME = "text/html"
_MARKDOWN_MIME = "text/markdown"

_FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n", re.DOTALL)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_CHROME_TAGS = ("script", "style", "noscript", "nav")


@dataclass(frozen=True, slots=True)
class _Section:
    label: str | None
    lines: list[str]


def _strip_front_matter(content: str) -> str:
    return _FRONT_MATTER.sub("", content, count=1)


def _html_to_headed_text(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag_name in _CHROME_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for level in range(1, 7):
        for heading in soup.find_all(f"h{level}"):
            heading.string = f"{'#' * level} {heading.get_text(strip=True)}"
    # `<head>` — `<title>`, `<meta>` — is page metadata, not content a reader
    # sees; walking `<body>` alone is what keeps a saved page's `<title>`
    # from becoming an unlabelled first section ahead of its real content.
    body = soup.body or soup
    return str(body.get_text(separator="\n"))


def _sections(content: str) -> list[_Section]:
    sections = [_Section(label=None, lines=[])]
    for line in content.splitlines():
        match = _MD_HEADING.match(line)
        if match:
            sections.append(_Section(label=match.group(2).strip(), lines=[line]))
        else:
            sections[-1].lines.append(line)
    return [section for section in sections if any(line.strip() for line in section.lines)]


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


async def run(work: "Work", report: "Report", factory: "async_sessionmaker[AsyncSession]") -> None:
    raw = await asyncio.to_thread(_read, work.path)

    if work.mime == _HTML_MIME:
        body = await asyncio.to_thread(_html_to_headed_text, raw)
    elif work.mime == _MARKDOWN_MIME:
        body = _strip_front_matter(raw)
    else:
        body = raw

    sections = _sections(body)
    if not sections:
        text = body.strip()
        lines = [text] if text else []
        sections = [_Section(label=None, lines=lines)]

    anchors: list[Anchor] = []
    for index, section in enumerate(sections, start=1):
        text = "\n".join(section.lines).strip()
        anchors.append(
            Anchor(page_number=index, label=section.label, text=text or None, has_text=bool(text))
        )
        await report(index, len(sections))

    await write_anchors(factory, work, anchors, ANCHOR_KIND)

    log.info(
        "extract_text_completed",
        document_id=str(work.document_id),
        filename=work.filename,
        mime=work.mime,
        sections=len(anchors),
    )
