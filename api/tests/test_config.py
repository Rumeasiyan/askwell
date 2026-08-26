"""Configuration must refuse bad input at startup, and name what was bad.

The value of this module is entirely in the error messages. Pydantic already
validates; what is being tested here is whether a person reading the failure
learns which variable to fix.
"""

import pytest
from pydantic import SecretStr, ValidationError

from askwell.config import (
    ENV_PREFIX,
    ConfigurationError,
    Environment,
    Profile,
    Settings,
    load_settings,
)


def test_loads_with_only_the_required_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASKWELL_DATABASE_URL", "postgresql://u:p@postgres:5432/askwell")
    loaded = load_settings()
    assert loaded.environment is Environment.DEVELOPMENT
    assert loaded.profile is Profile.BALANCED
    assert loaded.host == "127.0.0.1"


def test_missing_required_variable_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The case a new contributor hits first."""
    monkeypatch.delenv("ASKWELL_DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError) as raised:
        load_settings()
    message = str(raised.value)
    assert "ASKWELL_DATABASE_URL" in message
    assert "no default" in message
    assert "Nothing has started" in message


def test_unknown_variable_is_reported_not_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must not leave the intended setting silently on its default."""
    monkeypatch.setenv("ASKWELL_DATABASE_URL", "postgresql://u:p@postgres:5432/askwell")
    monkeypatch.setenv("ASKWELL_LOG_LEVE", "DEBUG")  # missing the L
    with pytest.raises(ConfigurationError) as raised:
        load_settings()
    assert "ASKWELL_LOG_LEVE" in str(raised.value)


def test_invalid_value_names_the_variable_and_the_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASKWELL_DATABASE_URL", "postgresql://u:p@postgres:5432/askwell")
    monkeypatch.setenv("ASKWELL_PORT", "70000")
    with pytest.raises(ConfigurationError) as raised:
        load_settings()
    message = str(raised.value)
    assert "ASKWELL_PORT" in message
    assert "invalid" in message


def test_every_reported_problem_is_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix one variable, restart, discover the next one is not a good loop."""
    monkeypatch.setenv("ASKWELL_PORT", "0")
    monkeypatch.setenv("ASKWELL_NOT_A_SETTING", "x")
    with pytest.raises(ConfigurationError) as raised:
        load_settings()
    message = str(raised.value)
    assert "ASKWELL_DATABASE_URL" in message
    assert "ASKWELL_PORT" in message
    assert "ASKWELL_NOT_A_SETTING" in message


def test_database_url_is_secret(settings: Settings) -> None:
    """C8: it carries a password, so it must not survive repr or str."""
    assert isinstance(settings.database_url, SecretStr)
    assert "pw" not in repr(settings)
    assert "pw" not in str(settings.database_url)
    assert "pw" in settings.database_url.get_secret_value()


def test_database_host_port_parses_out_of_the_secret(settings: Settings) -> None:
    assert settings.database_host_port == ("127.0.0.1", 1)


def test_settings_are_frozen(settings: Settings) -> None:
    """Configuration resolved once at startup should not drift at runtime."""
    with pytest.raises(ValidationError):
        settings.port = 9999  # type: ignore[misc]


def test_prefix_is_what_the_messages_claim() -> None:
    assert ENV_PREFIX == "ASKWELL_"
