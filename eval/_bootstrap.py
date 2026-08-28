"""Puts `askwell` and this repository's root on `sys.path`.

`eval/` is a top-level directory, a sibling of `api/`, not something installed
into the API image (`docs/build-plan.md` repository layout). Every entry point
under `eval/` imports this module first, before importing `askwell` or
anything else in this package, so the harness runs the same way whether it is
invoked as `python eval/bench.py` from the repository root or as
`pytest eval/tests` from anywhere.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_SRC = _REPO_ROOT / "api" / "src"

for _path in (_REPO_ROOT, _API_SRC):
    _str_path = str(_path)
    if _str_path not in sys.path:
        sys.path.insert(0, _str_path)
