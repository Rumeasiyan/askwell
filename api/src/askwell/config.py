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

from pydantic import Field, SecretStr, ValidationError, field_validator
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

    # The worker is not addressed by host and port, deliberately. An arq
    # worker consumes a queue; it does not listen on anything, so a TCP probe
    # can never see it and would report a perfectly healthy worker as down.
    # It publishes a health record into Redis instead, and that is what gets
    # read. The key expires, so its presence is also its freshness.
    worker_health_key: str = "arq:queue:health-check"

    # Inference is a native host process — GPU acceleration only works from
    # the host on all three platforms — and the containers reach it over a Unix
    # socket rather than the network. Every service is on a network with no
    # route off the machine (C1), so there is no address to dial; a socket file
    # on a bind mount needs no route at all. See docs/decisions.md.
    inference_socket: Path = Path("/run/askwell/inference.sock")

    # Three roles, three processes, three models. One llama.cpp process cannot
    # serve all three: reranking needs `--reranking` and a reranker model,
    # which is mutually exclusive with generation, and a generation model's
    # embeddings are the wrong width for the schema entirely. Measured, not
    # assumed — see issue #89.
    #
    # Used by the host-side supervisor only. The containers never see these;
    # they reach all three through one socket.
    inference_binary: str = "llama-server"
    inference_context_size: int = Field(default=8192, ge=512, le=1_048_576)

    inference_model_path: Path = Path("~/.local/share/askwell/models/model.gguf")
    inference_upstream_port: Port = 8080

    # bge-m3 at 1024 dimensions, matching chunks.embedding. A different model
    # here is a different width, and the database will refuse the insert rather
    # than silently storing something useless.
    embedding_model_path: Path = Path("~/.local/share/askwell/models/embedding.gguf")
    embedding_port: Port = 8081

    # Reranking is a separate model and a separate process. It scores
    # query-document pairs; it cannot generate and generation cannot rank.
    reranker_model_path: Path = Path("~/.local/share/askwell/models/reranker.gguf")
    reranker_port: Port = 8082

    egress_proxy_host: str = "egress-proxy"
    egress_proxy_port: Port = 3128

    # The embedding model's output dimension, and therefore the width of
    # chunks.embedding. It is configuration rather than a literal in the
    # migration because changing the model is a configuration change plus a
    # re-embed, not a schema edit. bge-m3 gives 1024.
    embedding_dimensions: int = Field(default=1024, ge=1, le=16000)

    # How many documents are ingested at once. Two, because this laptop is
    # also running the user's browser and the answer they are waiting for:
    # extraction and embedding are CPU-bound and will take every core they are
    # given, and an import that makes the machine unusable is an import the
    # user kills. Raise it on a workstation; it is configuration precisely
    # because the right number is a property of the machine.
    ingest_concurrency: int = Field(default=2, ge=1, le=32)

    # How long one document may spend in the pipeline before the worker gives
    # up on it. An hour, not the queue's default five minutes: OCR over a
    # 900-page scan on CPU is genuinely that slow, and a timeout shorter than
    # the work turns a slow file into a failed one.
    ingest_job_timeout_seconds: int = Field(default=3600, ge=30, le=86400)

    # How often the worker re-dispatches queued work the queue has forgotten.
    # This is the path that recovers an import from a Redis flush, a failed
    # enqueue, or a machine that woke up without its queue.
    ingest_reconcile_seconds: int = Field(default=30, ge=5, le=3600)

    # Traces are the largest and fastest-growing of the three audit stores,
    # and the only one that fails open. 256 MB is a few thousand traces —
    # enough that "show me what happened" works for anything recent, and small
    # enough that it never becomes the reason a laptop ran out of disk.
    trace_dir: Path = Path("/var/lib/askwell/traces")
    trace_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)

    # Where the built frontend lives. The default is the path inside the API
    # image; a source checkout points it at web/out.
    web_assets_dir: Path = Path("/app/web/out")

    # The one part of the user's filesystem the containers can see, bind-mounted
    # at the *same* absolute path so that a path means the same thing on the
    # host and inside the container. Nominated roots must lie under it.
    #
    # None — the default — means Askwell has no window onto the filesystem at
    # all, which is the correct state on a fresh install and the honest one
    # here: a container's mounts cannot be changed while it runs, so a root
    # outside this is registered and reported as `not_mounted` with the fix
    # stated, rather than failing later somewhere that will not mention a
    # mount. See `askwell.roots`.
    roots_mount: Path | None = None

    # How long a single health probe may take. Health must answer even when
    # every component is down, so this is short and it is a ceiling per probe,
    # not for the whole surface.
    health_probe_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    @field_validator("roots_mount", mode="before")
    @classmethod
    def _optional_path(cls, value: object) -> object:
        """An empty value means "no window", not a directory named "".

        Compose passes `ASKWELL_ROOTS_MOUNT: ${ASKWELL_ROOTS_MOUNT:-}`, so the
        variable is always present and is empty when the user has not set one.
        Without this, that empty string becomes `Path('')`, which is falsy in
        some checks and truthy in others — the worst kind of value to carry.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("roots_mount", mode="after")
    @classmethod
    def _absolute_mount(cls, value: Path | None) -> Path | None:
        """A relative window is not a window.

        The whole point of this setting is that a path means the same thing on
        the host and inside the container, and a path relative to a working
        directory the two do not share means neither.
        """
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            raise ValueError(
                f"must be an absolute path, got {str(value)!r}. It names the "
                f"same directory on the host and inside the container, so a "
                f"relative path names two different places"
            )
        return expanded

    @field_validator("inference_model_path", "inference_socket", "trace_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        """`~` is how a person writes a path, and `Path` does not expand it.

        Without this, `~/.local/share/...` becomes a directory literally named
        `~` in the working directory — which exists, is empty, and produces a
        "no model file" message pointing at a path that looks correct.
        """
        return value.expanduser()

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
