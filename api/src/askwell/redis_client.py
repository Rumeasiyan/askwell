"""Every Redis connection Askwell opens, authenticated as its own service.

`M8-FIX-SEC-177`, issue #730. Redis holds the egress grants the proxy
trusts, so which process may write which key is C1's business, not a detail.
`deploy/redis/users.acl` gives each service its own user with only the
commands and keys it uses; this module is how a process presents that user.

Redis is what enforces it. The `default` user is off, so a connection that
does not authenticate is refused outright, and a user reaching for a key it
was not given gets `NOPERM`. Nothing here decides a permission — it only
supplies the credential and, when a check is refused, says so in the log.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

from askwell.config import ConfigurationError, Settings
from askwell.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio

log = get_logger(__name__)


def credentials(settings: Settings) -> tuple[str | None, str | None]:
    """`(username, password)` as the Redis client takes them."""
    password = settings.redis_password
    return settings.redis_username, password.get_secret_value() if password else None


def connect(settings: Settings, *, timeout: float) -> redis.asyncio.Redis:
    """A client for this process's own Redis user. `timeout` bounds both
    connecting and each reply, the shape every caller already used."""
    import redis.asyncio as redis

    username, password = credentials(settings)
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        username=username,
        password=password,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )


def require_credentials(settings: Settings, service: str) -> None:
    """Refuse to start a process that uses Redis without its user.

    Redis would refuse it anyway, but later and less clearly: a missing
    password would surface as a failed health check or a queue that never
    moves, not as the one line that says what to set. Never a fallback to an
    unauthenticated connection — there is none to fall back to.
    """
    username, password = credentials(settings)
    missing = [
        name
        for name, value in (
            ("ASKWELL_REDIS_USERNAME", username),
            ("ASKWELL_REDIS_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            f"{service} connects to Redis as its own user and {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set. Compose sets both from the "
            f"REDIS_*_PASSWORD values in .env, which the installer generates (C8)."
        )


@contextlib.contextmanager
def refusal_logged(settings: Settings, operation: str) -> Iterator[None]:
    """Log a Redis refusal where it happened, then let it propagate.

    A `NOPERM` from Redis means this process reached for a key its user was
    not given — either `users.acl` is missing a grant this code needs, or the
    code is doing something it should not. Both are worth one loud line.
    """
    import redis.exceptions

    try:
        yield
    except redis.exceptions.NoPermissionError as error:
        log.error(
            "redis_write_refused",
            operation=operation,
            redis_user=settings.redis_username,
            error=str(error),
        )
        raise
