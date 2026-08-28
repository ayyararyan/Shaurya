"""Causal regime and jump-filtered intraday alpha candidates.

The functions in this module only construct positions.  They deliberately leave P&L,
transaction costs, walk-forward splits, and multiple-testing correction to the common
tournament evaluator.  All fitted cutoffs use a caller-specified calibration period;
the target return is never read while constructing a position.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]

DEFAULT_CALIBRATION_END = pd.Timestamp("2024-12-31")
TUESDAY_EXPIRY_START = pd.Timestamp("2025-09-01")


@dataclass(frozen=True)
class RegimeCalibration:
    """Cutoffs frozen using calibration rows only."""

    calibration_end: str
    volatility_terciles: Mapping[int, tuple[float, float]]
    absolute_gap_terciles: tuple[float, float]
    trend_strength_tercile: float
    jump_z_threshold: float


def _signed(values: pd.Series) -> FloatArray:
    return np.asarray(np.sign(values.fillna(0.0).to_numpy(float)), dtype=np.float64)


def _finite_quantiles(values: pd.Series, probabilities: tuple[float, ...]) -> tuple[float, ...]:
    finite = values.to_numpy(float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ValueError("calibration data contains no finite observations")
    return tuple(float(value) for value in np.quantile(finite, probabilities))


def _volatility_cutoffs(calibration: pd.DataFrame) -> dict[int, tuple[float, float]]:
    """Fit time-of-day cutoffs so the U-shaped volatility curve is not a regime."""

    result: dict[int, tuple[float, float]] = {}
    for elapsed, group in calibration.groupby("elapsed", sort=True):
        finite = group.loc[np.isfinite(group["rv_30"]), "rv_30"]
        if finite.empty:
            continue
        low, high = _finite_quantiles(finite, (1 / 3, 2 / 3))
        result[int(elapsed)] = (low, high)
    if not result:
        raise ValueError("calibration data contains no finite volatility observations")
    return result


def fit_regime_calibration(
    panel: pd.DataFrame,
    calibration_end: pd.Timestamp = DEFAULT_CALIBRATION_END,
    *,
    jump_z_threshold: float = 4.0,
) -> RegimeCalibration:
    """Fit fixed regime thresholds without observing post-calibration rows."""

    required = {"date", "elapsed", "rv_30", "ret_60", "overnight_gap"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"panel is missing columns: {sorted(missing)}")
    calibration = panel[panel["date"] <= calibration_end]
    if calibration.empty:
        raise ValueError("no rows occur on or before calibration_end")
    gap_terciles = _finite_quantiles(calibration["overnight_gap"].abs(), (1 / 3, 2 / 3))
    (trend_cutoff,) = _finite_quantiles(calibration["ret_60"].abs(), (2 / 3,))
    return RegimeCalibration(
        calibration_end=calibration_end.isoformat(),
        volatility_terciles=_volatility_cutoffs(calibration),
        absolute_gap_terciles=(gap_terciles[0], gap_terciles[1]),
        trend_strength_tercile=trend_cutoff,
        jump_z_threshold=float(jump_z_threshold),
    )


def expiry_day_mask(dates: pd.Series) -> npt.NDArray[np.bool_]:
    """Return the historical NIFTY weekly-expiry weekday regime.

    The rule intentionally identifies the scheduled weekday, not exchange-holiday
    adjustments.  It is known from the date before the session begins.
    """

    normalized = pd.to_datetime(dates).dt.normalize()
    weekday = normalized.dt.dayofweek
    return np.asarray(
        np.where(normalized < TUESDAY_EXPIRY_START, weekday == 3, weekday == 1),
        dtype=bool,
    )


def _map_volatility_cutoffs(
    panel: pd.DataFrame, calibration: RegimeCalibration
) -> tuple[FloatArray, FloatArray]:
    fallback_low = float(
        np.median([value[0] for value in calibration.volatility_terciles.values()])
    )
    fallback_high = float(
        np.median([value[1] for value in calibration.volatility_terciles.values()])
    )
    low = panel["elapsed"].map(
        {key: value[0] for key, value in calibration.volatility_terciles.items()}
    )
    high = panel["elapsed"].map(
        {key: value[1] for key, value in calibration.volatility_terciles.items()}
    )
    return low.fillna(fallback_low).to_numpy(float), high.fillna(fallback_high).to_numpy(float)


def jump_diagnostics(panel: pd.DataFrame, *, jump_z_threshold: float = 4.0) -> pd.DataFrame:
    """Classify the latest completed one-minute return as jump-like.

    ``rv_30`` includes ``ret_1``.  Subtracting its square gives a causal scale from
    the preceding observations and avoids allowing the shock to inflate its own
    threshold.  The continuous signal is the 15-minute return with a detected latest
    shock removed; it is not a full high-frequency jump decomposition.
    """

    variance_before_latest = np.maximum(
        panel["rv_30"].to_numpy(float) ** 2 - panel["ret_1"].fillna(0.0).to_numpy(float) ** 2,
        0.0,
    )
    prior_sigma = np.sqrt(variance_before_latest / 29.0)
    ret_1 = panel["ret_1"].fillna(0.0).to_numpy(float)
    valid_scale = np.isfinite(prior_sigma) & (prior_sigma > 0)
    jump = valid_scale & (np.abs(ret_1) > jump_z_threshold * prior_sigma)
    jump_return = np.where(jump, ret_1, 0.0)
    continuous_15 = panel["ret_15"].fillna(0.0).to_numpy(float) - jump_return
    return pd.DataFrame(
        {
            "prior_sigma_1m": prior_sigma,
            "latest_jump": jump,
            "latest_jump_return": jump_return,
            "continuous_return_15m": continuous_15,
        },
        index=panel.index,
    )


def regime_jump_positions(
    panel: pd.DataFrame,
    calibration: RegimeCalibration | None = None,
    *,
    calibration_end: pd.Timestamp = DEFAULT_CALIBRATION_END,
) -> tuple[dict[str, FloatArray], RegimeCalibration]:
    """Create a fixed family of causal positions for common evaluation.

    Each nonzero position is in ``{-1, +1}``; zero means no participation.  Signals
    use information through the decision timestamp and target the panel's next return.
    """

    required = {
        "date",
        "elapsed",
        "ret_1",
        "ret_15",
        "ret_60",
        "rv_30",
        "overnight_gap",
    }
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"panel is missing columns: {sorted(missing)}")
    fitted = calibration or fit_regime_calibration(panel, calibration_end)

    momentum = _signed(panel["ret_15"])
    reversal = -momentum
    rv = panel["rv_30"].to_numpy(float)
    vol_low_cutoff, vol_high_cutoff = _map_volatility_cutoffs(panel, fitted)
    low_vol = np.isfinite(rv) & (rv <= vol_low_cutoff)
    mid_vol = np.isfinite(rv) & (rv > vol_low_cutoff) & (rv <= vol_high_cutoff)
    high_vol = np.isfinite(rv) & (rv > vol_high_cutoff)

    trend_strength = panel["ret_60"].abs().to_numpy(float)
    trend = trend_strength >= fitted.trend_strength_tercile
    range_regime = trend_strength < fitted.trend_strength_tercile

    absolute_gap = panel["overnight_gap"].abs().to_numpy(float)
    small_gap = absolute_gap <= fitted.absolute_gap_terciles[0]
    large_gap = absolute_gap > fitted.absolute_gap_terciles[1]
    first_hour = panel["elapsed"].to_numpy(float) <= 60.0
    gap_direction = _signed(panel["overnight_gap"])

    expiry = expiry_day_mask(panel["date"])
    jumps = jump_diagnostics(panel, jump_z_threshold=fitted.jump_z_threshold)
    latest_jump = jumps["latest_jump"].to_numpy(bool)
    jump_direction = _signed(jumps["latest_jump_return"])
    continuous_direction = _signed(jumps["continuous_return_15m"])

    positions = {
        "low_vol_momentum_15m": np.where(low_vol, momentum, 0.0),
        "low_vol_reversal_15m": np.where(low_vol, reversal, 0.0),
        "mid_vol_momentum_15m": np.where(mid_vol, momentum, 0.0),
        "mid_vol_reversal_15m": np.where(mid_vol, reversal, 0.0),
        "high_vol_momentum_15m": np.where(high_vol, momentum, 0.0),
        "high_vol_reversal_15m": np.where(high_vol, reversal, 0.0),
        "trend_regime_momentum_15m": np.where(trend, momentum, 0.0),
        "trend_regime_reversal_15m": np.where(trend, reversal, 0.0),
        "range_regime_momentum_15m": np.where(range_regime, momentum, 0.0),
        "range_regime_reversal_15m": np.where(range_regime, reversal, 0.0),
        "small_gap_fade_first_hour": np.where(small_gap & first_hour, -gap_direction, 0.0),
        "large_gap_continuation_first_hour": np.where(large_gap & first_hour, gap_direction, 0.0),
        "large_gap_fade_first_hour": np.where(large_gap & first_hour, -gap_direction, 0.0),
        "expiry_momentum_15m": np.where(expiry, momentum, 0.0),
        "expiry_reversal_15m": np.where(expiry, reversal, 0.0),
        "post_jump_continuation": np.where(latest_jump, jump_direction, 0.0),
        "post_jump_reversal": np.where(latest_jump, -jump_direction, 0.0),
        "jump_filtered_momentum_15m": np.where(~latest_jump, continuous_direction, 0.0),
        "jump_filtered_reversal_15m": np.where(~latest_jump, -continuous_direction, 0.0),
    }
    return {name: np.asarray(value, dtype=float) for name, value in positions.items()}, fitted
