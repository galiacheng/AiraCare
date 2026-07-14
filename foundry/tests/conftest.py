"""Pytest bootstrap: make both deployables importable from the monorepo.

The foundry package (``airacare_foundry``) and the edge package (``airacare_edge``) live in
sibling directories. Adding both roots to ``sys.path`` lets the tests run straight from a
checkout without installing anything, and lets the parity test compare the Foundry reflex
grader against the edge stub. The edge import is optional — parity tests skip if it's absent.
"""

from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
_FOUNDRY_ROOT = _HERE.parents[1]  # foundry/
_REPO_ROOT = _FOUNDRY_ROOT.parent  # repo root
_EDGE_ROOT = _REPO_ROOT / "edge"  # sibling edge package

for _path in (_FOUNDRY_ROOT, _EDGE_ROOT):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
