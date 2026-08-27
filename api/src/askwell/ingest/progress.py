"""Where the worker says how far it has got, and where the API reads it.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-025`.

Two processes need to agree about one number many times a second, and the
choice of where to put it is the whole design.

**Not Postgres.** A 4 GB scan reporting every few megabytes is a thousand
`UPDATE`s on a row nobody will read afterwards, each one a WAL write, on a
laptop that is also running a model. The durable truth about a document — that
it is queued, running, done, or failed — belongs in Postgres and stays there.
Where the read head is inside a file does not: it is worth nothing the moment
the job ends.

**Redis, with a short expiry, and never a fallback to zero.** The key carries
its own freshness: a worker that is killed mid-file stops refreshing, the key
disappears within seconds, and the interface goes back to reporting what the
database says rather than a bar frozen at 43% forever. A stale progress bar is
worse than none — it is the shape of a hang, and it would be showing it about a
job that is no longer running.

**Throttled at the writer.** The report call is made per chunk because that is
where the number is known; whether it reaches Redis is decided here, on time and
on distance. Nobody can see a bar move a thousand times a second, and the cost
of pretending otherwise is paid by the machine the user is trying to work on.
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import redis.asyncio as redis

from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

PREFIX = "askwell:ingest:live:"

# Long enough to survive an ordinary pause between chunks on a slow share,
# short enough that a killed worker's last report is gone before anyone reads
# it as current.
TTL_SECONDS = 30

# The throttle. Both conditions, not either: time alone would still write a
# thousand times for a thousand small files, and distance alone would go silent
# for minutes on a slow network share, which is exactly when someone is
# watching to see whether it has hung.
MIN_INTERVAL_SECONDS = 0.25
MIN_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Live:
    """One document being worked on right now, as the worker last said."""

    document_id: uuid.UUID
    source_id: uuid.UUID
    filename: str
    stage: str
    bytes_done: int
    bytes_total: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": str(self.document_id),
            "source_id": str(self.source_id),
            "filename": self.filename,
            "stage": self.stage,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
        }


def key(document_id: uuid.UUID) -> str:
    return f"{PREFIX}{document_id}"


def client(settings: Settings) -> redis.Redis:
    """A Redis client for progress alone.

    Separate from arq's pool deliberately: arq owns its connection for queue
    operations, and a progress write that fails must never be able to disturb
    the queue.
    """
    return redis.Redis(host=settings.redis_host, port=settings.redis_port)


class Publisher:
    """The worker's end. One per document being processed.

    Never raises. Progress is a courtesy to somebody watching a bar; failing a
    document that read perfectly well because Redis hiccuped would be the
    tail wagging the dog. A failure is logged once — repeatedly logging it
    would fill the log with the same line a thousand times for one large file.
    """

    def __init__(self, connection: redis.Redis, document: "LiveDocument") -> None:
        self._connection = connection
        self._document = document
        self._last_at = 0.0
        self._last_bytes = -1
        self._complained = False

    async def report(self, stage: str, bytes_done: int, bytes_total: int | None) -> None:
        now = time.monotonic()
        near = bytes_done - self._last_bytes < MIN_BYTES
        soon = now - self._last_at < MIN_INTERVAL_SECONDS
        # The final report of a stage always goes through: it is the one that
        # takes the bar to the end, and dropping it leaves the last file of an
        # import showing 98% while the queue says it is finished.
        complete = bytes_total is not None and bytes_done >= bytes_total
        if near and soon and not complete:
            return

        self._last_at = now
        self._last_bytes = bytes_done

        live = Live(
            document_id=self._document.id,
            source_id=self._document.source_id,
            filename=self._document.filename,
            stage=stage,
            bytes_done=bytes_done,
            bytes_total=bytes_total,
        )
        try:
            await self._connection.set(
                key(self._document.id),
                json.dumps(live.as_dict()),
                ex=TTL_SECONDS,
            )
        except (OSError, redis.RedisError) as error:
            if not self._complained:
                self._complained = True
                log.warning(
                    "ingest_progress_unwritable",
                    document_id=str(self._document.id),
                    error=f"{type(error).__name__}: {error}",
                )

    async def clear(self) -> None:
        """Stop reporting this document, now rather than in thirty seconds."""
        try:
            await self._connection.delete(key(self._document.id))
        except (OSError, redis.RedisError):
            # The expiry is the backstop. It is why the key has one.
            pass


@dataclass(frozen=True, slots=True)
class LiveDocument:
    """The identifying fields a progress record carries."""

    id: uuid.UUID
    source_id: uuid.UUID
    filename: str


def _parse(raw: bytes | str) -> Live | None:
    try:
        payload = json.loads(raw)
        return Live(
            document_id=uuid.UUID(payload["document_id"]),
            source_id=uuid.UUID(payload["source_id"]),
            filename=payload["filename"],
            stage=payload["stage"],
            bytes_done=int(payload["bytes_done"]),
            bytes_total=None if payload["bytes_total"] is None else int(payload["bytes_total"]),
        )
    except (ValueError, KeyError, TypeError):
        # A malformed record is somebody else's key or a version skew. Dropping
        # it costs a progress bar; trusting it costs a 500 on the surface that
        # exists to say what is happening.
        return None


async def live(connection: redis.Redis) -> list[Live]:
    """Every document being worked on right now, as the workers last said.

    A scan rather than a known set of keys. The set of in-flight documents is
    bounded by the worker's concurrency — two on this machine — so this is a
    handful of keys, and a scan cannot go stale the way a separately maintained
    index can.
    """
    found: list[Live] = []
    try:
        async for name in connection.scan_iter(match=f"{PREFIX}*", count=100):
            raw = await connection.get(name)
            if raw is None:
                # Expired between the scan and the read. That is the mechanism
                # working, not an error.
                continue
            parsed = _parse(raw)
            if parsed is not None:
                found.append(parsed)
    except (OSError, redis.RedisError) as error:
        # The database still knows what is queued and what is done. Losing the
        # within-file detail degrades the answer; inventing it would corrupt it.
        log.warning("ingest_progress_unreadable", error=f"{type(error).__name__}: {error}")
        return []
    return sorted(found, key=lambda item: item.filename)
