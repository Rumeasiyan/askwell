"""The model acquisition step: real progress, resumable, cancellable. `M1-LIB-FE-052`.

C1's own note on this ticket: "the model acquisition step is the one
download in the product and it is user-initiated at install; it is not a
runtime network call." The user clicks Start; nothing here fires on its own.

**Resumability is the partial file, not a job record.** The download writes
to `<target>.part` and only renames it onto `<target>` once the whole file's
sha256 matches the catalog entry. Picking the download back up — whether
because the user clicked Cancel and Resume in the same session, or because
they closed the tab and came back after the API process itself restarted —
is the same operation either way: look at how many bytes `<target>.part`
already holds and ask for a `Range: bytes=<n>-` from there. No separate
"where did we get to" table to keep in sync with the file it describes.

**One download at a time, in-process.** A user has one machine and downloads
one model; this is not `askwell.ingest`'s durable multi-file queue, and does
not need arq's persistence — the file on disk already survives a restart,
which is the only durability this needs.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from shutil import disk_usage

import httpx

from askwell.logging import get_logger
from askwell.models_catalog import ModelSpec, spec_for_tier

log = get_logger(__name__)

# Left free below whatever the download itself needs, so a machine that just
# clears the floor does not immediately fill the disk with nothing left for
# the database or the rest of the corpus.
_DISK_MARGIN_BYTES = 500 * 1024 * 1024

_CHUNK_SIZE = 1024 * 1024


class DownloadStatus(StrEnum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"


class NoDiskSpace(Exception):
    def __init__(self, needed_bytes: int, free_bytes: int) -> None:
        self.needed_bytes = needed_bytes
        self.free_bytes = free_bytes
        super().__init__(f"Needs {needed_bytes} bytes, {free_bytes} free.")


@dataclass(slots=True)
class DownloadProgress:
    status: DownloadStatus
    tier: str
    display_name: str
    downloaded_bytes: int
    total_bytes: int
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": str(self.status),
            "tier": self.tier,
            "display_name": self.display_name,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "fraction": (self.downloaded_bytes / self.total_bytes) if self.total_bytes else 0.0,
            "error": self.error,
        }


ClientFactory = Callable[[], httpx.AsyncClient]


def _default_client() -> httpx.AsyncClient:
    # Streamed, no overall timeout: a 2-3 GB transfer on a slow connection is
    # exactly the case a fixed timeout would kill for no reason. `connect` and
    # `read` still bound each individual step so a truly dead peer is noticed.
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=None),
        follow_redirects=True,
    )


class ModelDownloadManager:
    """One model download at a time, tracked in memory for this process.

    `target_path` is `Settings.inference_model_path` — the same file the
    native inference supervisor (`M0-MODEL-DEPLOY-018`) expects to find
    already in place. This is what puts it there.
    """

    def __init__(
        self,
        target_path: Path,
        *,
        client_factory: ClientFactory = _default_client,
    ) -> None:
        self._target_path = target_path.expanduser()
        self._client_factory = client_factory
        self._task: asyncio.Task[None] | None = None
        self._cancel = asyncio.Event()
        self._progress: DownloadProgress | None = None

    @property
    def target_path(self) -> Path:
        return self._target_path

    def _part_path(self) -> Path:
        return self._target_path.with_name(self._target_path.name + ".part")

    def _bytes_on_disk(self, spec: ModelSpec) -> int:
        part = self._part_path()
        if self._target_path.is_file() and self._target_path.stat().st_size == spec.size_bytes:
            return spec.size_bytes
        if part.is_file():
            return min(part.stat().st_size, spec.size_bytes)
        return 0

    def snapshot(self, tier: str) -> DownloadProgress:
        """Progress right now, reconstructed from disk if nothing is running.

        This is what makes "returning before finishing resumes where it
        stopped" true without any state beyond the file itself: a fresh
        process asked for a snapshot sees exactly what a running one would.
        """
        if self._progress is not None and self._progress.tier == tier:
            return self._progress

        spec = spec_for_tier(tier)
        on_disk = self._bytes_on_disk(spec)
        if self._target_path.is_file() and on_disk == spec.size_bytes:
            status = DownloadStatus.READY
        elif on_disk > 0:
            status = DownloadStatus.PAUSED
        else:
            status = DownloadStatus.IDLE
        return DownloadProgress(
            status=status,
            tier=tier,
            display_name=spec.display_name,
            downloaded_bytes=on_disk,
            total_bytes=spec.size_bytes,
        )

    def disk_space_needed(self, tier: str) -> tuple[bool, int, int]:
        """`(has_enough, needed_bytes, free_bytes)`.

        Checked before a download starts and never assumed — the ticket's own
        validation rule: "The model step must never begin without confirming
        disk space."
        """
        spec = spec_for_tier(tier)
        already = self._bytes_on_disk(spec)
        needed = max(spec.size_bytes - already, 0) + _DISK_MARGIN_BYTES
        parent = self._target_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        free = disk_usage(parent).free
        return free >= needed, needed, free

    async def start(self, tier: str) -> DownloadProgress:
        if self._task is not None and not self._task.done():
            return self.snapshot(tier)

        has_enough, needed, free = self.disk_space_needed(tier)
        if not has_enough:
            raise NoDiskSpace(needed, free)

        spec = spec_for_tier(tier)
        on_disk = self._bytes_on_disk(spec)
        self._progress = DownloadProgress(
            status=DownloadStatus.DOWNLOADING,
            tier=tier,
            display_name=spec.display_name,
            downloaded_bytes=on_disk,
            total_bytes=spec.size_bytes,
        )
        self._cancel.clear()
        self._task = asyncio.create_task(self._run(tier, spec))
        return self._progress

    async def cancel(self, tier: str) -> DownloadProgress:
        self._cancel.set()
        if self._task is not None:
            await asyncio.wait([self._task])
        return self.snapshot(tier)

    def verify_manual(self, tier: str) -> DownloadProgress:
        """The offline path: a user places the file themselves.

        Checked against the same sha256 the automated download verifies
        against — `docs/ux/first-run.md` §6's settled decision that a
        correctly-named file is not assumed to be the right one.

        Writes the result into `self._progress`, the same as `_run` does for
        an automated download — without this, a poll immediately after
        calling this (`GET /setup`, which reads `snapshot()`) would keep
        returning whatever the in-memory state was *before* this ran, since
        `snapshot()` prefers `self._progress` over recomputing from disk.
        """
        spec = spec_for_tier(tier)
        if not self._target_path.is_file():
            result = DownloadProgress(
                status=DownloadStatus.IDLE,
                tier=tier,
                display_name=spec.display_name,
                downloaded_bytes=0,
                total_bytes=spec.size_bytes,
                error=f"No file found at {self._target_path}.",
            )
        else:
            digest = _sha256_file(self._target_path)
            if digest != spec.sha256:
                result = DownloadProgress(
                    status=DownloadStatus.FAILED,
                    tier=tier,
                    display_name=spec.display_name,
                    downloaded_bytes=self._target_path.stat().st_size,
                    total_bytes=spec.size_bytes,
                    error="This file does not match the model Askwell expects. Re-download it "
                    "or replace it with the correct file.",
                )
            else:
                result = DownloadProgress(
                    status=DownloadStatus.READY,
                    tier=tier,
                    display_name=spec.display_name,
                    downloaded_bytes=spec.size_bytes,
                    total_bytes=spec.size_bytes,
                )
        self._progress = result
        return result

    async def _run(self, tier: str, spec: ModelSpec) -> None:
        part = self._part_path()
        part.parent.mkdir(parents=True, exist_ok=True)
        resume_from = part.stat().st_size if part.is_file() else 0
        if resume_from > spec.size_bytes:
            # A stale partial from a different model's file name colliding is
            # not possible (the filename is the model), but a corrupt local
            # write growing the file past the known size is defended anyway.
            part.unlink()
            resume_from = 0

        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
        try:
            async with (
                self._client_factory() as client,
                client.stream("GET", spec.url, headers=headers) as response,
            ):
                if response.status_code == 416:
                    # Server says there is nothing left past what we hold —
                    # treat what is on disk as complete and let verification
                    # below decide if it actually matches.
                    resume_from = 0
                    part.unlink(missing_ok=True)
                elif response.status_code not in (200, 206):
                    response.raise_for_status()

                mode = "ab" if resume_from and response.status_code == 206 else "wb"
                if mode == "wb":
                    resume_from = 0
                downloaded = resume_from
                # Blocking `open`/write per 1 MB chunk: briefly holds the event
                # loop, but `aiofiles` is not otherwise a dependency here and a
                # single-user local server has nothing else time-critical
                # competing for the loop during a background download.
                with open(part, mode) as handle:  # noqa: ASYNC230
                    async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                        if self._cancel.is_set():
                            self._set_progress(tier, DownloadStatus.PAUSED, spec, downloaded)
                            log.info("model_download_cancelled", tier=tier, downloaded=downloaded)
                            return
                        handle.write(chunk)
                        downloaded += len(chunk)
                        self._set_progress(tier, DownloadStatus.DOWNLOADING, spec, downloaded)
        except httpx.HTTPError as error:
            self._set_progress(
                tier,
                DownloadStatus.FAILED,
                spec,
                part.stat().st_size if part.is_file() else 0,
                error=(
                    f"Download failed: {error}. "
                    "Nothing downloaded so far was lost — retry to resume."
                ),
            )
            log.warning("model_download_failed", tier=tier, error=str(error))
            return

        self._set_progress(tier, DownloadStatus.VERIFYING, spec, downloaded)
        digest = _sha256_file(part)
        if digest != spec.sha256:
            part.unlink(missing_ok=True)
            self._set_progress(
                tier,
                DownloadStatus.FAILED,
                spec,
                0,
                error=(
                    "The downloaded file did not match what Askwell expected. Retry the download."
                ),
            )
            log.warning("model_download_hash_mismatch", tier=tier)
            return

        part.replace(self._target_path)
        self._set_progress(tier, DownloadStatus.READY, spec, spec.size_bytes)
        log.info("model_download_complete", tier=tier)

    def _set_progress(
        self,
        tier: str,
        status: DownloadStatus,
        spec: ModelSpec,
        downloaded: int,
        *,
        error: str | None = None,
    ) -> None:
        self._progress = DownloadProgress(
            status=status,
            tier=tier,
            display_name=spec.display_name,
            downloaded_bytes=downloaded,
            total_bytes=spec.size_bytes,
            error=error,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
