"""The roots registry's rules, checked without a database.

These are the parts that decide whether Askwell reads a file at all, so they
are tested where they can be tested fast and exhaustively: path containment,
what a probe concludes and why, and what each state is called when a source
reports it.

Two things are deliberately *not* tested by changing file permissions. The API
image runs as root, and root bypasses the mode bits — a `chmod 000` test would
pass on a developer's host and assert nothing in the container, which is worse
than no test. The unreadable path is driven by making the syscall fail, which
is what actually happens on an SELinux host.
"""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from askwell import roots
from askwell.config import Settings
from askwell.roots import (
    MountState,
    Root,
    RootRefused,
    RootView,
    SourceState,
)


def a_root(path: str, filesystem: str | None = None) -> Root:
    return Root(
        id=uuid.uuid4(),
        path=path,
        filesystem=filesystem,
        added_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


# --- normalise --------------------------------------------------------------


def test_a_relative_path_is_refused_and_says_why() -> None:
    with pytest.raises(RootRefused) as refusal:
        roots.normalise("clients")
    assert "starting with a slash" in str(refusal.value)


def test_the_whole_disk_is_refused() -> None:
    """The one refusal that is about the product rather than the filesystem.

    Nominating `/` would hand over everything, which is the exact thing
    nominating a folder exists to avoid.
    """
    with pytest.raises(RootRefused) as refusal:
        roots.normalise("/")
    assert "whole disk" in str(refusal.value)


def test_a_path_that_climbs_back_to_the_disk_root_is_refused_too() -> None:
    """`/home/../..` is `/` written so that a prefix check would miss it."""
    with pytest.raises(RootRefused):
        roots.normalise("/home/anna/../../..")


def test_an_empty_path_is_refused() -> None:
    with pytest.raises(RootRefused):
        roots.normalise("   ")


def test_a_path_is_stored_normalised() -> None:
    assert roots.normalise("/home/anna/clients/") == "/home/anna/clients"
    assert roots.normalise("/home/anna/./papers/../clients") == "/home/anna/clients"


def test_symlinks_are_not_resolved_at_registration() -> None:
    """What is stored is what the user nominated.

    It is the same string the native picker returns in M7 and the same one the
    source viewer shows, so resolving here would display a path they never
    typed. Escape is handled in `covering()` instead.
    """
    assert roots.normalise("/home/anna/link") == "/home/anna/link"


# --- containment ------------------------------------------------------------


def test_a_root_contains_itself() -> None:
    assert roots.contains("/home/anna/clients", "/home/anna/clients")


def test_a_root_contains_what_is_under_it() -> None:
    assert roots.contains("/home/anna/clients", "/home/anna/clients/acme/contract.pdf")


def test_a_sibling_that_merely_shares_a_prefix_is_not_contained() -> None:
    """The check that must never become `startswith`.

    `/home/anna/clients-archive` is a different folder the user did not
    nominate, and a string prefix says otherwise.
    """
    assert not roots.contains("/home/anna/clients", "/home/anna/clients-archive/old.pdf")


def test_an_ancestor_is_not_contained_by_its_descendant() -> None:
    assert not roots.contains("/home/anna/clients", "/home/anna")


# --- probe ------------------------------------------------------------------


def test_with_no_window_configured_everything_is_not_mounted(tmp_path: Path) -> None:
    state, reason = roots.probe(str(tmp_path), None)
    assert state is MountState.NOT_MOUNTED
    assert reason is not None
    assert "ASKWELL_ROOTS_MOUNT" in reason


def test_a_folder_outside_the_window_is_not_mounted_and_names_the_fix(tmp_path: Path) -> None:
    window = tmp_path / "window"
    window.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    state, reason = roots.probe(str(outside), window)
    assert state is MountState.NOT_MOUNTED
    assert reason is not None
    assert "podman compose up -d" in reason


def test_a_readable_folder_inside_the_window_is_available(tmp_path: Path) -> None:
    inside = tmp_path / "clients"
    inside.mkdir()
    (inside / "contract.pdf").write_bytes(b"%PDF-")

    assert roots.probe(str(inside), tmp_path) == (MountState.AVAILABLE, None)


def test_an_empty_folder_is_still_available(tmp_path: Path) -> None:
    """Nominating a folder before putting anything in it is ordinary."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert roots.probe(str(empty), tmp_path)[0] is MountState.AVAILABLE


def test_a_folder_that_is_not_there_is_unavailable_not_deleted(tmp_path: Path) -> None:
    """The removable-media case. It must never read as data loss."""
    state, reason = roots.probe(str(tmp_path / "usb"), tmp_path)
    assert state is MountState.UNAVAILABLE
    assert reason is not None
    assert "nothing has been deleted" in reason.lower()


def test_a_file_nominated_as_a_folder_is_unavailable(tmp_path: Path) -> None:
    document = tmp_path / "contract.pdf"
    document.write_bytes(b"%PDF-")
    state, reason = roots.probe(str(document), tmp_path)
    assert state is MountState.UNAVAILABLE
    assert reason == "This is a file, not a folder."


def test_a_folder_the_container_may_not_traverse_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What SELinux refusing a bind mount looks like from in here.

    Driven by making the syscall fail rather than by `chmod`, because the image
    runs as root and root ignores the mode bits.
    """
    forbidden = tmp_path / "clients"
    forbidden.mkdir()

    def refuse(_: str) -> object:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "scandir", refuse)
    state, reason = roots.probe(str(forbidden), tmp_path)
    assert state is MountState.UNREADABLE
    assert reason is not None
    assert "SELinux" in reason


