"""Nominated root directories: the only paths Askwell is allowed to read.

Askwell indexes in place. It does not copy a 40 GB case-file tree into a
managed library, so the containers need a route to the user's own directories —
and the narrowest honest route is one the user nominates, not open filesystem
access.

Three ideas carry the whole module, and each of them is load-bearing.

**A root is a permission, not a location.** `covering()` is the check that
decides whether a path may be read at all, and `docs/backlog` states the rule
plainly: *a path outside every registered root is never read*. Everything else
here exists to make that check meaningful — registration writes the rule down,
removal takes it away, and the probe says whether the rule can currently be
acted on.

**Registration and mountedness are different facts, and neither implies the
other.** The user nominates `/home/anna/clients` in the interface; whether the
API container can actually see that path is decided by a bind mount in
`compose.yaml`, which cannot be added to a running container on any platform
Askwell supports. So the registry stores what the user nominated and the mount
state is *probed on every read*, never stored. A stored state says "available"
about a USB drive that was unplugged an hour ago, and there is no moment at
which anything would have corrected it.

**"I cannot see it" is four different situations with four different fixes**,
and collapsing them is how a user ends up hunting for a file they never moved:

  `not_mounted`   the container has no window onto this path at all. The fix is
                  a configuration line and bringing the stack up again.
  `unavailable`   the window exists, the path does not. Removable media that is
                  unplugged, a share that is disconnected, a folder that was
                  renamed. **Not deleted** — nothing here ever deletes.
  `unreadable`    it is there and the container may not read it. Permissions,
                  or SELinux refusing the bind mount.
  `available`     it is there and readable.

Removing a root is a tombstone rather than a delete, for the same reason
`documents` tombstones: afterwards, a source under that path has to be able to
say *why* it became unreadable. "There is no root covering this path" and "you
removed the root that covered this path on the 3rd" are the same state to a
query that forgot, and only one of them is an answer.
"""

import asyncio
import os
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

# Audit kinds. Registering and removing a root are source configuration
# changes, which `docs/audit-log.md` §2 puts in the decisions store.
REGISTERED = "root_registered"
REMOVED = "root_removed"

# Filesystems that are somebody else's machine. Indexing across one is slow in
# a way that is worth saying before someone starts, and the share has to be
# present again at query time or the source viewer has nothing to render.
#
# Detection is best-effort and says so: an unrecognised filesystem produces no
# claim either way rather than an assertion that it is local.
NETWORK_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "fuse.davfs",
        "fuse.sshfs",
        "glusterfs",
        "ncpfs",
        "nfs",
        "nfs4",
        "smb3",
        "smbfs",
    }
)

MOUNTS = Path("/proc/self/mounts")

