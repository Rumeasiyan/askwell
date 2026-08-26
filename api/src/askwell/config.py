"""Typed configuration, read from the environment once at startup.

Two rules shape this module.

Configuration is validated at load, not at first use. A misspelled variable
that surfaces an hour later as a connection error in unrelated code costs far
more to diagnose than a refusal to start that names the variable.

Nothing here is secret except by declaration. A value that carries a
credential is a `SecretStr`, which keeps it out of logs, tracebacks and
`repr()` by construction rather than by everyone remembering (C8).
"""

import os
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every Askwell variable carries this prefix. Without it, `extra="forbid"`
# below would reject the machine's entire environment.
ENV_PREFIX = "ASKWELL_"


class Environment(StrEnum):
    """Which way failures should go.

    AGENTS.md §6: fail loudly in development, degrade gracefully in production.
    """

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Profile(StrEnum):
    """Deployment profile, which selects models. Never a hardcoded model name."""

    LIGHT = "light"
    BALANCED = "balanced"
    FULL = "full"


Port = Annotated[int, Field(ge=1, le=65535)]


class Settings(BaseSettings):
    """Askwell's configuration. Constructed once, at startup."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    profile: Profile = Profile.BALANCED
    log_level: str = "INFO"

    # C1 and M0-STACK-SEC-012: the API binds to loopback. This is a default
    # that a later ticket will additionally enforce; it is not the enforcement.
    host: str = "127.0.0.1"
    port: Port = 8000

    # Required, and deliberately so: it carries a password, so there is no
    # honest default. Its absence is the case the startup message must handle
    # well, because it is the one a new contributor hits first.
    database_url: SecretStr

    # Components addressed by host and port rather than URL, because the health
    # probes are TCP-level at this stage. Defaults match the Compose service
    # names that arrive in M0-STACK-DEPLOY-009.
    redis_host: str = "redis"
    redis_port: Port = 6379

    worker_host: str = "worker"
    worker_port: Port = 8081

    # llama.cpp runs as a native host process, not a container, so from inside
    # the API container the host gateway is the address that reaches it.
    inference_host: str = "host.containers.internal"
    inference_port: Port = 8080

    egress_proxy_host: str = "egress-proxy"
    egress_proxy_port: Port = 3128

    # Where the built frontend lives. The default is the path inside the API
    # image; a source checkout points it at web/out.
    web_assets_dir: Path = Path("/app/web/out")

    # How long a single health probe may take. Health must answer even when
    # every component is down, so this is short and it is a ceiling per probe,
    # not for the whole surface.
    health_probe_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    @property
    def database_host_port(self) -> tuple[str, int]:
        """Host and port for the database, parsed out of the URL for probing.

        The URL is a secret because of its password; the host and port inside
        it are not, and health output needs them. Parsed here so that the
        secret is unwrapped in exactly one place.
        """
        from urllib.parse import urlsplit

        parts = urlsplit(self.database_url.get_secret_value())
        return parts.hostname or "postgres", parts.port or 5432


class ConfigurationError(RuntimeError):
    """Configuration is unusable. The message names what is wrong and where."""


def _unknown_variables(environ: Mapping[str, str]) -> list[str]:
    """`ASKWELL_*` variables that match no setting.

    `extra="forbid"` does not cover this and it is easy to assume it does:
    pydantic-settings reads only the variables it has fields for, so a
    misspelled name is not an extra value being rejected, it is a value never
    looked at. The setting it was meant to change keeps its default and nothing
    anywhere says so — which is the exact failure this module exists to
    prevent, so it is checked directly.
    """
    known = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}
    return sorted(
        name for name in environ if name.startswith(ENV_PREFIX) and name.upper() not in known
    )


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read configuration, or refuse to start with an explanation.

    Pydantic's own error text is accurate and unreadable at 6am. This turns it
    into something that names each offending variable by the name a person
    actually typed — `ASKWELL_DATABASE_URL`, not `database_url` — and says what
    to do about it.
    """
    unknown = _unknown_variables(os.environ if environ is None else environ)

    try:
        # Values come from the environment; the pydantic mypy plugin knows.
        settings = Settings()
    except ValidationError as error:
        raise ConfigurationError(_explain(error, unknown)) from error

    if unknown:
        raise ConfigurationError(_explain(None, unknown))
    return settings


def _explain(error: ValidationError | None, unknown: Sequence[str] = ()) -> str:
    lines = ["Askwell cannot start: its configuration is not usable.", ""]

    for variable in unknown:
        lines.append(
            f"  {variable} is set, but Askwell has no such setting. This is "
            f"usually a typo in a variable that does matter — if so, the one "
            f"you meant is still on its default. Check it against .env.example."
        )

    for problem in error.errors() if error is not None else []:
        location = problem["loc"]
        field = str(location[0]) if location else "(unknown)"
        variable = f"{ENV_PREFIX}{field.upper()}"

        if problem["type"] == "missing":
            lines.append(f"  {variable} is not set, and it has no default.")
        elif problem["type"] == "extra_forbidden":
            lines.append(
                f"  {variable} is set but Askwell has no such setting. "
                f"This is usually a typo in a variable that does matter — "
                f"check it against .env.example."
            )
        else:
            lines.append(f"  {variable} is set but invalid: {problem['msg']}.")

    lines += [
        "",
        "Nothing has started. Fix the above and start again — Askwell refuses",
        "to run on configuration it cannot validate, rather than failing later",
        "somewhere that will not mention the variable.",
    ]
    return "\n".join(lines)
