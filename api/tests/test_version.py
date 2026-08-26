"""The version must resolve to the repository's VERSION file, and to nothing else.

AGENTS.md §7 makes that file the single source of truth. These tests exist
because the failure they guard against is silent: a stale or duplicated version
does not crash anything, it just makes every release note, bug report and
changelog entry point at the wrong build.
"""

import re
from pathlib import Path

import askwell
from askwell._version import resolve_version

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPO_ROOT / "VERSION"

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def test_version_file_exists() -> None:
    assert VERSION_FILE.is_file(), f"{VERSION_FILE} is the single source of the version"


def test_version_file_is_semver_with_no_fourth_component() -> None:
    """§7: MAJOR.MINOR.PATCH. A hotfix is a PATCH release, not `1.4.2.1`."""
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert SEMVER.match(raw), f"VERSION is {raw!r}, expected MAJOR.MINOR.PATCH"


def test_package_version_matches_the_file() -> None:
    assert askwell.__version__ == VERSION_FILE.read_text(encoding="utf-8").strip()


def test_resolver_is_not_reading_a_stale_installed_copy() -> None:
    """Changing the file must change the answer, without reinstalling anything."""
    assert resolve_version() == VERSION_FILE.read_text(encoding="utf-8").strip()


# Directories that are not ours to police, or that hold generated output.
# Dependency caches matter here: pnpm's store holds thousands of vendored
# package.json files, and some package somewhere will always happen to be at
# whatever version Askwell is at.
_SKIP_DIRS = {
    ".git",
    ".pnpm-store",
    ".turbo",
    ".next",
    "out",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
}
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2", ".lock"}


def _source_files() -> list[Path]:
    """Every text file in the tree that a person maintains by hand."""
    found = []
    stack = [REPO_ROOT]
    while stack:
        directory = stack.pop()
        for entry in directory.iterdir():
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            elif entry.suffix not in _SKIP_SUFFIXES and entry.name != "VERSION":
                found.append(entry)
    return found


def test_version_is_declared_exactly_once() -> None:
    """No second hand-maintained version string anywhere in the tree.

    §7: 'a second hand-edited version is how a build ships with a number that
    matches nothing'. This catches the reintroduction directly rather than
    waiting for the two to drift, and it deliberately does not shell out to
    git — a check that silently skips where git is absent is not a check.
    """
    declared = VERSION_FILE.read_text(encoding="utf-8").strip()

    # A quoted, assignment-shaped occurrence of the exact version. Prose
    # mentioning a version in a changelog entry is a record, not a declaration.
    assignment = re.compile(
        r"""(?i)\bversion["']?\s*[:=]\s*["']""" + re.escape(declared) + r"""["']"""
    )

    offenders = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if assignment.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "The version is declared outside the VERSION file, which will drift: "
        f"{sorted(offenders)}. Read it from VERSION instead (AGENTS.md §7)."
    )
