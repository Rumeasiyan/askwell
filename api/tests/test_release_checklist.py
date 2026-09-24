"""`M7-QA-TEST-168` — the release readiness checklist and the walkthrough.

These are documents, so what is tested is what a later edit can quietly
break: that the checklist's eval table still matches the suites that
actually exist, that the two 1.00 categories stay pass-or-fail rather than
a number, that every gate the ticket names is still there with somewhere
for its evidence to live, that the walkthrough still reaches every
milestone's headline path and every screen, and that the release procedure
still refuses to checksum anything before the checklist has passed.

The suites are read as JSON rather than through `eval.suite`: this runs in
`api/tests/`, and the point is to compare the checklist against the files,
not against the loader's interpretation of them.
"""

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = REPO_ROOT / "docs" / "release-checklist.md"
WALKTHROUGH = REPO_ROOT / "docs" / "release-walkthrough.md"
RELEASE_LOG = REPO_ROOT / "docs" / "release-log.md"
PROCEDURE = REPO_ROOT / "docs" / "release-procedure.md"
BUILD_PLAN = REPO_ROOT / "docs" / "build-plan.md"
BACKLOG_INDEX = REPO_ROOT / "docs" / "backlog" / "README.md"
SUITES = REPO_ROOT / "eval" / "suites"
UX = REPO_ROOT / "docs" / "ux"

# Not a category: it checks the harness itself (`M2-EVAL-TEST-063`).
HARNESS_ONLY_SUITES = {"smoke.v1"}

# Screens with nothing a person walks through: the index and the token source.
UX_NOT_SCREENS = {"README.md", "design-system.md"}

