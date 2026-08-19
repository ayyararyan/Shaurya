"""Exploratory eSSVI-surface to five-second futures-mid scan.

Implements the frozen, permanently non-confirmatory design
``X-SURFACE-FUT5-20260819-06``.  The market-data timing is causal (past-only at each
surface anchor); that wording is not an economic-causality claim.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm, rankdata

from shaurya.analytics.surface_feed import SurfaceSnapshot
from shaurya.data.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals.cks_l1_ofi import cks_l1_transition
from shaurya.signals.deep_book_normal_activity import RidgeFit, fit_ridge, fit_ridge_path
from shaurya.signals.deep_book_ofi import price_keyed_ofi_transition

SCAN_ID = "X-SURFACE-FUT5-20260819-06"
CONFIRMATORY_ELIGIBLE = False
DESIGN_DOCUMENT = "docs/SURFACE-FUTURES-PREDICTIVE-SPEC-2026-08-19.md"

FUTURES_INSTRUMENT_ID = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
EXPIRIES = (date(2026, 8, 25), date(2026, 9, 1), date(2026, 9, 29))
TICK_SIZE = 0.05
FIT_INTERVAL_SECONDS = 5.0
DECISION_GAP_SECONDS = 0.5
RESPONSE_SECONDS = 5.0
TARGET_END_SECONDS = DECISION_GAP_SECONDS + RESPONSE_SECONDS
MAX_ASOF_AGE_SECONDS = 6.0
OFI_WINDOWS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
PRIMARY_OFI_WINDOW_SECONDS = 5.0
RIDGE_ALPHAS = (0.0, 0.01, 0.1, 1.0, 10.0, 100.0)
TRAIN_FRACTION = 0.70
EMBARGO_SECONDS = 120.0
HAC_LAG_FRAMES = 2
BOOTSTRAP_MEAN_BLOCK_FRAMES = 6.0
NON_OVERLAP_BLOCK_SECONDS = 10.0
SURFACE_LAG_PLACEBO_SECONDS = 300.0
FRESHNESS_THRESHOLDS_SECONDS = (480.0, 240.0)
NANOSECONDS_PER_SECOND = 1_000_000_000

INVALID_BOOK_FLAGS = frozenset(
    {
        "crossed_book",
        "invalid_depth",
        "partial_book",
        "sequence_gap",
        "connection_gap",
        "heartbeat_timeout",
    }
)

SURFACE_LEVEL_NAMES = ("theta", "rho", "psi", "atm_iv", "atm_skew", "atm_curvature")
TERM_NAMES = ("atm_iv", "atm_skew", "atm_curvature")

QUALITY_NUMERIC_NAMES = (
    "quality__weighted_r_squared",
    "quality__weighted_rmse_total_variance",
    "quality__used_quote_count",
    "quality__surface_age_seconds",
    # The live duration was not persisted in the tape. This fixed missing column prevents a
    # replay machine's wall-clock duration from masquerading as a market predictor.
    "quality__live_fit_duration_seconds",
    "quality__feed_age_seconds",
    "quality__worst_instrument_age_seconds",
    "quality__stale_instrument_count",
    "quality__packets_per_second",
    "quality__reconnect_count",
    "quality__surface_is_stale",
    "quality__is_temporally_smoothed",
    "quality__smoothing_reset",
    "quality__raw_unsmoothed",
    "quality__smoothing_component_count",
    "quality__smoothing_fallback_alpha",
    "quality__arbitrage_passed",
    *tuple(
        f"quality__{expiry.isoformat()}__{suffix}"
        for expiry in EXPIRIES
        for suffix in ("quote_count", "support_width")
    ),
)
QUALITY_CATEGORICAL_NAMES = ("quality__smoothing_status",)


def _expiry_label(expiry: date) -> str:
    return expiry.isoformat().replace("-", "_")


def _window_label(window: float) -> str:
    return str(window).replace(".", "p").rstrip("0").rstrip("p")


def surface_feature(expiry: date, name: str) -> str:
    return f"surface__{_expiry_label(expiry)}__{name}"


def term_feature(earlier: date, later: date, name: str) -> str:
    return f"surface__term_{_expiry_label(later)}_minus_{_expiry_label(earlier)}__{name}"


def ofi_feature(window: float, name: str) -> str:
    return f"ofi__w{_window_label(window)}__{name}"


def essvi_atm_shape(
    *, theta: float, rho: float, psi: float, maturity_years: float
) -> tuple[float, float, float]:
    """ATM IV, local IV slope and local IV curvature for the implemented eSSVI equation."""

    values = (theta, rho, psi, maturity_years)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("eSSVI shape inputs must be finite")
    if theta <= 0.0 or maturity_years <= 0.0 or psi <= 0.0 or not -1.0 < rho < 1.0:
        raise ValueError("eSSVI shape inputs are outside their admissible domain")
    root_t = math.sqrt(maturity_years)
    root_theta = math.sqrt(theta)
    atm = root_theta / root_t
    skew = (rho * psi) / (2.0 * root_t * root_theta)
    curvature = (psi**2 * (1.0 - 2.0 * rho**2)) / (
        4.0 * root_t * theta ** 1.5
    )
    return atm, skew, curvature


def essvi_implied_volatility(
    log_moneyness: float, *, theta: float, rho: float, psi: float, maturity_years: float
) -> float:
    """Direct equation used only for derivative parity tests and diagnostics."""

    core = math.sqrt(
        ((psi * log_moneyness) + (rho * theta)) ** 2
        + theta**2 * (1.0 - rho**2)
    )
    total_variance = 0.5 * (
        theta + (rho * psi * log_moneyness) + core
    )
    return math.sqrt(total_variance / maturity_years)


@dataclass(frozen=True, slots=True)
class FrameDraft:
    sequence: int
    receive_ts_ns: int
    connection_epoch: int
    economic: Mapping[str, float]
    quality_numeric: Mapping[str, float | None]
    quality_categorical: Mapping[str, str]
    surface_age_seconds: float
    smoothing_status: str


@dataclass(frozen=True, slots=True)
class SurfacePredictiveObservation:
    sequence: int
    receive_ts_ns: int
    connection_epoch: int
    economic: Mapping[str, float]
    quality_numeric: Mapping[str, float | None]
    quality_categorical: Mapping[str, str]
    lob: Mapping[str, float]
    ofi: Mapping[str, float]
    y_future_ticks: float
    y_past_ticks: float
    y_same_ticks: float
    target_start_age_seconds: float
    target_end_age_seconds: float
    surface_age_seconds: float
    smoothing_status: str


@dataclass(frozen=True, slots=True)
class ResolvedBook:
    state: BookState
    age_seconds: float


@dataclass(frozen=True, slots=True)
class TargetResolution:
    value_ticks: float
    start_age_seconds: float
    end_age_seconds: float


@dataclass(frozen=True, slots=True)
class ObservationSplit:
    train: tuple[int, ...]
    embargoed: tuple[int, ...]
    test: tuple[int, ...]
    boundary_ts_ns: int
    embargo_end_ts_ns: int


@dataclass(frozen=True, slots=True)
class PreparedDesign:
    names: tuple[str, ...]
    matrix: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class FeaturePreprocessor:
    numeric_names: tuple[str, ...]
    optional_quality_names: tuple[str, ...]
    quality_imputations: Mapping[str, float]
    category_levels: Mapping[str, tuple[str, ...]]

    @property
    def transformed_names(self) -> tuple[str, ...]:
        names: list[str] = list(self.numeric_names)
        for name in self.optional_quality_names:
            names.append(f"{name}__missing")
        if self.optional_quality_names:
            for name in QUALITY_CATEGORICAL_NAMES:
                for level in self.category_levels.get(name, ()):
                    names.append(f"{name}__{level}")
                names.append(f"{name}__other")
        return tuple(names)

    def transform(
        self, observations: Sequence[SurfacePredictiveObservation], positions: Sequence[int]
    ) -> PreparedDesign:
        rows: list[list[float]] = []
        for position in positions:
            observation = observations[position]
            merged: dict[str, float | None] = {
                **observation.economic,
                **observation.lob,
                **observation.ofi,
                **observation.quality_numeric,
            }
            values: list[float] = []
            for name in self.numeric_names:
                value = merged.get(name)
                if name in self.optional_quality_names:
                    values.append(
                        self.quality_imputations[name]
                        if value is None or not math.isfinite(float(value))
                        else float(value)
                    )
                elif value is None or not math.isfinite(float(value)):
                    raise ValueError(f"required common-case feature {name} is missing")
                else:
                    values.append(float(value))
            for name in self.optional_quality_names:
                value = merged.get(name)
                values.append(
                    1.0 if value is None or not math.isfinite(float(value)) else 0.0
                )
            if self.optional_quality_names:
                for name in QUALITY_CATEGORICAL_NAMES:
                    observed = observation.quality_categorical.get(name, "missing")
                    levels = self.category_levels.get(name, ())
                    values.extend(1.0 if observed == level else 0.0 for level in levels)
                    values.append(0.0 if observed in levels else 1.0)
            rows.append(values)
        matrix = np.asarray(rows, dtype=np.float64).reshape(
            len(positions), len(self.transformed_names)
        )
        return PreparedDesign(self.transformed_names, matrix)


@dataclass(frozen=True, slots=True)
class FittedModel:
    label: str
    source: Literal["future", "past", "same"]
    alpha: float
    preprocessor: FeaturePreprocessor
    fit: RidgeFit
    train_positions: tuple[int, ...]
    test_positions: tuple[int, ...]
    train_mean: float
    train_predictions: NDArray[np.float64]
    test_predictions: NDArray[np.float64]
    score: Mapping[str, Any]


class FutureBookSeries:
    """Front-future five-level states with explicit as-of, epoch and right-edge guards."""

    def __init__(self, states: Sequence[BookState]) -> None:
        self.states = tuple(sorted(states, key=lambda state: state.receive_ts_ns))
        self.timestamps = tuple(state.receive_ts_ns for state in self.states)
        self.epoch_end: dict[int, int] = {}
        for state in self.states:
            self.epoch_end[state.connection_epoch] = max(
                self.epoch_end.get(state.connection_epoch, state.receive_ts_ns),
                state.receive_ts_ns,
            )

    @staticmethod
    def usable(state: BookState) -> bool:
        if len(state.bids) < 5 or len(state.asks) < 5:
            return False
        if set(state.quality_flags) & INVALID_BOOK_FLAGS:
            return False
        bid = state.best_bid
        ask = state.best_ask
        return bid is not None and ask is not None and bid < ask

    def as_of(
        self,
        target_ts_ns: int,
        *,
        connection_epoch: int,
        max_age_seconds: float = MAX_ASOF_AGE_SECONDS,
    ) -> ResolvedBook | None:
        position = bisect_right(self.timestamps, target_ts_ns) - 1
        if position < 0:
            return None
        state = self.states[position]
        if state.connection_epoch != connection_epoch or not self.usable(state):
            return None
        age = (target_ts_ns - state.receive_ts_ns) / NANOSECONDS_PER_SECOND
        if age < 0.0 or age > max_age_seconds:
            return None
        return ResolvedBook(state, age)

    def as_of_failure_reason(
        self,
        target_ts_ns: int,
        *,
        connection_epoch: int,
        max_age_seconds: float = MAX_ASOF_AGE_SECONDS,
    ) -> str | None:
        """Return the explicit reason an as-of lookup would fail, or ``None``."""

        position = bisect_right(self.timestamps, target_ts_ns) - 1
        if position < 0:
            return "no_prior_state"
        state = self.states[position]
        if state.connection_epoch != connection_epoch:
            return "epoch_mismatch"
        if not self.usable(state):
            return "unusable_state"
        age = (target_ts_ns - state.receive_ts_ns) / NANOSECONDS_PER_SECOND
        if age < 0.0:
            return "negative_age"
        if age > max_age_seconds:
            return "stale_state"
        return None

    def move_failure_reason(
        self,
        start_ts_ns: int,
        end_ts_ns: int,
        *,
        connection_epoch: int,
    ) -> str | None:
        """Return the guarded move-resolution failure reason, or ``None``."""

        if end_ts_ns <= start_ts_ns:
            return "invalid_geometry"
        if self.epoch_end.get(connection_epoch, -1) < end_ts_ns:
            # If the global series does reach the endpoint, another epoch displaced the
            # requested one; otherwise this is the ordinary tape right edge.
            return (
                "epoch_right_edge"
                if self.timestamps and self.timestamps[-1] >= end_ts_ns
                else "right_edge_uncovered"
            )
        start_reason = self.as_of_failure_reason(
            start_ts_ns, connection_epoch=connection_epoch
        )
        if start_reason is not None:
            return f"start_{start_reason}"
        end_reason = self.as_of_failure_reason(
            end_ts_ns, connection_epoch=connection_epoch
        )
        if end_reason is not None:
            return f"end_{end_reason}"
        return None

    def move(
        self,
        start_ts_ns: int,
        end_ts_ns: int,
        *,
        connection_epoch: int,
    ) -> TargetResolution | None:
        if end_ts_ns <= start_ts_ns:
            return None
        if self.epoch_end.get(connection_epoch, -1) < end_ts_ns:
            return None
        start = self.as_of(start_ts_ns, connection_epoch=connection_epoch)
        end = self.as_of(end_ts_ns, connection_epoch=connection_epoch)
        if start is None or end is None:
            return None
        start_mid = (start.state.bids[0][0] + start.state.asks[0][0]) / 2.0
        end_mid = (end.state.bids[0][0] + end.state.asks[0][0]) / 2.0
        return TargetResolution(
            (end_mid - start_mid) / TICK_SIZE,
            start.age_seconds,
            end.age_seconds,
        )


def _parameter_levels(snapshot: SurfaceSnapshot) -> dict[str, float] | None:
    if snapshot.frame is None:
        return None
    parameters = {item.name: float(item.value) for item in snapshot.frame.parameters}
    diagnostics = snapshot.diagnostics
    support_raw = diagnostics.get("support")
    if not isinstance(support_raw, list):
        return None
    support: dict[date, dict[str, Any]] = {}
    for item in support_raw:
        if not isinstance(item, dict):
            continue
        expiry_raw = item.get("expiry")
        if not isinstance(expiry_raw, str):
            continue
        support[date.fromisoformat(expiry_raw)] = item
    result: dict[str, float] = {}
    for expiry in EXPIRIES:
        row = support.get(expiry)
        if row is None:
            return None
        lower = float(row["min_log_moneyness"])
        upper = float(row["max_log_moneyness"])
        if not lower <= 0.0 <= upper:
            return None
        theta = parameters.get(f"{expiry.isoformat()}.theta")
        rho = parameters.get(f"{expiry.isoformat()}.rho")
        psi = parameters.get(f"{expiry.isoformat()}.psi")
        if theta is None or rho is None or psi is None:
            return None
        maturity = float(row["maturity_years"])
        atm, skew, curvature = essvi_atm_shape(
            theta=theta, rho=rho, psi=psi, maturity_years=maturity
        )
        for name, value in zip(
            SURFACE_LEVEL_NAMES,
            (theta, rho, psi, atm, skew, curvature),
            strict=True,
        ):
            result[surface_feature(expiry, name)] = value
    for earlier, later in zip(EXPIRIES, EXPIRIES[1:], strict=False):
        for name in TERM_NAMES:
            result[term_feature(earlier, later, name)] = (
                result[surface_feature(later, name)]
                - result[surface_feature(earlier, name)]
            )
    return result


def surface_economic_features(
    snapshot: SurfaceSnapshot,
    previous_levels: Mapping[str, float] | None,
    previous_ts_ns: int | None,
) -> tuple[dict[str, float] | None, dict[str, float] | None]:
    """Displayed parameter/shape levels plus one-frame changes and velocities."""

    current = _parameter_levels(snapshot)
    if current is None:
        return None, None
    if previous_levels is None or previous_ts_ns is None:
        return None, current
    stamp = int(round(snapshot.fit_timestamp.timestamp() * NANOSECONDS_PER_SECOND))
    elapsed = (stamp - previous_ts_ns) / NANOSECONDS_PER_SECOND
    if elapsed <= 0.0 or set(current) != set(previous_levels):
        return None, current
    result = dict(current)
    for name, value in sorted(current.items()):
        delta = value - previous_levels[name]
        result[f"{name}__delta_1f"] = delta
        result[f"{name}__velocity_per_second"] = delta / elapsed
    return result, current


def surface_quality_features(
    snapshot: SurfaceSnapshot,
) -> tuple[dict[str, float | None], dict[str, str]]:
    """Fixed-schema quality block; optional diagnostics stay missing, never drop the row."""

    diagnostics = snapshot.diagnostics
    temporal_raw = diagnostics.get("temporal_smoothing")
    temporal = temporal_raw if isinstance(temporal_raw, dict) else {}
    smoothing_status = str(temporal.get("status") or "missing")
    smoothing_raw = diagnostics.get("smoothing")
    smoothing = smoothing_raw if isinstance(smoothing_raw, dict) else {}
    input_raw = diagnostics.get("input")
    input_metrics = input_raw if isinstance(input_raw, dict) else {}
    numeric: dict[str, float | None] = dict.fromkeys(QUALITY_NUMERIC_NAMES)

    def number(value: object) -> float | None:
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        return None

    numeric.update(
        {
            "quality__weighted_r_squared": number(diagnostics.get("weighted_r_squared")),
            "quality__weighted_rmse_total_variance": number(
                diagnostics.get("weighted_rmse_total_variance")
            ),
            "quality__used_quote_count": number(input_metrics.get("used_quote_count")),
            "quality__surface_age_seconds": snapshot.surface_age_seconds,
            "quality__live_fit_duration_seconds": None,
            "quality__feed_age_seconds": snapshot.health.feed_age_seconds,
            "quality__worst_instrument_age_seconds": (
                snapshot.health.worst_instrument_age_seconds
            ),
            "quality__stale_instrument_count": float(snapshot.health.stale_instrument_count),
            "quality__packets_per_second": snapshot.health.packets_per_second,
            "quality__reconnect_count": float(snapshot.health.reconnect_count),
            "quality__surface_is_stale": float(snapshot.surface_is_stale),
            "quality__is_temporally_smoothed": float(
                bool(temporal.get("is_temporally_smoothed"))
            ),
            "quality__smoothing_reset": float(smoothing_status.startswith("reset_then")),
            "quality__raw_unsmoothed": float(smoothing_status.startswith("raw_unsmoothed")),
            "quality__smoothing_component_count": number(
                smoothing.get("component_count")
            ),
            "quality__smoothing_fallback_alpha": number(
                smoothing.get("latest_raw_fallback_alpha")
            ),
            "quality__arbitrage_passed": float(
                bool(snapshot.arbitrage and snapshot.arbitrage.get("passed"))
            ),
        }
    )
    support_raw = diagnostics.get("support")
    if isinstance(support_raw, list):
        for item in support_raw:
            if not isinstance(item, dict) or not isinstance(item.get("expiry"), str):
                continue
            expiry = date.fromisoformat(str(item["expiry"]))
            if expiry not in EXPIRIES:
                continue
            prefix = f"quality__{expiry.isoformat()}"
            lower = number(item.get("min_log_moneyness"))
            upper = number(item.get("max_log_moneyness"))
            numeric[f"{prefix}__quote_count"] = number(item.get("quote_count"))
            numeric[f"{prefix}__support_width"] = (
                upper - lower if lower is not None and upper is not None else None
            )
    return numeric, {"quality__smoothing_status": smoothing_status}


def frame_draft(
    snapshot: SurfaceSnapshot,
    previous_levels: Mapping[str, float] | None,
    previous_ts_ns: int | None,
) -> tuple[FrameDraft | None, dict[str, float] | None]:
    economic, current_levels = surface_economic_features(
        snapshot, previous_levels, previous_ts_ns
    )
    if current_levels is None:
        return None, None
    if economic is None or snapshot.surface_age_seconds is None:
        return None, current_levels
    quality_numeric, quality_categorical = surface_quality_features(snapshot)
    stamp = int(round(snapshot.fit_timestamp.timestamp() * NANOSECONDS_PER_SECOND))
    smoothing_status = quality_categorical["quality__smoothing_status"]
    return (
        FrameDraft(
            sequence=snapshot.sequence,
            receive_ts_ns=stamp,
            connection_epoch=snapshot.health.connection_epoch,
            economic=economic,
            quality_numeric=quality_numeric,
            quality_categorical=quality_categorical,
            surface_age_seconds=snapshot.surface_age_seconds,
            smoothing_status=smoothing_status,
        ),
        current_levels,
    )


def _imbalance(bid: float, ask: float) -> float | None:
    denominator = bid + ask
    return (bid - ask) / denominator if denominator > 0.0 else None


def _quadratic_shape(
    levels: Sequence[tuple[float, int, int]], *, tick_size: float
) -> tuple[float, float] | None:
    if len(levels) < 5:
        return None
    cumulative = 0.0
    x: list[float] = []
    y: list[float] = []
    best = levels[0][0]
    for price, quantity, _ in levels[:5]:
        cumulative += quantity
        x.append(math.log1p(cumulative))
        y.append(abs(price - best) / tick_size)
    design = np.column_stack(
        (np.ones(len(x), dtype=np.float64), np.asarray(x), np.asarray(x) ** 2)
    )
    if np.linalg.matrix_rank(design) < 3:
        return None
    coefficients, *_ = np.linalg.lstsq(design, np.asarray(y), rcond=None)
    return float(coefficients[1]), float(coefficients[2])


def lob_features(state: BookState) -> dict[str, float] | None:
    """Frozen five-level LOB block from one usable front-future Full state."""

    if not FutureBookSeries.usable(state):
        return None
    bids = state.bids[:5]
    asks = state.asks[:5]
    best_bid, best_ask = bids[0][0], asks[0][0]
    bid_l1, ask_l1 = float(bids[0][1]), float(asks[0][1])
    l1_total = bid_l1 + ask_l1
    if l1_total <= 0.0:
        return None
    midpoint = (best_bid + best_ask) / 2.0
    microprice = (best_ask * bid_l1 + best_bid * ask_l1) / l1_total
    result: dict[str, float] = {
        "lob__spread_ticks": (best_ask - best_bid) / TICK_SIZE,
        "lob__microprice_tilt_ticks": (microprice - midpoint) / TICK_SIZE,
    }
    for level, (bid, ask) in enumerate(zip(bids, asks, strict=True), start=1):
        quantity_imbalance = _imbalance(float(bid[1]), float(ask[1]))
        order_imbalance = _imbalance(float(bid[2]), float(ask[2]))
        if quantity_imbalance is None or order_imbalance is None:
            return None
        result[f"lob__quantity_imbalance_l{level}"] = quantity_imbalance
        result[f"lob__order_count_imbalance_l{level}"] = order_imbalance
    for depth in (1, 5):
        bid_quantity = float(sum(level[1] for level in bids[:depth]))
        ask_quantity = float(sum(level[1] for level in asks[:depth]))
        value = _imbalance(bid_quantity, ask_quantity)
        if value is None:
            return None
        result[f"lob__quantity_imbalance_cum{depth}"] = value
    bid_total = float(sum(level[1] for level in bids))
    ask_total = float(sum(level[1] for level in asks))
    bid_orders = float(sum(level[2] for level in bids))
    ask_orders = float(sum(level[2] for level in asks))
    order_imbalance_5 = _imbalance(bid_orders, ask_orders)
    if bid_orders <= 0.0 or ask_orders <= 0.0 or order_imbalance_5 is None:
        return None
    bid_average = bid_total / bid_orders
    ask_average = ask_total / ask_orders
    result.update(
        {
            "lob__bid_total_quantity_5": bid_total,
            "lob__ask_total_quantity_5": ask_total,
            "lob__log1p_bid_total_quantity_5": math.log1p(bid_total),
            "lob__log1p_ask_total_quantity_5": math.log1p(ask_total),
            "lob__order_count_imbalance_cum5": order_imbalance_5,
            "lob__bid_average_order_size_proxy_5": bid_average,
            "lob__ask_average_order_size_proxy_5": ask_average,
            "lob__average_order_size_log_ratio_proxy_5": math.log(
                (1.0 + bid_average) / (1.0 + ask_average)
            ),
        }
    )
    bid_shape = _quadratic_shape(bids, tick_size=TICK_SIZE)
    ask_shape = _quadratic_shape(asks, tick_size=TICK_SIZE)
    if bid_shape is None or ask_shape is None:
        return None
    result.update(
        {
            "lob__bid_slope": bid_shape[0],
            "lob__bid_curvature": bid_shape[1],
            "lob__ask_slope": ask_shape[0],
            "lob__ask_curvature": ask_shape[1],
            "lob__slope_asymmetry_ask_minus_bid": ask_shape[0] - bid_shape[0],
            "lob__curvature_asymmetry_ask_minus_bid": ask_shape[1] - bid_shape[1],
        }
    )
    return result


@dataclass(frozen=True, slots=True)
class OFIPrefix:
    timestamps: tuple[int, ...]
    epochs: tuple[int, ...]
    invalid: tuple[int, ...]
    cks: tuple[float, ...]
    band1: tuple[float, ...]
    band2_5: tuple[float, ...]
    half_l1_depth: tuple[float, ...]
    band1_depth: tuple[float, ...]
    band2_5_depth: tuple[float, ...]
    count: tuple[int, ...]


def _canonical_full_adapter(state: BookState) -> BookState:
    """Present a five-level Full snapshot to canonical OFI functions without changing levels."""

    return replace(state, channel=DEPTH200)


def build_ofi_prefix(states: Sequence[BookState]) -> OFIPrefix:
    """Canonical CKS and price-keyed transitions over the Full packet's embedded five levels."""

    timestamps: list[int] = []
    epochs: list[int] = []
    invalid = [0]
    cks = [0.0]
    band1 = [0.0]
    band2_5 = [0.0]
    half_l1_depth = [0.0]
    band1_depth = [0.0]
    band2_5_depth = [0.0]
    count = [0]
    for previous, current in zip(states, states[1:], strict=False):
        old = _canonical_full_adapter(previous)
        new = _canonical_full_adapter(current)
        cks_transition = cks_l1_transition(old, new)
        price_keyed = price_keyed_ofi_transition(old, new)
        valid = cks_transition.invalid_reason is None and price_keyed.invalid_reason is None
        timestamps.append(current.receive_ts_ns)
        epochs.append(current.connection_epoch)
        invalid.append(invalid[-1] + int(not valid))
        cks.append(cks[-1] + (cks_transition.event if valid else 0.0))
        cumulative_1 = price_keyed.cumulative_by_depth[1] if valid else 0.0
        cumulative_5 = price_keyed.cumulative_by_depth[5] if valid else 0.0
        band1.append(band1[-1] + cumulative_1)
        band2_5.append(band2_5[-1] + cumulative_5 - cumulative_1)
        current_half_l1 = (
            (current.bids[0][1] + current.asks[0][1]) / 2.0
            if valid and current.bids and current.asks
            else 0.0
        )
        current_band1 = (
            float(current.bids[0][1] + current.asks[0][1])
            if valid and current.bids and current.asks
            else 0.0
        )
        current_band2_5 = (
            float(
                sum(item[1] for item in current.bids[1:5])
                + sum(item[1] for item in current.asks[1:5])
            )
            if valid and len(current.bids) >= 5 and len(current.asks) >= 5
            else 0.0
        )
        half_l1_depth.append(half_l1_depth[-1] + current_half_l1)
        band1_depth.append(band1_depth[-1] + current_band1)
        band2_5_depth.append(band2_5_depth[-1] + current_band2_5)
        count.append(count[-1] + int(valid))
    return OFIPrefix(
        tuple(timestamps),
        tuple(epochs),
        tuple(invalid),
        tuple(cks),
        tuple(band1),
        tuple(band2_5),
        tuple(half_l1_depth),
        tuple(band1_depth),
        tuple(band2_5_depth),
        tuple(count),
    )


