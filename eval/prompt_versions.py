"""What prompt version was in force for a run.

Filenames under `api/src/askwell/agent/prompts/` carry their own version
(`abstention.v1.md`) — this reads that back rather than duplicating it,
so a run's record can never claim a version the prompt file itself does not.
"""

import re
from pathlib import Path

_NAME_VERSION = re.compile(r"^(?P<name>.+)\.v(?P<version>\d+)$")


def read_prompt_versions(prompts_dir: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted(prompts_dir.glob("*.md")):
        match = _NAME_VERSION.match(path.stem)
        if match is None:
            continue
        versions[match.group("name")] = f"v{match.group('version')}"
    return versions


def default_prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "api" / "src" / "askwell" / "agent" / "prompts"
