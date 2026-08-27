"""Hash chain computation, without a database.

The chain's value is entirely in what it refuses to accept. These test the
hashing rules directly; `test_audit_chain.py` tests them against a real
Postgres, where the round trip through `jsonb` is the thing that can go wrong.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from askwell.audit import GENESIS, PayloadNotHashable, canonical_payload, compute_hash

WHEN = datetime(2026, 8, 27, 9, 0, 0, tzinfo=UTC)
RECORD = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _hash(**overrides: object) -> str:
    fields: dict[str, object] = {
        "record_id": RECORD,
        "kind": "source_added",
        "payload": {"name": "contracts"},
        "occurred_at": WHEN,
        "prev_hash": GENESIS,
    }
    fields.update(overrides)
    return compute_hash(**fields)  # type: ignore[arg-type]


def test_the_genesis_value_is_defined_not_null() -> None:
    """One rule instead of a rule plus a special case.

    A special case in an integrity check is where a forged first record hides.
    """
    assert GENESIS == "0" * 64
    assert len(GENESIS) == 64


def test_hashing_is_deterministic() -> None:
    assert _hash() == _hash()


def test_key_order_does_not_change_the_hash() -> None:
    """Postgres does not preserve `jsonb` key order, so neither may the hash."""
    first = _hash(payload={"a": "1", "b": "2"})
    second = _hash(payload={"b": "2", "a": "1"})
    assert first == second


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "source_removed"},
        {"payload": {"name": "invoices"}},
        {"prev_hash": "f" * 64},
        {"occurred_at": WHEN + timedelta(seconds=1)},
        {"record_id": uuid.UUID("22222222-2222-2222-2222-222222222222")},
    ],
    ids=["kind", "payload", "prev_hash", "occurred_at", "record_id"],
)
def test_changing_anything_changes_the_hash(change: dict[str, object]) -> None:
    """The id and timestamp are inside the hash on purpose.

    Without them a record could be moved, re-dated or duplicated and only its
    *contents* would be protected.
    """
    assert _hash(**change) != _hash()


def test_fields_cannot_be_shifted_across_their_boundary() -> None:
    """Joined with a separator, not concatenated.

    Concatenated, `kind="a"` with a payload starting `b` hashes identically to
    `kind="ab"` with the payload starting one character later — so a forged
    record could be made to collide with a real one by moving a boundary.
    """
    assert _hash(kind="ab", payload={"c": "1"}) != _hash(kind="a", payload={"bc": "1"})


def test_a_float_in_a_payload_is_refused_with_a_reason() -> None:
    """It would not survive the round trip through jsonb identically.

    Every later verification would then report tampering that never happened —
    worse than no verification, because it accuses the user of something they
    did not do.
    """
    with pytest.raises(PayloadNotHashable) as raised:
        canonical_payload({"duration": 1.5})
    message = str(raised.value)
    assert "payload.duration" in message
    assert "milliseconds" in message


def test_a_float_nested_anywhere_is_refused_and_named() -> None:
    with pytest.raises(PayloadNotHashable) as raised:
        canonical_payload({"steps": [{"ok": True}, {"score": 0.81}]})
    assert "payload.steps[1].score" in str(raised.value)


def test_integers_and_strings_are_fine() -> None:
    canonical_payload({"rows": 7, "name": "contracts", "ok": True, "reason": None})


def test_canonical_form_is_compact_and_sorted() -> None:
    assert canonical_payload({"b": "2", "a": "1"}) == '{"a":"1","b":"2"}'


def test_non_ascii_survives_unescaped() -> None:
    """Filenames are not ASCII, and escaping them would still hash stably —
    but the stored payload should read as what the user typed."""
    assert canonical_payload({"name": "договор"}) == '{"name":"договор"}'


def test_the_audit_code_never_claims_immutability() -> None:
    """C6 is about wording as much as mechanism.

    The user has root on their own machine. Calling this immutable would be a
    claim that is false in the exact situation where someone is relying on it,
    and `docs/audit-log.md` §4 says the difference is the whole point. Narrow
    on purpose: it checks that every use of the word in these two modules is a
    denial, rather than hunting for it across a repository where
    `Cache-Control: immutable` is a legitimate and unrelated use.
    """
    import askwell.audit
    import askwell.traces

    for module in (askwell.audit, askwell.traces):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), start=1):
            lowered = line.lower()
            if "immutable" not in lowered:
                continue
            assert "not immutable" in lowered, (
                f"{Path(module.__file__ or '').name}:{number} uses 'immutable' "
                f"without denying it: {line.strip()!r}"
            )