def trailing_ofi_features(
    prefix: OFIPrefix,
    series: FutureBookSeries,
    *,
    anchor_ts_ns: int,
    connection_epoch: int,
    windows: Sequence[float] = OFI_WINDOWS_SECONDS,
) -> dict[str, float] | None:
    """Frozen OFI windows ending at the surface anchor; all components are past-only."""

    result: dict[str, float] = {}
    for window in windows:
        if window not in OFI_WINDOWS_SECONDS:
            raise ValueError(f"undeclared OFI window {window}")
        start = anchor_ts_ns - int(round(window * NANOSECONDS_PER_SECOND))
        start_state = series.as_of(start, connection_epoch=connection_epoch)
        end_state = series.as_of(anchor_ts_ns, connection_epoch=connection_epoch)
        if start_state is None or end_state is None:
            return None
        left = bisect_right(prefix.timestamps, start)
        right = bisect_right(prefix.timestamps, anchor_ts_ns)
        if left >= right:
            return None
        if prefix.invalid[right] - prefix.invalid[left] != 0:
            return None
        if any(epoch != connection_epoch for epoch in prefix.epochs[left:right]):
            return None
        covered = prefix.count[right] - prefix.count[left]
        if covered <= 0:
            return None
        cks_value = prefix.cks[right] - prefix.cks[left]
        level1 = prefix.band1[right] - prefix.band1[left]
        level2_5 = prefix.band2_5[right] - prefix.band2_5[left]
        mean_half_l1 = (prefix.half_l1_depth[right] - prefix.half_l1_depth[left]) / covered
        mean_band1 = (prefix.band1_depth[right] - prefix.band1_depth[left]) / covered
        mean_band2_5 = (prefix.band2_5_depth[right] - prefix.band2_5_depth[left]) / covered
        result.update(
            {
                ofi_feature(window, "cks_l1_raw"): cks_value,
                ofi_feature(window, "cks_l1_depth_adjusted"): cks_value
                / max(mean_half_l1, 1.0),
                ofi_feature(window, "pk_level1_raw"): level1,
                ofi_feature(window, "pk_levels2_5_raw"): level2_5,
                ofi_feature(window, "pk_level1_depth_adjusted"): level1
                / max(mean_band1, 1.0),
                ofi_feature(window, "pk_levels2_5_depth_adjusted"): level2_5
                / max(mean_band2_5, 1.0),
            }
        )
    return result


