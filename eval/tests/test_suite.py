import json
from pathlib import Path

import pytest
from eval.suite import SuiteError, load_suite, resolve_suite_path, suites_dir


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(payload))
    return path


def _valid_payload() -> dict[str, object]:
    return {
        "name": "example.v1",
        "category": "example",
        "pass_bar": 0.85,
        "tasks": [
            {"id": "a", "prompt": "hi", "scorer": "contains_all", "expected": "hi"},
        ],
    }


def test_load_suite_reads_tasks(tmp_path: Path) -> None:
    suite = load_suite(_write(tmp_path, _valid_payload()))
    assert suite.name == "example.v1"
    assert len(suite.tasks) == 1
    assert suite.tasks[0].timeout_seconds == 60.0
    assert suite.strict is False


def test_pass_bar_one_is_strict(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["pass_bar"] = 1.0
    suite = load_suite(_write(tmp_path, payload))
    assert suite.strict is True


def test_missing_file_raises_suite_error(tmp_path: Path) -> None:
    with pytest.raises(SuiteError, match="no suite"):
        load_suite(tmp_path / "nope.json")


def test_invalid_json_raises_suite_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(SuiteError, match="not valid JSON"):
        load_suite(path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["pass_bar"]
    with pytest.raises(SuiteError, match="pass_bar"):
        load_suite(_write(tmp_path, payload))


def test_empty_tasks_raises(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["tasks"] = []
    with pytest.raises(SuiteError, match="no tasks"):
        load_suite(_write(tmp_path, payload))


def test_duplicate_task_id_raises(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["tasks"] = [payload["tasks"][0], payload["tasks"][0]]  # type: ignore[index]
    with pytest.raises(SuiteError, match="duplicate task id"):
        load_suite(_write(tmp_path, payload))


def test_out_of_range_pass_bar_raises(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["pass_bar"] = 1.5
    with pytest.raises(SuiteError, match=r"\[0, 1\]"):
        load_suite(_write(tmp_path, payload))


def test_resolve_suite_path_finds_real_fixture() -> None:
    path = resolve_suite_path("smoke.v1")
    assert path == suites_dir() / "smoke.v1.json"


def test_resolve_suite_path_unknown_lists_available() -> None:
    with pytest.raises(SuiteError, match=r"smoke\.v1"):
        resolve_suite_path("no-such-suite")
