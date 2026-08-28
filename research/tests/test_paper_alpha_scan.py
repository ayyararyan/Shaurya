from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shaurya.research.paper_alpha_scan import build_option_diagnostics, quadratic_atm_residual


def test_quadratic_smile_has_zero_atm_residual() -> None:
    offsets = np.asarray([-2, -1, 0, 1, 2], dtype=float)
    values = 100.0 + 3.0 * offsets + 2.0 * offsets**2
    assert quadratic_atm_residual(values) == pytest.approx(0.0, abs=1e-10)


def test_half_hour_target_is_strictly_forward_and_stays_in_session() -> None:
    timestamps = pd.to_datetime(
        ["2026-05-08 09:30", "2026-05-08 10:00", "2026-05-08 10:30", "2026-05-11 09:30"]
    )
    grid = pd.DataFrame({"datetime": timestamps})
    grid["date"] = grid["datetime"].dt.normalize()
    grid["minute"] = grid["datetime"].dt.hour * 60 + grid["datetime"].dt.minute
    for offset in (-2, -1, 0, 1, 2):
        grid[f"straddle_{offset}"] = [100.0, 110.0, 121.0, 200.0]
        grid[f"volume_{offset}"] = 10.0
    result = build_option_diagnostics(grid)
    assert result.loc[0, "atm_forward_30m"] == pytest.approx(np.log(1.1))
    assert result.loc[1, "atm_forward_30m"] == pytest.approx(np.log(1.1))
    assert np.isnan(result.loc[2, "atm_forward_30m"])
    assert np.isnan(result.loc[3, "atm_forward_30m"])