# Not built yet. The walkthrough says its steps are appended when it lands.
MILESTONES_NOT_LANDED = {"M8"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _category_suites() -> dict[str, dict[str, Any]]:
    suites: dict[str, dict[str, Any]] = {}
    for path in sorted(SUITES.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["name"] not in HARNESS_ONLY_SUITES:
            suites[raw["name"]] = raw
    return suites


def _eval_rows() -> dict[str, tuple[int, str]]:
    """Suite name → (task count, pass condition), from the checklist's table."""
    table = _section(_read(CHECKLIST), "### G3 — the eval table")
    rows: dict[str, tuple[int, str]] = {}
    for line in table.splitlines():
        found = re.match(r"^\| [^|]+ \| `([^`]+)` \| (\d+) \| (.+) \|$", line)
        if found:
            rows[found.group(1)] = (int(found.group(2)), found.group(3))
    return rows


# --- the eval gate -------------------------------------------------------------


def test_the_eval_table_lists_every_category_suite_and_nothing_else() -> None:
    assert set(_eval_rows()) == set(_category_suites())


def test_the_eval_table_has_eight_categories_and_165_tasks() -> None:
    rows = _eval_rows()
    assert len(rows) == 8
    assert sum(count for count, _ in rows.values()) == 165
    assert "**165 tasks.**" in _read(CHECKLIST)


def test_each_row_matches_its_suite_file() -> None:
    for name, raw in _category_suites().items():
        count, condition = _eval_rows()[name]
        assert count == len(raw["tasks"]), f"{name}: checklist says {count} tasks"
        bar = float(raw["pass_bar"])
        if bar < 1.0:
            assert f"mean ≥ {bar:.2f}" in condition, f"{name}: bar {bar:.2f} not stated"


def test_the_strict_categories_are_pass_or_fail_not_a_number() -> None:
    """A 0.9 on a ten-task safety suite reads as fine and is not."""
    strict = [n for n, raw in _category_suites().items() if float(raw["pass_bar"]) >= 1.0]
    assert sorted(strict) == ["sql_safety.v1", "web_escalation.v1"]
    for name in strict:
        _, condition = _eval_rows()[name]
        assert "pass-or-fail" in condition
        assert "result: PASS" in condition
        assert not re.search(r"\d\.\d", condition), f"{name} states a number: {condition}"
    text = _read(CHECKLIST)
    assert "**SQL safety at 0.9 is a\n`FAIL`.**" in text


def test_the_checklist_agrees_with_the_build_plan_quality_gate() -> None:
    gate = _section(_read(BUILD_PLAN), "## Quality gate")
    categories = re.findall(r"^\| ([^|]+?) \| \d+ \|", gate, flags=re.MULTILINE)
    assert len(categories) == 8
    assert "165 tasks" in gate
    table = _section(_read(CHECKLIST), "### G3 — the eval table")
    for category in categories:
        assert f"| {category.split(' (')[0]}" in table, f"{category} missing from checklist"


def test_a_zero_exit_from_a_scored_suite_is_not_read_as_a_pass() -> None:
    assert "exits 0 for a scored suite even when it is below its bar" in _read(CHECKLIST)


# --- every gate ----------------------------------------------------------------


GATES = {
    "G1": ["`VERSION`", "`CHANGELOG.md`"],
    "G2": ["scripts/dev.sh check", "scripts/dev.sh test-db"],
    "G3": ["docs/release-evidence/<version>/eval/"],
    "G4": ["docs/offline-release-test.md", "docs/offline-test-log.md"],
    "G5": ["docs/restore-release-test.md", "docs/restore-test-log.md"],
    "G6": ["docs/security-review.md", "docs/security-review-log.md"],
    "G7": ["answer-latency", "voice-latency", "p50 < 20s", "p95 < 60s"],
    "G8": ["scripts/dev.sh notices", "C9"],
    "G9": ["SUPPORT.md", "SECURITY.md", "private-vulnerability-reporting"],
    "G10": ["docs/installing.md"],
    "G11": ["docs/release-walkthrough.md"],
    "G12": ["gh issue list --state open --label bug"],
}


def _gate_rows() -> dict[str, str]:
    table = _section(_read(CHECKLIST), "## The gates")
    return {
        found.group(1): line
        for line in table.splitlines()
        if (found := re.match(r"^\| (G\d+) \|", line))
    }


def test_every_gate_is_present_with_its_pass_condition_and_evidence() -> None:
    rows = _gate_rows()
    assert set(rows) == set(GATES)
    for gate, needles in GATES.items():
        cells = [c.strip() for c in rows[gate].strip("|").split("|")]
        assert len(cells) == 5, f"{gate} is not a five-column row"
        assert all(cells), f"{gate} has an empty cell — every gate needs all five"
        for needle in needles:
            assert needle in rows[gate], f"{gate} no longer mentions {needle}"


def test_the_rules_that_block_a_release_are_stated() -> None:
    text = _read(CHECKLIST)
    assert "**A gate that cannot run blocks the release.**" in text
    assert "**An intermittent failure is a failure.**" in text
    assert "**A known issue is never carried silently.**" in text
    assert "`BLOCKED` | The gate could not be run" in text


def test_the_constraint_gates_cannot_be_accepted() -> None:
    never = _section(_read(CHECKLIST), "### What can be accepted, and what cannot")
    for needle in (
        "**SQL safety**",
        "**web escalation discipline**",
        "**abstention**",
        "**offline**",
        "**restore**",
        "**security review**",
    ):
        assert needle in never


# --- the walkthrough -------------------------------------------------------------


def _milestones() -> set[str]:
    table = _section(_read(BACKLOG_INDEX), "## 3. Delivery milestones")
    return set(re.findall(r"^\| (M\d+(?:\.\d+)?) \|", table, flags=re.MULTILINE))


def test_the_walkthrough_covers_every_landed_milestone() -> None:
    covered: set[str] = set()
    for heading in re.findall(r"^## W\d+ .*\(([^)]+)\)$", _read(WALKTHROUGH), flags=re.MULTILINE):
        covered |= {m.strip() for m in heading.split(",")}
    assert _milestones() - MILESTONES_NOT_LANDED <= covered
    assert not covered & MILESTONES_NOT_LANDED, "M8 landed? Remove it from MILESTONES_NOT_LANDED"
    assert "M8" in _section(_read(WALKTHROUGH), "## Keeping this current")


def test_the_walkthrough_starts_from_a_cold_install_of_the_artefact() -> None:
    first = _section(_read(WALKTHROUGH), "## W0 — Install from the release artefact (M7)")
    assert "SHA256SUMS" in first
    assert "docs/installing.md" in first


def test_the_walkthrough_exercises_every_screen() -> None:
    text = _read(WALKTHROUGH)
    for screen in sorted(UX.glob("*.md")):
        if screen.name not in UX_NOT_SCREENS:
            assert f"docs/ux/{screen.name}" in text, f"no step reaches {screen.name}"


def test_the_ticket_headline_steps_are_in_the_walkthrough() -> None:
    text = _read(WALKTHROUGH)
    for needle in (
        "scanned PDF",
        "Rename the cited PDF",
        "**None appears in the provenance margin**",
        "It starts local again",
        "**second machine**",
        "Export everything",
        "Verify the log",
        "press Stop",
    ):
        assert needle in text, needle


def test_an_intermittent_step_is_marked_fail() -> None:
    assert "fails and then passes on a retry is marked **`FAIL`**" in _read(WALKTHROUGH)


def test_every_step_id_is_unique() -> None:
    ids = re.findall(r"^\| (W\d+\.\d+) \|", _read(WALKTHROUGH), flags=re.MULTILINE)
    assert ids and len(ids) == len(set(ids))


# --- the record, and the procedure that obeys it -----------------------------


def test_the_release_log_has_a_row_for_every_gate() -> None:
    fmt = _read(RELEASE_LOG)
    for gate in GATES:
        assert f"| {gate} " in fmt, f"release-log format has no {gate} row"
    for name in _category_suites():
        assert f"G3 Eval — {name}" in fmt
    assert "**Accepted known issues:**" in fmt


def test_the_procedure_holds_checksums_until_the_checklist_passes() -> None:
    text = _read(PROCEDURE)
    gate = text.index("## 3d. The release checklist")
    assert gate < text.index("## 4. Generate checksums")
    section = _section(text, "## 3d. The release checklist")
    assert "docs/release-checklist.md" in section
    assert "Decision: release" in section


def test_every_path_the_documents_name_exists() -> None:
    for doc in (CHECKLIST, WALKTHROUGH, RELEASE_LOG):
        for path in re.findall(r"`((?:docs|scripts|api|eval|web|\.github)/[^`\s]+)`", _read(doc)):
            if "<" in path:
                continue
            assert (REPO_ROOT / path.rstrip("/")).exists(), f"{doc.name} names missing {path}"


def test_the_outbound_count_is_never_read_with_a_bare_network_curl() -> None:
    """`/network` needs the session the interface takes; a bare curl answers
    `No session.` at exactly the step meant to prove nothing left (#702)."""
    docs = [REPO_ROOT / "AGENTS.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]
    for doc in docs:
        for line in _read(doc).splitlines():
            if re.search(r"curl [^`]*(?:localhost|127\.0\.0\.1):8000/network", line):
                assert " -b " in line, f"{doc.relative_to(REPO_ROOT)}: {line.strip()}"


def test_the_walkthrough_runs_nothing_that_only_a_checkout_has() -> None:
    """The walkthrough starts from the installed artefact, which ships no
    `scripts/` and no development tree (#717)."""
    assert "scripts/" not in _read(WALKTHROUGH)


def test_every_known_hold_names_an_issue_and_a_gate() -> None:
    holds = _section(_read(CHECKLIST), "## Known holds on the next release")
    rows = re.findall(r"^\| (#\d+) \| ([^|]+) \|", holds, flags=re.MULTILINE)
    assert rows
    for issue, gates in rows:
        assert re.search(r"G\d+", gates), f"{issue} holds no named gate"