def build_predictive_observations(
    drafts: Sequence[FrameDraft], states: Sequence[BookState]
) -> tuple[list[SurfacePredictiveObservation], dict[str, int]]:
    """Join past-only surface/LOB/OFI features to guarded future, mirror and same targets."""

    series = FutureBookSeries(states)
    prefix = build_ofi_prefix(series.states)
    failures = {
        "no_current_future_state": 0,
        "lob_unusable": 0,
        "ofi_incomplete": 0,
        "future_target_uncovered": 0,
        "past_mirror_uncovered": 0,
        "same_window_uncovered": 0,
    }
    observations: list[SurfacePredictiveObservation] = []

    def fail(family: str, reason: str | None) -> None:
        failures[family] += 1
        key = f"{family}__{reason or 'unknown'}"
        failures[key] = failures.get(key, 0) + 1

    for draft in drafts:
        current = series.as_of(
            draft.receive_ts_ns, connection_epoch=draft.connection_epoch
        )
        if current is None:
            fail(
                "no_current_future_state",
                series.as_of_failure_reason(
                    draft.receive_ts_ns, connection_epoch=draft.connection_epoch
                ),
            )
            continue
        lob = lob_features(current.state)
        if lob is None:
            failures["lob_unusable"] += 1
            continue
        # Only the ranked five-second block is required for the primary common sample.
        # The other predeclared windows are emitted opportunistically and get explicit
        # support counts; they never remove a primary row.
        ofi = trailing_ofi_features(
            prefix,
            series,
            anchor_ts_ns=draft.receive_ts_ns,
            connection_epoch=draft.connection_epoch,
            windows=(PRIMARY_OFI_WINDOW_SECONDS,),
        )
        if ofi is None:
            failures["ofi_incomplete"] += 1
            continue
        for window in OFI_WINDOWS_SECONDS:
            if window == PRIMARY_OFI_WINDOW_SECONDS:
                continue
            robustness = trailing_ofi_features(
                prefix,
                series,
                anchor_ts_ns=draft.receive_ts_ns,
                connection_epoch=draft.connection_epoch,
                windows=(window,),
            )
            if robustness is None:
                key = f"ofi_robustness_w{_window_label(window)}_unavailable"
                failures[key] = failures.get(key, 0) + 1
            else:
                ofi.update(robustness)
        future_start = draft.receive_ts_ns + int(
            round(DECISION_GAP_SECONDS * NANOSECONDS_PER_SECOND)
        )
        future_end = draft.receive_ts_ns + int(
            round(TARGET_END_SECONDS * NANOSECONDS_PER_SECOND)
        )
        future = series.move(
            future_start, future_end, connection_epoch=draft.connection_epoch
        )
        if future is None:
            fail(
                "future_target_uncovered",
                series.move_failure_reason(
                    future_start,
                    future_end,
                    connection_epoch=draft.connection_epoch,
                ),
            )
            continue
        past_start = draft.receive_ts_ns - int(
            round(TARGET_END_SECONDS * NANOSECONDS_PER_SECOND)
        )
        past_end = draft.receive_ts_ns - int(
            round(DECISION_GAP_SECONDS * NANOSECONDS_PER_SECOND)
        )
        past = series.move(
            past_start,
            past_end,
            connection_epoch=draft.connection_epoch,
        )
        if past is None:
            fail(
                "past_mirror_uncovered",
                series.move_failure_reason(
                    past_start,
                    past_end,
                    connection_epoch=draft.connection_epoch,
                ),
            )
            continue
        same_start = draft.receive_ts_ns - int(
            round(RESPONSE_SECONDS * NANOSECONDS_PER_SECOND)
        )
        same_end = draft.receive_ts_ns
        same = series.move(
            same_start,
            same_end,
            connection_epoch=draft.connection_epoch,
        )
        if same is None:
            fail(
                "same_window_uncovered",
                series.move_failure_reason(
                    same_start,
                    same_end,
                    connection_epoch=draft.connection_epoch,
                ),
            )
            continue
        observations.append(
            SurfacePredictiveObservation(
                sequence=draft.sequence,
                receive_ts_ns=draft.receive_ts_ns,
                connection_epoch=draft.connection_epoch,
                economic=draft.economic,
                quality_numeric=draft.quality_numeric,
                quality_categorical=draft.quality_categorical,
                lob=lob,
                ofi=ofi,
                y_future_ticks=future.value_ticks,
                y_past_ticks=past.value_ticks,
                y_same_ticks=same.value_ticks,
                target_start_age_seconds=future.start_age_seconds,
                target_end_age_seconds=future.end_age_seconds,
                surface_age_seconds=draft.surface_age_seconds,
                smoothing_status=draft.smoothing_status,
            )
        )
    return observations, failures