def test_the_window_itself_can_be_nominated(tmp_path: Path) -> None:
    assert roots.probe(str(tmp_path), tmp_path)[0] is MountState.AVAILABLE


# --- filesystem detection ---------------------------------------------------


def _mounts(tmp_path: Path, content: str) -> Path:
    written = tmp_path / "mounts"
    written.write_text(content, encoding="utf-8")
    return written


def test_the_longest_matching_mount_point_wins(tmp_path: Path) -> None:
    """`/` matches everything and is the answer only when nothing else does."""
    content = "/dev/sda1 / ext4 rw 0 0\nserver:/export /home/anna/shared nfs4 rw 0 0\n"
    table = _mounts(tmp_path, content)
    assert roots.detect_filesystem("/home/anna/clients", table) == "ext4"
    assert roots.detect_filesystem("/home/anna/shared/acme", table) == "nfs4"


def test_a_mount_point_with_a_space_is_read_correctly(tmp_path: Path) -> None:
    """/proc/mounts octal-escapes spaces. A share called "Case Files" is normal."""
    table = _mounts(tmp_path, "//nas/cases /mnt/Case\\040Files cifs rw 0 0\n")
    assert roots.detect_filesystem("/mnt/Case Files/acme", table) == "cifs"


def test_an_unreadable_mount_table_gives_unknown_never_local(tmp_path: Path) -> None:
    """Null means "could not be told". Claiming "local" would be unchecked."""
    assert roots.detect_filesystem("/home/anna", tmp_path / "absent") is None


def test_a_network_share_warns_about_speed_and_about_the_viewer() -> None:
    warning = roots.warning_for("nfs4")
    assert warning is not None
    assert "slower" in warning
    assert "connected" in warning


def test_a_local_filesystem_produces_no_warning() -> None:
    assert roots.warning_for("ext4") is None
    assert roots.warning_for(None) is None


def test_a_network_share_is_permitted_rather_than_refused() -> None:
    """Permitted, with a warning. Refusing would exclude a real way of working."""
    assert a_root("/mnt/cases", "cifs").network_share


# --- what a source says when its root is gone -------------------------------


def available(path: str) -> RootView:
    return RootView(root=a_root(path), state=MountState.AVAILABLE, reason=None, warning=None)


def in_state(path: str, state: MountState) -> RootView:
    return RootView(root=a_root(path), state=state, reason="because.", warning=None)


def test_a_source_under_an_available_root_is_readable() -> None:
    state, _ = roots.source_availability(
        "/home/anna/clients/acme", [available("/home/anna/clients")], []
    )
    assert state is SourceState.READABLE


def test_an_unplugged_drive_is_unavailable_and_not_moved_or_deleted() -> None:
    """Three distinct states, and this is the one that must not be the others.

    A whole root being absent is not forty files having been moved. Offering to
    relocate each of them would be forty wrong questions.
    """
    state, reason = roots.source_availability(
        "/media/usb/cases/acme",
        [in_state("/media/usb/cases", MountState.UNAVAILABLE)],
        [],
    )
    assert state is SourceState.ROOT_UNAVAILABLE
    assert "/media/usb/cases" in reason


def test_a_source_under_a_removed_root_says_so_and_says_nothing_was_deleted() -> None:
    state, reason = roots.source_availability(
        "/home/anna/clients/acme", [], [a_root("/home/anna/clients")]
    )
    assert state is SourceState.ROOT_REMOVED
    assert "Nothing was deleted" in reason


