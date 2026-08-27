"""The two database-backed audit stores, and their hash chain.

`docs/audit-log.md` §2 and §4.

**Tamper-evident. Not immutable.** The user has root on their own machine and
always will, so preventing tampering is not on the table. What is available is
two honest things: the application never rewrites history — a grant, not a code
path anyone could forget — and manual tampering is detectable. That is enough
for the case this exists to serve: a consultant who has to show a client what
was asked of their confidential files can produce a log that is verifiable
rather than merely asserted.

Writing is part of the caller's transaction, deliberately. A decision that
cannot be recorded did not happen — the alternative is a memory fact with no
audit record behind it, which is exactly the state nobody can later explain.
Traces are elsewhere (`askwell.traces`) and never fail anything, because
bricking the product over a debugging aid is absurd.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.logging import get_logger

log = get_logger(__name__)

# The first record chains to this rather than to null. A defined genesis value
# means the verifier has one rule instead of a rule plus a special case, and a
# special case in an integrity check is where a forged first record hides.
GENESIS = "0" * 64

_SEPARATOR = "\x1f"  # ASCII unit separator: cannot appear in the fields it joins


class Store(StrEnum):
    """The two database-backed stores. Separate on purpose.

    Different retention and different volume: decisions are kilobytes and kept
    forever, interactions grow steadily and roll. Merging them would force one
    retention policy onto both, and the one that must never lose a write is
    precisely the small one.
    """

    DECISIONS = "audit_decisions"
    INTERACTIONS = "audit_interactions"


class AuditError(RuntimeError):
    """An audit record could not be written. The action must not proceed."""


class PayloadNotHashable(AuditError):
    """The payload contains something that would not survive the round trip."""


def canonical_payload(payload: dict[str, Any]) -> str:
    """Serialise a payload so that hashing it is stable across a round trip.

    This is the subtle part of the whole feature. The hash is computed here and
    the payload is stored as `jsonb`, and Postgres normalises `jsonb`: it does
    not preserve key order, and numeric representation is its own business. If
    verification recomputes from the round-tripped value and Postgres rendered
    anything differently, every record reads as tampered — which is worse than
    having no verification at all, because it accuses the user of something
    they did not do.

    Sorted keys handle ordering. Floats are refused rather than handled,
    because `0.1 + 0.2` and `numeric` do not agree about what they are and
    there is no formatting rule that makes them agree in every case. Audit
    payloads are identifiers, counts, names and reasons; a float in one is a
    mistake worth failing on rather than a case worth supporting.
    """
    _reject_floats(payload, path="payload")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _reject_floats(value: Any, path: str) -> None:
    if isinstance(value, float):
        raise PayloadNotHashable(
            f"{path} is a float ({value!r}). Audit payloads are hashed and then "
            f"stored as jsonb, and floats do not survive that round trip "
            f"identically — every later verification would report tampering "
            f"that never happened. Use a string, or an integer in a fixed unit "
            f"(milliseconds, cents, basis points)."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def compute_hash(
    *,
    record_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    prev_hash: str,
) -> str:
    """The hash of one record, over everything that identifies it.

    The record's own id and timestamp are inside the hash, so a record cannot
    be moved, re-dated or duplicated without breaking the chain — only removing
    or altering its *contents* would be caught otherwise.

    Fields are joined with a unit separator rather than concatenated. Without
    one, `kind="a"` with a payload starting `b` hashes identically to
    `kind="ab"` with a payload starting where the first left off, and a forged
    record could be made to collide with a real one by moving a boundary.
    """
    material = _SEPARATOR.join(
        [
            str(record_id),
            kind,
            canonical_payload(payload),
            occurred_at.astimezone(UTC).isoformat(),
            prev_hash,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _last_hash(session: AsyncSession, store: Store) -> str:
    """The hash of the most recent record, or the genesis value.

    An advisory lock, held for the caller's transaction, makes the read and the
    insert that follows it atomic. Without it two concurrent writes read the
    same predecessor and the chain forks — and a forked chain does not look
    broken, it looks like one of the two branches was deleted.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:store))"), {"store": str(store)}
    )
    result = await session.execute(
        text(f"SELECT hash FROM {store.value} ORDER BY occurred_at DESC, id DESC LIMIT 1")
    )
    row = result.first()
    return str(row[0]) if row is not None else GENESIS


async def record(
    session: AsyncSession,
    store: Store,
    kind: str,
    payload: dict[str, Any],
) -> uuid.UUID:
    """Append one record, in the caller's transaction.

    Not committed here. The record and the action it describes commit together
    or neither does — a decision that could not be recorded did not happen.
    """
    record_id = uuid.uuid4()
    # The lock first, then the timestamp. Stamping before the lock lets two
    # writers acquire it in one order and carry timestamps in the other, which
    # is harmless for the chain and was not harmless for the verifier that used
    # to read the chain in timestamp order.
    prev_hash = await _last_hash(session, store)
    occurred_at = datetime.now(UTC)

    digest = compute_hash(
        record_id=record_id,
        kind=kind,
        payload=payload,
        occurred_at=occurred_at,
        prev_hash=prev_hash,
    )

    await session.execute(
        text(
            f"INSERT INTO {store.value} (id, kind, payload, prev_hash, hash, occurred_at) "
            f"VALUES (:id, :kind, CAST(:payload AS jsonb), :prev_hash, :hash, :occurred_at)"
        ),
        {
            "id": record_id,
            "kind": kind,
            "payload": canonical_payload(payload),
            "prev_hash": prev_hash,
            "hash": digest,
            "occurred_at": occurred_at,
        },
    )
    return record_id


# --- verification -----------------------------------------------------------


