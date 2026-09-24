"""The user's own provider key, held as a secret. `M8-KEY-BE-173`.

Online AI uses a key from a provider the user already pays (`docs/decisions.md`,
2026-09-23). This module is where that key lives: one key, with the provider
it belongs to, in one `settings` row.

**Encrypted with the mechanism every other credential uses.** The key is a
Fernet token under `askwell.passphrase.current_key` — the same key
`sources.config_encrypted` and `chunks.content` use (`M4-CONN-SEC-098`,
`M7-SEC-BE-151`, `M7-SEC-BE-152`). A passphrase set, changed or removed
re-encrypts it alongside them (`reencrypt`), and a locked install cannot read
it until unlock, like everything else encrypted. The caller passes the
encryption key in rather than this module asking `askwell.passphrase` for it,
because `askwell.passphrase` is what calls `reencrypt`.

**The provider is not secret, and is stored beside the key in the clear.**
`destination` (`host:port`) is what a conversation's egress grant authorises
(`M8-ONLINE-SEC-169`), and `model` is what a request asks it for. Storing
them with the key is what makes "the destination the proxy authorises
matches the key" true by construction: there is no second setting naming a
destination that could disagree with the key's. Settings can read which
provider is set up without decrypting anything, so a locked install can
still say *what* is set up.

**The key leaves this module only as `ProviderKey.api_key`,** read by
`askwell.inference.provider` when it builds the `Authorization` header at
send time. Its `repr` is masked so a log line or an exception that captures
the object does not capture the value, and nothing here logs, records or
returns it anywhere else. Storing, replacing and removing are decisions
records naming the provider, never the value (`askwell.online`).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto
from askwell.settings_store import get_setting, set_setting

SETTING_KEY = "online_provider_key"

# The same shape `askwell.egress` authorises: one `host:port`, never a list.
DESTINATION_PATTERN = re.compile(r"^[A-Za-z0-9.-]+:[0-9]{1,5}$")
# A model identifier as providers write them: letters, digits and a few
# separators. It is sent in the request body and shown on every online turn.
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/@-]{1,128}$")
# An API key goes into an HTTP header, so it must be printable ASCII with no
# space. Real keys are well under this; the bound only refuses a paste of the
# wrong thing.
KEY_PATTERN = re.compile(r"^[\x21-\x7e]{8,512}$")


class InvalidProviderKey(ValueError):
    """What was offered cannot be stored. The message names the field and the
    reason, never the value."""


@dataclass(frozen=True, slots=True)
class Provider:
    """Which provider the stored key belongs to. Not secret."""

    destination: str
    model: str

    def as_dict(self) -> dict[str, str]:
        return {"destination": self.destination, "model": self.model}


@dataclass(frozen=True, slots=True)
class ProviderKey:
    """The provider and its decrypted key, for one send."""

    provider: Provider
    api_key: str = field(repr=False)

    def __repr__(self) -> str:
        return f"ProviderKey(provider={self.provider!r}, api_key='[redacted]')"


def validate(destination: str, model: str, api_key: str) -> Provider:
    """Refuse what cannot be a provider or a key, naming which and why.

    Deliberately no call to the provider: checking the key there would be a
    network request before the user has switched any conversation online
    (the ticket's own Out of Scope line, and C1).
    """
    if not DESTINATION_PATTERN.fullmatch(destination):
        raise InvalidProviderKey(
            "The provider's address must be a host and port, like api.example.com:443."
        )
    if not MODEL_PATTERN.fullmatch(model):
        raise InvalidProviderKey(
            "The model name must be 1 to 128 letters, digits or . _ : / @ - characters."
        )
    if not KEY_PATTERN.fullmatch(api_key):
        raise InvalidProviderKey(
            "The key must be 8 to 512 printable characters with no spaces or line breaks."
        )
    return Provider(destination=destination, model=model)


def _decode(raw: str) -> tuple[Provider, bytes]:
    stored = json.loads(raw)
    provider = Provider(destination=str(stored["destination"]), model=str(stored["model"]))
    return provider, base64.urlsafe_b64decode(str(stored["key_encrypted"]))


def _encode(provider: Provider, ciphertext: bytes) -> str:
    return json.dumps(
        {
            **provider.as_dict(),
            "key_encrypted": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
    )


async def stored_provider(session: AsyncSession) -> Provider | None:
    """Which provider a key is held for, or None. Decrypts nothing, so it
    answers on a locked install too."""
    raw = await get_setting(session, SETTING_KEY)
    return None if raw is None else _decode(raw)[0]


async def store(
    session: AsyncSession, encryption_key: bytes, provider: Provider, api_key: str
) -> Provider | None:
    """Store the key, replacing any held before. Returns the provider it
    replaced, or None if there was none. In the caller's transaction."""
    previous = await stored_provider(session)
    ciphertext = crypto.encrypt(api_key.encode("ascii"), encryption_key)
    await set_setting(session, SETTING_KEY, _encode(provider, ciphertext))
    return previous


async def remove(session: AsyncSession) -> Provider | None:
    """Delete the key. The row goes, not a flag on it: removing it removes
    it. Returns the provider it was for, or None if none was held."""
    previous = await stored_provider(session)
    await session.execute(text("DELETE FROM settings WHERE key = :key"), {"key": SETTING_KEY})
    return previous


async def load(session: AsyncSession, encryption_key: bytes) -> ProviderKey | None:
    """The key, decrypted, for a send. None when none is held.

    Raises `crypto.CredentialsLocked` when it cannot be decrypted — a lost
    install secret, or (as `askwell.passphrase.Locked`, raised by the caller's
    `current_key`) a passphrase not yet entered.
    """
    raw = await get_setting(session, SETTING_KEY)
    if raw is None:
        return None
    provider, ciphertext = _decode(raw)
    api_key = crypto.decrypt(ciphertext, encryption_key).decode("ascii")
    return ProviderKey(provider=provider, api_key=api_key)


async def reencrypt(session: AsyncSession, old_key: bytes, new_key: bytes) -> None:
    """Re-encrypt the held key under a new passphrase-derived key, in the
    caller's transaction. `askwell.passphrase` calls this beside its own
    re-encryption of connection credentials, so setting a passphrase never
    asks for the provider key again."""
    raw = await get_setting(session, SETTING_KEY)
    if raw is None:
        return
    provider, ciphertext = _decode(raw)
    plaintext = crypto.decrypt(ciphertext, old_key)
    await set_setting(session, SETTING_KEY, _encode(provider, crypto.encrypt(plaintext, new_key)))
