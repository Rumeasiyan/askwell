#!/usr/bin/env python3
"""Regenerate `NOTICES.md` and fail if anything bundled carries a disallowed
licence. `M7-DOC-DOC-163`.

Two halves, both real I/O against what is actually installed rather than a
manifest that can drift from it:

- Python: `importlib.metadata.distributions()` inside the API image for the
  installed name/version/licence of everything, split into shipped versus
  dev-only by walking `api/uv.lock`'s own resolved dependency graph from
  `askwell`'s runtime `dependencies` — not `pyproject.toml`'s declared list
  and not `Requires-Dist` markers, both of which get extras wrong (see
  `_runtime_dependency_names`).
- JavaScript: `pnpm licenses list --json --prod`, which already does the
  runtime/dev split pnpm's own way — read from a file because the web image
  has no Python and the API image has no Node, so the two must run as
  separate container invocations and hand off through the one thing both
  mount, the repository checkout itself.

Usage (see `scripts/dev.sh notices`, which drives both steps):

    scripts/dev.sh web-run pnpm licenses list --json --prod \\
        > .notices/web-licenses.json
    scripts/dev.sh run python scripts/generate_notices.py

Exits 1 (after still writing `NOTICES.md`, so the diff is visible) if any
dependency or bundled model carries a licence on `askwell.notices`'s
disallowed list. This is a release-gate check (`docs/release-procedure.md`),
not part of `scripts/dev.sh check` — see that file for why it is not wired
into every commit's run.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "api" / "src"))

from askwell.notices import MODEL_NOTICES, disallowed_tokens  # noqa: E402

DEFAULT_WEB_LICENSES = REPO_ROOT / ".notices" / "web-licenses.json"
NOTICES_PATH = REPO_ROOT / "NOTICES.md"

# PEP 639 classifiers use the long-form OSI name; this maps the ones this
# project's own dependency tree actually uses to an SPDX-shaped token so the
# disallow check can compare like with like. A name with no mapping is
# reported verbatim rather than guessed at — see `_python_license`.
_CLASSIFIER_TO_SPDX = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: "
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-3.0-only",
    "License :: OSI Approved :: "
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
}

# Neither package publishes a machine-readable licence (PyPI's own JSON API
# returns null for both, checked 2026-09-23) — their PyPI page states none,
# so `_python_license` alone would report "UNVERIFIED" for a licence that is
# in fact stated, just not where package metadata usually carries it. Both
# verified instead against their GitHub repository's own licence API
# (`GET /repos/<repo>/license`) on 2026-09-23: `thewh1teagle/kokoro-onnx` and
# `thewh1teagle/espeakng-loader`, both MIT.
_KNOWN_LICENSE_OVERRIDES = {
    "kokoro-onnx": "MIT",
    "espeakng-loader": "MIT",
}


@dataclass(frozen=True, slots=True)
class DependencyNotice:
    name: str
    version: str
    license: str
    scope: str  # "runtime" or "dev-only"


def _canonical(name: str) -> str:
    # PEP 503 normalisation: this is what lets "PyYAML" in pyproject.toml
    # match "pyyaml" as reported by importlib.metadata.
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_license(dist: metadata.Distribution) -> str:
    override = _KNOWN_LICENSE_OVERRIDES.get(_canonical(dist.metadata["Name"]))
    if override:
        return override
    expr = dist.metadata.get("License-Expression")
    if expr:
        return expr
    for classifier in dist.metadata.get_all("Classifier", []):
        mapped = _CLASSIFIER_TO_SPDX.get(classifier)
        if mapped:
            return mapped
    raw = (dist.metadata.get("License") or "").strip()
    if raw and "\n" not in raw and len(raw) < 60:
        return raw
    return "UNVERIFIED" if not raw else f"UNVERIFIED (raw metadata: {raw[:40]!r})"


def _runtime_dependency_names() -> set[str]:
    """Every package reachable from `askwell`'s own runtime dependencies,
    walking `api/uv.lock` rather than installed metadata's `Requires-Dist`.

    `Requires-Dist` strings carry a package's *own* environment markers
    (`pytest; extra == "test"` is common on libraries that declare their own
    test suite as an optional extra) with no way to tell, from the string
    alone, whether *this* project opted into that extra. The lockfile has
    already answered that question once, for the one resolution that matters
    here: each `[[package]]` entry's `dependencies` list is exactly what was
    selected for this project's environment, and an entry naming
    `extra = [...]` (e.g. `arq` unconditionally depending on `redis` with its
    `hiredis` extra) is followed into that package's own
    `optional-dependencies` table — not skipped, the way a bare `extra ==`
    marker match would skip it.
    """
    lock = tomllib.loads((REPO_ROOT / "api" / "uv.lock").read_text())
    packages = {_canonical(p["name"]): p for p in lock["package"]}

    closure: set[str] = set()
    frontier = ["askwell"]
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        closure.add(name)
        pkg = packages.get(name)
        if pkg is None:
            continue
        for dep in pkg.get("dependencies", []):
            dep_name = _canonical(dep["name"])
            frontier.append(dep_name)
            # `extra = ["hiredis"]` on a dependency entry means *that*
            # package's own `optional-dependencies.hiredis` table was
            # selected — e.g. arq's dependency on redis with its hiredis
            # extra, resolved by looking the extra up on redis's own
            # package entry, not arq's.
            extras = dep.get("extra", [])
            if extras:
                dep_pkg = packages.get(dep_name, {})
                for extra_name in extras:
                    for extra_dep in dep_pkg.get("optional-dependencies", {}).get(extra_name, []):
                        frontier.append(_canonical(extra_dep["name"]))
    closure.discard("askwell")
    return closure


def collect_python_dependencies() -> list[DependencyNotice]:
    runtime_names = _runtime_dependency_names()
    notices = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if _canonical(name) == "askwell":
            # This project's own editable install, not a third party.
            continue
        scope = "runtime" if _canonical(name) in runtime_names else "dev-only"
        notices.append(
            DependencyNotice(
                name=name,
                version=dist.version,
                license=_python_license(dist),
                scope=scope,
            )
        )
    return sorted(notices, key=lambda n: n.name.lower())


def collect_web_dependencies(web_licenses_path: Path) -> list[DependencyNotice]:
    if not web_licenses_path.exists():
        print(  # noqa: T201 - a command, talking to a terminal
            f"warning: {web_licenses_path} not found — run "
            f"`scripts/dev.sh web-run pnpm licenses list --json --prod "
            f"> {web_licenses_path}` first. The web half of NOTICES.md will be empty.",
            file=sys.stderr,
        )
        return []
    by_license = json.loads(web_licenses_path.read_text())
    notices = []
    for license_name, packages in by_license.items():
        for pkg in packages:
            for version in pkg["versions"]:
                notices.append(
                    DependencyNotice(
                        name=pkg["name"],
                        version=version,
                        license=license_name,
                        scope="runtime",
                    )
                )
    return sorted(notices, key=lambda n: n.name.lower())


def render(
    python_deps: list[DependencyNotice],
    web_deps: list[DependencyNotice],
) -> str:
    lines = [
        "# Third-party notices",
        "",
        "Generated by `scripts/generate_notices.py` — do not hand-edit. Regenerate with "
        "`scripts/dev.sh notices` after any dependency change.",
        "",
        "## Bundled model weights",
        "",
        "Verified against the model's own registry entry before being written here "
        "(`AGENTS.md` §4); C9 requires every one of these to permit redistribution and "
        "commercial use, and to be ungated. A model you swap in yourself is your own "
        "responsibility to check against the same terms.",
        "",
        "| Role | Model | Source | Licence | Verified | Note |",
        "| ---- | ----- | ------ | ------- | -------- | ---- |",
    ]
    for m in MODEL_NOTICES:
        lines.append(
            f"| {m.role} | {m.name} | {m.source} | {m.license} | {m.verified} | {m.note} |"
        )

    for title, deps in (
        ("Python dependencies (API, `api/pyproject.toml`)", python_deps),
        ("JavaScript dependencies (`web/package.json`)", web_deps),
    ):
        lines += ["", f"## {title}", ""]
        runtime = [d for d in deps if d.scope == "runtime"]
        dev_only = [d for d in deps if d.scope == "dev-only"]
        lines += [
            "### Shipped",
            "",
            "| Package | Version | Licence |",
            "| ------- | ------- | ------- |",
        ]
        lines += [f"| {d.name} | {d.version} | {d.license} |" for d in runtime]
        if dev_only:
            lines += [
                "",
                "### Development tooling only (never shipped)",
                "",
                "| Package | Version | Licence |",
                "| ------- | ------- | ------- |",
            ]
            lines += [f"| {d.name} | {d.version} | {d.license} |" for d in dev_only]

    lines.append("")
    return "\n".join(lines)


def check(python_deps: list[DependencyNotice], web_deps: list[DependencyNotice]) -> list[str]:
    problems = []
    for m in MODEL_NOTICES:
        for token in disallowed_tokens(m.license):
            problems.append(f"model {m.name!r} ({m.role}): disallowed licence {token}")
    for d in python_deps + web_deps:
        if d.scope != "runtime":
            continue
        for token in disallowed_tokens(d.license):
            problems.append(f"python/js package {d.name!r} {d.version}: disallowed licence {token}")
    return problems


def main() -> int:
    web_licenses_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_WEB_LICENSES
    python_deps = collect_python_dependencies()
    web_deps = collect_web_dependencies(web_licenses_path)

    NOTICES_PATH.write_text(render(python_deps, web_deps))
    print(f"wrote {NOTICES_PATH}")  # noqa: T201 - a command, talking to a terminal

    problems = check(python_deps, web_deps)
    if problems:
        print(  # noqa: T201 - a command, talking to a terminal
            "\nDISALLOWED LICENCES FOUND — release gate fails:", file=sys.stderr
        )
        for p in problems:
            print(f"  - {p}", file=sys.stderr)  # noqa: T201 - a command, talking to a terminal
        return 1

    print("no disallowed licences found")  # noqa: T201 - a command, talking to a terminal
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
