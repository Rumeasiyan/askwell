"""The Windows installer scripts as Windows PowerShell 5.1 will read them.

Every Windows PC runs Windows PowerShell 5.1 by default, and it reads a
`.ps1` without a byte-order mark as Windows-1252, not UTF-8. An em dash in
UTF-8 is `E2 80 94`, and `0x94` in Windows-1252 is a right double quote,
which PowerShell accepts as a string terminator: one em dash inside a string
ends it early and the whole file fails to parse. That is how `0.9.2` failed
on the first real Windows machine, while every test run under PowerShell 7,
which reads UTF-8, passed. Plain ASCII reads the same under either, so that
is the rule.

The second check is the same kind of trap: the setup exe is a 32-bit
program, and the PowerShell a 32-bit program starts cannot see `wsl.exe`.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS = REPO_ROOT / "deploy" / "windows"
SCRIPTS = sorted(WINDOWS.rglob("*.ps1"))
SETUP_NSI = WINDOWS / "setup" / "askwell-setup.nsi"


def test_the_windows_scripts_are_found() -> None:
    names = {p.name for p in SCRIPTS}
    assert {"install.ps1", "lib.ps1", "uninstall.ps1", "setup-bootstrap.ps1"} <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_powershell_script_is_plain_ascii(script: Path) -> None:
    lines = script.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        assert line.isascii(), (
            f"{script.relative_to(REPO_ROOT)}:{number} has non-ASCII text, which "
            f"Windows PowerShell 5.1 misreads and can fail to parse: {line.strip()!r}"
        )


def test_setup_starts_the_64_bit_powershell() -> None:
    code = "\n".join(
        line
        for line in SETUP_NSI.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(";")
    )
    assert r"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" in code
    assert 'nsExec::ExecToLog \'"$1"' in code
