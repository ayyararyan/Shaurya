"""Make the src-layout package importable to the externally installed pytest runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_ROOT not in sys.path:
    sys.path.insert(0, _SOURCE_ROOT)
_EXISTING_PYTHONPATH = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = (
    _SOURCE_ROOT
    if not _EXISTING_PYTHONPATH
    else f"{_SOURCE_ROOT}{os.pathsep}{_EXISTING_PYTHONPATH}"
)
