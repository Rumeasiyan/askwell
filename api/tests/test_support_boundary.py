"""`M7-DOC-DOC-164` — the stated support boundary and issue triage.

These are documents and templates, not code, so what is tested is the part
a later edit can quietly break: that the boundary still says it is one
maintainer, still names what is out of scope, still promises no response
time it cannot keep, and that the templates still *require* the version,
platform, profile and trace a report needs — plus that Settings → About
still reaches all of it.

Plain text checks rather than a YAML parser: nothing in the project depends
on one, and a structural check on `id:` blocks is enough to prove a field
is required.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPORT = REPO_ROOT / "SUPPORT.md"
SECURITY = REPO_ROOT / "SECURITY.md"
TEMPLATES = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
AGENTS = REPO_ROOT / "AGENTS.md"
ABOUT = REPO_ROOT / "web" / "components" / "settings" / "about.tsx"
COPY_SCRIPT = REPO_ROOT / "web" / "scripts" / "copy-support.mjs"
WEB_MANIFEST = REPO_ROOT / "web" / "package.json"

SECURITY_ADVISORY_URL = "https://github.com/Rumeasiyan/askwell/security/advisories/new"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _field_blocks(template: str) -> dict[str, str]:
    """Split an issue form into its fields, keyed by `id:`."""
    blocks: dict[str, str] = {}
    for chunk in re.split(r"^  - type: ", template, flags=re.MULTILINE)[1:]:
        found = re.search(r"^    id: (\S+)$", chunk, flags=re.MULTILINE)
        if found:
            blocks[found.group(1)] = chunk
    return blocks


def _required(template: str) -> set[str]:
    return {
        field_id
        for field_id, block in _field_blocks(template).items()
        if re.search(r"^      required: true$", block, flags=re.MULTILINE)
    }


# --- the boundary ------------------------------------------------------------


def test_the_boundary_says_it_is_one_maintainer() -> None:
    assert "maintained by one person" in _read(SUPPORT)


def test_the_boundary_has_every_section_the_ticket_names() -> None:
    text = _read(SUPPORT)
    for heading in (
        "## What is answered",
        "## What is not promised",
        "## What a good report contains",
        "## How issues are triaged",
    ):
        assert heading in text, heading


def test_a_good_report_names_version_platform_profile_and_trace() -> None:
    text = _read(SUPPORT)
    section = text[
        text.index("## What a good report contains") : text.index("## How issues are triaged")
    ]
    for item in ("**Version**", "**Platform**", "**Profile**", "**Trace**"):
        assert item in section, item
    # Each is paired with where to find it in the product, not just named.
    assert "Settings → About → Version" in section
    assert "Copy trace" in section


def test_own_database_and_hardware_are_named_out_of_scope() -> None:
    text = _read(SUPPORT)
    not_promised = text[
        text.index("## What is not promised") : text.index("## What a good report contains")
    ]
    assert "your own database" in not_promised
    assert "your own hardware" in not_promised
    # Named out of scope *with a pointer* to where it belongs.
    assert "belong with whoever runs that database" in not_promised


def test_no_response_time_is_promised_except_the_security_acknowledgement() -> None:
    """The ticket's Out of Scope: no response time a single maintainer cannot
    honour. The one time commitment is the owner-agreed security
    acknowledgement (issue #47); anything else is a promise that will be
    missed."""
    time_bound = re.compile(
        r"within (a|an|one|two|\d+) (hour|day|week|business day|working day)s?", re.IGNORECASE
    )
    promised = _read(SUPPORT)[: _read(SUPPORT).index("## What is not promised")]
    lines = [line for line in promised.splitlines() if time_bound.search(line)]
    assert lines == ["- Security reports are acknowledged within a week."]
    assert "A response time on ordinary issues" in _read(SUPPORT)


def test_triage_cadence_is_an_aim_not_a_deadline() -> None:
    text = _read(SUPPORT)
    triage = text[text.index("## How issues are triaged") :]
    assert "in batches" in triage
    assert "an aim rather than a deadline" in triage


def test_security_is_a_separate_route_in_the_boundary() -> None:
    text = _read(SUPPORT)
    assert "Report a security problem | **Not an issue.** See [`SECURITY.md`]" in text
    assert "separate route from ordinary support" in _read(SECURITY)


def test_every_triage_label_is_in_the_agents_label_table() -> None:
    """A label the convention relies on but nobody created is silently
    dropped by GitHub when a template applies it."""
    text = _read(SUPPORT)
    triage = text[text.index("## How issues are triaged") :]
    labels = set(re.findall(r"`([a-z][a-z-]+)`", triage)) - {"constraint"}
    agents = _read(AGENTS)
    table = agents[agents.index("### Labels") : agents.index("### Decision log")]
    for label in labels:
        assert f"`{label}`" in table, label


# --- the templates -----------------------------------------------------------


def test_blank_issues_are_off_and_security_has_its_own_route() -> None:
    config = _read(TEMPLATES / "config.yml")
    assert "blank_issues_enabled: false" in config
    assert SECURITY_ADVISORY_URL in config
    assert "not an issue" in config


def test_bug_template_requires_version_platform_profile_and_trace() -> None:
    bug = _read(TEMPLATES / "bug.yml")
    assert {"version", "platform", "profile", "trace", "what-happened"} <= _required(bug)
    assert "SECURITY.md" in bug


def test_bug_template_warns_that_a_trace_holds_the_users_material() -> None:
    trace = _field_blocks(_read(TEMPLATES / "bug.yml"))["trace"]
    assert "Read it before posting" in trace
    assert "this issue is public" in trace


def test_profile_options_match_the_real_profiles() -> None:
    bug = _field_blocks(_read(TEMPLATES / "bug.yml"))["profile"]
    for profile in ("light", "standard", "accelerated", "workstation"):
        assert f"        - {profile}\n" in bug, profile


def test_question_and_feature_templates_require_a_version() -> None:
    assert {"question", "version"} <= _required(_read(TEMPLATES / "question.yml"))
    assert {"problem", "version"} <= _required(_read(TEMPLATES / "feature.yml"))


def test_every_public_template_arrives_needing_triage() -> None:
    for name in ("bug.yml", "question.yml", "feature.yml"):
        assert '"needs-triage"' in _read(TEMPLATES / name), name


# --- reachable from the product ---------------------------------------------


def test_about_reaches_the_boundary_the_templates_and_the_security_route() -> None:
    about = _read(ABOUT)
    assert 'href="/support.txt"' in about
    assert 'href="/security-policy.txt"' in about
    assert "/issues/new/choose" in about
    # The boundary row comes before the row that opens an issue.
    assert about.index('href="/support.txt"') < about.index("/issues/new/choose")


def test_the_build_copies_the_boundary_rather_than_duplicating_it() -> None:
    script = _read(COPY_SCRIPT)
    assert '["SUPPORT.md", "support.txt"]' in script
    assert '["SECURITY.md", "security-policy.txt"]' in script
    assert "node scripts/copy-support.mjs" in _read(WEB_MANIFEST)
