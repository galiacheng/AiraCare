"""Pytest bootstrap: make the deterministic care package (and the edge, for parity) importable.

The hosted agent ships as a container, so there is no installed package to import in CI. The
offline suite tests only the pure ``airacare_care`` domain (never ``main.py``, which needs the
cloud-only agent-framework / azure deps). We add two roots to ``sys.path``:

- ``src/airacare-care-orchestrator`` so ``import airacare_care`` resolves the same way it does at
  runtime (``main.py`` runs with that dir as cwd);
- the sibling ``edge`` package so the parity test can compare against the edge's own stub. The edge
  import is optional — parity tests ``importorskip`` when it is absent.
"""

from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
_HOSTED_ROOT = _HERE.parents[1]  # foundry-hosted-agent/
_REPO_ROOT = _HOSTED_ROOT.parent  # repo root
_CARE_ROOT = _HOSTED_ROOT / "src" / "airacare-care-orchestrator"  # holds the airacare_care package
_EDGE_ROOT = _REPO_ROOT / "edge"  # sibling edge package (for parity)

for _path in (_CARE_ROOT, _EDGE_ROOT):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
