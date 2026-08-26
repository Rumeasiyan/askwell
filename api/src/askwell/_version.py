"""Resolve the running version.

There is one source of truth: the `VERSION` file at the repository root
(AGENTS.md §7). A version surfaced in the API must never be re-typed.

The file is preferred over installed package metadata, and the order matters.
Metadata is stamped once, when the package is built or installed. Working from
a checkout with the source mounted into a container, a `VERSION` bump would
otherwise not be visible until someone remembered to reinstall — and a build
reporting a number that matches nothing is precisely what §7 exists to prevent.
Released installs have no `VERSION` file above `site-packages`, so they fall
through to metadata, which by then is the same value.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path

_VERSION_FILENAME = "VERSION"


def _from_source_checkout() -> str | None:
    """Walk upwards for the repository's VERSION file. None if not in a checkout."""
    for directory in Path(__file__).resolve().parents:
        candidate = directory / _VERSION_FILENAME
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip() or None
    return None


def resolve_version() -> str:
    """The version of this checkout, or of the installed build."""
    from_file = _from_source_checkout()
    if from_file is not None:
        return from_file

    try:
        return _installed_version("askwell")
    except PackageNotFoundError:
        pass

    # Neither in a checkout nor installed. Say so rather than inventing a
    # number: a wrong version in a bug report costs more than a missing one.
    raise RuntimeError(
        "Cannot determine the Askwell version: no "
        f"{_VERSION_FILENAME} file was found above "
        f"{Path(__file__).resolve().parent}, and the package is not installed."
    )


__version__ = resolve_version()
