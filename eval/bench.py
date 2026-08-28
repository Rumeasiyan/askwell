#!/usr/bin/env python3
"""The eval harness entry point. `AGENTS.md` §4, `docs/build-plan.md`.

    python eval/bench.py --suite smoke.v1

Runs the named suite's tasks three times each against the configured model,
over the native inference process's Unix socket only — no other network
access is used or needed (C1). Prints a summary and writes the full record to
`eval/results/`.

Exits non-zero, with no results file written, if the model is not available:
a suite that could not be measured must never look like one that scored zero
(AGENTS.md's "fail clearly" edge case).
"""

import argparse
import sys
from pathlib import Path

# Inlined rather than `import eval._bootstrap`: run as `python eval/bench.py`,
# this script's own directory is on `sys.path`, not the repository root, so
# `eval` (and therefore `askwell`) is not importable until this runs.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (_REPO_ROOT, _REPO_ROOT / "api" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from askwell.config import ConfigurationError, load_settings  # noqa: E402
from eval.results import format_summary, suite_default_results_dir, write_report  # noqa: E402
from eval.runner import HarnessError, run_suite_sync  # noqa: E402
from eval.suite import SuiteError, load_suite, resolve_suite_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        required=True,
        help="suite name, the file stem under eval/suites/ (e.g. smoke.v1)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="where to write the result JSON (default: eval/results/)",
    )
    args = parser.parse_args(argv)

    try:
        suite_path = resolve_suite_path(args.suite)
        suite = load_suite(suite_path)
    except SuiteError as error:
        print(f"eval/bench.py: {error}", file=sys.stderr)  # noqa: T201 - a command, talking to a terminal
        return 2

    try:
        settings = load_settings()
    except ConfigurationError as error:
        print(f"eval/bench.py: {error}", file=sys.stderr)  # noqa: T201 - a command, talking to a terminal
        return 2

    try:
        report = run_suite_sync(settings, suite)
    except HarnessError as error:
        print(f"eval/bench.py: {error}", file=sys.stderr)  # noqa: T201 - a command, talking to a terminal
        return 1

    print(format_summary(report))  # noqa: T201 - a command, talking to a terminal
    out_path = write_report(report, args.results_dir or suite_default_results_dir())
    print(f"\nwritten to {out_path}")  # noqa: T201 - a command, talking to a terminal

    if report.strict and not report.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
