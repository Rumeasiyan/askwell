#!/usr/bin/env python3
"""Print a profile's model URL and checksum, one per line.

Exists because the eval workflow needed these two values and embedded a Python
heredoc in a `run:` block to get them. The heredoc body sat at column 0 while
the surrounding block scalar was indented, which ends a YAML block scalar — so
`eval.yml` was not a valid workflow at all. It failed instantly on all fifteen
runs it ever had, and the suites never executed once.

A file cannot have that problem. It is also runnable by hand, which the
heredoc was not:

    python3 eval/model_spec.py light

Stdlib only and no side effects: the workflow calls this before the stack is
necessarily up, and anything that touched the database or the network here
would fail in a way that looked like a model problem.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: model_spec.py <tier>", file=sys.stderr)
        return 2

    # `api/src` rather than an installed package: the workflow runs this from
    # a checkout, before anything is installed.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api" / "src"))
    from askwell.models_catalog import CATALOG, spec_for_tier

    # Checked against the catalogue rather than caught, because
    # `spec_for_tier` raises nothing: it falls back to the 4B spec for any
    # name it does not know. That fallback is right at runtime — a profile
    # that cannot be read should still start — and wrong here, where a typo
    # would print a different model's checksum and the caller would verify a
    # download against it happily.
    if argv[1] not in CATALOG:
        known = ", ".join(sorted(CATALOG))
        print(f"no model profile named {argv[1]!r}; known profiles: {known}", file=sys.stderr)
        return 2

    spec = spec_for_tier(argv[1])
    print(spec.url)
    print(spec.sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
