"""`M9-REL-DEPLOY-214` — the release workflow and the shell's bundling switch.

The workflow runs only on a tag, so nothing else exercises it before the day
it matters. What is pinned here is what a later edit could quietly break and
a green run would not show: that it never publishes, that one platform
failing stops the draft instead of shipping the other two, that a re-run
replaces its draft, that GitHub's own token is the only credential (C8), and
that every platform's artefact is built by a job of its own.

Read as text, split into jobs by indentation, rather than through a YAML
library: the API has none as a direct dependency, and adding one to test a
file that GitHub parses is the wrong trade.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
TAURI_CONF = REPO_ROOT / "web" / "src-tauri" / "tauri.conf.json"
ASSEMBLER = REPO_ROOT / "scripts" / "release-artefact.sh"

PLATFORMS = {"linux": "ubuntu-", "windows": "windows-", "macos": "macos-"}


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The workflow without its comments, so prose cannot satisfy or trip a check."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _jobs() -> dict[str, str]:
    body = _code(_text()).split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z0-9_-]*):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_bundling_is_enabled_in_the_shell_config() -> None:
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    assert conf["bundle"]["active"] is True


def test_runs_on_a_version_tag_and_by_hand() -> None:
    code = _code(_text())
    assert re.search(r'^  push:\n    tags: \["v\*"\]', code, re.MULTILINE)
    assert "workflow_dispatch:" in code


def test_each_platform_has_its_own_job_on_its_own_runner() -> None:
    jobs = _jobs()
    for job, runner in PLATFORMS.items():
        assert job in jobs, job
        assert re.search(rf"runs-on: {runner}", jobs[job]), job
        assert "cargo tauri build" in jobs[job], job
        assert f"name: shell-{job}" in jobs[job], job


def test_the_draft_waits_for_every_platform_and_names_a_failed_one() -> None:
    release = _jobs()["release"]
    assert "needs: [version, linux, windows, macos]" in release
    # always(), so it can say which platform failed; then it must stop.
    assert "if: ${{ always() }}" in release
    for label, job in (("Linux", "linux"), ("Windows", "windows"), ("macOS", "macos")):
        assert f"needs.{job}.result" in release
        assert f'failed="$failed {label} (' in release
    check = release.index("Every platform built")
    for later in ("gh release create", "gh api -X DELETE", "release-artefact.sh"):
        assert release.index(later) > check, later


def test_it_creates_a_draft_and_never_publishes() -> None:
    code = _code(_text())
    assert re.search(r"gh release create .*\n\s+--draft --prerelease", code)
    assert "gh release edit" not in code
    assert "--draft=false" not in code
    assert '"draft":false' not in code.replace(" ", "")


def test_a_rerun_replaces_its_draft_but_never_a_published_release() -> None:
    release = _jobs()["release"]
    replace = release.index("Replace any earlier draft")
    create = release.index("gh release create")
    assert replace < create
    step = release[replace:create]
    refuse = step.index('if [ "$draft" != true ]')
    assert step.index("gh api -X DELETE") > refuse


def test_githubs_own_token_is_the_only_credential() -> None:
    code = _code(_text())
    assert "secrets." not in code
    assert re.findall(r"contents: write", code) == ["contents: write"]
    assert "contents: write" in _jobs()["release"]
    assert re.search(r"^permissions:\n  contents: read$", code, re.MULTILINE)


def test_checksums_come_from_the_release_script_and_are_verified() -> None:
    release = _jobs()["release"]
    assert "scripts/release-checksums.sh" in release
    assert "sha256sum -c SHA256SUMS" in release
    for platform in PLATFORMS:
        assert f"scripts/release-artefact.sh {platform} " in release


def test_every_image_compose_names_is_saved() -> None:
    release = _jobs()["release"]
    assert "sed -n 's/^[[:space:]]*image:[[:space:]]*//p' compose.yaml" in release
    assert "docker save" in release


def test_the_assembler_ships_each_shell_where_its_installer_looks() -> None:
    script = ASSEMBLER.read_text(encoding="utf-8")
    expected = {
        "linux": ("deploy/linux/install.sh", "web/src-tauri/target/release/askwell-shell"),
        "windows": (
            "deploy/windows/install.ps1",
            "web\\src-tauri\\target\\release\\askwell-shell.exe",
        ),
        "macos": (
            "deploy/macos/install.sh",
            "web/src-tauri/target/release/bundle/macos/Askwell.app",
        ),
    }
    for platform, (installer, path) in expected.items():
        assert path in (REPO_ROOT / installer).read_text(encoding="utf-8"), platform
        assert path.replace("\\", "/") in script, platform
