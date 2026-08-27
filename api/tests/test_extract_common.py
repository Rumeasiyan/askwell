"""The filesystem check every extractor shares. `M1-EXTRACT-VAL-030`.

No database needed: `check_readable` only ever touches the path on `Work`,
never a row.
"""

import uuid
from pathlib import Path

import pytest

from askwell.extract_common import MissingSource, UnreadableSource, check_readable
from askwell.ingest import Work


def _work(path: str, filename: str = "contract.pdf") -> Work:
    return Work(
        document_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        path=path,
        filename=filename,
        mime="application/pdf",
        sha256="0" * 64,
    )


def test_a_file_that_disappeared_is_reported_as_missing_not_corrupt(tmp_path: Path) -> None:
    gone = tmp_path / "gone.pdf"
    with pytest.raises(MissingSource) as excinfo:
        check_readable(_work(str(gone), filename="gone.pdf"))
    assert "gone.pdf" in str(excinfo.value)
    assert str(gone) in str(excinfo.value)


def test_a_present_readable_file_raises_nothing(tmp_path: Path) -> None:
    present = tmp_path / "present.pdf"
    present.write_bytes(b"whatever")
    check_readable(_work(str(present), filename="present.pdf"))


def test_a_file_with_no_read_permission_is_reported_as_unreadable(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked.pdf"
    blocked.write_bytes(b"whatever")
    blocked.chmod(0o000)
    try:
        blocked.open("rb").close()
    except PermissionError:
        pass
    else:
        blocked.chmod(0o644)
        pytest.skip("running as a user unaffected by the file's own permissions (e.g. root)")

    try:
        with pytest.raises(UnreadableSource) as excinfo:
            check_readable(_work(str(blocked), filename="blocked.pdf"))
        assert "blocked.pdf" in str(excinfo.value)
    finally:
        blocked.chmod(0o644)
