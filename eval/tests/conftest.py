"""Puts `askwell` and the repo root on `sys.path` before any test imports.

Duplicated from `eval/_bootstrap.py` rather than importing it: pytest adds
this file's own directory to `sys.path`, not the repository root, since
`eval/tests/` has no `__init__.py` — so `import eval` is not yet possible at
the point conftest.py itself needs to run.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_API_SRC = _REPO_ROOT / "api" / "src"

for _path in (_REPO_ROOT, _API_SRC):
    _str_path = str(_path)
    if _str_path not in sys.path:
        sys.path.insert(0, _str_path)
