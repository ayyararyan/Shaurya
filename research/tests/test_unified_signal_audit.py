from __future__ import annotations

import numpy as np

from experiments import unified_signal_audit as audit


def test_valid_surface_ends_excludes_windows_that_cross_a_gap() -> None:
    timestamps = np.arange(100, dtype=np.int64) * audit.SURFACE_STEP_NS
    timestamps[50:] += audit.SURFACE_STEP_NS
    session = audit.SurfaceSession(
        date="2026-08-26",
        timestamps=timestamps,
        values=np.zeros((100, 1)),
        columns=("unused",),
    )
    ends = audit.valid_surface_ends(session, horizon=6, lag=12)
    assert 49 not in ends
    assert 50 not in ends
    assert np.all((ends + 6 < 50) | (ends - 12 >= 50))


def test_rank_correlation_requires_enough_nonconstant_observations() -> None:
    short = np.arange(20, dtype=np.float64)
    correlation, samples = audit.rank_correlation(short, short)
    assert np.isnan(correlation)
    assert samples == 20

    values = np.arange(100, dtype=np.float64)
    correlation, samples = audit.rank_correlation(values, values)
    assert np.isclose(correlation, 1.0)
    assert samples == 100


def test_prepared_ridge_uses_training_statistics_for_missing_values() -> None:
    x = np.column_stack((np.arange(100, dtype=np.float64), np.ones(100)))
    y = 2.0 * x[:, 0]
    model = audit.PreparedRidge(alpha=1.0).fit(x, y)
    first = model.predict(np.asarray([[np.nan, np.nan]]))
    second = model.predict(np.asarray([[np.nan, np.nan]]))
    np.testing.assert_allclose(first, second)
    assert np.all(np.isfinite(first))
