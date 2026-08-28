"""Scorers a suite task can name.

A scorer takes the model's raw text and the task's `expected` value and
returns a score in `[0.0, 1.0]`. The registry is intentionally small: the
eight real category suites (`M2-EVAL-TEST-064` onward) are what defines
real grading, including anything execution-matched (text-to-SQL) or
structural (tool selection). This ticket ships the harness, not the graders,
so only the two scorers generic enough to be useful for any suite — including
the fixture one — are here. A suite naming a scorer this registry does not
have fails loudly, listing what is available, rather than silently scoring
zero.
"""

from collections.abc import Callable

Scorer = Callable[[str, object], float]


def _contains_all(output: str, expected: object) -> float:
    """1.0 if every string in `expected` appears in `output`, else 0.0.

    Case-insensitive: task authors write natural phrases, and a model that
    capitalises differently has not failed the task.
    """
    if isinstance(expected, str):
        needles: list[str] = [expected]
    elif isinstance(expected, list) and all(isinstance(item, str) for item in expected):
        needles = expected
    else:
        raise ValueError(f"'contains_all' expects a string or list of strings, got {expected!r}")
    haystack = output.lower()
    return 1.0 if all(needle.lower() in haystack for needle in needles) else 0.0


def _exact(output: str, expected: object) -> float:
    """1.0 if `output`, stripped, equals `expected` exactly."""
    if not isinstance(expected, str):
        raise ValueError(f"'exact' expects a string, got {expected!r}")
    return 1.0 if output.strip() == expected else 0.0


SCORERS: dict[str, Scorer] = {
    "contains_all": _contains_all,
    "exact": _exact,
}


def score(name: str, output: str, expected: object) -> float:
    try:
        scorer = SCORERS[name]
    except KeyError:
        available = ", ".join(sorted(SCORERS))
        raise ValueError(f"unknown scorer {name!r}. Available: {available}") from None
    return scorer(output, expected)
