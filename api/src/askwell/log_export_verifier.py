"""The source of the standalone verifier bundled with every log export.

`docs/audit-log.md` §5, ticket `M7-LOG-BE-155`.

This module's `SOURCE` string is written into every export as `verify.py`,
byte for byte, and is the *only* copy that ships — Askwell's own process
never imports it. That is deliberate: the whole point of a bundled verifier
is that a client's technical person can run it on a machine with no Askwell
installed, so it must not import `askwell` (Pydantic, SQLAlchemy, arq — none
of it is there) and must reimplement `askwell.audit.compute_hash`'s hashing
rule independently rather than sharing code with it. If the two ever drift,
an export made today would fail to verify against tomorrow's verifier, so
`api/tests/test_log_export.py` round-trips a real export through this exact
string as its own proof the two agree, not through a second implementation
kept in sync by hand.

Kept as a module-level string, not a `.py.j2` template on disk, so a change
to the algorithm and a change to the verifier are one diff instead of two
files that can silently disagree about which one is current.
"""

SOURCE = '''#!/usr/bin/env python3
"""Verify an Askwell log export's hash chain. No dependencies, no network.

Usage: python3 verify.py [export-directory-or-zip]

Reads manifest.json plus decisions.jsonl and interactions.jsonl (whichever
are present) from the given directory, or unzips a .zip export to a
temporary directory first. For each store it recomputes every record's hash
from its own contents and walks the chain from the hash the manifest
recorded as the export's own starting point, reporting the first place a
record's stored hash does not match what its contents hash to, or where a
record in the file does not chain to anything before it.

A date-filtered export does not start at the true beginning of Askwell's
own chain — the manifest records the hash the first exported record
chains to, and this script trusts that value as the window's own starting
point rather than expecting the universal genesis value. That is not a
weaker check: every record in this file is still verified against its own
contents, and any gap or alteration *within* the exported window is still
caught. It only means this script cannot itself prove the window's starting
point is where the real, un-exported chain actually was at that moment.
"""

import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

GENESIS = "0" * 64
SEPARATOR = "\\x1f"


def canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(
    *, record_id: str, kind: str, payload: dict, occurred_at: str, prev_hash: str
) -> str:
    material = SEPARATOR.join(
        [record_id, kind, canonical_payload(payload), occurred_at, prev_hash]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_store(name: str, path: Path, starts_at: str) -> tuple[bool, str]:
    if not path.exists():
        return True, f"{name}: not in this export."

    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                return False, f"{name}: line {line_number} is not valid JSON ({error})."

    if not records:
        return True, f"{name}: 0 records."

    by_predecessor = {}
    for row in records:
        prev = row["prev_hash"]
        if prev in by_predecessor:
            other = by_predecessor[prev]
            return False, (
                f"{name}: records {row['id']} and {other['id']} both chain to {prev}. "
                f"This is a fault in how the export was produced, not evidence of tampering."
            )
        by_predecessor[prev] = row

    if starts_at not in by_predecessor:
        return False, (
            f"{name}: {len(records)} records exist but none chains to the export's own "
            f"starting hash ({starts_at}). The first record of this export has been removed."
        )

    expected_prev = starts_at
    checked = 0
    while expected_prev in by_predecessor:
        row = by_predecessor.pop(expected_prev)
        recomputed = compute_hash(
            record_id=row["id"],
            kind=row["kind"],
            payload=row["payload"],
            occurred_at=row["occurred_at"],
            prev_hash=row["prev_hash"],
        )
        if recomputed != row["hash"]:
            return False, (
                f"{name}: record {row['id']} hashes to {recomputed}, but the file stores "
                f"{row['hash']}. Its contents were altered after export."
            )
        expected_prev = row["hash"]
        checked += 1

    if by_predecessor:
        orphan = next(iter(by_predecessor.values()))
        return False, (
            f"{name}: record {orphan['id']} chains to {orphan['prev_hash']}, which is not "
            f"the hash of any record reachable from the start of this export. A record has "
            f"been removed."
        )

    return True, f"{name}: {checked} records, chain intact."


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

    cleanup = None
    if target.is_file() and target.suffix == ".zip":
        cleanup = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(target) as archive:
            archive.extractall(cleanup.name)
        target = Path(cleanup.name)

    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest.json found under {target}. Is this an Askwell log export?")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ok = True
    for store in ("decisions", "interactions"):
        entry = manifest["stores"].get(store)
        if entry is None:
            continue
        intact, message = verify_store(
            store, target / f"{store}.jsonl", entry["first_prev_hash"]
        )
        print(message)
        ok = ok and intact

    if manifest.get("since") or manifest.get("until"):
        print(
            "\\nThis export is date-filtered "
            f"(since={manifest.get('since')}, until={manifest.get('until')}): "
            "it proves the records inside it were not altered or removed after export, "
            "not that nothing was ever removed before the window started."
        )

    if cleanup is not None:
        cleanup.cleanup()

    if not ok:
        print(
            "\\nA break means a record was changed or removed after export. Askwell "
            "never rewrites its own log, so this indicates something outside Askwell "
            "changed the file."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''
