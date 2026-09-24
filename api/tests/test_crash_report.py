"""`askwell.crash_report` — `M7-OPS-DOC-165`.

The ticket's edge case, asserted directly: a crash whose error message, local
variables, cause and request all carry a filename and a question produces a
report containing neither. And the report is only ever a local file.
"""

import ast
import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from askwell import __version__, crash_report
from askwell.app import create_app
from askwell.config import Settings

# Stand-ins for the user's own material. Each must never appear in a report.
FILENAME = "Harlow-v-Pemberton-settlement-DRAFT.pdf"
QUESTION = "what did the tenant agree to pay for the roof repairs"
CORPUS_ROW = "4,200 credits quarterly retainer"
SECRETS_IN_PLAY = (FILENAME, QUESTION, CORPUS_ROW, "Harlow", "roof repairs")


@pytest.fixture
def crash_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"crash_report_dir": tmp_path / "crash-reports"})


def _failing_with_corpus_content() -> None:
    document = FILENAME  # noqa: F841 — a local variable a report must not read
    question = QUESTION  # noqa: F841
    try:
        raise FileNotFoundError(f"could not open {FILENAME} for {QUESTION!r}")
    except FileNotFoundError as cause:
        raise ValueError(f"extraction failed on {CORPUS_ROW} in {FILENAME}") from cause


def _raised() -> ValueError:
    try:
        _failing_with_corpus_content()
    except ValueError as error:
        return error
    raise AssertionError("did not raise")


def _only_report(directory: Path) -> str:
    reports = list(directory.iterdir())
    assert len(reports) == 1, reports
    return reports[0].read_text(encoding="utf-8")


def test_report_is_written_locally_at_the_stated_location(crash_settings: Settings) -> None:
    path = crash_report.write(_raised(), component="worker", settings=crash_settings)

    assert path is not None
    assert path.parent == crash_settings.crash_report_dir
    assert crash_report._NAME.match(path.name)
    assert "-worker-" in path.name


def test_default_location_is_inside_the_state_volume() -> None:
    # The stated location in `docs/rollback-and-incidents.md` and SUPPORT.md.
    assert Settings.model_fields["crash_report_dir"].default == Path(
        "/var/lib/askwell/crash-reports"
    )


def test_report_carries_no_filename_question_or_corpus_content(
    crash_settings: Settings,
) -> None:
    crash_report.write(_raised(), component="api", settings=crash_settings, route="/ask")

    text = _only_report(crash_settings.crash_report_dir)
    for secret in SECRETS_IN_PLAY:
        assert secret not in text, secret


def test_report_carries_what_a_maintainer_needs(crash_settings: Settings) -> None:
    crash_report.write(_raised(), component="api", settings=crash_settings, route="/ask")

    report = json.loads(_only_report(crash_settings.crash_report_dir))
    assert report["format"] == crash_report.FORMAT
    assert report["askwell_version"] == __version__
    assert report["component"] == "api"
    assert report["profile"] == str(crash_settings.profile)
    assert report["route"] == "/ask"
    assert report["exception"]["type"] == "builtins.ValueError"
    assert report["exception"]["chain"] == ["builtins.FileNotFoundError"]
    functions = [frame["function"] for frame in report["frames"]]
    assert "_failing_with_corpus_content" in functions
    assert report["excluded"] == crash_report.EXCLUDED


def test_report_has_exactly_the_allow_listed_keys(crash_settings: Settings) -> None:
    report = crash_report.build_report(_raised(), component="api", settings=crash_settings)

    assert set(report) == {
        "format",
        "askwell_version",
        "component",
        "occurred_at",
        "platform",
        "profile",
        "route",
        "exception",
        "frames",
        "excluded",
    }
    for frame in report["frames"]:
        assert set(frame) == {"location", "function", "line"}


def test_a_frame_outside_known_code_is_not_named(tmp_path: Path) -> None:
    # A frame path is reported only when it is Askwell's, a dependency's or
    # the standard library's — never an arbitrary path that could be a user's.
    assert crash_report._frame_location(str(tmp_path / FILENAME)) == "<other>"
    assert crash_report._frame_location("<string>") == "<other>"
    assert crash_report._frame_location(crash_report.__file__) == "askwell/crash_report.py"


