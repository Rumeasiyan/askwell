"""The API's unlock, handed to the worker. `M9-FIX-BE-205`, issue #508.

Without a database: the socket's own shape — owner-only, push-only, refusing
anything malformed — and the API's side deciding whether to push or lock.
With one: the round trip the ticket is about. The key a correct passphrase
derives reaches the worker and opens it; a key a wrong passphrase derives is
refused there and nothing decrypts.

API and worker are one Python process here, so they share
`askwell.passphrase`'s in-memory state. "The worker starts fresh" is
therefore `_reset_lock_state_for_tests()`, the same stand-in for a restart
`test_passphrase.py` already uses.
"""

import asyncio
import json
import shutil
import stat
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import crypto, passphrase, worker_unlock
from askwell.config import Settings

PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    """A short directory: a Unix socket path is capped near 108 bytes, and
    pytest's own `tmp_path` can run past that on a long test name."""
    directory = Path(tempfile.mkdtemp(prefix="aw-", dir="/tmp"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def channel(settings: Settings, socket_dir: Path) -> Settings:
    return settings.model_copy(
        update={
            "worker_unlock_socket": socket_dir / "unlock.sock",
            "install_secret_path": socket_dir / "install.key",
        }
    )


async def _raw(path: Path, payload: bytes) -> dict[str, Any]:
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write(payload)
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    reply = json.loads(line)
    assert isinstance(reply, dict)
    return reply


# --- no database ---------------------------------------------------------------


async def test_the_socket_is_owner_only(channel: Settings) -> None:
    server = await worker_unlock.serve(channel, None)  # type: ignore[arg-type]
    try:
        mode = stat.S_IMODE(channel.worker_unlock_socket.stat().st_mode)
        assert mode == 0o600
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)
    assert not channel.worker_unlock_socket.exists()


async def test_a_stale_socket_file_from_the_last_worker_does_not_stop_this_one(
    channel: Settings,
) -> None:
    channel.worker_unlock_socket.write_bytes(b"")
    server = await worker_unlock.serve(channel, None)  # type: ignore[arg-type]
    await worker_unlock.close(server, channel.worker_unlock_socket)


async def test_malformed_and_unknown_requests_are_refused(channel: Settings) -> None:
    server = await worker_unlock.serve(channel, None)  # type: ignore[arg-type]
    try:
        path = channel.worker_unlock_socket
        assert (await _raw(path, b"not json\n"))["ok"] is False
        assert (await _raw(path, b'["a list"]\n'))["ok"] is False
        assert (await _raw(path, b'{"op": "give me the key"}\n'))["ok"] is False
        assert (await _raw(path, b'{"op": "unlock"}\n'))["ok"] is False
        assert (await _raw(path, b'{"op": "unlock", "key": "!!!"}\n'))["ok"] is False
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)


async def test_lock_forgets_the_workers_key(channel: Settings) -> None:
    passphrase._unlocked_key = b"k" * 44  # what an earlier unlock would have left
    server = await worker_unlock.serve(channel, None)  # type: ignore[arg-type]
    try:
        assert await worker_unlock.push_lock(channel) is True
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)
    assert passphrase.held_key() is None


async def test_no_worker_listening_is_unreachable_not_an_error(channel: Settings) -> None:
    assert await worker_unlock.worker_state(channel) is None
    assert await worker_unlock.push_lock(channel) is False
    assert await worker_unlock.sync(channel) == "unreachable"


