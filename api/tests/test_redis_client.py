"""`askwell.redis_client` — every Redis connection carries its service's user.

`M8-FIX-SEC-177`. What Redis refuses is proved against a real one in
`test_redis_acl.py`; this is the client side: the credential reaches every
connection, a process without one refuses to start, and a refusal is logged
by the process that was refused.
"""

from typing import Any

import pytest
import redis.asyncio as redis
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoPermissionError
from structlog.testing import capture_logs

from askwell import redis_client
from askwell.config import ConfigurationError, Settings
from askwell.worker import redis_settings


def _with(settings: Settings, **changes: Any) -> Settings:
    return settings.model_copy(update=changes)


def test_every_connection_presents_the_services_user(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(redis, "Redis", lambda **kwargs: seen.update(kwargs))
    redis_client.connect(
        _with(settings, redis_username="worker", redis_password=SecretStr("pw")), timeout=1.5
    )
    assert seen["username"] == "worker"
    assert seen["password"] == "pw"
    assert seen["socket_connect_timeout"] == seen["socket_timeout"] == 1.5


def test_the_queue_is_reached_as_the_same_user(settings: Settings) -> None:
    """arq opens its own connections; they must authenticate too, or the
    worker would be the one service still arriving as nobody."""
    queue = redis_settings(_with(settings, redis_username="api", redis_password=SecretStr("pw")))
    assert (queue.username, queue.password) == ("api", "pw")


@pytest.mark.parametrize(
    ("username", "password", "missing"),
    [
        (None, None, "ASKWELL_REDIS_USERNAME, ASKWELL_REDIS_PASSWORD are"),
        ("proxy", None, "ASKWELL_REDIS_PASSWORD is"),
        ("proxy", "", "ASKWELL_REDIS_PASSWORD is"),
        (None, "pw", "ASKWELL_REDIS_USERNAME is"),
    ],
)
def test_a_process_without_its_credential_refuses_to_start(
    settings: Settings, username: str | None, password: str | None, missing: str
) -> None:
    """The ticket's edge case: a password missing from `.env` fails loudly at
    start rather than falling back to no authentication."""
    incomplete = _with(
        settings,
        redis_username=username,
        redis_password=SecretStr(password) if password is not None else None,
    )
    with pytest.raises(ConfigurationError, match=missing) as refused:
        redis_client.require_credentials(incomplete, "The egress proxy")
    assert "The egress proxy" in str(refused.value)


def test_a_complete_credential_starts(settings: Settings) -> None:
    redis_client.require_credentials(
        _with(settings, redis_username="api", redis_password=SecretStr("pw")), "The API"
    )


def test_the_proxy_refuses_to_start_without_its_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ticket's own scenario, at the entry point: remove the proxy's
    password and the proxy does not start."""
    from askwell import egress

    for name, value in {
        "ASKWELL_DATABASE_URL": "postgresql://x:x@127.0.0.1:1/x",
        "ASKWELL_SANDBOX_DATABASE_URL": "postgresql://x:x@127.0.0.1:1/postgres",
        "ASKWELL_SANDBOX_OWNER_PASSWORD": "x",
        "ASKWELL_SANDBOX_READONLY_PASSWORD": "x",
        "ASKWELL_REDIS_USERNAME": "proxy",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ASKWELL_REDIS_PASSWORD", raising=False)
    started: list[bool] = []
    monkeypatch.setattr(egress, "serve", lambda _settings: started.append(True))

    with pytest.raises(SystemExit, match="ASKWELL_REDIS_PASSWORD"):
        egress.main()
    assert started == []


def test_a_refusal_is_logged_by_the_refused_process_and_still_raised(
    settings: Settings,
) -> None:
    with (
        capture_logs() as logged,
        pytest.raises(NoPermissionError),
        redis_client.refusal_logged(_with(settings, redis_username="worker"), "open_grant"),
    ):
        raise NoPermissionError("No permissions to access a key")
    assert logged == [
        {
            "event": "redis_write_refused",
            "log_level": "error",
            "operation": "open_grant",
            "redis_user": "worker",
            "error": "No permissions to access a key",
        }
    ]


def test_any_other_redis_failure_is_not_called_a_refusal(settings: Settings) -> None:
    with (
        capture_logs() as logged,
        pytest.raises(RedisConnectionError),
        redis_client.refusal_logged(settings, "open_grant"),
    ):
        raise RedisConnectionError("down")
    assert logged == []
