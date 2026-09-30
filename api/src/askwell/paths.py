"""The one translation between a path on the user's machine and the same file
inside a container.

Askwell stores **host paths**: `sources.root_path` and `documents.path` hold
what the user sees, what the native picker returns and what a citation has to
reopen. On Linux and macOS the user's home folder is mounted at the same path
inside the API and the worker, so a host path *is* a container path and every
function here is the identity.

On Windows that identity is impossible — `C:\\Users\\anna` is not a path a
Linux container can have — so the home folder is mounted at a fixed prefix
instead, `C:\\Users\\anna` → `/host/c/Users/anna`, and every place the API or
the worker touches the filesystem translates first. The stored path stays the
Windows one. `docs/decisions.md`, "Askwell may read the user's whole home
folder", says why this is one module and not a translation at each call site:
one missed translation is a file that cannot be found for reasons nobody can
see.

Pure: nothing here touches a disk, and nothing depends on which platform the
code runs on. The shape of the path decides — a drive letter is Windows, a
leading slash is not — which is also what lets the Linux test suite cover the
Windows case.

The Windows installer computes the mount's container side too, because
Compose cannot call a function (`deploy/windows/lib.ps1`,
`Get-AskwellRootsTarget`). The API checks at start that the two agree
(`askwell.roots.log_effective_mount`), so a second copy that drifts is a line
in the log naming both values rather than a folder that silently reads empty.
"""

import ntpath
import posixpath
import re

# Where a Windows drive's files appear inside a container. Fixed rather than
# configurable: it is a contract between `compose.yaml`, the Windows installer
# and this module, and a setting would be a fourth party able to disagree.
CONTAINER_PREFIX = "/host"

# `C:\` or `C:/`, and only with the separator. `C:` alone and `C:folder` are
# relative to the *current directory on that drive*, a notion no container
# shares, so they are not Windows absolute paths and are not recognised as one.
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def is_windows(path: str) -> bool:
    """Whether `path` is an absolute Windows path with a drive letter."""
    return _DRIVE.match(path) is not None


def is_unc(path: str) -> bool:
    """Whether `path` names a Windows network share, `\\\\server\\share`.

    Only the backslash form. `//server/share` is also UNC to Windows, but on
    Linux and macOS a leading `//` is a legal spelling of an ordinary absolute
    path, so it is only treated as a share where the caller knows the host is
    Windows.
    """
    return path.startswith("\\\\")


def drive(path: str) -> str | None:
    """The upper-case drive letter of a Windows path, or None."""
    match = _DRIVE.match(path)
    return match.group(1).upper() if match else None


def normalise_windows(path: str) -> str:
    """The canonical spelling of a Windows path: `C:\\Users\\anna\\x`.

    Upper-case drive letter, backslash separators, `.` and `..` collapsed, no
    trailing separator except on a drive root. Everything after the drive keeps
    the case the user gave it — Windows compares names case-insensitively, but
    what is stored is what the user is shown, and rewriting `Documents` to
    `documents` would show them a path they never typed.
    """
    if not is_windows(path):
        raise ValueError(f"not a Windows absolute path: {path!r}")
    tidy = ntpath.normpath(path)
    return tidy[0].upper() + tidy[1:]


def to_container(host: str) -> str:
    """Where the file at host path `host` is, from inside a container.

    `C:\\Users\\anna\\x` → `/host/c/Users/anna/x`. Anything that is not a
    Windows drive path is returned unchanged: on Linux and macOS the mount is
    the identity, and that is the whole reason this is safe to call everywhere.
    """
    if not is_windows(host):
        return host
    canonical = normalise_windows(host)
    rest = canonical[3:].replace("\\", "/")
    base = f"{CONTAINER_PREFIX}/{canonical[0].lower()}"
    return f"{base}/{rest}" if rest else base


def to_host(container: str) -> str:
    """The Windows host path for a container path under `/host/<drive>`.

    The inverse of `to_container` for a Windows path, and the identity for
    anything outside the prefix. Only call it for a path that came from a
    Windows host path — on Linux, `/host/c/...` could be a real directory
    somebody has, and it is not this function's place to rename it.
    """
    # The prefix read at call time, not compiled in, so a test can point it at
    # a temporary directory and exercise the real translation end to end.
    match = re.match(re.escape(CONTAINER_PREFIX) + r"/([a-z])(?:/|$)", container)
    if match is None:
        return container
    tidy = posixpath.normpath(container)
    rest = tidy[len(CONTAINER_PREFIX) + 2 :].lstrip("/")
    return f"{match.group(1).upper()}:\\" + rest.replace("/", "\\")


def join(root: str, relative: str) -> str:
    """`relative` under host path `root`, in the host's own spelling.

    The relative part may use either separator when the root is Windows —
    the interface sends `/`, the Windows picker sends `\\`. Normalised, so a
    `..` is collapsed here and a caller's containment check sees where the
    path actually lands.
    """
    if is_windows(root):
        return normalise_windows(ntpath.join(root, relative.replace("/", "\\")))
    return posixpath.normpath(posixpath.join(root, relative))


def basename(path: str) -> str:
    """The last component of a host path, in either spelling."""
    if is_windows(path):
        return ntpath.basename(normalise_windows(path))
    return posixpath.basename(path)


def parent(path: str) -> str:
    """The folder holding a host path, in either spelling."""
    if is_windows(path):
        return ntpath.dirname(normalise_windows(path))
    return posixpath.dirname(posixpath.normpath(path)) or "/"