async def test_sync_locks_a_worker_the_api_has_not_unlocked(
    channel: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restart edge case: a fresh API holds no key, so a worker still
    holding one from before is locked too."""
    sent: list[str] = []

    async def state(_settings: Settings) -> worker_unlock.WorkerState:
        return worker_unlock.WorkerState(holds_key=True, current=True)

    async def lock(_settings: Settings) -> bool:
        sent.append("lock")
        return True

    monkeypatch.setattr(worker_unlock, "worker_state", state)
    monkeypatch.setattr(worker_unlock, "push_lock", lock)

    assert await worker_unlock.sync(channel) == "locked"
    assert sent == ["lock"]


async def test_sync_pushes_the_key_to_a_worker_that_lacks_it(
    channel: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    passphrase._unlocked_key = b"k" * 44
    pushed: list[bytes] = []

    async def state(_settings: Settings) -> worker_unlock.WorkerState:
        return worker_unlock.WorkerState(holds_key=False, current=False)

    async def push(_settings: Settings, key: bytes) -> bool:
        pushed.append(key)
        return True

    monkeypatch.setattr(worker_unlock, "worker_state", state)
    monkeypatch.setattr(worker_unlock, "push_unlock", push)

    assert await worker_unlock.sync(channel) == "unlocked"
    assert pushed == [b"k" * 44]


async def test_sync_leaves_a_worker_already_in_step_alone(
    channel: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def state(_settings: Settings) -> worker_unlock.WorkerState:
        return worker_unlock.WorkerState(holds_key=False, current=False)

    monkeypatch.setattr(worker_unlock, "worker_state", state)
    assert await worker_unlock.sync(channel) == "in_step"


async def test_the_key_is_never_logged(
    channel: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = crypto.derive_key(b"s" * 32, PASSPHRASE)
    passphrase._unlocked_key = key

    async def state(_settings: Settings) -> worker_unlock.WorkerState:
        return worker_unlock.WorkerState(holds_key=False, current=False)

    async def push(_settings: Settings, _key: bytes) -> bool:
        return True

    monkeypatch.setattr(worker_unlock, "worker_state", state)
    monkeypatch.setattr(worker_unlock, "push_unlock", push)
    await worker_unlock.sync(channel)

    captured = capsys.readouterr()
    assert key.decode("ascii") not in captured.out + captured.err
    assert PASSPHRASE not in captured.out + captured.err


# --- database-backed -------------------------------------------------------------


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def factory(async_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def clear() -> None:
        async with sessions() as opened:
            await opened.execute(text("TRUNCATE audit_decisions"))
            await opened.execute(
                text("DELETE FROM settings WHERE key = :key"), {"key": passphrase.VERIFIER_KEY}
            )
            await opened.commit()

    await clear()
    yield sessions
    await clear()
    await engine.dispose()


async def _set_passphrase(factory: async_sessionmaker[AsyncSession], settings: Settings) -> bytes:
    """Set the passphrase as the API would, and return the key it derived.
    Then forget it, as a worker that has never been unlocked would."""
    async with factory() as session:
        await passphrase.set_passphrase(
            session, settings, PASSPHRASE, acknowledged_no_recovery=True
        )
        await session.commit()
    key = passphrase.held_key()
    assert key is not None
    passphrase._reset_lock_state_for_tests()
    return key


@pytest.mark.requires_db
async def test_the_right_key_unlocks_the_worker_and_revives_its_waiting_work(
    factory: async_sessionmaker[AsyncSession], channel: Settings
) -> None:
    key = await _set_passphrase(factory, channel)
    revived: list[str] = []

    async def on_unlocked() -> None:
        revived.append("revived")

    server = await worker_unlock.serve(channel, factory, on_unlocked)
    try:
        before = await worker_unlock.worker_state(channel)
        assert before == worker_unlock.WorkerState(holds_key=False, current=False)
        async with factory() as session:
            with pytest.raises(passphrase.Locked):
                await passphrase.current_key(session, channel)

        assert await worker_unlock.push_unlock(channel, key) is True

        after = await worker_unlock.worker_state(channel)
        assert after == worker_unlock.WorkerState(holds_key=True, current=True)
        async with factory() as session:
            assert await passphrase.current_key(session, channel) == key
        assert revived == ["revived"]
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)


@pytest.mark.requires_db
async def test_a_key_from_the_wrong_passphrase_is_refused_and_nothing_decrypts(
    factory: async_sessionmaker[AsyncSession], channel: Settings
) -> None:
    await _set_passphrase(factory, channel)
    install_secret = crypto.load_or_create_install_secret(channel.install_secret_path)
    wrong = crypto.derive_key(install_secret, "not the right passphrase")
    revived: list[str] = []

    async def on_unlocked() -> None:
        revived.append("revived")

    server = await worker_unlock.serve(channel, factory, on_unlocked)
    try:
        assert await worker_unlock.push_unlock(channel, wrong) is False
        assert passphrase.held_key() is None
        async with factory() as session:
            with pytest.raises(passphrase.Locked):
                await passphrase.current_key(session, channel)
        assert revived == []
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)


@pytest.mark.requires_db
async def test_status_never_carries_the_key(
    factory: async_sessionmaker[AsyncSession], channel: Settings
) -> None:
    key = await _set_passphrase(factory, channel)
    server = await worker_unlock.serve(channel, factory)
    try:
        assert await worker_unlock.push_unlock(channel, key) is True
        reply = await _raw(channel.worker_unlock_socket, b'{"op": "status"}\n')
    finally:
        await worker_unlock.close(server, channel.worker_unlock_socket)
    assert set(reply) == {"ok", "holds_key", "current"}
    assert key.decode("ascii") not in json.dumps(reply)


@pytest.mark.requires_db
async def test_the_unlock_route_hands_the_worker_its_key_only_when_it_is_right(
    factory: async_sessionmaker[AsyncSession],
    channel: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring the acceptance criterion rests on: unlocking through the
    API's own route brings the worker along at once, and a wrong passphrase
    brings nothing along. One process here, so what is asserted is that the
    route syncs, with what key — the socket itself is covered above."""
    import httpx

    await _set_passphrase(factory, channel)
    app = FastAPI()
    passphrase.register_passphrase(app, channel, factory)
    synced: list[bytes | None] = []

    async def sync(_settings: Settings) -> str:
        synced.append(passphrase.held_key())
        return "unlocked"

    monkeypatch.setattr(worker_unlock, "sync", sync)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://askwell") as client:
        wrong = await client.post(
            "/settings/passphrase/unlock", json={"passphrase": "not it at all"}
        )
        assert wrong.status_code == 401
        assert synced == []

        right = await client.post("/settings/passphrase/unlock", json={"passphrase": PASSPHRASE})
        assert right.status_code == 200

    assert len(synced) == 1
    assert synced[0] is not None
