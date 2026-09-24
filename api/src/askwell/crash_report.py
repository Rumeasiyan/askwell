"""Local crash reports. `M7-OPS-DOC-165`.

When Askwell fails in a way it did not expect, it writes one small JSON file
to `Settings.crash_report_dir` (`/var/lib/askwell/crash-reports`, inside the
`askwell-state` volume) and logs one line saying so. **That is all.** There is
no network code in this module and none is reachable from it: a crash report
leaves this machine only when the person downloads it from Settings → About
and attaches it to an issue themselves. Crash reporting that phones home is a
C1 violation, not a feature, and there is no setting that would turn one on.

**The report is built from an allow-list, not by scrubbing.** It carries the
version, the component, the platform, the profile, the exception's *type*
names and the stack as `(module, function, line)` triples — nothing else.
The exception's message, local variables, request bodies and the request's
own path are never read into it, because each of those can carry a filename,
a question, a SQL string or a row from the user's own data, and a scrubber
that tries to find those after the fact misses the one it was not written
for. A report is less useful for missing them, and that trade is the point:
a person must be able to attach it to a public issue without reading it
first. `api/tests/test_crash_report.py` asserts a filename and a question
placed in every one of those places never reach the file.

**Writing a report never raises.** It runs inside the handler for a failure
that has already happened; a second failure there would replace the first
with a less useful one. If the directory cannot be written, the log line says
so and the original failure carries on as it would have.
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import secrets
import sys
import sysconfig
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from askwell import __version__
from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

FORMAT = "askwell-crash-report/1"

# Newest reports kept; older ones are removed when a new one is written. A
# crash loop must not be the reason a laptop runs out of disk.
KEEP = 20

# What a report deliberately leaves out, written into every report so a
# person reading it — or a maintainer wondering why it is so thin — does not
# have to find this module to learn why.
EXCLUDED = (
    "Left out on purpose: the error message, local variables, request bodies, "
    "request paths and anything read from your files, questions or databases. "
    "Those can contain your own material. This report was written on this "
    "machine and has not been sent anywhere."
)

# `crash-20260924T101500Z-api-1a2b3c4d.json`. The download route accepts only
# names of this shape, then only if the file is really there, so a name can
# never walk out of the directory.
_NAME = re.compile(r"^crash-\d{8}T\d{6}Z-[a-z]+-[0-9a-f]{8}\.json$")

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_STDLIB = Path(sysconfig.get_paths()["stdlib"]).resolve()


def _frame_location(filename: str) -> str:
    """A code location a maintainer can find, and nothing else.

    Askwell's own frames become `askwell/ask.py`; a dependency's become the
    path below `site-packages`. Anything else — an interpreter-internal
    frame, `<string>` — is reported as `<other>` rather than trusted, because
    the one thing a frame path must never be is somebody's file.
    """
    path = Path(filename)
    try:
        return path.resolve().relative_to(_PACKAGE_ROOT).as_posix()
    except (ValueError, OSError):
        pass
    parts = path.parts
    if "site-packages" in parts:
        return Path(*parts[parts.index("site-packages") + 1 :]).as_posix()
    try:
        return f"stdlib/{path.resolve().relative_to(_STDLIB).as_posix()}"
    except (ValueError, OSError):
        pass
    return "<other>"


def _chain(error: BaseException) -> Iterator[BaseException]:
    """The error, then whatever caused it, without looping on a cycle."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _type_name(error: BaseException) -> str:
    kind = type(error)
    return f"{kind.__module__}.{kind.__qualname__}"


def _frames(tb: TracebackType | None) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(
            {
                "location": _frame_location(code.co_filename),
                "function": code.co_name,
                "line": tb.tb_lineno,
            }
        )
        tb = tb.tb_next
    return frames