def chronological_split(
    observations: Sequence[SurfacePredictiveObservation],
    *,
    train_fraction: float = TRAIN_FRACTION,
    embargo_seconds: float = EMBARGO_SECONDS,
) -> ObservationSplit:
    if len(observations) < 2 or not 0.0 < train_fraction < 1.0:
        raise ValueError("chronological split needs at least two rows and 0<train_fraction<1")
    ordered = sorted(range(len(observations)), key=lambda item: observations[item].receive_ts_ns)
    cut = max(1, int(len(ordered) * train_fraction))
    boundary = observations[ordered[cut - 1]].receive_ts_ns
    embargo_end = boundary + int(round(embargo_seconds * NANOSECONDS_PER_SECOND))
    train: list[int] = []
    embargoed: list[int] = []
    test: list[int] = []
    for position in ordered:
        stamp = observations[position].receive_ts_ns
        if stamp <= boundary:
            train.append(position)
        elif stamp <= embargo_end:
            embargoed.append(position)
        else:
            test.append(position)
    if len(train) < 20 or len(test) < 20:
        raise ValueError("chronological split leaves fewer than 20 train or test observations")
    return ObservationSplit(
        tuple(train), tuple(embargoed), tuple(test), boundary, embargo_end
    )


def _primary_ofi_names(observations: Sequence[SurfacePredictiveObservation]) -> tuple[str, ...]:
    prefix = f"ofi__w{_window_label(PRIMARY_OFI_WINDOW_SECONDS)}__"
    return tuple(sorted(name for name in observations[0].ofi if name.startswith(prefix)))


