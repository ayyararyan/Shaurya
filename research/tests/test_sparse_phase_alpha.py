from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shaurya.research.sparse_phase_alpha import (
    FEATURES,
    Candidate,
    candidate_positions,
    evaluate_candidate,
    walk_forward_predictions,
)


def _frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2026-07-01 09:15",
                    "2026-07-01 09:30",
                    "2026-07-01 09:45",
                    "2026-07-02 09:15",
                ]
            ),
            "minute": [555, 570, 585, 555],
            "prediction_bps": [3.0, -4.0, 5.0, 2.0],
            "threshold_p10": [1.0, 1.0, 1.0, 1.0],
            "target_5m_bps": [2.0, -3.0, 4.0, -1.0],
        }
    )
    frame["date"] = frame["datetime"].dt.normalize()
    return frame


def test_cooldown_resets_each_session() -> None:
    candidate = Candidate(5, 0.10, 30, "all")
    assert candidate_positions(_frame(), candidate).tolist() == [1.0, 0.0, 1.0, 1.0]


def test_time_bucket_is_applied_before_position() -> None:
    frame = _frame()
    frame.loc[2, "minute"] = 14 * 60
    candidate = Candidate(5, 0.10, 0, "afternoon")
    assert candidate_positions(frame, candidate).tolist() == [0.0, 0.0, 1.0, 0.0]


def test_metric_charges_one_round_trip_per_trade() -> None:
    candidate = Candidate(5, 0.10, 0, "all")
    metric = evaluate_candidate(_frame(), candidate, round_trip_cost_bps=1.0)
    # Day one gross is 9 bps less three costs; day two gross is -1 less one cost.
    assert metric.gross_mean_bps_per_day == pytest.approx(4.0)
    assert metric.net_mean_bps_per_day == pytest.approx(2.0)
    assert metric.trades == 4


def test_position_threshold_is_discovery_supplied() -> None:
    frame = _frame()
    frame["threshold_p10"] = np.asarray([3.1, 4.1, 5.1, 2.1])
    candidate = Candidate(5, 0.10, 0, "all")
    assert not candidate_positions(frame, candidate).any()


def test_walk_forward_training_ends_before_prediction_month() -> None:
    dates = pd.to_datetime(["2025-09-01", "2025-10-01", "2026-06-01", "2026-07-01"])
    panel = pd.DataFrame({"date": dates, "datetime": dates, "target_1m_bps": range(4)})
    for feature in FEATURES:
        panel[feature] = np.arange(4, dtype=float)
    predicted = walk_forward_predictions(
        panel, 1, pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-31")
    )
    assert (predicted["trained_through"] < pd.Timestamp("2026-07-01")).all()
