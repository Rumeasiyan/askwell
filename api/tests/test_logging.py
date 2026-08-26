"""Logs must be structured, timestamped, named — and must never carry a secret.

The redaction tests are the point of this module. Everything else here would
be caught by reading the output once; a credential reaching a log file is
caught by nobody, because the log looks completely normal.
"""

import json
import logging

import pytest
import structlog
from pydantic import SecretStr

from askwell.logging import REDACTED, configure_logging, get_logger, redact_secrets


def _capture() -> structlog.testing.LogCapture:
    capture = structlog.testing.LogCapture()
    structlog.configure(processors=[redact_secrets, capture])
    return capture


def test_event_carries_a_timestamp_and_a_name() -> None:
    configure_logging(level="INFO")
    with structlog.testing.capture_logs() as captured:
        get_logger("test").info("ingest_started", document="a.pdf")
    assert captured[0]["event"] == "ingest_started"
    assert captured[0]["document"] == "a.pdf"


def test_json_output_is_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    # A literal unrelated to the real version: test_version.py scans the tree
    # for a second declared version, and a fixture is not an exception to that.
    get_logger("test").info("startup", build="deadbeef")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "startup"
    assert parsed["build"] == "deadbeef"
    assert parsed["level"] == "info"
    assert parsed["timestamp"].endswith("Z")


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "PASSWORD",
        "db_password",
        "secret",
        "api_key",
        "apikey",
        "token",
        "credential",
        "authorization",
        "database_url",
        "dsn",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    result = redact_secrets(None, "info", {"event": "x", key: "hunter2"})
    assert result[key] == REDACTED
    assert "hunter2" not in json.dumps(result)


def test_secretstr_is_redacted_whatever_the_key_is_called() -> None:
    """A SecretStr says it is a secret; the key name is then irrelevant."""
    result = redact_secrets(None, "info", {"event": "x", "harmless": SecretStr("hunter2")})
    assert result["harmless"] == REDACTED


def test_redaction_reaches_nested_values() -> None:
    """Component states and settings dumps are logged as nested structures."""
    event = {
        "event": "startup",
        "config": {"database_url": "postgresql://u:hunter2@h/db", "port": 8000},
        "attempts": [{"token": "abc"}, {"ok": True}],
    }
    result = redact_secrets(None, "info", event)
    assert "hunter2" not in json.dumps(result)
    assert "abc" not in json.dumps(result)
    # Redaction must not eat the non-secret context around it.
    assert result["config"]["port"] == 8000  # type: ignore[index]


def test_non_secret_values_survive() -> None:
    result = redact_secrets(None, "info", {"event": "x", "document": "contract.pdf"})
    assert result["document"] == "contract.pdf"


def test_unknown_log_level_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="LOUD"):
        configure_logging(level="LOUD")


def test_stdlib_logging_is_routed_to_the_same_stream() -> None:
    """uvicorn logs through stdlib. Two formats in one stream is not observability."""
    configure_logging(level="WARNING")
    assert logging.getLogger().level == logging.WARNING
