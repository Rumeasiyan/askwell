"""Structured logging. JSON out, never `print`, never a secret.

AGENTS.md §6 requires structlog with JSON output and no direct printing —
`ruff`'s `T20` rule enforces the second half at lint time. This module supplies
the first, plus a redaction processor.

Redaction is a processor rather than a convention because conventions are
maintained by whoever is paying attention. A connection string logged into a
user's own log file is a leak of their own credential on their own machine —
smaller than a breach, but the kind of thing that ends up pasted into a bug
report.
"""

import logging
import sys
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import SecretStr

# Substrings that mark a value as not for logging. Matched against the key,
# case-insensitively, at any depth.
_SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "database_url",
    "dsn",
)

REDACTED = "[redacted]"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _redact(value: Any) -> Any:
    """Recursively redact by key name, and unconditionally for SecretStr."""
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else _redact(inner)
            for key, inner in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def redact_secrets(_logger: object, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: strip anything that looks like a credential."""
    result = _redact(event_dict)
    # _redact returns the same shape it was given; a dict in means a dict out.
    assert isinstance(result, dict)
    return result


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install the logging configuration. Safe to call more than once.

    `json_output=False` gives a human-readable console renderer, which is for
    a developer reading a terminal. Everything that is not that should stay
    JSON so it can be searched.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError(
            f"Unknown log level {level!r}. Expected one of: "
            f"{', '.join(sorted(logging.getLevelNamesMapping()))}."
        )

    shared: list[Callable[..., Any]] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        # ISO 8601, UTC. A local timestamp in a log a user emails you is a
        # small puzzle every single time.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Last before rendering, so nothing added by an earlier processor
        # escapes it.
        redact_secrets,
    ]

    renderer: Callable[..., Any] = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Not cached, deliberately. Caching binds a logger to whatever
        # configuration was active the first time it was used, and modules hold
        # their loggers at import time — before `configure_logging` has run. The
        # result is a module whose output silently ignores the configuration,
        # which is worth more than the small per-call saving caching buys.
        cache_logger_on_first_use=False,
    )

    # uvicorn, and anything else that logs through the standard library, is
    # rendered by the same renderer rather than passed through verbatim. Left
    # alone, `Started server process [1]` lands as a bare line among JSON
    # objects, and a stream that is only sometimes parseable has to be handled
    # as if it never is.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Applied to records that did not come from structlog, to give them
            # the level, timestamp and redaction that structlog events already
            # carry by this point.
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A logger bound to a name. Use the module's `__name__`."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
