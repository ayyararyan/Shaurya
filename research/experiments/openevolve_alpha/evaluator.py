from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shaurya.research.openevolve_alpha import evaluate_discovery_program  # noqa: E402


def evaluate(program_path: str) -> dict[str, float]:
    cache = Path(
        os.environ.get(
            "SHAURYA_ALPHA_CACHE",
            ROOT / "scratch" / "openevolve-alpha" / "discovery.npz",
        )
    )
    try:
        return evaluate_discovery_program(Path(program_path), cache)
    except Exception:
        return {
            "combined_score": -1_000_000.0,
            "robust_net_1bps": -1_000_000.0,
            "net_1bps": -1_000_000.0,
            "net_6bps": -1_000_000.0,
            "first_period_net_1bps": -1_000_000.0,
            "second_period_net_1bps": -1_000_000.0,
            "average_round_trips_per_day": 1_000_000.0,
            "complexity": 1_000_000.0,
        }
