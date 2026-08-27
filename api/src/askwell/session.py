"""The local session.

There is one user. They already control the machine, the disk and the
database, so this is not authentication in the sense that word usually carries.
It stops another process on the same machine from casually driving the API, and
that is the entire ambition.

What it deliberately is not: a login. No password, no roles, no recovery, no
sign-in screen anywhere. `docs/ux/first-run.md` §5 — no account, no email, no
sign-in. Someone opening Askwell for the first time gets a session and never
learns that sessions exist.

The passphrase in M7 is a different feature about encryption at rest. Nothing
here should grow into it.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.logging import get_logger

log = get_logger(__name__)

COOKIE_NAME = "askwell_session"
SECRET_SETTING = "session_secret"

# Long enough that a browser left open over a holiday still works. There is
# nobody to lock out, so a short expiry would only ever inconvenience the one
# person entitled to be here.
MAX_AGE_SECONDS = 365 * 24 * 60 * 60

_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class Session:
    """A local session. It identifies a browser, not a person."""

    token: str

    @property
    def short(self) -> str:
        """A prefix, for logs.

        The token itself is never logged. It is the only thing standing
        between another process on this machine and the user's material, and a
        log file is world-readable far more often than anyone intends.
        """
        return self.token[:8]


async def secret(session: AsyncSession) -> bytes:
    """The signing secret, created once and kept in the database.

    In the database rather than in memory so a session survives a stack
    restart, and rather than in a file so it travels with the data it protects.
    Generated on first use: there is no value to ship, and a default would be
    the same on every install.
    """
    row = (
        await session.execute(
            text("SELECT value FROM settings WHERE key = :key"), {"key": SECRET_SETTING}
        )
    ).first()
    if row is not None:
        return base64.urlsafe_b64decode(str(row[0]))

    created = secrets.token_bytes(_TOKEN_BYTES)
    await session.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:key, :value) ON CONFLICT (key) DO NOTHING"
        ),
        {"key": SECRET_SETTING, "value": base64.urlsafe_b64encode(created).decode("ascii")},
    )
    await session.commit()

    # Re-read rather than returning what was just generated: two workers
    # starting together would otherwise sign with different secrets, and every
    # session issued by one would be rejected by the other.
    row = (
        await session.execute(
            text("SELECT value FROM settings WHERE key = :key"), {"key": SECRET_SETTING}
        )
    ).first()
    if row is None:  # pragma: no cover - the insert above just ran
        raise RuntimeError("the session secret could not be established")
    return base64.urlsafe_b64decode(str(row[0]))


def issue(signing_secret: bytes) -> str:
    """A fresh signed session value."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return f"{token}.{_sign(signing_secret, token)}"


def verify(signing_secret: bytes, value: str | None) -> Session | None:
    """The session a cookie carries, or None.

    None covers every failure — malformed, wrong signature, empty. The caller
    does the same thing in each case, and telling them apart in a response
    would say more about the secret than a stranger should learn.
    """
    if not value or "." not in value:
        return None
    token, _, signature = value.rpartition(".")
    if not token or not signature:
        return None
    if not hmac.compare_digest(_sign(signing_secret, token), signature):
        return None
    return Session(token=token)


def _sign(signing_secret: bytes, token: str) -> str:
    digest = hmac.new(signing_secret, token.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
