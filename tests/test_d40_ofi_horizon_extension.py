"""Acceptance probes for D40's fixed seven-horizon summary contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.d40_ofi_horizon_extension import HORIZONS_SECONDS, _c8_summary


def _artifact(values: tuple[float, ...]) -> dict[str, Any]:
    cells = []
    for horizon, value in zip(HORIZONS_SECONDS, values, strict=True):
        cells.append(
            {
                "reference_price": "displayed_mid",
                "levels": 10,
                "h1_seconds": 10.0,
                "h2_seconds": horizon,
                "status": "estimated",
                "train_n": 100,
                "test_n": 40,
                "common_test_row_hash": str(horizon),
                "competitors": [
                    {
                        "competitor": "C8",
                        "status": "estimated",
                        "absolute_oos_r2": value,
                        "selected_alpha": 1.0,
                    }
                ],
            }
        )
    return {
        "cells": cells,
        "sample_role": "retrospective_partial_session_exploration",
        "source_tape": "fixture.jsonl",
        "tape": {"sha256": "0" * 64},
        "code_commit": "1" * 40,
        "split": {"embargo_seconds": 120.5},
    }


def test_d40_summary_reports_monotonicity_peak_and_first_decline() -> None:
    increasing = _c8_summary(_artifact((0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07)))
    assert increasing["strictly_increasing"] is True
    assert increasing["peak_horizon_seconds"] == 120.0
    assert increasing["first_decline_horizon_seconds"] is None

    turns = _c8_summary(_artifact((0.01, 0.02, 0.03, 0.04, 0.035, 0.03, 0.02)))
    assert turns["strictly_increasing"] is False
    assert turns["peak_horizon_seconds"] == 45.0
    assert turns["first_decline_horizon_seconds"] == 60.0


def test_d40_runner_supports_direct_invocation_from_another_working_directory(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "d40_ofi_horizon_extension.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "D40 displayed-mid OFI horizon extension" in completed.stdout
