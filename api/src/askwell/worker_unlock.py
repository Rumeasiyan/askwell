"""The API's unlock, handed to the worker. `M9-FIX-BE-205`, issues #508 and #504.

A passphrase unlocks one process at a time (`askwell.passphrase`), and only
the API has a surface a person can type into. The worker — which chunks,
embeds and re-introspects connections, all of which need the key — had no way
to unlock at all, so once a passphrase was set no new document ever finished
indexing. This is the channel that closes that gap.

**The worker listens; the API speaks.** A Unix socket in the directory both
containers already share with the inference socket — the run-directory bind
mount on Linux and macOS, a named volume on Windows, where a bind-mounted
Windows directory cannot hold a socket (`M11-FIX-DEPLOY-223`). The key
travels kernel to kernel between two processes on this machine: no route, no
Redis, no file. The socket file itself holds nothing, and the key is never
logged on either side.

**Push only. Nothing can ask the worker for its key.** Three requests exist —
`status`, `unlock`, `lock` — and none of them returns key material. `status`
answers two booleans. Anything that can reach the socket can already read the
install secret, which is mounted into the same two containers, but not the
passphrase, so a channel that *served*
the key would hand it the one thing the passphrase protects.

**The worker verifies what it is given.** `unlock` goes through
`passphrase.adopt_key`, which checks the key against the verifier exactly as
a typed passphrase is checked. A wrong key is refused and nothing decrypts.
The worst a stranger on the socket can do is `lock`, which pauses indexing
until the API's next sync restores it.

**The worker mirrors the API, and the API is checked on a timer.** API
unlocked and worker not holding the current key: the API pushes it. API
locked and worker holding a key: the API tells it to lock. That covers a
worker restarted on its own (unlocked again within one interval, because the
person using Askwell has not locked anything), a passphrase changed (the old
key reads as locked in the worker until the new one arrives), and an API
restarted on its own (it starts locked, so the worker is locked too — the
restart edge case: nothing decrypts again until the passphrase is entered).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import passphrase
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

# One request is one line of JSON carrying at most a 44-character key. A
# kilobyte is generous; anything longer is not Askwell talking.
MAX_REQUEST_BYTES = 1024

# How long the API waits for the worker before treating it as not there. The
# worker answers from memory and one settings read, so this is only ever
# reached when it is down or wedged — and the caller is a request handler.
REQUEST_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class WorkerState:
    """What the worker says about itself. Never the key."""

    # Some key is cached in the worker, current or not.
    holds_key: bool
    # The cached key opens the verifier on file right now.
    current: bool


OnUnlocked = Callable[[], Awaitable[object]]


# --- the worker's side -------------------------------------------------------


async def _answer(
    request: dict[str, Any],
    factory: async_sessionmaker[AsyncSession],
    on_unlocked: OnUnlocked | None,
) -> dict[str, Any]:
    op = request.get("op")
    if op == "status":
        async with session_scope(factory) as session:
            state = await passphrase.status(session)
        return {
            "ok": True,
            "holds_key": passphrase.held_key() is not None,
            "current": state["enabled"] and not state["locked"],
        }
    if op == "lock":
        passphrase.forget_unlocked_key()
        log.info("worker_locked_by_api")
        return {"ok": True}
    if op == "unlock":
        encoded = request.get("key")
        if not isinstance(encoded, str):
            return {"ok": False, "error": "no key"}
        try:
            key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
        except (binascii.Error, UnicodeEncodeError):
            return {"ok": False, "error": "malformed key"}
        if not key:
            return {"ok": False, "error": "malformed key"}
        async with session_scope(factory) as session:
            adopted = await passphrase.adopt_key(session, key)
        if not adopted:
            # Named, never the key. A refusal here is either a stale push
            # racing a passphrase change, or something on the socket that is
            # not the API — both worth a line in the log.
            log.warning("worker_unlock_refused")
            return {"ok": False, "error": "refused"}
        if on_unlocked is not None:
            try:
                await on_unlocked()
            except Exception as error:
                # The unlock itself stands: the reconcile timer revives the
                # waiting work on its next pass even if this one failed.
                log.warning(
                    "worker_unlock_revive_deferred", error=f"{type(error).__name__}: {error}"
                )
        return {"ok": True}
    return {"ok": False, "error": "unknown request"}


async def serve(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    on_unlocked: OnUnlocked | None = None,
) -> asyncio.AbstractServer:
    """Listen on `settings.worker_unlock_socket`. Called at worker startup.

    A stale socket file from the last process is removed first: it is not
    state, only a name, and binding fails while it exists. The file is made
    owner-only before anything can connect.
    """
    path = settings.worker_unlock_socket

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=REQUEST_TIMEOUT_SECONDS)
            if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                reply: dict[str, Any] = {"ok": False, "error": "malformed request"}
            else:
                try:
                    request = json.loads(line)
                except ValueError:
                    request = None
                reply = (
                    await _answer(request, factory, on_unlocked)
                    if isinstance(request, dict)
                    else {"ok": False, "error": "malformed request"}
                )
            writer.write(json.dumps(reply).encode("utf-8") + b"\n")
            await writer.drain()
        except (TimeoutError, ValueError, ConnectionError) as error:
            log.warning("worker_unlock_request_dropped", error=type(error).__name__)
        except Exception as error:
            # The database not being up yet, most likely. The API asks again
            # on its next sync; nothing here must take the worker down.
            log.warning("worker_unlock_request_failed", error=f"{type(error).__name__}: {error}")
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    previous = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handle, path=str(path), limit=MAX_REQUEST_BYTES)
    finally:
        os.umask(previous)
    os.chmod(path, 0o600)
    log.info("worker_unlock_listening", socket=str(path))
    return server


async def close(server: asyncio.AbstractServer, path: Path) -> None:
    server.close()
    await server.wait_closed()
    await asyncio.to_thread(path.unlink, missing_ok=True)


# --- the API's side ----------------------------------------------------------


async def _request(settings: Settings, request: dict[str, Any]) -> dict[str, Any] | None:
    """One request, one reply, or `None` when the worker is not there.

    Never raises: the worker being down is ordinary on a laptop, and every
    caller — a passphrase route, the sync timer — must go on regardless.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(settings.worker_unlock_socket)),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except (OSError, TimeoutError):
        return None
    try:
        writer.write(json.dumps(request).encode("utf-8") + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=REQUEST_TIMEOUT_SECONDS)
        reply = json.loads(line) if line else None
    except (OSError, TimeoutError, ValueError):
        return None
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return reply if isinstance(reply, dict) else None