def model_raw_names(
    label: str, observations: Sequence[SurfacePredictiveObservation]
) -> tuple[str, ...]:
    economic = tuple(sorted(observations[0].economic))
    lob = tuple(sorted(observations[0].lob))
    ofi = _primary_ofi_names(observations)
    quality = tuple(QUALITY_NUMERIC_NAMES)
    mapping = {
        "S": economic,
        "SQ": (*economic, *quality),
        "L": lob,
        "O": ofi,
        "LO": (*lob, *ofi),
        "LOS": (*lob, *ofi, *economic),
        "LOSQ": (*lob, *ofi, *economic, *quality),
    }
    if label not in mapping:
        raise ValueError(f"unknown model label {label}")
    return tuple(mapping[label])


def fit_preprocessor(
    observations: Sequence[SurfacePredictiveObservation],
    positions: Sequence[int],
    *,
    raw_names: Sequence[str],
) -> FeaturePreprocessor:
    optional = tuple(name for name in raw_names if name in QUALITY_NUMERIC_NAMES)
    imputation: dict[str, float] = {}
    for name in optional:
        values = [
            observations[position].quality_numeric.get(name)
            for position in positions
        ]
        finite = sorted(
            float(value)
            for value in values
            if value is not None and math.isfinite(float(value))
        )
        if finite:
            middle = len(finite) // 2
            imputation[name] = (
                finite[middle]
                if len(finite) % 2
                else 0.5 * (finite[middle - 1] + finite[middle])
            )
        else:
            imputation[name] = 0.0
    categories: dict[str, tuple[str, ...]] = {}
    if optional:
        for name in QUALITY_CATEGORICAL_NAMES:
            categories[name] = tuple(
                sorted(
                    {
                        observations[position].quality_categorical.get(name, "missing")
                        for position in positions
                    }
                )
            )
    return FeaturePreprocessor(
        numeric_names=tuple(raw_names),
        optional_quality_names=optional,
        quality_imputations=imputation,
        category_levels=categories,
    )


def target_vector(
    observations: Sequence[SurfacePredictiveObservation],
    positions: Sequence[int],
    source: Literal["future", "past", "same"],
) -> NDArray[np.float64]:
    attribute = {
        "future": "y_future_ticks",
        "past": "y_past_ticks",
        "same": "y_same_ticks",
    }[source]
    return np.asarray(
        [float(getattr(observations[position], attribute)) for position in positions],
        dtype=np.float64,
    )


def _inner_folds(
    observations: Sequence[SurfacePredictiveObservation], positions: Sequence[int]
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    ordered = tuple(sorted(positions, key=lambda item: observations[item].receive_ts_ns))
    n = len(ordered)
    folds: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    embargo_ns = int(round(EMBARGO_SECONDS * NANOSECONDS_PER_SECOND))
    for start_fraction, end_fraction in ((0.55, 0.70), (0.70, 0.85), (0.85, 1.0)):
        start = max(1, int(n * start_fraction))
        end = max(start + 1, int(n * end_fraction))
        validation = ordered[start:min(end, n)]
        if not validation:
            continue
        validation_start = observations[validation[0]].receive_ts_ns
        inner_train = tuple(
            position
            for position in ordered[:start]
            if observations[position].receive_ts_ns <= validation_start - embargo_ns
        )
        if len(inner_train) >= 20 and len(validation) >= 20:
            folds.append((inner_train, validation))
    if len(folds) != 3:
        raise ValueError("training sample cannot support three expanding embargoed inner folds")
    return tuple(folds)


def select_alpha(
    observations: Sequence[SurfacePredictiveObservation],
    positions: Sequence[int],
    *,
    raw_names: Sequence[str],
    source: Literal["future", "past", "same"],
) -> float:
    """Three expanding inner folds; every fold learns imputation/scaling on its train only."""

    losses = dict.fromkeys(RIDGE_ALPHAS, 0.0)
    folds = _inner_folds(observations, positions)
    for inner_train, validation in folds:
        processor = fit_preprocessor(
            observations, inner_train, raw_names=raw_names
        )
        train_design = processor.transform(observations, inner_train)
        validation_design = processor.transform(observations, validation)
        y_train = target_vector(observations, inner_train, source)
        y_validation = target_vector(observations, validation, source)
        fits = fit_ridge_path(
            train_design.matrix,
            y_train,
            feature_names=train_design.names,
            penalties=RIDGE_ALPHAS,
        )
        for alpha, fit in fits.items():
            prediction = fit.predict(validation_design.matrix)
            losses[alpha] += float(np.mean((y_validation - prediction) ** 2))
    return min(RIDGE_ALPHAS, key=lambda alpha: (losses[alpha] / len(folds), alpha))


def _r_squared(
    actual: NDArray[np.float64], predicted: NDArray[np.float64], benchmark: float
) -> float | None:
    denominator = float(np.sum((actual - benchmark) ** 2))
    if denominator <= 0.0:
        return None
    return 1.0 - float(np.sum((actual - predicted) ** 2)) / denominator


def _score_slice(
    actual: NDArray[np.float64], predicted: NDArray[np.float64], train_mean: float
) -> dict[str, float | int | None]:
    residual = actual - predicted
    return {
        "n": len(actual),
        "oos_r2_vs_training_mean": _r_squared(actual, predicted, train_mean),
        "rmse": float(math.sqrt(float(np.mean(residual**2)))) if len(actual) else None,
        "mae": float(np.mean(np.abs(residual))) if len(actual) else None,
        "zero_no_change_rmse": (
            float(math.sqrt(float(np.mean(actual**2)))) if len(actual) else None
        ),
    }


def fit_model(
    observations: Sequence[SurfacePredictiveObservation],
    train_positions: Sequence[int],
    test_positions: Sequence[int],
    *,
    label: str,
    source: Literal["future", "past", "same"],
    raw_names_override: Sequence[str] | None = None,
) -> FittedModel:
    raw_names = tuple(
        raw_names_override
        if raw_names_override is not None
        else model_raw_names(label, observations)
    )
    alpha = select_alpha(
        observations, train_positions, raw_names=raw_names, source=source
    )
    processor = fit_preprocessor(
        observations, train_positions, raw_names=raw_names
    )
    train_design = processor.transform(observations, train_positions)
    test_design = processor.transform(observations, test_positions)
    y_train = target_vector(observations, train_positions, source)
    y_test = target_vector(observations, test_positions, source)
    fit = fit_ridge(
        train_design.matrix,
        y_train,
        feature_names=train_design.names,
        penalty=alpha,
    )
    train_prediction = fit.predict(train_design.matrix)
    test_prediction = fit.predict(test_design.matrix)
    train_mean = float(np.mean(y_train))
    score: dict[str, Any] = {
        **_score_slice(y_test, test_prediction, train_mean),
        "in_sample_r2": _r_squared(y_train, train_prediction, train_mean),
        "alpha": alpha,
        "feature_count_raw": len(raw_names),
        "feature_count_transformed": len(train_design.names),
        "train_n": len(train_positions),
        "test_n": len(test_positions),
        "train_mean_ticks": train_mean,
    }
    midpoint = len(test_positions) // 2
    halves = (tuple(test_positions[:midpoint]), tuple(test_positions[midpoint:]))
    predictions = (test_prediction[:midpoint], test_prediction[midpoint:])
    score["held_out_halves"] = [
        {
            "half": index + 1,
            **_score_slice(
                target_vector(observations, positions, source), prediction, train_mean
            ),
            "start_ts_ns": (
                observations[positions[0]].receive_ts_ns if positions else None
            ),
            "end_ts_ns": (
                observations[positions[-1]].receive_ts_ns if positions else None
            ),
        }
        for index, (positions, prediction) in enumerate(
            zip(halves, predictions, strict=True)
        )
    ]
    return FittedModel(
        label=label,
        source=source,
        alpha=alpha,
        preprocessor=processor,
        fit=fit,
        train_positions=tuple(train_positions),
        test_positions=tuple(test_positions),
        train_mean=train_mean,
        train_predictions=train_prediction,
        test_predictions=test_prediction,
        score=score,
    )


def benchmark_score(
    observations: Sequence[SurfacePredictiveObservation],
    train_positions: Sequence[int],
    test_positions: Sequence[int],
    *,
    source: Literal["future", "past", "same"],
) -> dict[str, Any]:
    y_train = target_vector(observations, train_positions, source)
    y_test = target_vector(observations, test_positions, source)
    mean = float(np.mean(y_train))
    prediction = np.full(len(y_test), mean, dtype=np.float64)
    return {
        "model": "N",
        "source": source,
        "alpha": None,
        "feature_count_raw": 0,
        "feature_count_transformed": 0,
        "train_n": len(train_positions),
        "test_n": len(test_positions),
        "train_mean_ticks": mean,
        **_score_slice(y_test, prediction, mean),
        "in_sample_r2": 0.0,
    }


def fit_model_family(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
    *,
    source: Literal["future", "past", "same"],
    labels: Sequence[str] = ("S", "SQ", "L", "O", "LO", "LOS", "LOSQ"),
    train_positions: Sequence[int] | None = None,
    test_positions: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, FittedModel]]:
    train = tuple(train_positions if train_positions is not None else split.train)
    test = tuple(test_positions if test_positions is not None else split.test)
    rows = [benchmark_score(observations, train, test, source=source)]
    fitted: dict[str, FittedModel] = {}
    for label in labels:
        model = fit_model(observations, train, test, label=label, source=source)
        fitted[label] = model
        rows.append({"model": label, "source": source, **model.score})
    baseline = next(row for row in rows if row["model"] == "N")
    for row in rows:
        row["incremental_oos_r2_over_N"] = (
            None
            if row.get("oos_r2_vs_training_mean") is None
            or baseline.get("oos_r2_vs_training_mean") is None
            else float(row["oos_r2_vs_training_mean"])
            - float(baseline["oos_r2_vs_training_mean"])
        )
    by_label = {str(row["model"]): row for row in rows}
    for enhanced, base in (("SQ", "S"), ("LOS", "LO"), ("LOSQ", "LOS")):
        if enhanced in by_label and base in by_label:
            value = by_label[enhanced].get("oos_r2_vs_training_mean")
            base_value = by_label[base].get("oos_r2_vs_training_mean")
            by_label[enhanced][f"incremental_oos_r2_over_{base}"] = (
                None
                if value is None or base_value is None
                else float(value) - float(base_value)
            )
    return rows, fitted


