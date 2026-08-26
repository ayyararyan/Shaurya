#!/usr/bin/env python3
"""Repository wrapper for the D51 Step-7 controller."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shaurya.cli.feature_selection_experiment import main

if __name__ == "__main__":
    raise SystemExit(main())