def test_re_nominating_a_removed_root_restores_its_sources_silently() -> None:
    """Live roots are consulted first, so an undone removal leaves no trace."""
    gone = a_root("/home/anna/clients")
    state, _ = roots.source_availability(
        "/home/anna/clients/acme", [available("/home/anna/clients")], [gone]
    )
    assert state is SourceState.READABLE


def test_a_path_no_root_covers_is_never_read() -> None:
    state, reason = roots.source_availability("/etc/shadow", [available("/home/anna/clients")], [])
    assert state is SourceState.NO_ROOT
    assert "will not read it" in reason


def test_a_not_mounted_root_is_its_own_state() -> None:
    state, _ = roots.source_availability(
        "/home/anna/clients/acme",
        [in_state("/home/anna/clients", MountState.NOT_MOUNTED)],
        [],
    )
    assert state is SourceState.ROOT_NOT_MOUNTED


# --- the consequence of removing one ----------------------------------------


def test_removal_always_says_nothing_is_deleted() -> None:
    """The word that must survive every edit of that string.

    Someone removing a folder from a list has every reason to fear they are
    deleting their own files, and Askwell never held a copy of them.
    """
    for affected in (0, 1, 12):
        assert "deleted" in roots.consequence("/home/anna/clients", affected)
        assert "not" in roots.consequence("/home/anna/clients", affected)


def test_removal_counts_what_it_costs() -> None:
    assert "1 source " in roots.consequence("/home/anna/clients", 1)
    assert "12 sources " in roots.consequence("/home/anna/clients", 12)


# --- the symlink seam -------------------------------------------------------


def test_a_symlink_out_of_a_root_is_resolved_before_it_is_judged(tmp_path: Path) -> None:
    """A link inside a nominated folder must not stand in for the whole disk.

    `covering()` checks both the literal path and where it leads; this is the
    half that can be tested without a database.
    """
    inside = tmp_path / "clients"
    inside.mkdir()
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("private", encoding="utf-8")
    (inside / "link.txt").symlink_to(secret)

    resolved = roots.literal_and_real(str(inside / "link.txt"))
    assert resolved is not None
    literal, real = resolved
    assert roots.contains(str(inside), literal)
    assert not roots.contains(str(inside), real)


def test_a_relative_candidate_has_no_covering_root(tmp_path: Path) -> None:
    assert roots.literal_and_real("clients/contract.pdf") is None


# --- configuration ----------------------------------------------------------


def test_an_unset_window_is_none_rather_than_a_directory_named_nothing() -> None:
    """Compose always passes the variable, empty when the user has not set it."""
    settings = Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        roots_mount="",  # type: ignore[arg-type]
    )
    assert settings.roots_mount is None


def test_a_relative_window_is_refused() -> None:
    """It names the same directory on both sides, so relative names neither."""
    with pytest.raises(ValueError, match="absolute"):
        Settings(
            database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
            roots_mount="./files",  # type: ignore[arg-type]
        )


# --- a root that is itself a symlink -----------------------------------------


def test_a_symlinked_root_covers_the_files_inside_it(tmp_path: Path) -> None:
    """The shape that broke the primary acceptance criterion.

    `/home/anna/work -> /mnt/big/work` is an ordinary thing for someone with a
    second disk. Comparing a file's resolved path against the root's
    *unresolved* one made such a root register happily and then cover nothing —
    and the refusal offered to nominate the same folder again.
    """
    real = tmp_path / "big" / "work"
    real.mkdir(parents=True)
    (real / "lease.pdf").write_text("x")

    link = tmp_path / "work"
    link.symlink_to(real)

    assert roots.contains(str(link), str(link / "lease.pdf"))
    assert roots.contains(os.path.realpath(str(link)), os.path.realpath(str(link / "lease.pdf")))


def test_a_symlink_inside_a_symlinked_root_still_cannot_escape(tmp_path: Path) -> None:
    """The other half, which the fix must not cost.

    Resolving the root must not turn into resolving everything and trusting the
    result — a link inside a nominated folder still has to be judged against
    where it actually leads.
    """
    real = tmp_path / "big" / "work"
    real.mkdir(parents=True)
    secret = tmp_path / "elsewhere" / "private.pdf"
    secret.parent.mkdir(parents=True)
    secret.write_text("not yours")
    (real / "escape.pdf").symlink_to(secret)

    link = tmp_path / "work"
    link.symlink_to(real)

    escape = str(link / "escape.pdf")
    assert roots.contains(str(link), escape)
    assert not roots.contains(os.path.realpath(str(link)), os.path.realpath(escape))