def _bartlett_long_run_variance(values: NDArray[np.float64], lag: int) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    residual = values - float(np.mean(values))
    total = float(np.dot(residual, residual) / n)
    for offset in range(1, min(lag, n - 1) + 1):
        covariance = float(np.dot(residual[offset:], residual[:-offset]) / n)
        total += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    return max(total, 0.0)


def paired_error_inference(
    observations: Sequence[SurfacePredictiveObservation],
    base: FittedModel,
    enhanced: FittedModel,
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    if base.test_positions != enhanced.test_positions or base.source != enhanced.source:
        raise ValueError("paired inference requires identical held-out rows and target source")
    actual = target_vector(observations, base.test_positions, base.source)
    differential = (actual - base.test_predictions) ** 2 - (
        actual - enhanced.test_predictions
    ) ** 2
    n = len(differential)
    mean = float(np.mean(differential))
    hac_variance = _bartlett_long_run_variance(differential, HAC_LAG_FRAMES)
    hac_se = math.sqrt(hac_variance / n) if n else 0.0
    generator = np.random.default_rng(seed)
    restart = 1.0 / BOOTSTRAP_MEAN_BLOCK_FRAMES
    draws: list[float] = []
    for _ in range(replicates):
        if not n:
            draws.append(0.0)
            continue
        index = int(generator.integers(n))
        sample: list[float] = []
        for position in range(n):
            if position and generator.random() < restart:
                index = int(generator.integers(n))
            elif position:
                index = (index + 1) % n
            sample.append(float(differential[index]))
        draws.append(sum(sample) / len(sample))
    bootstrap_se = float(np.std(np.asarray(draws), ddof=1)) if replicates > 1 else None
    block_ns = int(round(NON_OVERLAP_BLOCK_SECONDS * NANOSECONDS_PER_SECOND))
    origin = observations[base.test_positions[0]].receive_ts_ns if base.test_positions else 0
    buckets: dict[int, list[float]] = {}
    for value, position in zip(differential, base.test_positions, strict=True):
        block = (observations[position].receive_ts_ns - origin) // block_ns
        buckets.setdefault(block, []).append(float(value))
    block_means = np.asarray(
        [sum(values) / len(values) for _, values in sorted(buckets.items())],
        dtype=np.float64,
    )
    block_se = (
        float(np.std(block_means, ddof=1) / math.sqrt(len(block_means)))
        if len(block_means) >= 2
        else None
    )
    return {
        "source": base.source,
        "base_model": base.label,
        "enhanced_model": enhanced.label,
        "n": n,
        "mean_squared_error_improvement": mean,
        "newey_west_lag_frames": HAC_LAG_FRAMES,
        "newey_west_standard_error": hac_se if hac_se > 0.0 else None,
        "newey_west_t": mean / hac_se if hac_se > 0.0 else None,
        "stationary_bootstrap_replicates": replicates,
        "stationary_bootstrap_mean_block_frames": BOOTSTRAP_MEAN_BLOCK_FRAMES,
        "stationary_bootstrap_standard_error": bootstrap_se,
        "stationary_bootstrap_t": (
            mean / bootstrap_se if bootstrap_se is not None and bootstrap_se > 0.0 else None
        ),
        "non_overlapping_block_seconds": NON_OVERLAP_BLOCK_SECONDS,
        "non_overlapping_blocks": len(block_means),
        "non_overlapping_standard_error": block_se,
        "non_overlapping_t": (
            mean / block_se if block_se is not None and block_se > 0.0 else None
        ),
    }


def _correlation_with_hac(
    x: NDArray[np.float64], y: NDArray[np.float64], *, method: Literal["pearson", "spearman"]
) -> tuple[float | None, float | None, float | None]:
    if len(x) < 3 or len(x) != len(y):
        return None, None, None
    if method == "spearman":
        x = np.asarray(rankdata(x), dtype=np.float64)
        y = np.asarray(rankdata(y), dtype=np.float64)
    x_scale = float(np.std(x))
    y_scale = float(np.std(y))
    if x_scale <= 0.0 or y_scale <= 0.0:
        return None, None, None
    x_standard = (x - float(np.mean(x))) / x_scale
    y_standard = (y - float(np.mean(y))) / y_scale
    products = x_standard * y_standard
    correlation = float(np.mean(products))
    variance = _bartlett_long_run_variance(products, HAC_LAG_FRAMES)
    standard_error = math.sqrt(variance / len(products)) if variance > 0.0 else None
    t_value = correlation / standard_error if standard_error is not None else None
    p_value = 2.0 * float(norm.sf(abs(t_value))) if t_value is not None else None
    return correlation, t_value, p_value


def _bh_adjust(rows: list[dict[str, Any]]) -> None:
    eligible = [
        (position, float(row["hac_p_value"]))
        for position, row in enumerate(rows)
        if row.get("hac_p_value") is not None
    ]
    eligible.sort(key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running = 1.0
    total = len(eligible)
    for rank, (position, p_value) in reversed(list(enumerate(eligible, start=1))):
        running = min(running, p_value * total / rank)
        adjusted[position] = running
    for position, row in enumerate(rows):
        row["bh_fdr_q_value"] = adjusted.get(position)
        row["bh_family_size"] = total


def coefficient_diagnostics(
    model: FittedModel,
    observations: Sequence[SurfacePredictiveObservation],
) -> dict[str, dict[str, float]]:
    test_design = model.preprocessor.transform(observations, model.test_positions)
    standardised = (test_design.matrix - model.fit.centre) / model.fit.scale
    result: dict[str, dict[str, float]] = {}
    for index, name in enumerate(model.fit.feature_names):
        coefficient = float(model.fit.coefficients[index])
        result[name] = {
            "standardized_ridge_coefficient": coefficient,
            "mean_absolute_held_out_contribution_ticks": float(
                np.mean(np.abs(standardised[:, index] * coefficient))
            ),
        }
    return result


def correlation_rows(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
    fitted_future: Mapping[str, FittedModel],
) -> list[dict[str, Any]]:
    """Complete surface-feature Pearson/Spearman screen with HAC and BH-FDR."""

    features = tuple(sorted(observations[0].economic))
    contributions = {
        label: coefficient_diagnostics(fitted_future[label], observations)
        for label in ("S", "LOS")
    }
    rows: list[dict[str, Any]] = []
    for source in ("future", "past", "same"):
        scopes = (("full", tuple(range(len(observations)))), ("held_out", split.test))
        for scope, positions in scopes:
            y = target_vector(observations, positions, source)
            for method in ("pearson", "spearman"):
                family: list[dict[str, Any]] = []
                for name in features:
                    x = np.asarray(
                        [observations[position].economic[name] for position in positions],
                        dtype=np.float64,
                    )
                    correlation, t_value, p_value = _correlation_with_hac(
                        x, y, method=method
                    )
                    row: dict[str, Any] = {
                        "source": source,
                        "scope": scope,
                        "method": method,
                        "feature": name,
                        "n": len(positions),
                        "correlation": correlation,
                        "hac_lag_frames": HAC_LAG_FRAMES,
                        "hac_t": t_value,
                        "hac_p_value": p_value,
                    }
                    if source == "future" and scope == "held_out":
                        for label, diagnostic in contributions.items():
                            values = diagnostic.get(name)
                            row[f"{label}_standardized_ridge_coefficient"] = (
                                values["standardized_ridge_coefficient"] if values else None
                            )
                            row[f"{label}_mean_absolute_held_out_contribution_ticks"] = (
                                values["mean_absolute_held_out_contribution_ticks"]
                                if values
                                else None
                            )
                    family.append(row)
                _bh_adjust(family)
                rows.extend(family)
    return rows


def coefficient_rows(models: Mapping[tuple[str, str], FittedModel]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (source, label), model in sorted(models.items()):
        for index, name in enumerate(model.fit.feature_names):
            rows.append(
                {
                    "source": source,
                    "model": label,
                    "feature": name,
                    "alpha": model.alpha,
                    "standardized_coefficient": float(model.fit.coefficients[index]),
                    "training_centre": float(model.fit.centre[index]),
                    "training_scale": float(model.fit.scale[index]),
                }
            )
    return rows


def _filtered_positions(
    observations: Sequence[SurfacePredictiveObservation],
    positions: Sequence[int],
    *,
    maximum_surface_age_seconds: float,
) -> tuple[int, ...]:
    return tuple(
        position
        for position in positions
        if observations[position].surface_age_seconds <= maximum_surface_age_seconds
    )


def freshness_rows(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], FittedModel]]:
    rows: list[dict[str, Any]] = []
    models: dict[tuple[str, str], FittedModel] = {}
    labels = ("S", "SQ", "LO", "LOS", "LOSQ")
    for threshold in FRESHNESS_THRESHOLDS_SECONDS:
        train = _filtered_positions(
            observations, split.train, maximum_surface_age_seconds=threshold
        )
        test = _filtered_positions(
            observations, split.test, maximum_surface_age_seconds=threshold
        )
        if len(train) < 20 or len(test) < 20:
            rows.append(
                {
                    "source": "future",
                    "arm": f"surface_age_le_{int(threshold)}s",
                    "status": "insufficient_support",
                    "train_n": len(train),
                    "test_n": len(test),
                }
            )
            continue
        try:
            family_rows, fitted = fit_model_family(
                observations,
                split,
                source="future",
                labels=labels,
                train_positions=train,
                test_positions=test,
            )
        except ValueError as error:
            rows.append(
                {
                    "source": "future",
                    "arm": f"surface_age_le_{int(threshold)}s",
                    "status": "insufficient_inner_cv_support",
                    "reason": str(error),
                    "train_n": len(train),
                    "test_n": len(test),
                }
            )
            continue
        for row in family_rows:
            rows.append(
                {
                    **row,
                    "arm": f"surface_age_le_{int(threshold)}s",
                    "status": "fitted",
                }
            )
        for label, model in fitted.items():
            models[(f"fresh_{int(threshold)}", label)] = model
    return rows, models


def lagged_surface_source_positions(
    observations: Sequence[SurfacePredictiveObservation],
) -> dict[int, int]:
    """Map each row to the latest same-epoch surface at least 300 seconds earlier."""

    timestamps = tuple(observation.receive_ts_ns for observation in observations)
    lag_ns = int(round(SURFACE_LAG_PLACEBO_SECONDS * NANOSECONDS_PER_SECOND))
    lag_source: dict[int, int] = {}
    for position, observation in enumerate(observations):
        source_position = bisect_right(timestamps, observation.receive_ts_ns - lag_ns) - 1
        if source_position < 0:
            continue
        source = observations[source_position]
        if (
            source.connection_epoch != observation.connection_epoch
            or observation.receive_ts_ns - source.receive_ts_ns < lag_ns
        ):
            continue
        lag_source[position] = source_position
    return lag_source


def lagged_surface_placebo(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
    *,
    replicates: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lag_source = lagged_surface_source_positions(observations)
    placebo_observations = list(observations)
    for position, source_position in lag_source.items():
        placebo_observations[position] = replace(
            observations[position], economic=observations[source_position].economic
        )
    train = tuple(position for position in split.train if position in lag_source)
    test = tuple(position for position in split.test if position in lag_source)
    if len(train) < 20 or len(test) < 20:
        return (
            [
                {
                    "arm": "surface_lag_300s_no_wrap",
                    "status": "insufficient_support",
                    "train_n": len(train),
                    "test_n": len(test),
                }
            ],
            {},
        )
    lo = fit_model(placebo_observations, train, test, label="LO", source="future")
    los = fit_model(placebo_observations, train, test, label="LOS", source="future")
    rows = [
        {
            "arm": "surface_lag_300s_no_wrap",
            "status": "fitted",
            "model": model.label,
            **model.score,
        }
        for model in (lo, los)
    ]
    lo_r2 = lo.score.get("oos_r2_vs_training_mean")
    los_r2 = los.score.get("oos_r2_vs_training_mean")
    rows[1]["incremental_oos_r2_over_LO"] = (
        None if lo_r2 is None or los_r2 is None else float(los_r2) - float(lo_r2)
    )
    inference = paired_error_inference(
        placebo_observations, lo, los, replicates=replicates, seed=seed
    )
    return rows, inference


def _quantiles(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "min": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p95": None,
            "max": None,
        }
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": len(values),
        "min": float(np.min(array)),
        "p25": float(np.quantile(array, 0.25)),
        "p50": float(np.quantile(array, 0.50)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
        "max": float(np.max(array)),
    }


def surface_collinearity_summary(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
) -> list[dict[str, Any]]:
    """Deterministic surface-feature collinearity diagnostics by declared sample scope."""

    names = tuple(sorted(observations[0].economic))
    scopes = (
        ("full", tuple(range(len(observations)))),
        ("training", split.train),
        ("held_out", split.test),
    )
    rows: list[dict[str, Any]] = []
    for scope, positions in scopes:
        matrix = np.asarray(
            [
                [observations[position].economic[name] for name in names]
                for position in positions
            ],
            dtype=np.float64,
        ).reshape(len(positions), len(names))
        scales = np.std(matrix, axis=0)
        active = np.flatnonzero(scales > 0.0)
        zero_variance = [names[index] for index in range(len(names)) if scales[index] <= 0.0]
        standardized = (
            (matrix[:, active] - np.mean(matrix[:, active], axis=0)) / scales[active]
            if len(active)
            else np.empty((len(positions), 0), dtype=np.float64)
        )
        rank = int(np.linalg.matrix_rank(standardized)) if standardized.size else 0
        singular = (
            np.linalg.svd(standardized, compute_uv=False)
            if standardized.size
            else np.asarray([], dtype=np.float64)
        )
        condition: float | None = None
        if len(singular) and rank == standardized.shape[1] and singular[-1] > 0.0:
            condition = float(singular[0] / singular[-1])
        pair_rows: list[dict[str, Any]] = []
        if len(active) >= 2:
            correlations = np.corrcoef(standardized, rowvar=False)
            for left_position, left_index in enumerate(active):
                for right_position in range(left_position + 1, len(active)):
                    right_index = int(active[right_position])
                    correlation = float(correlations[left_position, right_position])
                    pair_rows.append(
                        {
                            "left": names[int(left_index)],
                            "right": names[right_index],
                            "pearson_correlation": correlation,
                            "absolute_correlation": abs(correlation),
                        }
                    )
        pair_rows.sort(
            key=lambda row: (
                -float(row["absolute_correlation"]),
                str(row["left"]),
                str(row["right"]),
            )
        )
        rows.append(
            {
                "scope": scope,
                "n": len(positions),
                "feature_count": len(names),
                "nonconstant_feature_count": len(active),
                "zero_variance_features": zero_variance,
                "standardized_matrix_rank": rank,
                "standardized_condition_number_full_rank_only": condition,
                "pair_count": len(pair_rows),
                "absolute_correlation_ge_0_90": sum(
                    float(row["absolute_correlation"]) >= 0.90 for row in pair_rows
                ),
                "absolute_correlation_ge_0_95": sum(
                    float(row["absolute_correlation"]) >= 0.95 for row in pair_rows
                ),
                "absolute_correlation_ge_0_99": sum(
                    float(row["absolute_correlation"]) >= 0.99 for row in pair_rows
                ),
                "strongest_25_pairs": pair_rows[:25],
            }
        )
    return rows


def build_scan_artifact(
    observations: Sequence[SurfacePredictiveObservation],
    split: ObservationSplit,
    *,
    source_metadata: Mapping[str, Any],
    replay_metadata: Mapping[str, Any],
    replicates: int,
    seed: int,
    code_commit: str | None,
) -> dict[str, Any]:
    """Fit every frozen arm and return deterministic JSON-compatible machine results."""

    if not observations:
        raise ValueError("surface predictive scan has no common observations")
    model_rows: list[dict[str, Any]] = []
    all_models: dict[tuple[str, str], FittedModel] = {}
    by_source: dict[str, dict[str, FittedModel]] = {}
    for source in ("future", "past", "same"):
        rows, models = fit_model_family(observations, split, source=source)
        model_rows.extend(rows)
        by_source[source] = models
        all_models.update({(source, label): model for label, model in models.items()})

    inference_rows: list[dict[str, Any]] = []
    # Preserve every frozen paired comparison.  The first three directly compare the
    # surface-only model with the LOB/OFI alternatives; the final three measure the
    # declared surface and quality increments.  A positive error improvement always
    # favours ``enhanced_model`` over ``base_model``.
    comparisons = (
        ("S", "L"),
        ("S", "O"),
        ("S", "LO"),
        ("LO", "LOS"),
        ("S", "SQ"),
        ("LOS", "LOSQ"),
    )
    for _source, models in by_source.items():
        for base, enhanced in comparisons:
            inference_rows.append(
                paired_error_inference(
                    observations,
                    models[base],
                    models[enhanced],
                    replicates=replicates,
                    seed=seed + len(inference_rows),
                )
            )

    correlations = correlation_rows(observations, split, by_source["future"])
    freshness, freshness_models = freshness_rows(observations, split)
    placebo_rows, placebo_inference = lagged_surface_placebo(
        observations, split, replicates=replicates, seed=seed + 100
    )

    smoothing_counts: dict[str, int] = {}
    for observation in observations:
        smoothing_counts[observation.smoothing_status] = (
            smoothing_counts.get(observation.smoothing_status, 0) + 1
        )
    ofi_window_support = {
        f"w{_window_label(window)}": sum(
            all(
                ofi_feature(window, name) in observation.ofi
                for name in (
                    "cks_l1_raw",
                    "cks_l1_depth_adjusted",
                    "pk_level1_raw",
                    "pk_levels2_5_raw",
                    "pk_level1_depth_adjusted",
                    "pk_levels2_5_depth_adjusted",
                )
            )
            for observation in observations
        )
        for window in OFI_WINDOWS_SECONDS
    }
    all_ofi_names = {
        name for observation in observations for name in observation.ofi
    }
    model_index = {
        (str(row["source"]), str(row["model"])): row
        for row in model_rows
    }
    lo = model_index[("future", "LO")]
    los = model_index[("future", "LOS")]
    s = model_index[("future", "S")]
    sq = model_index[("future", "SQ")]
    losq = model_index[("future", "LOSQ")]

    def difference(enhanced: Mapping[str, Any], base: Mapping[str, Any]) -> float | None:
        left = enhanced.get("oos_r2_vs_training_mean")
        right = base.get("oos_r2_vs_training_mean")
        return None if left is None or right is None else float(left) - float(right)

    return {
        "scan_id": SCAN_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "evidence_boundary": (
            "exploratory predictive comparison on one already-inspected session; not causal, "
            "confirmed, economic, tradeable or a signal"
        ),
        "design_document": DESIGN_DOCUMENT,
        "code_commit": code_commit,
        "seed": seed,
        "bootstrap_replicates": replicates,
        "source": dict(source_metadata),
        "replay": dict(replay_metadata),
        "timing": {
            "fit_interval_seconds": FIT_INTERVAL_SECONDS,
            "decision_gap_seconds": DECISION_GAP_SECONDS,
            "response_seconds": RESPONSE_SECONDS,
            "target": "mid_asof(t+5.5s)-mid_asof(t+0.5s)",
            "past_mirror": "mid_asof(t-0.5s)-mid_asof(t-5.5s)",
            "same_window": "mid_asof(t)-mid_asof(t-5.0s)",
            "maximum_asof_age_seconds": MAX_ASOF_AGE_SECONDS,
        },
        "sample": {
            "common_observations": len(observations),
            "train_n": len(split.train),
            "embargoed_n": len(split.embargoed),
            "test_n": len(split.test),
            "first_ts_ns": observations[0].receive_ts_ns,
            "last_ts_ns": observations[-1].receive_ts_ns,
            "train_boundary_ts_ns": split.boundary_ts_ns,
            "embargo_end_ts_ns": split.embargo_end_ts_ns,
            "target_start_asof_age_seconds": _quantiles(
                [item.target_start_age_seconds for item in observations]
            ),
            "target_end_asof_age_seconds": _quantiles(
                [item.target_end_age_seconds for item in observations]
            ),
            "surface_age_seconds": _quantiles(
                [item.surface_age_seconds for item in observations]
            ),
            "smoothing_status_counts": dict(sorted(smoothing_counts.items())),
            "ofi_window_support": ofi_window_support,
        },
        "feature_counts": {
            "surface_economic": len(observations[0].economic),
            "surface_quality_numeric_fixed_schema": len(QUALITY_NUMERIC_NAMES),
            "surface_quality_categorical_fixed_schema": len(QUALITY_CATEGORICAL_NAMES),
            "lob_five_level": len(observations[0].lob),
            "ofi_primary_five_second": len(_primary_ofi_names(observations)),
            "ofi_all_predeclared_windows_emitted": len(all_ofi_names),
        },
        "surface_collinearity": surface_collinearity_summary(observations, split),
        "headline": {
            "S_oos_r2": s.get("oos_r2_vs_training_mean"),
            "L_oos_r2": model_index[("future", "L")].get("oos_r2_vs_training_mean"),
            "O_oos_r2": model_index[("future", "O")].get("oos_r2_vs_training_mean"),
            "LO_oos_r2": lo.get("oos_r2_vs_training_mean"),
            "LOS_oos_r2": los.get("oos_r2_vs_training_mean"),
            "LOS_minus_LO_oos_r2": difference(los, lo),
            "SQ_minus_S_oos_r2": difference(sq, s),
            "LOSQ_minus_LOS_oos_r2": difference(losq, los),
        },
        "model_scores": model_rows,
        "coefficients": coefficient_rows(all_models),
        "correlations": correlations,
        "paired_inference": inference_rows,
        "freshness": freshness,
        "freshness_models_fitted": sorted(
            f"{arm}:{label}" for arm, label in freshness_models
        ),
        "lag_placebo": placebo_rows,
        "lag_placebo_inference": placebo_inference,
    }


def observation_to_dict(observation: SurfacePredictiveObservation) -> dict[str, Any]:
    return asdict(observation)
