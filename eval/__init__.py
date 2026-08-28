"""The eval harness. `docs/build-plan.md` quality gate; `AGENTS.md` §4.

This package holds the harness only: suite loading, scoring, three-run
execution, mean/worst-of-3 aggregation, and the results format. The eight
category suites (165 tasks) are separate tickets (`M2-EVAL-TEST-064` onward)
and are not implemented here — `eval/suites/smoke.v1.json` is a fixture that
exercises the harness itself, not one of them.
"""

import eval._bootstrap  # noqa: F401  (import order is the point: sys.path first)
