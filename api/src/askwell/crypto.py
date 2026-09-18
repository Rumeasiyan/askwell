"""Encrypting stored connection configuration at rest. `M4-CONN-SEC-098`.

`sources.config_encrypted` is encrypted with a key derived from a per-install
secret — 32 random bytes generated once, on first use, and kept outside the
database (`Settings.install_secret_path`, on the same host-backed mount the
inference socket already uses). A copy of `postgres-data` alone is therefore
not a credential leak: the ciphertext travels with the volume, the key does
not. `docs/architecture.md` §7 and `docs/decisions.md` (this ticket's date)
have the reasoning.

Key derivation is HKDF over the install secret, with room for a passphrase
(M7) to be folded in later without re-encrypting anything already stored —
extending the key material, not replacing the scheme. Never hand-rolled:
HKDF and Fernet (AES-128-CBC + HMAC, authenticated) both come from
`cryptography`, the standard library for this in Python.
"""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INSTALL_SECRET_BYTES = 32
_HKDF_INFO = b"askwell-config-encryption-v1"


class CredentialsLocked(Exception):
    """Stored configuration exists but cannot be decrypted with today's key.

    Raised when the per-install secret has been lost, replaced, or is
    unreadable since a credential was encrypted with a different one — never
    for a wrong database password, which is a connection failure, not this
    one. The caller's job is to report "locked, re-enter", not to guess.
    """


def load_or_create_install_secret(path: Path) -> bytes:
    """Read the per-install secret, generating it on first use.

    A fresh secret is 32 random bytes, written with owner-only permissions
    and never logged. Losing this file *is* the locked state this ticket
    names: regenerating it silently on every read would look identical to a
    working install right up until the first decrypt, so a missing file is
    the one case this function is allowed to fill in — every other read
    failure (permission denied, a directory where the file should be)
    propagates as `OSError` rather than being papered over.
    """
    try:
        secret = path.read_bytes()
    except FileNotFoundError:
        secret = os.urandom(_INSTALL_SECRET_BYTES)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        tmp_path.write_bytes(secret)
        tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        tmp_path.replace(path)
        return secret

    if len(secret) != _INSTALL_SECRET_BYTES:
        raise CredentialsLocked(
            f"Install secret at {path} is not {_INSTALL_SECRET_BYTES} bytes — "
            "it is not a key this install generated."
        )
    return secret


def derive_key(install_secret: bytes, passphrase: str | None = None) -> bytes:
    """A Fernet key from the install secret, extensible to a passphrase.

    `passphrase` folds into the same derivation rather than layering a second
    encryption step, so when M7 adds one, existing credentials decrypt under
    the new key the instant the passphrase is set — no re-entry needed, which
    is this ticket's own acceptance criterion for that future change.
    """
    ikm = install_secret + (passphrase.encode("utf-8") if passphrase else b"")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(ikm)
    return base64.urlsafe_b64encode(key)


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    return Fernet(key).encrypt(plaintext)


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt, or raise `CredentialsLocked` rather than a raw crypto error.

    An `InvalidToken` from Fernet means either the key is wrong (the install
    secret changed) or the bytes are not what this module wrote — both are
    the same user-facing fact: these credentials cannot be read back, and
    re-entry is the only way forward.
    """
    try:
        return Fernet(key).decrypt(ciphertext)
    except InvalidToken as error:
        raise CredentialsLocked(
            "Stored credentials cannot be decrypted with the current key."
        ) from error
