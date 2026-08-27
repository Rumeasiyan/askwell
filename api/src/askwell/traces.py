"""The trace ring buffer.

`docs/audit-log.md` §2. Traces are the largest and fastest-growing of the three
stores, and the only one that fails open.

The reasoning is worth keeping: a trace is a debugging aid. Losing one is an
inconvenience. Bricking the product because one could not be written is absurd.
So every failure in this module is swallowed and logged, and nothing here can
propagate into the action that produced the trace.

Losing a trace costs nothing the user can see, because citations and fact usage
are real tables and do not rotate. An answer from a year ago keeps its sources
long after its tool detail has been dropped.
"""

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from askwell.logging import get_logger

log = get_logger(__name__)

SUFFIX = ".trace.json"


class TraceRing:
    """A capped directory of trace files, oldest dropped first.

    A directory of files rather than one appended log: a trace is read whole,
    by id, when someone opens the trace screen — and pruning a ring buffer that
    is one big file means rewriting it, which is the operation most likely to
    fail on the full disk that caused the pruning.
    """

    def __init__(self, directory: Path, max_bytes: int) -> None:
        self.directory = directory
        self.max_bytes = max_bytes

    def write(self, message_id: uuid.UUID, trace: dict[str, Any]) -> Path | None:
        """Store one trace. Returns None if it could not be stored.

        Never raises. A caller that checks the return value is welcome to; a
        caller that ignores it is behaving correctly too.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{message_id}{SUFFIX}"
            document = {
                "message_id": str(message_id),
                "written_at": datetime.now(UTC).isoformat(),
                "trace": trace,
            }
            # Written to a temporary file and moved into place, so a trace that
            # is interrupted half-written is absent rather than corrupt. A
            # corrupt trace looks like a bug in whatever produced it.
            temporary = path.with_suffix(".partial")
            temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        except OSError as error:
            # The disk is full, or the directory is not writable. Neither is a
            # reason to fail the answer the user just asked for.
            log.warning("trace_write_failed", message_id=str(message_id), error=str(error))
            return None

        self.prune()
        return path

    def read(self, message_id: uuid.UUID) -> dict[str, Any] | None:
        """One trace, or None if it has rotated out. Rotating out is normal."""
        path = self.directory / f"{message_id}{SUFFIX}"
        try:
            loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded

    def total_bytes(self) -> int:
        return sum(path.stat().st_size for path in self._files())

    def prune(self) -> int:
        """Drop oldest traces until the directory fits its cap.

        Returns how many were dropped. Silent by design at the individual
        level — a trace ageing out is the buffer working, not an incident — but
        the total is logged so that a cap set far too low is visible as a
        stream of prunes rather than as traces mysteriously never being there.
        """
        try:
            files = sorted(self._files(), key=lambda path: path.stat().st_mtime)
        except OSError:
            return 0

        total = sum(path.stat().st_size for path in files)
        dropped = 0
        for path in files:
            if total <= self.max_bytes:
                break
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:  # pragma: no cover - raced with another prune
                continue
            total -= size
            dropped += 1

        if dropped:
            log.info("traces_pruned", dropped=dropped, remaining_bytes=total)
        return dropped

    def _files(self) -> list[Path]:
        try:
            return [path for path in self.directory.iterdir() if path.name.endswith(SUFFIX)]
        except OSError:
            return []