def test_writing_never_raises_when_the_directory_is_unwritable(
    settings: Settings, tmp_path: Path
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    unwritable = settings.model_copy(update={"crash_report_dir": blocker / "crash-reports"})

    assert crash_report.write(_raised(), component="api", settings=unwritable) is None


def test_old_reports_are_pruned(crash_settings: Settings) -> None:
    for _ in range(crash_report.KEEP + 5):
        crash_report.write(_raised(), component="api", settings=crash_settings)

    assert len(list(crash_settings.crash_report_dir.iterdir())) == crash_report.KEEP


def test_crash_is_logged_locally_without_its_message(crash_settings: Settings) -> None:
    with capture_logs() as logged:
        crash_report.write(_raised(), component="api", settings=crash_settings)

    events = [entry for entry in logged if entry["event"] == "crash_report_written"]
    assert len(events) == 1
    assert events[0]["exception_type"] == "builtins.ValueError"
    text = json.dumps(logged)
    for secret in SECRETS_IN_PLAY:
        assert secret not in text, secret


def test_unhandled_api_error_writes_a_report_without_the_request(
    crash_settings: Settings,
) -> None:
    app = create_app(crash_settings)

    async def crash(name: str) -> None:
        raise RuntimeError(f"failed on {name}")

    app.add_api_route("/test-crash/{name}", crash)
    # Ahead of the interface's catch-all, which would otherwise answer 404.
    app.router.routes.insert(0, app.router.routes.pop())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/test-crash/{FILENAME}", params={"q": QUESTION})

    assert response.status_code == 500
    report = json.loads(_only_report(crash_settings.crash_report_dir))
    assert report["route"] == "/test-crash/{name}"
    text = json.dumps(report)
    for secret in SECRETS_IN_PLAY:
        assert secret not in text, secret


def test_reports_are_listed_and_downloaded_from_this_machine(
    crash_settings: Settings,
) -> None:
    path = crash_report.write(_raised(), component="api", settings=crash_settings)
    assert path is not None
    client = TestClient(create_app(crash_settings))

    listed = client.get("/crash-reports").json()
    assert listed["directory"] == str(crash_settings.crash_report_dir)
    assert [item["name"] for item in listed["reports"]] == [path.name]

    downloaded = client.get(f"/crash-reports/{path.name}")
    assert downloaded.status_code == 200
    assert downloaded.json()["format"] == crash_report.FORMAT


def test_no_reports_is_an_empty_list_not_an_error(crash_settings: Settings) -> None:
    client = TestClient(create_app(crash_settings))

    assert client.get("/crash-reports").json()["reports"] == []


@pytest.mark.parametrize("name", ["..%2F..%2Fetc%2Fpasswd", "notes.txt", "crash-x.json"])
def test_download_refuses_anything_but_a_report_name(crash_settings: Settings, name: str) -> None:
    crash_settings.crash_report_dir.mkdir(parents=True)
    (crash_settings.crash_report_dir / "notes.txt").write_text(FILENAME)
    client = TestClient(create_app(crash_settings))

    assert client.get(f"/crash-reports/{name}").status_code == 404


def test_process_level_hooks_write_a_report_and_keep_the_previous_hook(
    crash_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda *_: seen.append("sys"))
    monkeypatch.setattr(threading, "excepthook", lambda _: seen.append("thread"))

    crash_report.install_excepthook(crash_settings, "worker")
    error = _raised()
    sys.excepthook(type(error), error, error.__traceback__)
    thread = threading.Thread(target=_failing_with_corpus_content)
    thread.start()
    thread.join()

    assert seen == ["sys", "thread"]
    reports = list(crash_settings.crash_report_dir.iterdir())
    assert len(reports) == 2
    for report in reports:
        text = report.read_text(encoding="utf-8")
        for secret in SECRETS_IN_PLAY:
            assert secret not in text, secret


def test_module_has_no_way_to_send_anything() -> None:
    # Nothing is transmitted, ever: the module imports no network client.
    tree = ast.parse(Path(crash_report.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"httpx", "requests", "urllib", "http", "socket", "aiohttp", "smtplib", "ssl"}
    assert not imported & forbidden, imported & forbidden