# The four characters the kernel escapes in a mount point, and nothing else.
# `unicode_escape` would do this in one call and would also mangle every
# non-ASCII byte on the way — a folder called `Dossiers Privés` would come back
# as something that matches no path on the machine.
MOUNT_ESCAPES = (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\"))


class MountState(StrEnum):
    """Whether Askwell can currently read a nominated root, and if not, why."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNREADABLE = "unreadable"
    NOT_MOUNTED = "not_mounted"


class SourceState(StrEnum):
    """Why a source's files can or cannot be read right now.

    Deliberately distinct from `documents.missing_since`, which is the file
    moving underneath a root that is otherwise fine. A whole root being absent
    is not forty files being moved, and offering to relocate each of them would
    be forty wrong questions.
    """

    READABLE = "readable"
    ROOT_REMOVED = "root_removed"
    ROOT_UNAVAILABLE = "root_unavailable"
    ROOT_UNREADABLE = "root_unreadable"
    ROOT_NOT_MOUNTED = "root_not_mounted"
    NO_ROOT = "no_root"


class RootRefused(ValueError):
    """The path cannot be nominated. The message is shown to the user."""


class RootNotFound(LookupError):
    """No registered root with that identifier."""


@dataclass(frozen=True, slots=True)
class Root:
    """A nominated root, as stored. Nothing here is probed."""

    id: uuid.UUID
    path: str
    filesystem: str | None
    added_at: datetime

    @property
    def network_share(self) -> bool:
        return self.filesystem in NETWORK_FILESYSTEMS

    @property
    def name(self) -> str:
        """What to call it in a sentence. The last component, or the path."""
        return os.path.basename(self.path) or self.path


@dataclass(frozen=True, slots=True)
class RootView:
    """A root plus what is true about it at this instant."""

    root: Root
    state: MountState
    reason: str | None
    warning: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.root.id),
            "path": self.root.path,
            "name": self.root.name,
            "state": str(self.state),
            "reason": self.reason,
            "warning": self.warning,
            "filesystem": self.root.filesystem,
            "network_share": self.root.network_share,
            "added_at": self.root.added_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Registration:
    """The outcome of nominating a path.

    `created` is false when an already-registered root covers the path. That is
    a success — files under it can be added — and reporting it as a conflict
    would send the user to remove a root they need.
    """

    created: bool
    view: RootView
    covers: Sequence[str] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "root": self.view.as_dict(),
            "already_covered": not self.created,
            # Narrower roots this one now also covers. They stay registered:
            # two rules that both permit the same path permit it once, and
            # silently removing a root the user nominated would be a decision
            # taken on their behalf.
            "also_covers": list(self.covers),
        }


@dataclass(frozen=True, slots=True)
class Removal:
    """What removing a root did, and what it costs."""

    path: str
    sources_affected: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sources_affected": self.sources_affected,
            "consequence": consequence(self.path, self.sources_affected),
        }


def consequence(path: str, sources_affected: int) -> str:
    """What the user is about to lose, said before and after they do it.

    The word that must survive every edit of this string is **not deleted**.
    Someone removing a folder from a list has every reason to fear they are
    deleting their own files, and Askwell has never had a copy of them.
    """
    if sources_affected == 0:
        return (
            f"Askwell will stop reading anything under {path}. No source is "
            "using this folder yet, and nothing is deleted — not the folder, "
            "and not your files, which Askwell never held a copy of."
        )
    plural = "source" if sources_affected == 1 else "sources"
    return (
        f"{sources_affected} {plural} under {path} will stop being readable. "
        "They stay in your library with that reason shown, their answers keep "
        "their citations, and nothing is deleted — not the sources and not "
        "your files. Nominate the folder again to restore them."
    )


# --- paths ------------------------------------------------------------------


def normalise(requested: str) -> str:
    """The stored form of a nominated path, or a refusal a person can act on.

    Symlinks are deliberately **not** resolved. What is stored is the path the
    user nominated — the same string the native directory picker will hand over
    in M7 and the same one the source viewer shows — and resolving it here
    would make the interface display a path the user never typed. Symlink
    escape is handled where it matters instead, in `covering()`, which checks
    the real path of the file being read rather than the shape of the root.
    """
    stripped = requested.strip()
    if not stripped:
        raise RootRefused("No folder was given.")
    if not stripped.startswith("/"):
        raise RootRefused(
            f"Askwell needs the whole path, starting with a slash — {stripped!r} "
            "is relative to something, and Askwell and your file manager do "
            "not share a current directory."
        )

    path = os.path.normpath(stripped)
    if path == "/":
        raise RootRefused(
            "Nominating / would give Askwell your whole disk, which is the "
            "thing nominating a folder exists to avoid. Name the folder your "
            "material is actually in."
        )
    return path


def contains(root: str, candidate: str) -> bool:
    """Whether `candidate` lies at or under `root`.

    Compared component-wise rather than by string prefix. `startswith` says
    that `/home/anna/clients` contains `/home/anna/clients-archive`, which is a
    different folder that the user did not nominate — and that is precisely the
    over-permission this whole module exists to prevent.
    """
    if root == candidate:
        return True
    return candidate.startswith(root.rstrip("/") + "/")


def detect_filesystem(path: str, mounts: Path = MOUNTS) -> str | None:
    """The filesystem type carrying `path`, or None when it cannot be told.

    None means unknown, never "local". The only thing this drives is a warning
    about network shares, and inventing "it is a local disk" to avoid an empty
    field would be a claim nothing checked.
    """
    try:
        content = mounts.read_text(encoding="utf-8")
    except OSError:
        return None

    best: tuple[int, str] | None = None
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        point = fields[1]
        for escape, character in MOUNT_ESCAPES:
            point = point.replace(escape, character)
        if not contains(point, path):
            continue
        # Longest match wins: / matches everything, and is the answer only when
        # nothing more specific does.
        if best is None or len(point) > best[0]:
            best = (len(point), fields[2])
    return best[1] if best else None


def probe(path: str, mount: Path | None) -> tuple[MountState, str | None]:
    """What is true about `path` from inside this container, right now.

    The readability check opens the directory rather than calling `access()`.
    `access()` answers a question about the file mode, and the two things most
    likely to stop Askwell reading a nominated folder — a bind mount SELinux
    will not let the container traverse, and a network share whose credentials
    have expired — both leave the mode looking perfectly fine.
    """
    if mount is None:
        return (
            MountState.NOT_MOUNTED,
            "Askwell has no window onto your filesystem yet. Set "
            "ASKWELL_ROOTS_MOUNT in .env to a folder containing this one and "
            "run `podman compose up -d` again.",
        )
    window = os.path.normpath(str(mount))
    if not contains(window, path):
        return (
            MountState.NOT_MOUNTED,
            f"This folder is outside {window}, which is the only part of your "
            "filesystem the containers can see. Widen ASKWELL_ROOTS_MOUNT in "
            ".env to a folder containing both, then run `podman compose up -d` "
            "again — a container's mounts cannot be changed while it runs, on "
            "any platform Askwell supports.",
        )

    try:
        with os.scandir(path) as entries:
            next(iter(entries), None)
    except FileNotFoundError:
        return (
            MountState.UNAVAILABLE,
            "This folder is not there at the moment. If it is on a drive or a "
            "share, reconnect it — nothing has been deleted and nothing needs "
            "re-indexing.",
        )
    except NotADirectoryError:
        return (MountState.UNAVAILABLE, "This is a file, not a folder.")
    except PermissionError:
        return (
            MountState.UNREADABLE,
            "Askwell is not allowed to read this folder. Check its permissions "
            "— and on a machine with SELinux, that the bind mount is labelled "
            "so a container may traverse it.",
        )
    except OSError as error:
        return (MountState.UNAVAILABLE, f"This folder could not be read: {error.strerror}.")

    return (MountState.AVAILABLE, None)


def warning_for(filesystem: str | None) -> str | None:
    """The one thing worth saying at registration that is not an error."""
    if filesystem not in NETWORK_FILESYSTEMS:
        return None
    return (
        f"This folder is on a network share ({filesystem}). Indexing it will be "
        "considerably slower than a local disk, and the share has to be "
        "connected whenever you open a document from it — a citation cannot "
        "show you a page it cannot reach."
    )


# How long a single probe may take before the folder is treated as unreachable.
#
# A hard-mounted network share whose server has gone away does not fail — it
# blocks, for as long as the kernel is willing to wait, which can be minutes.
# Network shares are a supported configuration here, so this is a case the
# product will meet rather than a theoretical one.
PROBE_TIMEOUT_SECONDS = 3.0


async def view_async(root: Root, mount: Path | None) -> RootView:
    """`view`, off the event loop.

    `probe` opens a directory, which is a blocking syscall, and it is reached
    from three request handlers. AGENTS.md §6 forbids a blocking call in a
    request handler, and the reason is concrete rather than stylistic: one
    hanging share would take out every other request including `/health`, so
    the surface that exists to say what is wrong would be the first thing to
    stop answering.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            state, reason = await asyncio.to_thread(probe, root.path, mount)
    except TimeoutError:
        state, reason = (
            MountState.UNAVAILABLE,
            f"This folder did not respond within {PROBE_TIMEOUT_SECONDS:g}s. "
            "That usually means a network share whose server is unreachable — "
            "the folder is not gone, and Askwell has stopped waiting so the "
            "rest of it keeps working.",
        )
    return RootView(root=root, state=state, reason=reason, warning=warning_for(root.filesystem))


def view(root: Root, mount: Path | None) -> RootView:
    """The synchronous form, for tests and for code already off the loop."""
    state, reason = probe(root.path, mount)
    return RootView(root=root, state=state, reason=reason, warning=warning_for(root.filesystem))


def source_availability(
    source_path: str, roots: Iterable[RootView], removed: Iterable[Root]
) -> tuple[SourceState, str]:
    """Why a source's files can or cannot be read, in words the user gets.

    A removed root is checked *after* the live ones, so re-nominating a folder
    silently restores everything under it rather than leaving sources citing a
    removal that has been undone.
    """
    for candidate in roots:
        if not contains(candidate.root.path, source_path):
            continue
        if candidate.state is MountState.AVAILABLE:
            return (SourceState.READABLE, "Readable.")
        mapping = {
            MountState.UNAVAILABLE: SourceState.ROOT_UNAVAILABLE,
            MountState.UNREADABLE: SourceState.ROOT_UNREADABLE,
            MountState.NOT_MOUNTED: SourceState.ROOT_NOT_MOUNTED,
        }
        reason = candidate.reason or "Askwell cannot reach this folder."
        return (mapping[candidate.state], f"{candidate.root.path} — {reason}")

    for gone in removed:
        if contains(gone.path, source_path):
            return (
                SourceState.ROOT_REMOVED,
                f"You removed {gone.path} from the folders Askwell may read. "
                "Nothing was deleted. Nominate it again to make this readable.",
            )

    return (
        SourceState.NO_ROOT,
        "No nominated folder covers this path, so Askwell will not read it.",
    )


# --- the registry -----------------------------------------------------------


def _row_to_root(row: Any) -> Root:
    return Root(id=row.id, path=row.path, filesystem=row.filesystem, added_at=row.added_at)


async def active(session: AsyncSession) -> list[Root]:
    """Every root currently nominated, longest path first.

    Longest first so that a nested root is the one reported as covering a path.
    Both cover it; the narrower one is the more informative answer.
    """
    result = await session.execute(
        text(
            "SELECT id, path, filesystem, added_at FROM roots "
            "WHERE removed_at IS NULL ORDER BY length(path) DESC, path"
        )
    )
    return [_row_to_root(row) for row in result]


async def tombstoned(session: AsyncSession) -> list[Root]:
    result = await session.execute(
        text(
            "SELECT id, path, filesystem, added_at FROM roots "
            "WHERE removed_at IS NOT NULL ORDER BY length(path) DESC, path"
        )
    )
    return [_row_to_root(row) for row in result]


async def listing(session: AsyncSession, settings: Settings) -> list[RootView]:
    """Every live root with its current state.

    Probed concurrently: the list is short, and one unreachable share should
    cost the wait once rather than once per root ahead of it in the list.
    """
    roots = await active(session)
    return list(await asyncio.gather(*(view_async(root, settings.roots_mount) for root in roots)))


def literal_and_real(candidate: str) -> tuple[str, str] | None:
    """A path and where it actually leads, or None if it is not absolute.

    Separated from `covering()` because it touches the filesystem and
    `covering()` is a coroutine; the resolution is a syscall per component and
    belongs somewhere it is visibly synchronous.
    """
    path = os.path.normpath(candidate)
    if not path.startswith("/"):
        return None
    return (path, os.path.realpath(path))


def lexical_and_parent(candidate: str) -> tuple[str, str]:
    """A path tidied up and the folder holding it, by string alone.

    Separated for the same reason as `literal_and_real()`, though the opposite
    one: `normpath` and `dirname` never touch the disk, but `os.path` inside a
    coroutine is flagged all the same, and the lint cannot tell the two apart.
    Naming them here settles it once instead of at every call site.
    """
    path = os.path.normpath(candidate)
    return (path, os.path.dirname(path) or "/")


async def covering(session: AsyncSession, candidate: str) -> Root | None:
    """The nominated root that permits reading `candidate`, or None.

    **This is the check.** A path with no covering root is never read.

    The real path is tested as well as the literal one, so a symlink placed
    inside a nominated folder cannot be used to read outside it. Both must be
    covered: covering the link but not its target would let one symlink stand
    in for the whole disk, which is the exact permission the user declined to
    give.
    """
    resolved = literal_and_real(candidate)
    if resolved is None:
        return None
    path, real = resolved

    candidates = await active(session)
    index = await asyncio.to_thread(first_covering, [r.path for r in candidates], path, real)
    return candidates[index] if index is not None else None


def first_covering(root_paths: list[str], path: str, real: str) -> int | None:
    """Which root covers this path, by index. Synchronous, and deliberately so.

    Both `realpath` and the comparison touch the filesystem — a syscall per
    path component — so this is called through a thread rather than run on the
    event loop, for the same reason `probe` is.

    Public because `askwell.sources` checks a whole batch against roots that
    were read once. Going through `covering()` per file would re-read the
    registry five thousand times to learn one fact that cannot change during a
    request — and the check itself must not be copied, because a second copy is
    a second place for the symlink half to be left out.
    """
    for index, root_path in enumerate(root_paths):
        # The root's real path, not its stored one, on the right-hand side.
        #
        # Comparing the file's resolved path against the root's *unresolved*
        # one refuses every file inside a root that is itself a symlink —
        # `/home/anna/work -> /mnt/big/work` registers happily and then covers
        # nothing, which is the ticket's primary acceptance criterion failing
        # on a shape people genuinely have. The stored path stays unresolved
        # because that is what the user typed and what the viewer shows; only
        # the comparison resolves.
        #
        # Both halves are still required. The literal check keeps the stored
        # path meaningful, and the resolved check is what stops a symlink
        # placed inside a nominated folder standing in for the whole disk.
        if contains(root_path, path) and contains(os.path.realpath(root_path), real):
            return index
    return None


async def register(session: AsyncSession, settings: Settings, requested: str) -> Registration:
    """Nominate a folder. Refuses with a reason rather than half-succeeding.

    A folder Askwell can see and cannot use is refused here — that is a problem
    the user can fix now, and letting it in would leave a root in the list that
    never works. A folder Askwell *cannot see at all* is accepted, because the
    only thing wrong with it is a bind mount, the fix is stated in the reply,
    and refusing would make it impossible to nominate anything on a fresh
    install. `docs/backlog` calls that restart a known gap, not a defect.
    """
    path = normalise(requested)

    for existing in await active(session):
        if contains(existing.path, path):
            # Nested inside something already nominated. Recognised, not
            # registered twice.
            return Registration(
                created=False, view=await view_async(existing, settings.roots_mount)
            )

    state, reason = await asyncio.to_thread(probe, path, settings.roots_mount)
    if state in (MountState.UNAVAILABLE, MountState.UNREADABLE):
        raise RootRefused(reason or "Askwell cannot read this folder.")

    filesystem = detect_filesystem(path)
    result = await session.execute(
        text(
            "INSERT INTO roots (path, filesystem) VALUES (:path, :filesystem) "
            "RETURNING id, path, filesystem, added_at"
        ),
        {"path": path, "filesystem": filesystem},
    )
    root = _row_to_root(result.one())

    await record(
        session,
        Store.DECISIONS,
        REGISTERED,
        {
            "root_id": str(root.id),
            "path": root.path,
            "filesystem": filesystem,
            "mount_state": str(state),
        },
    )

    covers = [
        narrower.path
        for narrower in await active(session)
        if narrower.id != root.id and contains(path, narrower.path)
    ]
    log.info("root_registered", path=path, state=str(state), filesystem=filesystem)
    return Registration(
        created=True,
        view=RootView(root=root, state=state, reason=reason, warning=warning_for(filesystem)),
        covers=covers,
    )


async def sources_under(session: AsyncSession, path: str) -> int:
    """How many live sources this root is what makes readable.

    `starts_with` rather than `LIKE`: a folder called `100%_final` is a folder
    somebody has, and in a LIKE pattern it matches most of the disk.
    """
    result = await session.execute(
        text(
            "SELECT count(*) FROM sources WHERE root_path IS NOT NULL "
            "AND status <> 'deleted' "
            "AND (root_path = :path OR starts_with(root_path, :prefix))"
        ),
        {"path": path, "prefix": path.rstrip("/") + "/"},
    )
    return int(result.scalar_one())


async def preview_removal(session: AsyncSession, root_id: uuid.UUID) -> Removal:
    """What removing this root would cost, without removing it."""
    root = await _require(session, root_id)
    return Removal(path=root.path, sources_affected=await sources_under(session, root.path))


async def remove(session: AsyncSession, root_id: uuid.UUID) -> Removal:
    """Stop reading under a root. Tombstoned, so its sources can say why.

    Nothing is deleted: not the sources, not the documents, not one byte of the
    user's own material, which Askwell never held a copy of in the first place.
    """
    root = await _require(session, root_id)
    affected = await sources_under(session, root.path)

    await session.execute(
        text("UPDATE roots SET removed_at = now() WHERE id = :id AND removed_at IS NULL"),
        {"id": root_id},
    )
    await record(
        session,
        Store.DECISIONS,
        REMOVED,
        {"root_id": str(root_id), "path": root.path, "sources_affected": affected},
    )
    log.info("root_removed", path=root.path, sources_affected=affected)
    return Removal(path=root.path, sources_affected=affected)


async def _require(session: AsyncSession, root_id: uuid.UUID) -> Root:
    result = await session.execute(
        text(
            "SELECT id, path, filesystem, added_at FROM roots WHERE id = :id AND removed_at IS NULL"
        ),
        {"id": root_id},
    )
    row = result.first()
    if row is None:
        raise RootNotFound(str(root_id))
    return _row_to_root(row)


# --- the surface ------------------------------------------------------------


class NominateRequest(BaseModel):
    """A typed or picker-provided path.

    One field, and that is the seam. `M7-TAURI-FE-182` replaces the *selection*
    step with the platform's own directory dialog, which hands back exactly
    this — so the picker arrives without touching the registry, the validation
    or what removing a root does. A browser upload control would have had to be
    undone: it copies bytes, and Askwell copies nothing.
    """

    path: str = Field(min_length=1, max_length=4096)


def register_roots(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """Attach the roots surface. Register before the interface catch-all."""

    @app.get("/roots")
    async def list_roots(request: Request) -> JSONResponse:
        """Every nominated folder, with what is true about it now.

        `count` is the local counter the ticket asks for and the only analytics
        this feature has. It is computed here, read by the interface, and goes
        nowhere else — there is no transmission path for it to take (C1).
        """
        settings: Settings = request.app.state.settings
        async with factory() as db:
            views = await listing(db, settings)
            removed = await tombstoned(db)
        return JSONResponse(
            {
                "count": len(views),
                "roots": [item.as_dict() for item in views],
                "removed": [
                    {"id": str(item.id), "path": item.path, "name": item.name} for item in removed
                ],
                "mount": str(settings.roots_mount) if settings.roots_mount else None,
            }
        )

    @app.post("/roots")
    async def nominate(request: Request, body: NominateRequest) -> JSONResponse:
        settings: Settings = request.app.state.settings
        try:
            async with session_scope(factory) as db:
                result = await register(db, settings, body.path)
        except RootRefused as refusal:
            # 400, not 422: the path is a well-formed string and the request is
            # exactly what the interface meant to send. What is wrong is the
            # folder, and the message is the whole answer.
            return JSONResponse({"error": str(refusal), "path": body.path}, status_code=400)
        return JSONResponse(result.as_dict(), status_code=201 if result.created else 200)

    # Before `/roots/{root_id}` and deliberately: a literal segment registered
    # after a parameterised one at the same depth is shadowed by it, and the
    # symptom is a UUID parsing error about a request that was never malformed.
    @app.get("/roots/covering")
    async def covering_root(request: Request, path: str) -> JSONResponse:
        """Whether a file may be read, and what to ask if it may not.

        This is what the add-source screen calls before it accepts anything.
        When the answer is no, the reply carries the folder to nominate and the
        sentence explaining why — so a file from an unregistered drive produces
        a question, not an obscure failure.
        """
        settings: Settings = request.app.state.settings
        async with factory() as db:
            root = await covering(db, path)
            views = await listing(db, settings)
            removed = await tombstoned(db)

        normalised, suggested = lexical_and_parent(path)
        state, reason = source_availability(normalised, views, removed)
        if root is None:
            return JSONResponse(
                {
                    "covered": False,
                    "root": None,
                    "state": str(state),
                    "reason": reason,
                    "prompt": {
                        "suggested_root": suggested,
                        "headline": "Askwell has not been given this folder yet.",
                        "explanation": (
                            "Askwell reads your files where they are and never "
                            "copies them, so it needs to be told which folders "
                            f"it may open. Nominating {suggested} lets it read "
                            "anything inside it, and nothing outside it."
                        ),
                    },
                }
            )

        return JSONResponse(
            {
                "covered": True,
                "root": (await view_async(root, settings.roots_mount)).as_dict(),
                "state": str(state),
                "reason": reason,
                "prompt": None,
            }
        )

    @app.get("/roots/{root_id}/removal")
    async def removal_preview(root_id: uuid.UUID) -> JSONResponse:
        """What removing it would cost. Asked before showing a confirmation."""
        async with factory() as db:
            try:
                result = await preview_removal(db, root_id)
            except RootNotFound:
                return JSONResponse({"error": "No such folder is nominated."}, status_code=404)
        return JSONResponse(result.as_dict())

    @app.delete("/roots/{root_id}")
    async def unnominate(root_id: uuid.UUID) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                result = await remove(db, root_id)
        except RootNotFound:
            return JSONResponse({"error": "No such folder is nominated."}, status_code=404)
        return JSONResponse(result.as_dict())