async def worker_state(settings: Settings) -> WorkerState | None:
    reply = await _request(settings, {"op": "status"})
    if reply is None or reply.get("ok") is not True:
        return None
    return WorkerState(holds_key=bool(reply.get("holds_key")), current=bool(reply.get("current")))


async def push_unlock(settings: Settings, key: bytes) -> bool:
    encoded = base64.urlsafe_b64encode(key).decode("ascii")
    reply = await _request(settings, {"op": "unlock", "key": encoded})
    return reply is not None and reply.get("ok") is True


async def push_lock(settings: Settings) -> bool:
    reply = await _request(settings, {"op": "lock"})
    return reply is not None and reply.get("ok") is True


async def sync(settings: Settings) -> str:
    """Bring the worker into step with this process. Returns what it did.

    `unlocked`, `locked`, `in_step`, or `unreachable`. Called after every
    passphrase change and unlock so the worker follows at once, and by
    `keep_in_step` so it follows even when a push was missed.
    """
    state = await worker_state(settings)
    if state is None:
        return "unreachable"
    key = passphrase.held_key()
    if key is not None and not state.current:
        if await push_unlock(settings, key):
            log.info("worker_unlocked")
            return "unlocked"
        return "unreachable"
    if key is None and state.holds_key:
        if await push_lock(settings):
            log.info("worker_locked")
            return "locked"
        return "unreachable"
    return "in_step"


async def keep_in_step(settings: Settings) -> None:
    """The API's timer. Runs for the life of the process.

    Starts by locking the worker: this process has just started, so it holds
    no key, and a worker still holding one from before the restart is exactly
    the "restart and it stays unlocked" case the passphrase exists to prevent.
    `sync` does that on its first pass by itself.
    """
    while True:
        try:
            await sync(settings)
        except Exception as error:  # never let the timer die quietly
            log.warning("worker_unlock_sync_failed", error=f"{type(error).__name__}: {error}")
        await asyncio.sleep(settings.worker_unlock_sync_seconds)
