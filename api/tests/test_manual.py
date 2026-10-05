"""The user manual cannot drift from the product. `docs/manual/AUTHORING.md`.

Each chapter records, in `docs/manual/manifest.json`, the routes and labels its
steps send the reader to. A screen change that removes one fails here, so the
chapter, its anchors and its screenshot are fixed in the same change rather
than discovered wrong by a reader.
"""

import html
import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
MANUAL = REPO / "docs" / "manual"
CHAPTERS = MANUAL / "chapters"
SCREENSHOTS = MANUAL / "screenshots"
BUILT = MANUAL / "askwell-manual.html"

# Where a label is looked for when its anchor names no `in`: the interface.
DEFAULT_SEARCH = ("web/app", "web/components", "web/lib")
SOURCE_SUFFIXES = {".ts", ".tsx", ".html", ".md", ".py", ".ps1", ".nsi", ".sh"}

# A version, a milestone, a ticket. The manual describes the product as it is.
FORBIDDEN_IN_PROSE = (
    (re.compile(r"\b\d+\.\d+\.\d+\b"), "a version number"),
    (re.compile(r"\bM\d+(\.\d+)?\b"), "a milestone name"),
    (re.compile(r"#\d+\b"), "an issue reference"),
    (re.compile(r"\bM\d+-[A-Z]+-[A-Z]+-\d+\b"), "a ticket id"),
)


def _manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((MANUAL / "manifest.json").read_text(encoding="utf-8"))
    return loaded


def _chapters() -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = _manifest()["chapters"]
    return chapters


def _normalise(text: str) -> str:
    """Source text as a reader would see it: JSX entities decoded, line breaks
    inside a sentence collapsed."""
    return " ".join(html.unescape(text.replace("&apos;", "'")).split())


def _sources(scope: str) -> list[Path]:
    root = REPO / scope
    if root.is_file():
        return [root]
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and "node_modules" not in path.parts
        and ".test." not in path.name
        and "target" not in path.parts
    ]


_corpus_cache: dict[tuple[str, ...], str] = {}


def _corpus(scopes: tuple[str, ...]) -> str:
    if scopes not in _corpus_cache:
        _corpus_cache[scopes] = "\n".join(
            _normalise(path.read_text(encoding="utf-8", errors="replace"))
            for scope in scopes
            for path in _sources(scope)
        )
    return _corpus_cache[scopes]


def _route_exists(route: str) -> bool:
    page = REPO / "web" / "app" / route.strip("/") / "page.tsx"
    return page.is_file()


def _anchor_cases() -> list[Any]:
    cases = []
    for chapter in _chapters():
        for anchor in chapter["anchors"]:
            name = anchor.get("label") or anchor.get("route") or anchor.get("id")
            cases.append(pytest.param(chapter["file"], anchor, id=f"{chapter['id']}:{name}"))
    return cases


@pytest.mark.parametrize(("chapter", "anchor"), _anchor_cases())
def test_every_anchor_still_exists(chapter: str, anchor: dict[str, str]) -> None:
    if "route" in anchor:
        assert _route_exists(anchor["route"]), (
            f"{chapter} sends the reader to {anchor['route']}, which no longer exists under "
            f"web/app/. Update the chapter and docs/manual/manifest.json."
        )
        return
    scopes = (anchor["in"],) if "in" in anchor else DEFAULT_SEARCH
    if "id" in anchor:
        needle = f'id="{anchor["id"]}"'
    else:
        needle = _normalise(anchor["label"])
    # Whole words: "Re-index" must not be satisfied by "Re-indexing".
    pattern = re.compile(r"(?<![\w-])" + re.escape(needle) + r"(?![\w-])")
    assert pattern.search(_corpus(scopes)) is not None, (
        f"{chapter} tells the reader to look for {needle!r}, which no longer appears in "
        f"{', '.join(scopes)}. The screen changed: rewrite the step, update its anchor in "
        f"docs/manual/manifest.json and retake its screenshot (docs/manual/AUTHORING.md)."
    )


def test_every_chapter_file_is_in_the_manifest_and_exists() -> None:
    listed = [chapter["file"] for chapter in _chapters()]
    on_disk = sorted(path.name for path in CHAPTERS.glob("*.html"))
    assert sorted(listed) == on_disk
    assert len(set(listed)) == len(listed)


def test_every_screenshot_is_listed_and_exists() -> None:
    for chapter in _chapters():
        text = (CHAPTERS / chapter["file"]).read_text(encoding="utf-8")
        used = sorted(set(re.findall(r'src="screenshots/([^"]+)"', text)))
        assert used == sorted(chapter["screenshots"]), (
            f"{chapter['file']} uses {used}; manifest.json lists {chapter['screenshots']}"
        )
        for name in used:
            assert (SCREENSHOTS / name).is_file(), f"screenshots/{name} is missing"


def test_cross_references_point_at_chapters() -> None:
    ids = {f"ch-{chapter['id']}" for chapter in _chapters()}
    for chapter in _chapters():
        text = (CHAPTERS / chapter["file"]).read_text(encoding="utf-8")
        for target in re.findall(r'href="#([^"]+)"', text):
            assert target in ids, f"{chapter['file']} links to #{target}, which is no chapter"


@pytest.mark.parametrize("chapter", [c["file"] for c in _chapters()])
def test_prose_describes_the_product_as_it_is(chapter: str) -> None:
    """No version, milestone or ticket in what the reader reads (AUTHORING.md)."""
    raw = (CHAPTERS / chapter).read_text(encoding="utf-8")
    prose = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    for pattern, what in FORBIDDEN_IN_PROSE:
        found = pattern.search(prose)
        assert found is None, f"{chapter} contains {what}: {found.group(0)!r}"


def test_the_built_manual_is_up_to_date() -> None:
    """`askwell-manual.html` is committed; a chapter changed without rebuilding
    it would ship the old text."""
    built = BUILT.read_text(encoding="utf-8")
    for chapter in _chapters():
        source = (CHAPTERS / chapter["file"]).read_text(encoding="utf-8").strip()
        assert source in built, (
            f"{chapter['file']} changed since askwell-manual.html was built. "
            "Run scripts/dev.sh manual."
        )
