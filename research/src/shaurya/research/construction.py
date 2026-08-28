"""Registry-driven construction adapters for canonical high-frequency research.

The frozen registries name semantic constructors in :mod:`shaurya.data.high_frequency`, but
those constructors intentionally expose different signatures.  This module is the single
research-side adapter that supplies causal context and keeps constructor-specific argument
plumbing out of the registry and out of the scientific evaluator.

Unsupported context is represented as missing data, never as an alternate formula.  That lets
an automated daily run account a candidate as having insufficient support without silently
changing its semantic identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from shaurya.contracts.tape import TapeRow
from shaurya.data import (
    TimedValue,
    ccz_average,
    convergence,
    future_mid_move_target,
    future_range_target,
    futures_microprice_tilt_ticks,
    inverse_depth_quantity_imbalance,
    ist_clock_bucket,
    l1_total_quantity,
    log_l1_depth,
    microprice_shift,
    midpoint_volatility,
    order_count_imbalance,
    raw_option_markout,
    prior_move_ticks,
    quantity_imbalance,
    reversal_pressure_5s,
    spread_change_target,
    spread_ticks,
    trend_efficiency,
)


@dataclass(frozen=True, slots=True)
class ConstructionResult:
    handled: bool
    value: float | None


def construct_v2_feature(
    feature_id: str,
    *,
    row: TapeRow,
    tick_size: float,
    partition_rows: Sequence[TapeRow],
    midpoint_history: Sequence[TimedValue],
) -> ConstructionResult:
    """Construct v2 features that need only the current book or same-instrument history.

    Cross-instrument parity, option-surface, ATM-IV, relative-state, and post-fill features are
    deliberately not approximated here.  Their exact context belongs in dedicated adapters.
    """

    is_future = ":future:" in row.instrument_id
    is_option = ":option:" in row.instrument_id

    if feature_id == "futures.ccz_ofi_0p5s_m1_average.v1":
        return ConstructionResult(
            True,
            ccz_average(partition_rows, anchor=row.receive_ts, window_seconds=0.5, levels=1)
            if is_future
            else None,
        )
    if feature_id == "futures.order_count_imbalance_cum5.v1":
        return ConstructionResult(True, order_count_imbalance(row, levels=5) if is_future else None)
    if feature_id == "futures.quantity_imbalance_cum1.v1":
        return ConstructionResult(True, quantity_imbalance(row, levels=1) if is_future else None)
    if feature_id == "futures.quantity_imbalance_cum5.v1":
        return ConstructionResult(True, quantity_imbalance(row, levels=5) if is_future else None)
    if feature_id == "futures.microprice_tilt_ticks.v1":
        return ConstructionResult(
            True, futures_microprice_tilt_ticks(row, tick_size=tick_size) if is_future else None
        )
    if feature_id == "futures.prior_mid_move_5s_ticks.v1":
        return ConstructionResult(
            True,
            prior_move_ticks(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=5,
                tick_size=tick_size,
            )
            if is_future
            else None,
        )
    if feature_id == "futures.mid_reversal_pressure_5s.v1":
        prior = (
            prior_move_ticks(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=5,
                tick_size=tick_size,
            )
            if is_future
            else None
        )
        return ConstructionResult(True, reversal_pressure_5s(prior))

    if feature_id == "option.quantity_imbalance_invdepth5.v1":
        return ConstructionResult(
            True, inverse_depth_quantity_imbalance(row, levels=5) if is_option else None
        )
    option_levels = {
        "option.quantity_imbalance_cum1.v1": 1,
        "option.quantity_imbalance_cum2.v1": 2,
        "option.quantity_imbalance_cum3.v1": 3,
        "option.quantity_imbalance_cum5.v1": 5,
    }
    if feature_id in option_levels:
        return ConstructionResult(
            True,
            quantity_imbalance(row, levels=option_levels[feature_id]) if is_option else None,
        )
    if feature_id == "option.order_count_imbalance_cum5.v1":
        return ConstructionResult(True, order_count_imbalance(row, levels=5) if is_option else None)
    if feature_id == "option.microprice_shift_l1.v1":
        return ConstructionResult(True, microprice_shift(row) if is_option else None)

    if feature_id == "liquidity.l1_total_quantity.v1":
        return ConstructionResult(True, l1_total_quantity(row) if is_future else None)
    if feature_id == "liquidity.log_l1_depth.v1":
        return ConstructionResult(True, log_l1_depth(row) if is_future else None)
    if feature_id == "liquidity.spread_ticks.v1":
        value = spread_ticks(row, tick_size=tick_size) if is_future else None
        return ConstructionResult(True, value)
    if feature_id == "risk.midpoint_vol_10s.v2":
        return ConstructionResult(
            True,
            midpoint_volatility(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=10,
            )
            if is_future
            else None,
        )
    if feature_id == "risk.midpoint_vol_30s.v2":
        return ConstructionResult(
            True,
            midpoint_volatility(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=30,
            )
            if is_future
            else None,
        )
    if feature_id == "risk.option_midpoint_vol_10s.v2":
        return ConstructionResult(
            True,
            midpoint_volatility(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=10,
            )
            if is_option
            else None,
        )
    if feature_id == "risk.option_midpoint_vol_30s.v2":
        return ConstructionResult(
            True,
            midpoint_volatility(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
                seconds=30,
            )
            if is_option
            else None,
        )
    if feature_id == "state.trend_efficiency_10s.v1":
        return ConstructionResult(
            True,
            trend_efficiency(
                midpoint_history,
                anchor=row.receive_ts,
                connection_epoch=row.connection_epoch,
            )
            if is_future
            else None,
        )
    if feature_id == "state.ist_clock_bucket.v1":
        bucket = ist_clock_bucket(row.receive_ts)
        encoding = {"open": 0.0, "morning": 1.0, "midday": 2.0, "late": 3.0, "close": 4.0}
        return ConstructionResult(True, None if bucket is None else encoding[bucket.value])

    return ConstructionResult(False, None)



def construct_v2_target(
    constructor: str,
    *,
    anchor: datetime,
    connection_epoch: int,
    horizon_seconds: int,
    tick_size: float | None,
    current_mid: float,
    future_mid: float,
    path_midpoints: Sequence[float] = (),
    parity_pressure_value: float | None = None,
    current_spread_ticks: float | None = None,
    future_spread_ticks: float | None = None,
) -> ConstructionResult:
    """Dispatch v2 endpoint targets through their canonical DAT constructors.

    Targets that require a synchronized cross-instrument state (ATM-IV or beta-hedged option
    markouts) deliberately remain unhandled until that context adapter exists.
    """

    if constructor == "future_mid_move_target":
        if tick_size is None:
            return ConstructionResult(True, None)
        points = (
            TimedValue(anchor, connection_epoch, current_mid),
            TimedValue(
                anchor + timedelta(seconds=horizon_seconds),
                connection_epoch,
                future_mid,
            ),
        )
        target = future_mid_move_target(
            points,
            anchor=anchor,
            connection_epoch=connection_epoch,
            horizon_seconds=horizon_seconds,
            tick_size=tick_size,
        )
        return ConstructionResult(True, target.value)
    if constructor == "future_range_target":
        if tick_size is None or len(path_midpoints) != horizon_seconds + 1:
            return ConstructionResult(True, None)
        points = tuple(
            TimedValue(anchor + timedelta(seconds=offset), connection_epoch, value)
            for offset, value in enumerate(path_midpoints)
        )
        target = future_range_target(
            points,
            anchor=anchor,
            connection_epoch=connection_epoch,
            horizon_seconds=horizon_seconds,
            tick_size=tick_size,
        )
        return ConstructionResult(True, target.value)
    if constructor == "raw_option_markout":
        return ConstructionResult(True, raw_option_markout(current_mid, future_mid))
    if constructor == "spread_change_target":
        return ConstructionResult(
            True,
            spread_change_target(current_spread_ticks, future_spread_ticks),
        )
    if constructor == "convergence":
        if tick_size is None:
            return ConstructionResult(True, None)
        move = (future_mid - current_mid) / tick_size
        return ConstructionResult(True, convergence(parity_pressure_value, move))
    return ConstructionResult(False, None)
