"""The host supervisor reads Askwell's `.env` when told where it is.
`M11-FIX-DEPLOY-225`.

Before this, every installer started the supervisor with no settings at all:
it looked for a model at "." and, taking the socket's default, wrote its
`state.json` into `/run/askwell` (Linux, permission denied) or
`C:\\run\\askwell` (Windows), neither of which the API reads. Same
arrangement as `test_model_swap_host.py`: the supervisor is a standalone
stdlib script, loaded by path.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SUPERVISOR = Path(__file__).resolve().parents[2] / "deploy" / "inference" / "askwell-inference"

# What an installed `.env` holds, trimmed: the containers' socket path, a
# relative run directory, a `~` model path, and a password it must not keep.
INSTALLED_ENV = """\
# Askwell settings
POSTGRES_APP_PASSWORD=s3cret=with=equals
ASKWELL_INFERENCE_SOCKET=/run/askwell/inference.sock
ASKWELL_RUN_DIR=./.run
ASKWELL_SOCKET_DIR=
ASKWELL_INFERENCE_MODEL_PATH=~/.local/share/askwell/models/model.gguf
ASKWELL_INFERENCE_CONTEXT_SIZE=4096
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_loader(
        "askwell_inference_env_file_host",
        importlib.machinery.SourceFileLoader("askwell_inference_env_file_host", str(SUPERVISOR)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["askwell_inference_env_file_host"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Whatever the test runner's own environment says is not under test.
    for name in list(os.environ):
        if name.startswith("ASKWELL_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return _load()


def _env_file(directory: Path, text: str = INSTALLED_ENV) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_supervisor_takes_its_settings_from_the_file(host: ModuleType, tmp_path: Path) -> None:
    host.load_env_file(_env_file(tmp_path / "app"))
    generation = host.Supervisor()
    assert generation.context_size == 4096
    # `~` expanded as the supervisor always has.
    assert generation.model == tmp_path / "home" / ".local/share/askwell/models/model.gguf"


def test_state_goes_in_the_run_directory_beside_the_file_not_the_containers_path(
    host: ModuleType, tmp_path: Path
) -> None:
    """The Ubuntu VM's `Permission denied: '/run/askwell'`, and Windows'
    `C:\\run\\askwell`: the file's socket is the containers' path, so the
    host's comes from ASKWELL_RUN_DIR, resolved against the app directory."""
    app = tmp_path / "app"
    host.load_env_file(_env_file(app))
    generation = host.Supervisor()
    assert generation.socket_path == app.resolve() / ".run" / "inference.sock"
    assert generation.state_path == app.resolve() / ".run" / "state.json"


def test_an_absolute_run_directory_is_used_as_it_is(host: ModuleType, tmp_path: Path) -> None:
    run = tmp_path / "elsewhere"
    host.load_env_file(_env_file(tmp_path / "app", f"ASKWELL_RUN_DIR={run}\n"))
    assert host.Supervisor().state_path == run / "state.json"


def test_a_run_directory_under_home_is_expanded(host: ModuleType, tmp_path: Path) -> None:
    host.load_env_file(_env_file(tmp_path / "app", "ASKWELL_RUN_DIR=~/askwell-run\n"))
    assert host.Supervisor().state_path == tmp_path / "home" / "askwell-run" / "state.json"


def test_no_run_directory_means_dot_run_beside_the_file(host: ModuleType, tmp_path: Path) -> None:
    app = tmp_path / "app"
    host.load_env_file(_env_file(app, "ASKWELL_INFERENCE_CONTEXT_SIZE=2048\n"))
    assert host.Supervisor().state_path == app.resolve() / ".run" / "state.json"


def test_the_file_never_overrides_what_is_already_set(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASKWELL_INFERENCE_CONTEXT_SIZE", "16384")
    monkeypatch.setenv("ASKWELL_RUN_DIR", str(tmp_path / "from-environment"))
    host.load_env_file(_env_file(tmp_path / "app"))
    generation = host.Supervisor()
    assert generation.context_size == 16384
    assert generation.state_path == tmp_path / "from-environment" / "state.json"


def test_a_socket_named_by_the_environment_wins(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`scripts/dev.sh inference` names the socket itself."""
    socket = tmp_path / "dev" / "inference.sock"
    monkeypatch.setenv("ASKWELL_INFERENCE_SOCKET", str(socket))
    host.load_env_file(_env_file(tmp_path / "app"))
    assert host.Supervisor().socket_path == socket


def test_everything_after_the_first_equals_sign_is_the_value(
    host: ModuleType, tmp_path: Path
) -> None:
    host.load_env_file(
        _env_file(tmp_path / "app", "ASKWELL_INFERENCE_BINARY=/opt/llama=b10645/llama-server\n")
    )
    assert host.env("ASKWELL_INFERENCE_BINARY", "") == "/opt/llama=b10645/llama-server"


def test_quotes_comments_export_and_blank_lines(host: ModuleType, tmp_path: Path) -> None:
    host.load_env_file(
        _env_file(
            tmp_path / "app",
            '\n# ASKWELL_EMBEDDING_PORT=9999\nexport ASKWELL_EMBEDDING_PORT="8181"\n'
            "ASKWELL_RERANKER_PORT='8282'\nnot a setting\n",
        )
    )
    assert host.env("ASKWELL_EMBEDDING_PORT", "") == "8181"
    assert host.env("ASKWELL_RERANKER_PORT", "") == "8282"


def test_an_empty_value_means_the_default(host: ModuleType, tmp_path: Path) -> None:
    host.load_env_file(_env_file(tmp_path / "app", "ASKWELL_INFERENCE_BINARY=\n"))
    assert host.env("ASKWELL_INFERENCE_BINARY", "llama-server") == "llama-server"


def test_a_windows_file_with_a_byte_order_mark_reads(host: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "app" / ".env"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xef\xbb\xbfASKWELL_INFERENCE_CONTEXT_SIZE=2048\r\n")
    host.load_env_file(path)
    assert host.Supervisor().context_size == 2048


def test_the_file_is_not_copied_into_the_environment(host: ModuleType, tmp_path: Path) -> None:
    """A llama-server started from here inherits the environment; the file's
    passwords must not be in it (C8). Nothing but ASKWELL_ names is kept."""
    host.load_env_file(_env_file(tmp_path / "app"))
    assert "ASKWELL_INFERENCE_MODEL_PATH" not in os.environ
    assert "POSTGRES_APP_PASSWORD" not in os.environ
    assert "POSTGRES_APP_PASSWORD" not in host.SETTINGS


def test_the_option_is_parsed(host: ModuleType) -> None:
    assert host.parse_arguments(["--env-file", "/opt/askwell/.env"]).env_file == Path(
        "/opt/askwell/.env"
    )
    assert host.parse_arguments([]).env_file is None


def test_a_missing_file_stops_it_with_the_reason(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere" / ".env"
    result = subprocess.run(
        [sys.executable, str(SUPERVISOR), "--env-file", str(missing)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert "cannot read settings" in result.stderr
    assert "Traceback" not in result.stderr
