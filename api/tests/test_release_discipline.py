"""Version and changelog discipline. `AGENTS.md` §7.

`test_version.py` already proves the running version comes from the `VERSION`
file and that no second copy exists in the tree. This is the other half: that
each version has a changelog entry, and that the frontend reads the same file
rather than being merely silent about its own.

A number nobody can trace to a change is a number nobody can act on. Someone
reporting a bug against `0.1.7` should be able to find out what `0.1.7` was.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPO_ROOT / "VERSION"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
WEB_MANIFEST = REPO_ROOT / "web" / "package.json"
NEXT_CONFIG = REPO_ROOT / "web" / "next.config.ts"

HEADING = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)


def current_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def test_the_changelog_has_an_entry_for_the_current_version() -> None:
    versions = HEADING.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert current_version() in versions, (
        f"VERSION is {current_version()} and CHANGELOG.md has no `## "
        f"{current_version()}` heading. §7: every version bump adds an entry."
    )


def test_the_changelog_is_newest_first() -> None:
    """The order the file claims, and the order anyone reads it in."""
    versions = [tuple(int(part) for part in v.split(".")) for v in HEADING.findall(
        CHANGELOG.read_text(encoding="utf-8")
    )]
    assert versions == sorted(versions, reverse=True), (
        f"CHANGELOG.md headings are out of order: {versions}"
    )


def test_no_version_is_listed_twice() -> None:
    versions = HEADING.findall(CHANGELOG.read_text(encoding="utf-8"))
    duplicates = {v for v in versions if versions.count(v) > 1}
    assert not duplicates, f"CHANGELOG.md lists {sorted(duplicates)} more than once"


def test_the_frontend_declares_no_version_of_its_own() -> None:
    """Silence by accident is not the same as reading the right file.

    `web/package.json` having no `version` field satisfied §7 by omission
    before this was checked. A second hand-maintained copy is how a build
    ships a number that matches nothing.
    """
    import json

    manifest = json.loads(WEB_MANIFEST.read_text(encoding="utf-8"))
    assert "version" not in manifest, (
        f"web/package.json declares version {manifest.get('version')!r}. The "
        f"version comes from the VERSION file, read by next.config.ts."
    )


def test_the_frontend_reads_the_version_file() -> None:
    assert '"VERSION"' in NEXT_CONFIG.read_text(encoding="utf-8"), (
        "next.config.ts no longer reads the VERSION file, so the interface "
        "would report whatever was last baked in"
    )


def test_the_running_version_is_in_the_startup_log() -> None:
    """When someone says it did not work this morning, this is the record."""
    source = (REPO_ROOT / "api" / "src" / "askwell" / "app.py").read_text(encoding="utf-8")
    startup = source[source.index('"startup"') : source.index('"startup"') + 300]
    assert "version=__version__" in startup
