"""`.env.example` must describe reality, and a test is the only thing that keeps it doing so.

The file existed for three tickets before this one and was already wrong: five
variables listed out of nineteen. That is the failure mode — an example file
drifts silently, and it drifts while being read as authoritative, which is
worse than not having one.

So this is not a test of the file's contents. It is the mechanism that makes
adding a variable without documenting it a build failure.
"""

import re
from pathlib import Path

import pytest

from askwell.config import ENV_PREFIX, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "compose.yaml"

ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# `${VAR}`, `${VAR:-default}`, `${VAR:?message}` — every shape Compose accepts.
COMPOSE_REFERENCE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")

# Referenced by compose.yaml but supplied by it rather than by the operator.
COMPOSE_INTERNAL = {
    # Set for the Postgres image by Compose itself, from POSTGRES_* above.
    "PGDATA",
}


def documented() -> set[str]:
    return set(ASSIGNMENT.findall(EXAMPLE.read_text(encoding="utf-8")))


def application_variables() -> set[str]:
    """Every variable the application reads, by the name a person types."""
    return {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}


def compose_variables() -> set[str]:
    return set(COMPOSE_REFERENCE.findall(COMPOSE.read_text(encoding="utf-8"))) - COMPOSE_INTERNAL


def test_every_variable_the_application_reads_is_documented() -> None:
    missing = sorted(application_variables() - documented())
    assert not missing, (
        f"read by the application but missing from .env.example: {missing}. "
        f"Add them in the same change that introduced them — an example file "
        f"that lags is read as authoritative and is wrong."
    )


def test_every_variable_compose_needs_is_documented() -> None:
    """A variable used only in a container definition is still a variable.

    Someone bringing the stack up has to know it exists, and `compose.yaml`
    failing with `variable is not set` is a worse way to find out.
    """
    missing = sorted(compose_variables() - documented())
    assert not missing, f"referenced by compose.yaml but missing from .env.example: {missing}"


def test_nothing_documented_is_stale() -> None:
    """The other direction, which is the one that rots quietly.

    A removed setting leaves a line nobody notices, and the next person sets it
    and wonders why it does nothing.
    """
    known = application_variables() | compose_variables()
    stale = sorted(documented() - known)
    assert not stale, (
        f"in .env.example but read by nothing: {stale}. Either it was removed "
        f"from the code, or it is a typo that has been silently doing nothing."
    )


def test_the_example_carries_no_real_looking_secret() -> None:
    """Placeholders, always. This file is committed."""
    text = EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("POSTGRES_") or "PASSWORD" not in line:
            continue
        _, _, value = line.partition("=")
        assert "change-me" in value, (
            f"{line.split('=')[0]} has a value that is not obviously a "
            f"placeholder. This file is committed."
        )


def test_the_real_environment_file_cannot_be_committed() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored


@pytest.mark.parametrize(
    "variable",
    ["ASKWELL_DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD"],
)
def test_the_variables_that_carry_credentials_are_documented_as_such(variable: str) -> None:
    """Whoever copies this file should know which lines matter."""
    text = EXAMPLE.read_text(encoding="utf-8")
    position = text.index(f"{variable}=")
    preceding = text[:position].rsplit("\n\n", 1)[-1].lower()
    assert any(
        word in preceding for word in ("credential", "password", "connection string", "secret")
    ), f"{variable} is listed without saying it carries a credential"


def test_only_the_api_publishes_a_port_and_only_to_loopback() -> None:
    """`"8000:8000"` and `"127.0.0.1:8000:8000"` differ by nine characters.

    Both produce a working product on the developer's machine. The first one
    puts the user's entire corpus on whatever network they are on.

    Checked statically here as well as from outside the machine by
    `scripts/verify-localhost-binding.sh`, because this is the version that
    runs on every push without a stack being up.
    """
    import re

    compose = COMPOSE.read_text(encoding="utf-8")
    mappings = re.findall(r'^\s*-\s*"([^"]*:\d+)"\s*$', compose, re.MULTILINE)
    published = [m for m in mappings if ":" in m]

    assert published, "no published port found — has the ports section moved?"
    for mapping in published:
        assert mapping.startswith("127.0.0.1:"), (
            f"compose.yaml publishes {mapping!r}, which is not loopback. "
            f"There is no configuration in v1 for exposing Askwell to a network."
        )
