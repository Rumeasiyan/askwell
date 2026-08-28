"""Suite and task definitions, loaded from `eval/suites/*.json`.

A suite is one category from the quality gate (`docs/build-plan.md`) — or,
until those exist, the harness's own fixture. The file format is deliberately
plain JSON rather than a Python module: a task list is data a non-engineer
reviewing the quality bar can read, and versioning a suite (`v1`, `v2`) is a
new file rather than a diff that changes what "the abstention suite" meant
retroactively.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SuiteError(ValueError):
    """A suite file is malformed or names something the harness cannot do."""


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    prompt: str
    scorer: str
    expected: object
    timeout_seconds: float
    expected_documents: tuple[str, ...] = ()
    """`mode: "grounded"` only: filenames under `eval/fixtures/corpus/` that
    a citation must resolve to for the task to count as correctly grounded.
    More than one filename is the ticket's own "answer appears in two
    places" edge case — either is accepted."""
    expected_passages: tuple[str, ...] = ()
    """`mode: "grounded"` only: substrings (case-insensitive) of which at
    least one must appear in the cited chunk's content. Several entries
    exist for the same "two places" edge case as `expected_documents`."""
    expect_conflict: bool = True
    """`mode: "conflict"` only: `true` for a genuine two-position task —
    scored on presenting and citing both `expected_documents`. `false` for
    the false-conflict-on-wording and superseded-document edge cases
    (`M2-EVAL-TEST-066`), where a single, non-conflict answer is correct and
    presenting one anyway is the over-detection failure this field exists
    to catch."""
    position_values: tuple[str, ...] = ()
    """`mode: "conflict"` only: substrings (case-insensitive) the composed
    answer must contain. For a genuine conflict, both positions' values —
    the "no silent preference" check, since a silently preferred source
    would only surface one. For a false conflict or a superseded pair, the
    single correct value."""


@dataclass(frozen=True, slots=True)
class Suite:
    name: str
    category: str
    pass_bar: float
    """The quality-gate bar for this category (`docs/build-plan.md`).

    `1.0` marks a suite that must report pass/fail rather than a mean — SQL
    safety and web-escalation discipline are the two named there, because
    "0.97 on ten tasks" reads as nearly fine when it is a failure.
    """
    tasks: tuple[Task, ...]
    mode: str = "completion"
    """`"completion"` (default) runs `eval.runner` — one isolated
    `InferenceClient.generate()` call per task, no retrieval. `"grounded"`
    runs `eval.grounded` instead — the real `askwell.ask` retrieve-and-cite
    path against the fixture corpus, needed once a suite's tasks carry
    `expected_documents`/`expected_passages` (`M2-EVAL-TEST-064`). `"abstain"`
    runs `eval.abstain` — the same real `askwell.ask` path, scored on whether
    the turn abstained and named what it searched (`M2-EVAL-TEST-065`).
    `"conflict"` runs `eval.conflict` — the same real path again, scored on
    whether a genuine conflict between two live documents is presented as
    both positions, cited, with neither silently preferred
    (`M2-EVAL-TEST-066`)."""

    @property
    def strict(self) -> bool:
        return self.pass_bar >= 1.0


_DEFAULT_TIMEOUT_SECONDS = 60.0


def load_suite(path: Path) -> Suite:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise SuiteError(f"no suite at {path}") from None
    except json.JSONDecodeError as error:
        raise SuiteError(f"{path} is not valid JSON: {error}") from error

    for field in ("name", "category", "pass_bar", "tasks"):
        if field not in raw:
            raise SuiteError(f"{path} is missing required field '{field}'")

    tasks_raw = raw["tasks"]
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise SuiteError(f"{path} has no tasks")

    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for entry in tasks_raw:
        task = _load_task(path, entry)
        if task.id in seen_ids:
            raise SuiteError(f"{path} has a duplicate task id: {task.id!r}")
        seen_ids.add(task.id)
        tasks.append(task)

    pass_bar = float(raw["pass_bar"])
    if not 0.0 <= pass_bar <= 1.0:
        raise SuiteError(f"{path} pass_bar must be in [0, 1], got {pass_bar!r}")

    mode = str(raw.get("mode", "completion"))
    if mode not in ("completion", "grounded", "abstain", "conflict"):
        raise SuiteError(
            f"{path}: unknown mode {mode!r}. Available: completion, grounded, abstain, conflict"
        )
    if mode == "grounded":
        for task in tasks:
            if not task.expected_documents or not task.expected_passages:
                raise SuiteError(
                    f"{path}: task {task.id!r} is in a 'grounded' suite but is missing "
                    "'expected_documents' and/or 'expected_passages'"
                )
    if mode == "conflict":
        for task in tasks:
            if not task.expected_documents or not task.position_values:
                raise SuiteError(
                    f"{path}: task {task.id!r} is in a 'conflict' suite but is missing "
                    "'expected_documents' and/or 'position_values'"
                )

    return Suite(
        name=str(raw["name"]),
        category=str(raw["category"]),
        pass_bar=pass_bar,
        tasks=tuple(tasks),
        mode=mode,
    )


def _load_task(path: Path, entry: Any) -> Task:
    for field in ("id", "prompt", "scorer", "expected"):
        if field not in entry:
            raise SuiteError(f"{path}: task {entry!r} is missing required field '{field}'")
    return Task(
        id=str(entry["id"]),
        prompt=str(entry["prompt"]),
        scorer=str(entry["scorer"]),
        expected=entry["expected"],
        timeout_seconds=float(entry.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)),
        expected_documents=tuple(entry.get("expected_documents", ())),
        expected_passages=tuple(entry.get("expected_passages", ())),
        expect_conflict=bool(entry.get("expect_conflict", True)),
        position_values=tuple(entry.get("position_values", ())),
    )


def suites_dir() -> Path:
    return Path(__file__).resolve().parent / "suites"


def resolve_suite_path(name: str) -> Path:
    """`name` is the file stem under `eval/suites/`, e.g. `smoke.v1`."""
    direct = suites_dir() / f"{name}.json"
    if direct.exists():
        return direct
    raise SuiteError(
        f"no suite named {name!r} in {suites_dir()}. "
        f"Available: {', '.join(sorted(p.stem for p in suites_dir().glob('*.json')))}"
    )
