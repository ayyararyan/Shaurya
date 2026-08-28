from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shaurya.research.parallel_alpha_tournament import (
    evaluate_parallel_candidates,
    holm_passes,
    validate_positions,
)


def _panel() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2026-07-01",
            "2026-07-01",
            "2026-07-02",
            "2026-07-02",
            "2026-08-17",
            "2026-08-17",
            "2026-08-18",
            "2026-08-18",
        ]
    )
    return pd.DataFrame({"date": dates, "forward_return_bps": [2.0] * len(dates)})


def test_holm_is_step_down_and_familywise() -> None:
    assert holm_passes({"a": 0.01, "b": 0.02, "c": 0.20}) == {"a", "b"}


def test_candidate_evaluation_uses_shared_cost_and_splits() -> None:
    panel = _panel()
    position = np.ones(len(panel))
    result = evaluate_parallel_candidates(panel, {"always": position}, {"always": "test"})
    validation = result["registry"]["always"]["results"]["validation"]["cost_1bps"]
    assert validation["mean_daily_bps"] == pytest.approx(3.0)
    assert result["summary"]["candidate_count"] == 1


def test_invalid_position_is_rejected() -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="invalid candidate positions"):
        validate_positions(panel, {"leveraged": np.full(len(panel), 2.0)})
