"""Key derivation and encryption for stored connection configuration.
`M4-CONN-SEC-098`.
"""

from pathlib import Path

import pytest

from askwell import crypto


def test_a_fresh_secret_is_generated_on_first_use(tmp_path: Path) -> None:
    path = tmp_path / "install.key"
    assert not path.exists()

    secret = crypto.load_or_create_install_secret(path)
    assert len(secret) == 32
    assert path.exists()
    assert path.read_bytes() == secret


def test_the_same_secret_is_reused_across_reads(tmp_path: Path) -> None:
    path = tmp_path / "install.key"
    first = crypto.load_or_create_install_secret(path)
    second = crypto.load_or_create_install_secret(path)
    assert first == second


def test_the_secret_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "install.key"
    crypto.load_or_create_install_secret(path)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_a_malformed_secret_file_locks_rather_than_derives_a_weak_key(tmp_path: Path) -> None:
    path = tmp_path / "install.key"
    path.write_bytes(b"too-short")
    with pytest.raises(crypto.CredentialsLocked):
        crypto.load_or_create_install_secret(path)


def test_round_trips_a_credential(tmp_path: Path) -> None:
    secret = crypto.load_or_create_install_secret(tmp_path / "install.key")
    key = crypto.derive_key(secret)

    ciphertext = crypto.encrypt(b'{"password": "hunter2"}', key)
    assert b"hunter2" not in ciphertext

    plaintext = crypto.decrypt(ciphertext, key)
    assert plaintext == b'{"password": "hunter2"}'


def test_a_different_install_secret_cannot_decrypt(tmp_path: Path) -> None:
    secret_a = crypto.load_or_create_install_secret(tmp_path / "a.key")
    secret_b = crypto.load_or_create_install_secret(tmp_path / "b.key")

    ciphertext = crypto.encrypt(b"secret-config", crypto.derive_key(secret_a))
    with pytest.raises(crypto.CredentialsLocked):
        crypto.decrypt(ciphertext, crypto.derive_key(secret_b))


def test_a_passphrase_changes_the_derived_key(tmp_path: Path) -> None:
    secret = crypto.load_or_create_install_secret(tmp_path / "install.key")
    without = crypto.derive_key(secret)
    with_passphrase = crypto.derive_key(secret, "correct horse battery staple")
    assert without != with_passphrase

    ciphertext = crypto.encrypt(b"secret-config", without)
    with pytest.raises(crypto.CredentialsLocked):
        crypto.decrypt(ciphertext, with_passphrase)
