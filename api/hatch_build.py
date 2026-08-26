"""Read the package version from the repository's VERSION file.

AGENTS.md §7 makes root `VERSION` the single source of truth. A second
hand-maintained version string is how a build ships a number that matches
nothing, so this hook reads that file rather than letting `pyproject.toml`
declare its own.
"""

from pathlib import Path
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface


class VersionFromRepoRoot(MetadataHookInterface):
    """Set `version` from the VERSION file one directory above the project."""

    def update(self, metadata: dict[str, Any]) -> None:
        version_file = Path(self.root).parent / "VERSION"
        if not version_file.is_file():
            raise FileNotFoundError(
                f"{version_file} is missing. It is the single source of the "
                f"version (AGENTS.md §7); the build cannot guess one. If you "
                f"are building from a partial copy of the repository, build "
                f"from the repository root instead."
            )
        version = version_file.read_text(encoding="utf-8").strip()
        if not version:
            raise ValueError(f"{version_file} is empty. Expected a version like 0.1.0.")
        metadata["version"] = version
