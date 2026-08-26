from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from shaurya.analytics import post_close_alpha_research as post_close


def test_daily_parser_accepts_a_trading_date_instead_of_dataset_id() -> None:
    args = post_close.parser().parse_args(
        [
            "--date",
            "2026-08-26",
            "--catalog",
            "/tmp/datasets.jsonl",
            "--output-root",
            "/tmp/results",
        ]
    )
    assert args.dataset_id is None
    assert args.trading_date == date(2026, 8, 26)


def test_standardized_ols_recovers_increment() -> None:
    rng = np.random.default_rng(7)
    control = rng.normal(size=(500, 2))
    incremental = rng.normal(size=(500, 1))
    x = np.column_stack([control, incremental])
    y = control[:, 0] + 2.0 * incremental[:, 0]
    beta, mean, scale = post_close.fit_standardized_ols(x[:350], y[:350])
    prediction = post_close.predict(beta, mean, scale, x[350:])
    assert post_close.r2(y[350:], prediction) > 0.999


def test_book_state_fails_crossed() -> None:
    class Level:
        def __init__(self, price: float, quantity: int) -> None:
            self.price = price
            self.quantity = quantity

    class Row:
        bids = (Level(101.0, 2),)
        asks = (Level(100.0, 2),)
        receive_ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    with pytest.raises(post_close.GateFailure, match="crossed"):
        post_close.book_state(Row())


def test_count_group_rejects_malformed() -> None:
    with pytest.raises(post_close.GateFailure):
        post_close.sum_counts({"standard": -1})


def test_exclusion_flags_cover_requested_quality_conditions() -> None:
    assert {"connection_gap", "reconnected", "partial_book", "crossed_book"}.issubset(
        post_close.EXCLUSION_FLAGS
    )


def test_interval_subtraction_and_minimum_support() -> None:
    assert post_close._subtract_intervals(0, 100, [(10, 20), (15, 30), (80, 90)]) == [
        (0, 10),
        (30, 80),
        (90, 100),
    ]


def test_quality_window_requires_lookback_and_outcome_support() -> None:
    second = 1_000_000_000
    windows = [(1, 0, 100 * second)]
    assert post_close._eligible_for_window(50 * second, 1, windows)
    assert not post_close._eligible_for_window(20 * second, 1, windows)
    assert not post_close._eligible_for_window(50 * second, 2, windows)
