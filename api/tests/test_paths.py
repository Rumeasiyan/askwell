"""The host-to-container translation, both ways. `M11-FIX-BE-227`.

Pure, so exhaustive here. Every read of the user's own files goes through
`to_container`, and one wrong case is a folder that reads as empty on Windows
for reasons nobody can see. The Windows installer carries a second copy for
`compose.yaml` (`Get-AskwellRootsTarget`); `deploy/windows/install.test.ps1`
checks it against the same cases as `test_windows_paths_map_under_the_prefix`.
"""

import pytest

from askwell import paths


@pytest.mark.parametrize(
    ("host", "container"),
    [
        ("C:\\Users\\askwell", "/host/c/Users/askwell"),
        ("c:\\Users\\askwell", "/host/c/Users/askwell"),
        ("C:/Users/askwell/", "/host/c/Users/askwell"),
        ("C:\\Users/askwell\\Documents", "/host/c/Users/askwell/Documents"),
        ("C:\\Users\\Anna Privé", "/host/c/Users/Anna Privé"),
        ("C:\\Users\\x\\..\\askwell", "/host/c/Users/askwell"),
        ("D:\\", "/host/d"),
    ],
)
def test_windows_paths_map_under_the_prefix(host: str, container: str) -> None:
    assert paths.to_container(host) == container


@pytest.mark.parametrize(
    "posix", ["/home/anna/clients", "/Users/anna/Documents", "/", "/host/c/Users/anna"]
)
def test_a_posix_path_is_its_own_container_path(posix: str) -> None:
    """Linux and macOS mount the home folder at the same path: identity."""
    assert paths.to_container(posix) == posix


@pytest.mark.parametrize(
    ("container", "host"),
    [
        ("/host/c/Users/askwell", "C:\\Users\\askwell"),
        ("/host/c/Users/askwell/Documents/corpus", "C:\\Users\\askwell\\Documents\\corpus"),
        ("/host/c/Users/Anna Privé/", "C:\\Users\\Anna Privé"),
        ("/host/d", "D:\\"),
    ],
)
def test_container_paths_map_back_to_windows(container: str, host: str) -> None:
    assert paths.to_host(container) == host


@pytest.mark.parametrize("other", ["/home/anna", "/hostile/c/x", "/host/cd/x", "/host"])
def test_a_path_outside_the_prefix_maps_back_to_itself(other: str) -> None:
    assert paths.to_host(other) == other


@pytest.mark.parametrize(
    "host",
    ["C:\\Users\\askwell\\Documents\\corpus", "C:\\Users\\Anna Privé\\notes.txt", "E:\\"],
)
def test_there_and_back_is_the_canonical_spelling(host: str) -> None:
    assert paths.to_host(paths.to_container(host)) == host


def test_the_canonical_spelling_upper_cases_only_the_drive() -> None:
    """Windows compares names case-insensitively, but what is stored is what
    the user is shown — `Documents` stays `Documents`."""
    assert paths.normalise_windows("c:/Users/askwell/Documents/") == "C:\\Users\\askwell\\Documents"


@pytest.mark.parametrize(
    ("path", "windows"),
    [
        ("C:\\Users", True),
        ("z:/", True),
        ("C:", False),  # the current directory on drive C, not a path
        ("C:folder", False),
        ("\\\\server\\share", False),
        ("/home/anna", False),
        ("clients", False),
    ],
)
def test_only_a_drive_with_a_separator_is_a_windows_path(path: str, windows: bool) -> None:
    assert paths.is_windows(path) is windows


def test_a_unc_path_is_recognised() -> None:
    assert paths.is_unc("\\\\server\\share\\x")
    assert not paths.is_unc("C:\\Users")
    assert not paths.is_unc("//also-a-posix-path")


def test_joining_under_a_windows_root_takes_either_separator() -> None:
    root = "C:\\Users\\askwell\\corpus"
    assert paths.join(root, "sub/handbook.pdf") == "C:\\Users\\askwell\\corpus\\sub\\handbook.pdf"
    assert paths.join(root, "sub\\handbook.pdf") == "C:\\Users\\askwell\\corpus\\sub\\handbook.pdf"
    assert paths.join(root, "../other.pdf") == "C:\\Users\\askwell\\other.pdf"


def test_joining_under_a_posix_root_is_unchanged() -> None:
    assert paths.join("/home/anna/corpus", "sub/../a.pdf") == "/home/anna/corpus/a.pdf"


def test_basename_and_parent_read_either_spelling() -> None:
    assert paths.basename("C:\\Users\\askwell\\handbook.pdf") == "handbook.pdf"
    assert paths.parent("C:\\Users\\askwell\\handbook.pdf") == "C:\\Users\\askwell"
    assert paths.parent("C:\\Users") == "C:\\"
    assert paths.basename("/home/anna/handbook.pdf") == "handbook.pdf"
    assert paths.parent("/home/anna/handbook.pdf") == "/home/anna"