class Break(StrEnum):
    """Why a chain stopped verifying."""

    ALTERED = "altered"
    """The record's contents no longer produce its stored hash."""

    UNLINKED = "unlinked"
    """A record exists that nothing in the chain links to.

    Which is what a deletion looks like from here: the record before the gap
    still points at something, and the records after it are no longer reachable
    from the start.
    """

    FORKED = "forked"
    """Two records claim the same predecessor.

    This is not something a user can do by hand — it is what a concurrency bug
    in Askwell itself would look like, and it must not be reported as
    tampering. Telling someone their log was altered because their own software
    wrote two records at once would be a lie with their name on it.
    """

    MISSING_GENESIS = "missing_genesis"
    """Records exist but none starts the chain. The first record was removed."""


class VerificationResult:
    """What a verification pass found. Plain, and naming the record."""

    __slots__ = ("checked", "detail", "first_break", "reason", "store")

    def __init__(
        self,
        store: Store,
        checked: int,
        first_break: uuid.UUID | None = None,
        reason: Break | None = None,
        detail: str = "",
    ) -> None:
        self.store = store
        self.checked = checked
        self.first_break = first_break
        self.reason = reason
        self.detail = detail

    @property
    def intact(self) -> bool:
        """Whether the chain verified.

        Derived from `reason`, not from `first_break`. Not every break has a
        record to name — deleting the *first* record leaves nothing chaining to
        genesis and no single row to point at — and an earlier version keyed
        this off `first_break`, so that exact case reported as intact. A
        verifier that says "fine" about a chain whose start was removed is
        worse than no verifier.
        """
        return self.reason is None

    def __str__(self) -> str:
        if self.intact:
            return f"{self.store.value}: {self.checked} records, chain intact."
        where = f" at record {self.first_break}" if self.first_break else ""
        return f"{self.store.value}: chain breaks{where} ({self.reason}). {self.detail}"


async def verify(session: AsyncSession, store: Store) -> VerificationResult:
    """Walk a chain and report the first break, by record.

    The walk follows the links rather than sorting by anything. A chain defines
    its own order, and every ordering column available here is worse: a
    timestamp depends on clock resolution and on when it was taken relative to
    the lock, and a surrogate id has no order at all. An earlier version sorted
    by `occurred_at` and reported perfectly good chains as broken whenever two
    records landed close enough together.

    A record whose computed hash does not match its stored hash is a break, not
    a warning. Reporting the *first* one matters: everything after a break is
    unverifiable rather than wrong, and listing all of it would bury the one
    record the user needs to look at.
    """
    result = await session.execute(
        # The table name is interpolated, which would be alarming if it came
        # from anywhere but a closed enum defined in this module.
        text(f"SELECT id, kind, payload, prev_hash, hash, occurred_at FROM {store.value}")
    )

    by_predecessor: dict[str, tuple[Any, ...]] = {}
    total = 0
    for row in result:
        total += 1
        predecessor = str(row[3])
        if predecessor in by_predecessor:
            existing = by_predecessor[predecessor]
            return VerificationResult(
                store,
                0,
                uuid.UUID(str(row[0])),
                Break.FORKED,
                f"It and record {existing[0]} both chain to {predecessor}. "
                f"This is a fault in Askwell, not evidence of tampering.",
            )
        by_predecessor[predecessor] = tuple(row)

    if total == 0:
        return VerificationResult(store, 0)

    if GENESIS not in by_predecessor:
        return VerificationResult(
            store,
            0,
            None,
            Break.MISSING_GENESIS,
            f"{total} records exist but none chains to the genesis value. "
            f"The first record has been removed.",
        )

    expected_prev = GENESIS
    checked = 0

    while expected_prev in by_predecessor:
        record_id, kind, payload, prev_hash, stored_hash, occurred_at = by_predecessor.pop(
            expected_prev
        )
        recomputed = compute_hash(
            record_id=uuid.UUID(str(record_id)),
            kind=kind,
            payload=payload,
            occurred_at=occurred_at,
            prev_hash=prev_hash,
        )
        if recomputed != stored_hash:
            return VerificationResult(
                store,
                checked,
                uuid.UUID(str(record_id)),
                Break.ALTERED,
                f"Its contents hash to {recomputed}, but it stores {stored_hash}.",
            )
        expected_prev = str(stored_hash)
        checked += 1

    if by_predecessor:
        # Reachability ran out before the records did.
        orphan = next(iter(by_predecessor.values()))
        return VerificationResult(
            store,
            checked,
            uuid.UUID(str(orphan[0])),
            Break.UNLINKED,
            f"It chains to {orphan[3]}, which is not the hash of any record "
            f"reachable from the start. A record has been removed.",
        )

    return VerificationResult(store, checked)


def main() -> None:
    """Verify both chains and say plainly what was found.

    The settings surface for this arrives in M7. Until then it is a command,
    because a verification nobody can run is a guarantee nobody can check.
    """
    import asyncio

    from askwell.config import ConfigurationError, load_settings
    from askwell.db.engine import build_engine, session_factory

    try:
        settings = load_settings()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None

    async def run() -> int:
        engine = build_engine(settings)
        factory = session_factory(engine)
        broken = 0
        try:
            async with factory() as session:
                for store in Store:
                    outcome = await verify(session, store)
                    print(outcome)  # noqa: T201 - a command, talking to a terminal
                    if not outcome.intact:
                        broken += 1
        finally:
            await engine.dispose()

        if broken:
            print(  # noqa: T201
                "\nA break means a record was changed or removed after it was "
                "written. Askwell never rewrites these — it has no permission "
                "to. Something else on this machine did."
            )
        return 1 if broken else 0

    raise SystemExit(asyncio.run(run()))