def build_report(
    error: BaseException,
    *,
    component: str,
    settings: Settings,
    route: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """The report's whole content. Every key is listed here; nothing is copied
    across from the error wholesale."""
    when = occurred_at or datetime.now(UTC)
    return {
        "format": FORMAT,
        "askwell_version": __version__,
        "component": component,
        "occurred_at": when.isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "profile": str(settings.profile),
        # A route *template* (`/documents/{document_id}`), never the path a
        # request actually used, which can carry a name or a query string.
        "route": route,
        "exception": {
            "type": _type_name(error),
            "chain": [_type_name(item) for item in _chain(error)][1:],
        },
        "frames": _frames(error.__traceback__),
        "excluded": EXCLUDED,
    }


def _prune(directory: Path) -> None:
    reports = sorted(
        (item for item in directory.iterdir() if _NAME.match(item.name)),
        key=lambda item: item.name,
    )
    for stale in reports[:-KEEP]:
        stale.unlink(missing_ok=True)


def write(
    error: BaseException,
    *,
    component: str,
    settings: Settings,
    route: str | None = None,
) -> Path | None:
    """Write a report and log that it was written. Never raises."""
    try:
        when = datetime.now(UTC)
        report = build_report(
            error, component=component, settings=settings, route=route, occurred_at=when
        )
        directory = settings.crash_report_dir
        directory.mkdir(parents=True, exist_ok=True)
        name = f"crash-{when.strftime('%Y%m%dT%H%M%SZ')}-{component}-{secrets.token_hex(4)}.json"
        path = directory / name
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        _prune(directory)
    except Exception as failure:  # never raise from a crash handler; see the docstring
        log.error(
            "crash_report_not_written",
            component=component,
            exception_type=_type_name(error),
            reason=type(failure).__name__,
        )
        return None
    # The type only — the message is exactly what the report left out.
    log.error(
        "crash_report_written",
        component=component,
        exception_type=_type_name(error),
        report=str(path),
    )
    return path


def install_excepthook(settings: Settings, component: str) -> None:
    """Write a report for anything that would otherwise end the process, then
    let the interpreter's own hook run as before."""
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def hook(kind: type[BaseException], error: BaseException, tb: TracebackType | None) -> None:
        if not isinstance(error, (KeyboardInterrupt, SystemExit)):
            write(error.with_traceback(tb), component=component, settings=settings)
        previous(kind, error, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None and not isinstance(args.exc_value, SystemExit):
            write(
                args.exc_value.with_traceback(args.exc_traceback),
                component=component,
                settings=settings,
            )
        previous_thread(args)

    sys.excepthook = hook
    threading.excepthook = thread_hook


@dataclass(frozen=True, slots=True)
class ReportFile:
    name: str
    bytes: int

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "bytes": self.bytes}


def list_reports(settings: Settings) -> list[ReportFile]:
    """Newest first. An absent directory is no reports, not an error."""
    directory = settings.crash_report_dir
    if not directory.is_dir():
        return []
    found = [
        ReportFile(name=item.name, bytes=item.stat().st_size)
        for item in directory.iterdir()
        if _NAME.match(item.name) and item.is_file()
    ]
    return sorted(found, key=lambda item: item.name, reverse=True)


def register_crash_reports(app: FastAPI, settings: Settings) -> None:
    """List and download. No upload, no send: there is nowhere to send to."""

    @app.get("/crash-reports")
    async def read_reports() -> JSONResponse:
        reports = await asyncio.to_thread(list_reports, settings)
        return JSONResponse(
            {
                "directory": str(settings.crash_report_dir),
                "reports": [item.as_dict() for item in reports],
            }
        )

    @app.get("/crash-reports/{name}", response_model=None)
    async def download_report(name: str) -> FileResponse | JSONResponse:
        path = settings.crash_report_dir / name
        if not _NAME.match(name) or not await asyncio.to_thread(path.is_file):
            return JSONResponse({"error": "No such crash report."}, status_code=404)
        return FileResponse(path, filename=name, media_type="application/json")
