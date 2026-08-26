"""Read-only surface-relative executable option-mispricing monitor.

The displayed ANL-03 eSSVI surface is fitted to market midpoints.  Its in-sample residual is
therefore not an independent fair-value test.  This module builds a second, research-only
reference surface with the target strike held out, prices the target from that surface, and
tracks only executable dislocations that clear uncertainty, costs, multiplicity, liquidity,
and persistence gates.

Nothing in this module imports an execution or broker-order path.  "Mispricing" below always
means *confirmed surface-relative executable mispricing*, not an observed latent true value.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from statistics import median

import numpy as np
from numpy.typing import NDArray
from shaurya.contracts.tape import QualityFlag, TapeRow
from shaurya.contracts.timing import IST, nse_equity_derivatives_close

from shaurya.surfaces.base import EvaluationStatus, SurfaceFitRequest
from shaurya.surfaces.essvi import (
    ESSVISurface,
    SurfaceCalibrationError,
    black76_price,
    implied_volatility,
)
from shaurya.surfaces.state import ESSVITemporalSmoother

SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
FEE_SCHEDULE_VERSION = "india-index-options-2026-08-13"


class MispricingDirection(StrEnum):
    CHEAP = "cheap"
    RICH = "rich"


class EpisodeStatus(StrEnum):
    ACTIVE = "active"
    CORRECTED = "corrected"
    INVALIDATED = "invalidated"
    CENSORED = "censored"


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    """Contract metadata that is not present in a CON-01 tape row."""

    tick_size: float
    lot_size: int | None
    source: str

    def __post_init__(self) -> None:
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.lot_size is not None and self.lot_size <= 0:
            raise ValueError("lot_size must be positive when supplied")


@dataclass(frozen=True, slots=True)
class MispricingPolicy:
    """Approved ANL-07 detector policy.

    Fee defaults are the option-premium turnover rates independently verified in Market
    Making on 2026-08-13.  They are surfaced in every payload and remain CLI-overridable.
    The two-tick non-statutory floor represents one tick of expected exit slippage and one
    tick of hedge slippage; it is deliberately visible rather than hidden in a threshold.
    """

    enabled: bool = True
    cross_fit_folds: int = 5
    quote_max_age_seconds: float = 3.0
    fit_max_age_seconds: float = 10.0
    residual_quantile: float = 0.99
    min_residual_history: int = 100
    residual_history_limit: int = 20_000
    residual_neighbor_count: int = 500
    residual_moneyness_bandwidth: float = 0.02
    residual_log_spread_bandwidth: float = 1.0
    fdr_level: float = 0.01
    confirmation_frames: int = 2
    correction_frames: int = 2
    reference_smoothing_half_life_seconds: float = 120.0
    reference_smoothing_max_history: int = 24
    reference_smoothing_min_frames: int = 6
    reference_smoothing_max_gap_seconds: float = 15.0
    reference_max_raw_smoothed_iv_gap_points: float = 0.50
    default_tick_size: float = 0.05
    default_lot_size: int | None = None
    buy_turnover_rate: float = 0.0004504340
    sell_turnover_rate: float = 0.0019204340
    exit_slippage_ticks: float = 1.0
    hedge_slippage_ticks: float = 1.0
    recent_episode_limit: int = 100

    def __post_init__(self) -> None:
        if self.cross_fit_folds < 2:
            raise ValueError("cross_fit_folds must be at least two")
        if self.quote_max_age_seconds <= 0 or self.fit_max_age_seconds <= 0:
            raise ValueError("quote and fit age thresholds must be positive")
        if not 0.5 < self.residual_quantile < 1.0:
            raise ValueError("residual_quantile must lie in (0.5, 1)")
        if self.min_residual_history < 1 or self.residual_history_limit < 1:
            raise ValueError("residual history bounds must be positive")
        if self.residual_history_limit < self.min_residual_history:
            raise ValueError("residual_history_limit cannot be below its minimum")
        if not self.min_residual_history <= self.residual_neighbor_count:
            raise ValueError("residual_neighbor_count cannot be below its minimum")
        if self.residual_neighbor_count > self.residual_history_limit:
            raise ValueError("residual_neighbor_count cannot exceed retained history")
        if (
            min(
                self.residual_moneyness_bandwidth,
                self.residual_log_spread_bandwidth,
            )
            <= 0
        ):
            raise ValueError("continuous residual bandwidths must be positive")
        if not 0 < self.fdr_level <= 1:
            raise ValueError("fdr_level must lie in (0, 1]")
        if self.confirmation_frames < 1 or self.correction_frames < 1:
            raise ValueError("episode frame counts must be positive")
        if self.reference_smoothing_half_life_seconds <= 0:
            raise ValueError("reference smoothing half-life must be positive")
        if self.reference_smoothing_max_history < 2:
            raise ValueError("reference smoothing history must retain at least two fits")
        if not 2 <= self.reference_smoothing_min_frames <= self.reference_smoothing_max_history:
            raise ValueError("reference smoothing minimum must fit inside retained history")
        if self.reference_smoothing_max_gap_seconds <= 0:
            raise ValueError("reference smoothing maximum gap must be positive")
        if self.reference_max_raw_smoothed_iv_gap_points <= 0:
            raise ValueError("reference IV agreement limit must be positive")
        if self.default_tick_size <= 0:
            raise ValueError("default_tick_size must be positive")
        if self.default_lot_size is not None and self.default_lot_size <= 0:
            raise ValueError("default_lot_size must be positive when supplied")
        if min(self.buy_turnover_rate, self.sell_turnover_rate) < 0:
            raise ValueError("turnover rates cannot be negative")
        if min(self.exit_slippage_ticks, self.hedge_slippage_ticks) < 0:
            raise ValueError("slippage ticks cannot be negative")
        if self.recent_episode_limit < 1:
            raise ValueError("recent_episode_limit must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "definition": "confirmed_surface_relative_executable_iv_mispricing",
            "cross_fit_folds": self.cross_fit_folds,
            "quote_max_age_seconds": self.quote_max_age_seconds,
            "fit_max_age_seconds": self.fit_max_age_seconds,
            "residual_quantile": self.residual_quantile,
            "min_residual_history": self.min_residual_history,
            "residual_uncertainty_method": "past_only_gaussian_weighted_knn_iv",
            "residual_neighbor_count": self.residual_neighbor_count,
            "residual_moneyness_bandwidth": self.residual_moneyness_bandwidth,
            "residual_log_spread_bandwidth": self.residual_log_spread_bandwidth,
            "fdr_level": self.fdr_level,
            "confirmation_frames": self.confirmation_frames,
            "correction_frames": self.correction_frames,
            "reference_smoothing_method": "causal_time_decayed_essvi_parameters",
            "reference_smoothing_half_life_seconds": (self.reference_smoothing_half_life_seconds),
            "reference_smoothing_max_history": self.reference_smoothing_max_history,
            "reference_smoothing_min_frames": self.reference_smoothing_min_frames,
            "reference_smoothing_max_gap_seconds": (self.reference_smoothing_max_gap_seconds),
            "reference_stability_window_enabled": False,
            "reference_max_raw_smoothed_iv_gap_points": (
                self.reference_max_raw_smoothed_iv_gap_points
            ),
            "reference_rewarm_after_invalidation": False,
            "default_tick_size": self.default_tick_size,
            "default_lot_size": self.default_lot_size,
            "fee_schedule_version": FEE_SCHEDULE_VERSION,
            "buy_turnover_rate": self.buy_turnover_rate,
            "sell_turnover_rate": self.sell_turnover_rate,
            "exit_slippage_ticks": self.exit_slippage_ticks,
            "hedge_slippage_ticks": self.hedge_slippage_ticks,
            "order_authority": "none_read_only_research_monitor",
        }


@dataclass(frozen=True, slots=True)
class _OptionKey:
    expiry: date
    strike: float
    is_call: bool

    @property
    def option_type(self) -> str:
        return "CE" if self.is_call else "PE"

    @property
    def strike_pair(self) -> tuple[date, float]:
        return self.expiry, self.strike


@dataclass(frozen=True, slots=True)
class _ForwardBand:
    expiry: date
    centre: float
    lower: float
    upper: float
    method: str
    source_count: int


@dataclass(frozen=True, slots=True)
class _IVResidualSample:
    """One causal held-out IV residual with continuous conditioning coordinates."""

    log_moneyness: float
    log_relative_spread: float
    residual_points: float


@dataclass(frozen=True, slots=True)
class MispricingObservation:
    instrument_id: str
    expiry: str
    strike: float
    option_type: str
    direction: MispricingDirection | None
    observed_bid: float
    observed_ask: float
    observed_mid: float
    observed_mid_iv: float | None
    observed_bid_iv: float
    observed_ask_iv: float
    executable_iv: float | None
    quote_age_seconds: float
    displayed_quantity: int | None
    lot_size: int | None
    tick_size: float
    metadata_source: str
    forward: float
    forward_method: str
    log_moneyness: float
    log_relative_spread: float
    fair_iv: float
    fair_iv_lower: float
    fair_iv_upper: float
    raw_fair_iv: float
    raw_smoothed_iv_gap_points: float
    exact_fair_iv: float | None
    exact_smoothed_iv_gap_points: float | None
    reference_smoothing_components: int
    reference_eligible: bool
    reference_eligibility_reason: str | None
    fair_price: float
    fair_lower: float
    fair_upper: float
    model_uncertainty: float
    forward_uncertainty: float
    asynchrony_uncertainty: float
    total_uncertainty: float
    tick_uncertainty_iv_points: float
    model_uncertainty_iv_points: float
    forward_uncertainty_iv_points: float
    asynchrony_uncertainty_iv_points: float
    total_uncertainty_iv_points: float
    gross_iv_edge_points: float
    target_correction_required_iv_points: float
    gross_edge: float
    gross_edge_ticks: float
    estimated_cost_per_unit: float
    net_edge: float
    net_edge_ticks: float
    net_edge_per_lot: float | None
    iv_residual_points: float | None
    empirical_p_value: float | None
    fdr_significant: bool
    exact_leave_strike_confirmed: bool
    residual_history_count: int
    residual_effective_sample_size: float
    residual_bucket: str
    fair_delta: float

    def to_dict(self) -> dict[str, object]:
        value = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in {"direction"}
        }
        value["direction"] = self.direction.value if self.direction else None
        return value


@dataclass(slots=True)
class _PendingEpisode:
    direction: MispricingDirection
    first_seen_at: datetime
    count: int
    observation: MispricingObservation


@dataclass(slots=True)
class _ActiveEpisode:
    episode_id: str
    direction: MispricingDirection
    first_seen_at: datetime
    confirmed_at: datetime
    initial: MispricingObservation
    latest: MispricingObservation
    peak_gross_edge: float
    peak_net_edge: float
    correction_count: int = 0
    target_correction_count: int = 0


@dataclass(frozen=True, slots=True)
class _SmoothedReference:
    raw_surface: ESSVISurface
    surface: ESSVISurface
    bands: dict[date, _ForwardBand]
    component_count: int
    status: str


@dataclass(frozen=True, slots=True)
class GapCloseTrace:
    """Signed IV-state accounting plus a separate rupee execution overlay.

    Both IV legs are market-derived. ``target_iv_contribution_points`` is the executable-IV
    movement of the classified contract; ``reference_iv_contribution_points`` is movement of
    the strike-held-out fair-IV boundary. Positive values close the IV gap. Legacy-named rupee
    fields retain endpoint price accounting only and never determine correction.
    """

    entry_executable_price: float
    close_executable_price: float
    entry_reference_boundary: float
    close_reference_boundary: float
    entry_gap: float
    close_gap: float
    gap_closed: float
    target_option_contribution: float
    reference_market_contribution: float
    entry_gap_ticks: float
    close_gap_ticks: float
    gap_closed_ticks: float
    target_option_contribution_ticks: float
    reference_market_contribution_ticks: float
    target_option_share: float | None
    reference_market_share: float | None
    target_correction_required: float
    target_correction_required_ticks: float
    target_correction_achieved: bool
    attribution: str
    closure_gate: str | None
    identity_error: float
    entry_executable_iv: float
    close_executable_iv: float
    entry_reference_iv_boundary: float
    close_reference_iv_boundary: float
    entry_iv_gap_points: float
    close_iv_gap_points: float
    iv_gap_closed_points: float
    target_iv_contribution_points: float
    reference_iv_contribution_points: float
    target_correction_required_iv_points: float
    iv_identity_error_points: float
    entry_delta: float
    forward_change: float
    delta_hedged_gross_per_unit: float
    delta_hedged_cost_per_unit: float
    delta_hedged_net_per_unit: float
    delta_hedged_net_per_lot: float | None

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class MispricingEpisode:
    episode_id: str
    status: EpisodeStatus
    direction: MispricingDirection
    instrument_id: str
    expiry: str
    strike: float
    option_type: str
    first_seen_at: datetime
    confirmed_at: datetime
    last_observed_at: datetime
    corrected_at: datetime | None
    invalidated_at: datetime | None
    duration_seconds: float
    peak_gross_edge: float
    peak_net_edge: float
    correction_driver: str | None
    censor_reason: str | None
    gap_close_trace: GapCloseTrace
    latest: MispricingObservation

    def to_dict(self) -> dict[str, object]:
        return {
            **self.latest.to_dict(),
            "episode_id": self.episode_id,
            "status": self.status.value,
            "direction": self.direction.value,
            "instrument_id": self.instrument_id,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type,
            "first_seen_at": self.first_seen_at.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat(),
            "last_observed_at": self.last_observed_at.isoformat(),
            "corrected_at": self.corrected_at.isoformat() if self.corrected_at else None,
            "invalidated_at": (self.invalidated_at.isoformat() if self.invalidated_at else None),
            "duration_seconds": self.duration_seconds,
            "peak_gross_edge": self.peak_gross_edge,
            "peak_net_edge": self.peak_net_edge,
            "correction_driver": self.correction_driver,
            "censor_reason": self.censor_reason,
            "gap_close_trace": self.gap_close_trace.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MispricingFrame:
    timestamp: datetime
    status: str
    reasons: tuple[str, ...]
    policy: MispricingPolicy
    eligible_contract_count: int
    ineligible_counts: Mapping[str, int]
    statistically_tested_count: int
    outside_band_count: int
    fdr_significant_count: int
    exact_confirmed_count: int
    reference_warming_count: int
    reference_rejected_count: int
    pending_count: int
    active: tuple[MispricingEpisode, ...]
    recent: tuple[MispricingEpisode, ...]
    cross_fit_successful_folds: int
    cross_fit_failed_folds: int

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "reasons": list(self.reasons),
            "policy": self.policy.to_dict(),
            "eligible_contract_count": self.eligible_contract_count,
            "ineligible_counts": dict(sorted(self.ineligible_counts.items())),
            "statistically_tested_count": self.statistically_tested_count,
            "outside_band_count": self.outside_band_count,
            "fdr_significant_count": self.fdr_significant_count,
            "exact_confirmed_count": self.exact_confirmed_count,
            "reference_warming_count": self.reference_warming_count,
            "reference_rejected_count": self.reference_rejected_count,
            "pending_count": self.pending_count,
            "active": [episode.to_dict() for episode in self.active],
            "recent": [episode.to_dict() for episode in self.recent],
            "cross_fit_successful_folds": self.cross_fit_successful_folds,
            "cross_fit_failed_folds": self.cross_fit_failed_folds,
            "surface_mode": ("causal_smoothed_strike_cross_fit_executable_iv_research_only"),
            "correction_semantics": (
                "target correction requires executable IV to close the frozen entry after-cost "
                "IV gap; absolute-price and reference-closed residuals are invalidated; "
                "stale/disappeared/unsupported observations are censored, not corrected; "
                "target-option and held-out reference-market IV movements are signed separately; "
                "rupee edge and frozen-delta markout are scenario overlays"
            ),
        }


def _option_key(instrument_id: str) -> _OptionKey | None:
    parts = instrument_id.split(":")
    if len(parts) != 7 or parts[3].lower() != "option":
        return None
    try:
        expiry = date.fromisoformat(parts[4])
        strike = float(parts[5])
    except ValueError:
        return None
    option_type = parts[6].upper()
    if strike <= 0 or option_type not in {"CE", "PE"}:
        return None
    return _OptionKey(expiry, strike, option_type == "CE")


def _future_expiry(instrument_id: str) -> date | None:
    parts = instrument_id.split(":")
    if len(parts) != 5 or parts[3].lower() != "future":
        return None
    try:
        return date.fromisoformat(parts[4])
    except ValueError:
        return None


def _valid_bbo(row: TapeRow) -> bool:
    invalid = {QualityFlag.CROSSED_BOOK, QualityFlag.INVALID_DEPTH, QualityFlag.STALE_QUOTE}
    bid = row.best_bid
    ask = row.best_ask
    return (
        bid is not None
        and ask is not None
        and bid > 0
        and ask >= bid
        and not invalid.intersection(row.quality_flags)
    )


def _latest(rows: Iterable[TapeRow]) -> dict[str, TapeRow]:
    result: dict[str, TapeRow] = {}
    for row in rows:
        incumbent = result.get(row.instrument_id)
        if incumbent is None or (row.receive_ts, row.receive_sequence) > (
            incumbent.receive_ts,
            incumbent.receive_sequence,
        ):
            result[row.instrument_id] = row
    return result


def _expiry_timestamp(expiry: date) -> datetime:
    return datetime.combine(expiry, nse_equity_derivatives_close(expiry), tzinfo=IST)


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _weighted_quantile(values_and_weights: Sequence[tuple[float, float]], fraction: float) -> float:
    if not values_and_weights:
        raise ValueError("weighted quantile requires at least one value")
    ordered = sorted(values_and_weights, key=lambda item: item[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        raise ValueError("weighted quantile requires positive total weight")
    threshold = fraction * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black76_delta(
    *,
    forward: float,
    strike: float,
    maturity_years: float,
    volatility: float,
    risk_free_rate: float,
    is_call: bool,
) -> float:
    discount = math.exp(-risk_free_rate * maturity_years)
    sigma_root = max(volatility * math.sqrt(maturity_years), 1e-12)
    d1 = math.log(forward / strike) / sigma_root + 0.5 * sigma_root
    return discount * (_normal_cdf(d1) if is_call else -_normal_cdf(-d1))


def _log_relative_spread(bid: float, ask: float) -> float:
    relative = (ask - bid) / max(0.5 * (bid + ask), 1e-12)
    return math.log(max(relative, 1e-6))


def _bh_significant(p_values: Mapping[str, float], level: float) -> set[str]:
    if not p_values:
        return set()
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    cutoff_rank = 0
    count = len(ordered)
    for rank, (_, value) in enumerate(ordered, start=1):
        if value <= level * rank / count:
            cutoff_rank = rank
    return {instrument_id for instrument_id, _ in ordered[:cutoff_rank]}


@dataclass
class SurfaceMispricingDetector:
    """Stateful, causal monitor driven once per successful surface fit."""

    policy: MispricingPolicy = field(default_factory=MispricingPolicy)
    instrument_metadata: Mapping[str, InstrumentMetadata] = field(default_factory=dict)
    min_quotes_per_slice: int = 5
    _residuals: dict[tuple[date, bool], deque[_IVResidualSample]] = field(
        default_factory=lambda: defaultdict(deque), init=False, repr=False
    )
    _residual_versions: dict[tuple[date, bool], int] = field(
        default_factory=lambda: defaultdict(int), init=False, repr=False
    )
    _residual_array_cache: dict[
        tuple[date, bool], tuple[int, NDArray[np.float64]]
    ] = field(
        default_factory=dict, init=False, repr=False
    )
    _forward_motion: dict[date, deque[float]] = field(
        default_factory=lambda: defaultdict(deque), init=False, repr=False
    )
    _last_forward: dict[date, tuple[datetime, float]] = field(
        default_factory=dict, init=False, repr=False
    )
    _fold_smoothers: dict[int, ESSVITemporalSmoother] = field(
        default_factory=dict, init=False, repr=False
    )
    _fold_last_update: dict[int, datetime] = field(default_factory=dict, init=False, repr=False)
    _pending: dict[str, _PendingEpisode] = field(default_factory=dict, init=False, repr=False)
    _active: dict[str, _ActiveEpisode] = field(default_factory=dict, init=False, repr=False)
    _recent: deque[MispricingEpisode] = field(init=False, repr=False)
    _episode_sequence: int = field(default=0, init=False)
    _latest_frame: MispricingFrame | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_quotes_per_slice < 5:
            raise ValueError("mispricing cross-fit requires at least five quotes per slice")
        self._recent = deque(maxlen=self.policy.recent_episode_limit)

    @property
    def latest_frame(self) -> MispricingFrame | None:
        return self._latest_frame

    def _metadata(self, instrument_id: str) -> InstrumentMetadata:
        return self.instrument_metadata.get(
            instrument_id,
            InstrumentMetadata(
                tick_size=self.policy.default_tick_size,
                lot_size=self.policy.default_lot_size,
                source="explicit_detector_default",
            ),
        )

    def _fresh_rows(self, rows: Iterable[TapeRow], now: datetime) -> tuple[TapeRow, ...]:
        return tuple(
            row
            for row in _latest(rows).values()
            if row.receive_ts.astimezone(IST) <= now
            and (now - row.receive_ts.astimezone(IST)).total_seconds()
            <= self.policy.quote_max_age_seconds
            and _valid_bbo(row)
        )

    def _forward_bands(
        self,
        *,
        rows: Iterable[TapeRow],
        expiries: Iterable[date],
        maturities: Mapping[date, float],
        risk_free_rate: float,
    ) -> dict[date, _ForwardBand]:
        latest = _latest(rows)
        futures: dict[date, TapeRow] = {}
        options: dict[tuple[date, float], dict[str, TapeRow]] = {}
        for row in latest.values():
            if not _valid_bbo(row):
                continue
            future_expiry = _future_expiry(row.instrument_id)
            if future_expiry is not None:
                futures[future_expiry] = row
                continue
            key = _option_key(row.instrument_id)
            if key is not None:
                options.setdefault(key.strike_pair, {})[key.option_type] = row

        result: dict[date, _ForwardBand] = {}
        for expiry in sorted(set(expiries)):
            future = futures.get(expiry)
            if future is not None:
                assert future.best_bid is not None and future.best_ask is not None
                result[expiry] = _ForwardBand(
                    expiry=expiry,
                    centre=0.5 * (future.best_bid + future.best_ask),
                    lower=future.best_bid,
                    upper=future.best_ask,
                    method="traded_future",
                    source_count=1,
                )
                continue
            maturity = maturities.get(expiry)
            if maturity is None or maturity <= 0:
                continue
            centres: list[float] = []
            lows: list[float] = []
            highs: list[float] = []
            discount_inverse = math.exp(risk_free_rate * maturity)
            for (pair_expiry, strike), pair in options.items():
                if pair_expiry != expiry or "CE" not in pair or "PE" not in pair:
                    continue
                call, put = pair["CE"], pair["PE"]
                assert call.best_bid is not None and call.best_ask is not None
                assert put.best_bid is not None and put.best_ask is not None
                centres.append(
                    strike
                    + discount_inverse
                    * (0.5 * (call.best_bid + call.best_ask) - 0.5 * (put.best_bid + put.best_ask))
                )
                lows.append(strike + discount_inverse * (call.best_bid - put.best_ask))
                highs.append(strike + discount_inverse * (call.best_ask - put.best_bid))
            if not centres:
                continue
            centre = median(centres)
            lower = min(centre, _quantile(lows, 0.10), _quantile(centres, 0.10))
            upper = max(centre, _quantile(highs, 0.90), _quantile(centres, 0.90))
            if lower <= 0:
                continue
            result[expiry] = _ForwardBand(
                expiry=expiry,
                centre=centre,
                lower=lower,
                upper=upper,
                method="robust_put_call_parity_excluding_heldout_strikes",
                source_count=len(centres),
            )
        return result

    def _fit_reference(
        self,
        *,
        rows: tuple[TapeRow, ...],
        expiries: tuple[date, ...],
        now: datetime,
        risk_free_rate: float,
    ) -> tuple[ESSVISurface, dict[date, _ForwardBand]] | None:
        maturities = {
            expiry: (_expiry_timestamp(expiry) - now).total_seconds() / SECONDS_PER_YEAR
            for expiry in expiries
        }
        bands = self._forward_bands(
            rows=rows,
            expiries=expiries,
            maturities=maturities,
            risk_free_rate=risk_free_rate,
        )
        if not bands:
            return None
        request = SurfaceFitRequest(
            tape_rows=rows,
            valuation_timestamp=now,
            forward_by_expiry={expiry: item.centre for expiry, item in bands.items()},
            expiry_timestamp_by_expiry={expiry: _expiry_timestamp(expiry) for expiry in bands},
            risk_free_rate=risk_free_rate,
            min_quotes_per_slice=self.min_quotes_per_slice,
            previous_surface=None,
        )
        try:
            return ESSVISurface.fit(request), bands
        except (SurfaceCalibrationError, ValueError):
            return None

    def _smooth_reference(
        self,
        *,
        fold: int,
        raw_surface: ESSVISurface,
        bands: dict[date, _ForwardBand],
        now: datetime,
    ) -> _SmoothedReference:
        smoother = self._fold_smoothers.get(fold)
        if smoother is None:
            smoother = ESSVITemporalSmoother(
                half_life_seconds=self.policy.reference_smoothing_half_life_seconds,
                max_history=self.policy.reference_smoothing_max_history,
            )
            self._fold_smoothers[fold] = smoother
        previous = self._fold_last_update.get(fold)
        reset_reason: str | None = None
        if (
            previous is not None
            and (now - previous).total_seconds() > self.policy.reference_smoothing_max_gap_seconds
        ):
            smoother.reset()
            reset_reason = "fit_gap_exceeded"
        try:
            surface = smoother.update(raw_surface, observation_timestamp=now)
        except (SurfaceCalibrationError, ValueError) as error:
            smoother.reset()
            surface = smoother.update(raw_surface, observation_timestamp=now)
            reset_reason = f"smoother_reset:{error}"
        self._fold_last_update[fold] = now
        smoothing = surface._fit_metrics.get("smoothing", {})
        component_count = (
            int(smoothing.get("component_count", 1)) if isinstance(smoothing, dict) else 1
        )
        status = (
            "smoothed" if surface.is_temporally_smoothed else reset_reason or "smoothing_warmup"
        )
        return _SmoothedReference(
            raw_surface=raw_surface,
            surface=surface,
            bands=bands,
            component_count=component_count,
            status=status,
        )

    def _with_reference_eligibility(
        self, observation: MispricingObservation
    ) -> MispricingObservation:
        reason: str | None = None
        if observation.reference_smoothing_components < self.policy.reference_smoothing_min_frames:
            reason = "reference_smoothing_warmup"
        elif (
            observation.raw_smoothed_iv_gap_points
            > self.policy.reference_max_raw_smoothed_iv_gap_points
        ):
            reason = "reference_raw_smoothed_iv_gap_exceeded"
        return replace(
            observation,
            reference_eligible=reason is None,
            reference_eligibility_reason=reason,
        )

    def _uncertainty_and_p(
        self,
        *,
        expiry: date,
        is_call: bool,
        log_moneyness: float,
        log_relative_spread: float,
        residual_points: float,
    ) -> tuple[float | None, float | None, int, float, str]:
        """Continuous past-only IV uncertainty with no feature bucket boundaries."""

        label = f"{expiry.isoformat()}|{'CE' if is_call else 'PE'}|continuous_knn_iv"
        key = (expiry, is_call)
        history = self._residuals[key]
        if len(history) < self.policy.min_residual_history:
            return None, None, len(history), 0.0, label
        version = self._residual_versions[key]
        cached = self._residual_array_cache.get(key)
        if cached is None or cached[0] != version:
            values = np.asarray(
                [
                    (
                        sample.log_moneyness,
                        sample.log_relative_spread,
                        sample.residual_points,
                    )
                    for sample in history
                ],
                dtype=np.float64,
            )
            self._residual_array_cache[key] = (version, values)
        else:
            values = cached[1]
        moneyness_distance = (
            values[:, 0] - log_moneyness
        ) / self.policy.residual_moneyness_bandwidth
        spread_distance = (
            values[:, 1] - log_relative_spread
        ) / self.policy.residual_log_spread_bandwidth
        distance_squared = (
            moneyness_distance * moneyness_distance + spread_distance * spread_distance
        )
        neighbour_count = min(self.policy.residual_neighbor_count, len(history))
        if neighbour_count < len(history):
            indices = np.argpartition(distance_squared, neighbour_count - 1)[:neighbour_count]
        else:
            indices = np.arange(neighbour_count)
        weighted_absolute: list[tuple[float, float]] = []
        tail_weight = 0.0
        total_weight = 0.0
        squared_weight = 0.0
        target = abs(residual_points)
        for index in indices:
            weight = max(math.exp(-0.5 * float(distance_squared[index])), 1e-12)
            absolute = abs(float(values[index, 2]))
            weighted_absolute.append((absolute, weight))
            total_weight += weight
            squared_weight += weight * weight
            if absolute >= target:
                tail_weight += weight
        effective = total_weight * total_weight / squared_weight if squared_weight > 0 else 0.0
        uncertainty = _weighted_quantile(weighted_absolute, self.policy.residual_quantile)
        p_value = (1.0 + tail_weight) / (1.0 + total_weight)
        return uncertainty, p_value, neighbour_count, effective, label

    def _append_residual(self, key: tuple[date, bool], sample: _IVResidualSample) -> None:
        history = self._residuals[key]
        history.append(sample)
        while len(history) > self.policy.residual_history_limit:
            history.popleft()
        self._residual_versions[key] += 1

    @staticmethod
    def _iv_width_from_price_stress(
        *,
        centre_price: float,
        price_width: float,
        centre_iv: float,
        forward: float,
        strike: float,
        maturity: float,
        risk_free_rate: float,
        is_call: bool,
    ) -> float | None:
        widths: list[float] = []
        for price in (centre_price - price_width, centre_price + price_width):
            if price <= 0:
                continue
            stressed_iv = implied_volatility(
                price=price,
                forward=forward,
                strike=strike,
                maturity_years=maturity,
                risk_free_rate=risk_free_rate,
                is_call=is_call,
            )
            if stressed_iv is not None:
                widths.append(abs(stressed_iv - centre_iv) * 100.0)
        return max(widths) if widths else None

    def _asynchrony_uncertainty(
        self,
        *,
        expiry: date,
        forward_band: _ForwardBand,
        delta: float,
        quote_age_seconds: float,
    ) -> float:
        half_width = 0.5 * (forward_band.upper - forward_band.lower)
        motion = self._forward_motion[expiry]
        per_second = _quantile(tuple(motion), 0.99) if len(motion) >= 10 else half_width
        move = max(half_width, per_second * max(quote_age_seconds, 1.0))
        return abs(delta) * move

    def _cost(
        self,
        *,
        direction: MispricingDirection,
        market_price: float,
        fair_price: float,
        tick_size: float,
    ) -> float:
        if direction is MispricingDirection.CHEAP:
            turnover = (
                market_price * self.policy.buy_turnover_rate
                + fair_price * self.policy.sell_turnover_rate
            )
        else:
            turnover = (
                market_price * self.policy.sell_turnover_rate
                + fair_price * self.policy.buy_turnover_rate
            )
        slippage = tick_size * (self.policy.exit_slippage_ticks + self.policy.hedge_slippage_ticks)
        return turnover + slippage

    def _observation(
        self,
        *,
        row: TapeRow,
        key: _OptionKey,
        surface: ESSVISurface,
        raw_surface: ESSVISurface | None = None,
        reference_smoothing_components: int = 1,
        forward_band: _ForwardBand,
        now: datetime,
        risk_free_rate: float,
    ) -> tuple[MispricingObservation | None, str | None]:
        bid, ask = row.best_bid, row.best_ask
        if bid is None or ask is None or not _valid_bbo(row):
            return None, "invalid_bbo"
        quote_age = (now - row.receive_ts.astimezone(IST)).total_seconds()
        if quote_age < 0 or quote_age > self.policy.quote_max_age_seconds:
            return None, "target_quote_stale"
        maturity = (_expiry_timestamp(key.expiry) - now).total_seconds() / SECONDS_PER_YEAR
        if maturity <= 0:
            return None, "expired"
        log_moneyness = math.log(key.strike / forward_band.centre)
        fitted_maturity = next(
            (item.maturity_years for item in surface.slices if item.expiry == key.expiry),
            maturity,
        )
        evaluation = surface.evaluate(log_moneyness=log_moneyness, maturity_years=fitted_maturity)
        if evaluation.status is EvaluationStatus.DATA_INSUFFICIENT:
            return None, "outside_cross_fit_support"
        fair_iv = evaluation.implied_volatility
        if fair_iv is None:
            return None, "cross_fit_fair_iv_missing"
        raw_fair_iv = fair_iv
        if raw_surface is not None:
            raw_evaluation = raw_surface.evaluate(
                log_moneyness=log_moneyness, maturity_years=fitted_maturity
            )
            if (
                raw_evaluation.status is EvaluationStatus.DATA_INSUFFICIENT
                or raw_evaluation.implied_volatility is None
            ):
                return None, "raw_cross_fit_fair_iv_missing"
            raw_fair_iv = raw_evaluation.implied_volatility
        fair_price = black76_price(
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            volatility=fair_iv,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        observed_mid = 0.5 * (bid + ask)
        observed_iv = implied_volatility(
            price=observed_mid,
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        observed_bid_iv = implied_volatility(
            price=bid,
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        observed_ask_iv = implied_volatility(
            price=ask,
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        if observed_iv is None or observed_bid_iv is None or observed_ask_iv is None:
            return None, "executable_iv_unavailable"
        metadata = self._metadata(row.instrument_id)
        log_relative_spread = _log_relative_spread(bid, ask)
        iv_residual_points = (observed_iv - fair_iv) * 100.0
        (
            model_uncertainty_iv,
            p_value,
            history_count,
            effective_history,
            residual_label,
        ) = self._uncertainty_and_p(
            expiry=key.expiry,
            is_call=key.is_call,
            log_moneyness=log_moneyness,
            log_relative_spread=log_relative_spread,
            residual_points=iv_residual_points,
        )
        if model_uncertainty_iv is None:
            return None, f"residual_history_warmup:{residual_label}:{history_count}"

        stressed_prices = [
            black76_price(
                forward=forward,
                strike=key.strike,
                maturity_years=maturity,
                volatility=fair_iv,
                risk_free_rate=risk_free_rate,
                is_call=key.is_call,
            )
            for forward in (forward_band.lower, forward_band.upper)
        ]
        forward_uncertainty = max(abs(value - fair_price) for value in stressed_prices)
        forward_iv_candidates = [
            value
            for stressed_forward in (forward_band.lower, forward_band.upper)
            if (
                value := implied_volatility(
                    price=fair_price,
                    forward=stressed_forward,
                    strike=key.strike,
                    maturity_years=maturity,
                    risk_free_rate=risk_free_rate,
                    is_call=key.is_call,
                )
            )
            is not None
        ]
        if not forward_iv_candidates:
            return None, "forward_iv_uncertainty_unavailable"
        forward_uncertainty_iv = max(
            abs(value - fair_iv) * 100.0 for value in forward_iv_candidates
        )
        delta = _black76_delta(
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            volatility=fair_iv,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        async_uncertainty = self._asynchrony_uncertainty(
            expiry=key.expiry,
            forward_band=forward_band,
            delta=delta,
            quote_age_seconds=quote_age,
        )
        tick_uncertainty_iv = self._iv_width_from_price_stress(
            centre_price=fair_price,
            price_width=metadata.tick_size,
            centre_iv=fair_iv,
            forward=forward_band.centre,
            strike=key.strike,
            maturity=maturity,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        async_uncertainty_iv = self._iv_width_from_price_stress(
            centre_price=fair_price,
            price_width=async_uncertainty,
            centre_iv=fair_iv,
            forward=forward_band.centre,
            strike=key.strike,
            maturity=maturity,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        if tick_uncertainty_iv is None or async_uncertainty_iv is None:
            return None, "iv_uncertainty_conversion_unavailable"
        total_uncertainty_iv = max(
            tick_uncertainty_iv,
            model_uncertainty_iv,
            forward_uncertainty_iv,
            async_uncertainty_iv,
        )
        fair_iv_lower = max(1e-8, fair_iv - total_uncertainty_iv / 100.0)
        fair_iv_upper = fair_iv + total_uncertainty_iv / 100.0
        fair_lower = black76_price(
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            volatility=fair_iv_lower,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        fair_upper = black76_price(
            forward=forward_band.centre,
            strike=key.strike,
            maturity_years=maturity,
            volatility=fair_iv_upper,
            risk_free_rate=risk_free_rate,
            is_call=key.is_call,
        )
        model_prices = [
            black76_price(
                forward=forward_band.centre,
                strike=key.strike,
                maturity_years=maturity,
                volatility=volatility,
                risk_free_rate=risk_free_rate,
                is_call=key.is_call,
            )
            for volatility in (
                max(1e-8, fair_iv - model_uncertainty_iv / 100.0),
                fair_iv + model_uncertainty_iv / 100.0,
            )
        ]
        model_uncertainty = max(abs(value - fair_price) for value in model_prices)
        total_uncertainty = max(abs(fair_lower - fair_price), abs(fair_upper - fair_price))
        buy_iv_edge_points = (fair_iv_lower - observed_ask_iv) * 100.0
        sell_iv_edge_points = (observed_bid_iv - fair_iv_upper) * 100.0
        buy_edge = fair_lower - ask
        sell_edge = bid - fair_upper
        direction = (
            MispricingDirection.CHEAP
            if buy_iv_edge_points > 0 and buy_iv_edge_points >= sell_iv_edge_points
            else MispricingDirection.RICH
            if sell_iv_edge_points > 0
            else None
        )
        gross_iv_edge_points = max(buy_iv_edge_points, sell_iv_edge_points)
        gross_edge = (
            buy_edge
            if direction is MispricingDirection.CHEAP
            else sell_edge
            if direction is MispricingDirection.RICH
            else max(buy_edge, sell_edge)
        )
        executable_price = ask if direction is MispricingDirection.CHEAP else bid
        executable_iv = (
            observed_ask_iv
            if direction is MispricingDirection.CHEAP
            else observed_bid_iv
            if direction is MispricingDirection.RICH
            else None
        )
        cost = (
            self._cost(
                direction=direction,
                market_price=executable_price,
                fair_price=fair_price,
                tick_size=metadata.tick_size,
            )
            if direction is not None
            else 0.0
        )
        net_edge = gross_edge - cost if direction is not None else gross_edge
        target_correction_required_iv_points = 0.0
        if direction is MispricingDirection.CHEAP and net_edge > 0:
            break_even_iv = implied_volatility(
                price=ask + net_edge,
                forward=forward_band.centre,
                strike=key.strike,
                maturity_years=maturity,
                risk_free_rate=risk_free_rate,
                is_call=key.is_call,
            )
            if break_even_iv is None:
                return None, "after_cost_iv_target_unavailable"
            target_correction_required_iv_points = max(
                0.0, (break_even_iv - observed_ask_iv) * 100.0
            )
        elif direction is MispricingDirection.RICH and net_edge > 0:
            break_even_iv = implied_volatility(
                price=bid - net_edge,
                forward=forward_band.centre,
                strike=key.strike,
                maturity_years=maturity,
                risk_free_rate=risk_free_rate,
                is_call=key.is_call,
            )
            if break_even_iv is None:
                return None, "after_cost_iv_target_unavailable"
            target_correction_required_iv_points = max(
                0.0, (observed_bid_iv - break_even_iv) * 100.0
            )
        displayed_quantity = (
            row.asks[0].quantity
            if direction is MispricingDirection.CHEAP and row.asks
            else row.bids[0].quantity
            if direction is MispricingDirection.RICH and row.bids
            else None
        )
        lot_size = metadata.lot_size
        per_lot = net_edge * lot_size if lot_size is not None else None
        return (
            MispricingObservation(
                instrument_id=row.instrument_id,
                expiry=key.expiry.isoformat(),
                strike=key.strike,
                option_type=key.option_type,
                direction=direction,
                observed_bid=bid,
                observed_ask=ask,
                observed_mid=observed_mid,
                observed_mid_iv=observed_iv,
                observed_bid_iv=observed_bid_iv,
                observed_ask_iv=observed_ask_iv,
                executable_iv=executable_iv,
                quote_age_seconds=quote_age,
                displayed_quantity=displayed_quantity,
                lot_size=lot_size,
                tick_size=metadata.tick_size,
                metadata_source=metadata.source,
                forward=forward_band.centre,
                forward_method=forward_band.method,
                log_moneyness=log_moneyness,
                log_relative_spread=log_relative_spread,
                fair_iv=fair_iv,
                fair_iv_lower=fair_iv_lower,
                fair_iv_upper=fair_iv_upper,
                raw_fair_iv=raw_fair_iv,
                raw_smoothed_iv_gap_points=abs(raw_fair_iv - fair_iv) * 100.0,
                exact_fair_iv=None,
                exact_smoothed_iv_gap_points=None,
                reference_smoothing_components=reference_smoothing_components,
                reference_eligible=False,
                reference_eligibility_reason="reference_eligibility_not_evaluated",
                fair_price=fair_price,
                fair_lower=fair_lower,
                fair_upper=fair_upper,
                model_uncertainty=model_uncertainty,
                forward_uncertainty=forward_uncertainty,
                asynchrony_uncertainty=async_uncertainty,
                total_uncertainty=total_uncertainty,
                tick_uncertainty_iv_points=tick_uncertainty_iv,
                model_uncertainty_iv_points=model_uncertainty_iv,
                forward_uncertainty_iv_points=forward_uncertainty_iv,
                asynchrony_uncertainty_iv_points=async_uncertainty_iv,
                total_uncertainty_iv_points=total_uncertainty_iv,
                gross_iv_edge_points=gross_iv_edge_points,
                target_correction_required_iv_points=(target_correction_required_iv_points),
                gross_edge=gross_edge,
                gross_edge_ticks=gross_edge / metadata.tick_size,
                estimated_cost_per_unit=cost,
                net_edge=net_edge,
                net_edge_ticks=net_edge / metadata.tick_size,
                net_edge_per_lot=per_lot,
                iv_residual_points=iv_residual_points,
                empirical_p_value=p_value,
                fdr_significant=False,
                exact_leave_strike_confirmed=False,
                residual_history_count=history_count,
                residual_effective_sample_size=effective_history,
                residual_bucket=residual_label,
                fair_delta=delta,
            ),
            None,
        )

    def _episode(
        self,
        active: _ActiveEpisode,
        *,
        now: datetime,
        status: EpisodeStatus = EpisodeStatus.ACTIVE,
        censor_reason: str | None = None,
    ) -> MispricingEpisode:
        trace = self._gap_close_trace(
            active,
            closure_gate=(
                "frozen_entry_target_reached"
                if status is EpisodeStatus.CORRECTED
                else self._closure_gate(active)
                if status is EpisodeStatus.INVALIDATED
                else None
            ),
        )
        return MispricingEpisode(
            episode_id=active.episode_id,
            status=status,
            direction=active.direction,
            instrument_id=active.latest.instrument_id,
            expiry=active.latest.expiry,
            strike=active.latest.strike,
            option_type=active.latest.option_type,
            first_seen_at=active.first_seen_at,
            confirmed_at=active.confirmed_at,
            last_observed_at=now,
            corrected_at=now if status is EpisodeStatus.CORRECTED else None,
            invalidated_at=now if status is EpisodeStatus.INVALIDATED else None,
            duration_seconds=max(0.0, (now - active.first_seen_at).total_seconds()),
            peak_gross_edge=active.peak_gross_edge,
            peak_net_edge=active.peak_net_edge,
            correction_driver=(trace.attribution if status is EpisodeStatus.CORRECTED else None),
            censor_reason=censor_reason,
            gap_close_trace=trace,
            latest=active.latest,
        )

    @staticmethod
    def _closure_gate(active: _ActiveEpisode) -> str:
        latest = active.latest
        if not latest.reference_eligible:
            return latest.reference_eligibility_reason or "reference_ineligible"
        if latest.direction is None:
            return "inside_uncertainty_band"
        if latest.direction is not active.direction:
            return "direction_reversed"
        if latest.net_edge <= 0:
            return "after_cost_edge_nonpositive"
        if not latest.fdr_significant:
            return "multiplicity_significance_lost"
        if not latest.exact_leave_strike_confirmed:
            return "exact_confirmation_lost"
        return "qualification_lost"

    def _gap_close_trace(
        self, active: _ActiveEpisode, *, closure_gate: str | None
    ) -> GapCloseTrace:
        initial, latest = active.initial, active.latest
        if active.direction is MispricingDirection.CHEAP:
            entry_executable = initial.observed_ask
            close_executable = latest.observed_ask
            entry_reference = initial.fair_lower
            close_reference = latest.fair_lower
            entry_gap = entry_reference - entry_executable
            close_gap = close_reference - close_executable
            target = close_executable - entry_executable
            reference = entry_reference - close_reference
            entry_executable_iv = initial.observed_ask_iv
            close_executable_iv = latest.observed_ask_iv
            entry_reference_iv = initial.fair_iv_lower
            close_reference_iv = latest.fair_iv_lower
            entry_iv_gap_points = (entry_reference_iv - entry_executable_iv) * 100.0
            close_iv_gap_points = (close_reference_iv - close_executable_iv) * 100.0
            target_iv_points = (close_executable_iv - entry_executable_iv) * 100.0
            reference_iv_points = (entry_reference_iv - close_reference_iv) * 100.0
            option_markout = latest.observed_bid - initial.observed_ask
            hedge_markout = -initial.fair_delta * (latest.forward - initial.forward)
            markout_cost = (
                initial.observed_ask * self.policy.buy_turnover_rate
                + latest.observed_bid * self.policy.sell_turnover_rate
            )
        else:
            entry_executable = initial.observed_bid
            close_executable = latest.observed_bid
            entry_reference = initial.fair_upper
            close_reference = latest.fair_upper
            entry_gap = entry_executable - entry_reference
            close_gap = close_executable - close_reference
            target = entry_executable - close_executable
            reference = close_reference - entry_reference
            entry_executable_iv = initial.observed_bid_iv
            close_executable_iv = latest.observed_bid_iv
            entry_reference_iv = initial.fair_iv_upper
            close_reference_iv = latest.fair_iv_upper
            entry_iv_gap_points = (entry_executable_iv - entry_reference_iv) * 100.0
            close_iv_gap_points = (close_executable_iv - close_reference_iv) * 100.0
            target_iv_points = (entry_executable_iv - close_executable_iv) * 100.0
            reference_iv_points = (close_reference_iv - entry_reference_iv) * 100.0
            option_markout = initial.observed_bid - latest.observed_ask
            hedge_markout = initial.fair_delta * (latest.forward - initial.forward)
            markout_cost = (
                initial.observed_bid * self.policy.sell_turnover_rate
                + latest.observed_ask * self.policy.buy_turnover_rate
            )
        gap_closed = entry_gap - close_gap
        iv_gap_closed_points = entry_iv_gap_points - close_iv_gap_points
        positive_target = max(0.0, target_iv_points)
        positive_reference = max(0.0, reference_iv_points)
        positive_total = positive_target + positive_reference
        target_share = positive_target / positive_total if positive_total > 1e-12 else None
        reference_share = positive_reference / positive_total if positive_total > 1e-12 else None
        if iv_gap_closed_points <= 1e-12 or positive_total <= 1e-12:
            attribution = "gap_not_closed"
        elif target_share is not None and target_share >= 0.60:
            attribution = "target_option_led"
        elif reference_share is not None and reference_share >= 0.60:
            attribution = "reference_market_led"
        else:
            attribution = "mixed"
        tick_size = initial.tick_size
        target_correction_required = max(0.0, initial.net_edge)
        target_correction_required_iv = max(0.0, initial.target_correction_required_iv_points)
        target_correction_achieved = target_iv_points + 1e-12 >= target_correction_required_iv
        markout_cost += tick_size * (
            self.policy.exit_slippage_ticks + self.policy.hedge_slippage_ticks
        )
        delta_hedged_gross = option_markout + hedge_markout
        delta_hedged_net = delta_hedged_gross - markout_cost
        return GapCloseTrace(
            entry_executable_price=entry_executable,
            close_executable_price=close_executable,
            entry_reference_boundary=entry_reference,
            close_reference_boundary=close_reference,
            entry_gap=entry_gap,
            close_gap=close_gap,
            gap_closed=gap_closed,
            target_option_contribution=target,
            reference_market_contribution=reference,
            entry_gap_ticks=entry_gap / tick_size,
            close_gap_ticks=close_gap / tick_size,
            gap_closed_ticks=gap_closed / tick_size,
            target_option_contribution_ticks=target / tick_size,
            reference_market_contribution_ticks=reference / tick_size,
            target_option_share=target_share,
            reference_market_share=reference_share,
            target_correction_required=target_correction_required,
            target_correction_required_ticks=target_correction_required / tick_size,
            target_correction_achieved=target_correction_achieved,
            attribution=attribution,
            closure_gate=closure_gate,
            identity_error=gap_closed - target - reference,
            entry_executable_iv=entry_executable_iv,
            close_executable_iv=close_executable_iv,
            entry_reference_iv_boundary=entry_reference_iv,
            close_reference_iv_boundary=close_reference_iv,
            entry_iv_gap_points=entry_iv_gap_points,
            close_iv_gap_points=close_iv_gap_points,
            iv_gap_closed_points=iv_gap_closed_points,
            target_iv_contribution_points=target_iv_points,
            reference_iv_contribution_points=reference_iv_points,
            target_correction_required_iv_points=target_correction_required_iv,
            iv_identity_error_points=(
                iv_gap_closed_points - target_iv_points - reference_iv_points
            ),
            entry_delta=initial.fair_delta,
            forward_change=latest.forward - initial.forward,
            delta_hedged_gross_per_unit=delta_hedged_gross,
            delta_hedged_cost_per_unit=markout_cost,
            delta_hedged_net_per_unit=delta_hedged_net,
            delta_hedged_net_per_lot=(
                delta_hedged_net * initial.lot_size if initial.lot_size is not None else None
            ),
        )

    def _update_episodes(
        self,
        *,
        now: datetime,
        observations: Mapping[str, MispricingObservation],
        qualified: Mapping[str, MispricingObservation],
        ineligible: Mapping[str, str],
    ) -> None:
        for instrument_id, active in list(self._active.items()):
            current = observations.get(instrument_id)
            qualifying = qualified.get(instrument_id)
            if current is None:
                reason = ineligible.get(instrument_id, "observation_unavailable")
                closed = self._episode(
                    active,
                    now=now,
                    status=EpisodeStatus.CENSORED,
                    censor_reason=reason,
                )
                self._recent.appendleft(closed)
                del self._active[instrument_id]
                continue
            active.latest = current
            active.peak_gross_edge = max(active.peak_gross_edge, current.gross_edge)
            active.peak_net_edge = max(active.peak_net_edge, current.net_edge)
            trace = self._gap_close_trace(active, closure_gate=None)
            if trace.target_correction_achieved:
                active.target_correction_count += 1
            else:
                active.target_correction_count = 0
            if active.target_correction_count >= self.policy.correction_frames:
                self._recent.appendleft(
                    self._episode(active, now=now, status=EpisodeStatus.CORRECTED)
                )
                del self._active[instrument_id]
                continue
            if qualifying is not None and qualifying.direction is active.direction:
                active.correction_count = 0
                continue
            active.correction_count += 1
            if active.correction_count >= self.policy.correction_frames:
                closed = self._episode(
                    active,
                    now=now,
                    status=EpisodeStatus.INVALIDATED,
                )
                self._recent.appendleft(closed)
                del self._active[instrument_id]

        for instrument_id, observation in qualified.items():
            if instrument_id in self._active or observation.direction is None:
                continue
            pending = self._pending.get(instrument_id)
            if pending is None or pending.direction is not observation.direction:
                pending = _PendingEpisode(
                    direction=observation.direction,
                    first_seen_at=now,
                    count=1,
                    observation=observation,
                )
                self._pending[instrument_id] = pending
            else:
                pending.count += 1
                pending.observation = observation
            if pending.count >= self.policy.confirmation_frames:
                self._episode_sequence += 1
                active = _ActiveEpisode(
                    episode_id=f"MP-{now:%Y%m%d}-{self._episode_sequence:06d}",
                    direction=pending.direction,
                    first_seen_at=pending.first_seen_at,
                    confirmed_at=now,
                    initial=pending.observation,
                    latest=observation,
                    peak_gross_edge=observation.gross_edge,
                    peak_net_edge=observation.net_edge,
                )
                self._active[instrument_id] = active
                del self._pending[instrument_id]

        for instrument_id in list(self._pending):
            if instrument_id not in qualified:
                del self._pending[instrument_id]

    def _frame(
        self,
        *,
        now: datetime,
        status: str,
        reasons: tuple[str, ...],
        eligible_count: int,
        ineligible: Mapping[str, int],
        tested_count: int,
        outside_count: int,
        fdr_count: int,
        exact_count: int,
        reference_warming_count: int,
        reference_rejected_count: int,
        successful_folds: int,
        failed_folds: int,
    ) -> MispricingFrame:
        active = tuple(
            sorted(
                (self._episode(item, now=now) for item in self._active.values()),
                key=lambda item: (-item.latest.net_edge, item.instrument_id),
            )
        )
        frame = MispricingFrame(
            timestamp=now,
            status=status,
            reasons=reasons,
            policy=self.policy,
            eligible_contract_count=eligible_count,
            ineligible_counts=dict(ineligible),
            statistically_tested_count=tested_count,
            outside_band_count=outside_count,
            fdr_significant_count=fdr_count,
            exact_confirmed_count=exact_count,
            reference_warming_count=reference_warming_count,
            reference_rejected_count=reference_rejected_count,
            pending_count=len(self._pending),
            active=active,
            recent=tuple(self._recent),
            cross_fit_successful_folds=successful_folds,
            cross_fit_failed_folds=failed_folds,
        )
        self._latest_frame = frame
        return frame

    def unavailable(self, now: datetime, reason: str) -> MispricingFrame:
        """Censor live episodes when the detector loses a valid observation path."""

        for instrument_id, active in list(self._active.items()):
            self._recent.appendleft(
                self._episode(
                    active,
                    now=now,
                    status=EpisodeStatus.CENSORED,
                    censor_reason=reason,
                )
            )
            del self._active[instrument_id]
        self._pending.clear()
        return self._frame(
            now=now,
            status="unavailable",
            reasons=(reason,),
            eligible_count=0,
            ineligible={reason: 1},
            tested_count=0,
            outside_count=0,
            fdr_count=0,
            exact_count=0,
            reference_warming_count=0,
            reference_rejected_count=0,
            successful_folds=0,
            failed_folds=self.policy.cross_fit_folds,
        )

    def evaluate(
        self,
        *,
        rows: Iterable[TapeRow],
        expiries: Iterable[date],
        now: datetime,
        risk_free_rate: float,
        base_fit_age_seconds: float = 0.0,
        base_arbitrage_passed: bool = True,
    ) -> MispricingFrame:
        if not self.policy.enabled:
            return self.unavailable(now, "detector_disabled")
        if base_fit_age_seconds > self.policy.fit_max_age_seconds:
            return self.unavailable(now, "base_fit_too_old")
        if not base_arbitrage_passed:
            return self.unavailable(now, "base_surface_arbitrage_check_failed")

        expiries_tuple = tuple(sorted(set(expiries)))
        fresh = self._fresh_rows(rows, now)
        option_rows = [row for row in fresh if _option_key(row.instrument_id) is not None]
        if not option_rows:
            return self.unavailable(now, "no_fresh_two_sided_option_quotes")

        strike_pairs = sorted(
            {key.strike_pair for row in option_rows if (key := _option_key(row.instrument_id))}
        )
        per_expiry: dict[date, list[float]] = defaultdict(list)
        for expiry, strike in strike_pairs:
            per_expiry[expiry].append(strike)
        fold_by_pair = {
            (expiry, strike): index % self.policy.cross_fit_folds
            for expiry, strikes in per_expiry.items()
            for index, strike in enumerate(sorted(set(strikes)))
        }

        references: dict[int, _SmoothedReference] = {}
        failed_folds = 0
        for fold in range(self.policy.cross_fit_folds):
            training = tuple(
                row
                for row in fresh
                if (key := _option_key(row.instrument_id)) is None
                or fold_by_pair.get(key.strike_pair) != fold
            )
            fitted = self._fit_reference(
                rows=training,
                expiries=expiries_tuple,
                now=now,
                risk_free_rate=risk_free_rate,
            )
            if fitted is None:
                failed_folds += 1
            else:
                raw_surface, bands = fitted
                references[fold] = self._smooth_reference(
                    fold=fold,
                    raw_surface=raw_surface,
                    bands=bands,
                    now=now,
                )

        ineligible_by_contract: dict[str, str] = {}
        observations: dict[str, MispricingObservation] = {}
        counter: Counter[str] = Counter()
        preliminary: dict[str, MispricingObservation] = {}
        row_by_id = {row.instrument_id: row for row in option_rows}

        for row in option_rows:
            key = _option_key(row.instrument_id)
            assert key is not None
            fold = fold_by_pair[key.strike_pair]
            reference = references.get(fold)
            if reference is None:
                reason = "cross_fit_fold_failed"
                ineligible_by_contract[row.instrument_id] = reason
                counter[reason] += 1
                continue
            forward_band = reference.bands.get(key.expiry)
            if forward_band is None:
                reason = "cross_fit_forward_unavailable"
                ineligible_by_contract[row.instrument_id] = reason
                counter[reason] += 1
                continue
            observation, observation_reason = self._observation(
                row=row,
                key=key,
                surface=reference.surface,
                raw_surface=reference.raw_surface,
                reference_smoothing_components=reference.component_count,
                forward_band=forward_band,
                now=now,
                risk_free_rate=risk_free_rate,
            )
            if observation is None:
                assert observation_reason is not None
                ineligible_by_contract[row.instrument_id] = observation_reason
                counter[observation_reason.split(":", 1)[0]] += 1
                # Warm-up still needs causal residuals.  Re-evaluate with a temporary zero
                # history floor by pricing directly, then append below where possible.
                continue
            observation = self._with_reference_eligibility(observation)
            observations[row.instrument_id] = observation
            if not observation.reference_eligible:
                eligibility_reason = (
                    observation.reference_eligibility_reason or "reference_ineligible"
                )
                counter[eligibility_reason] += 1
                ineligible_by_contract[row.instrument_id] = eligibility_reason
            elif observation.empirical_p_value is not None:
                preliminary[row.instrument_id] = observation

        # Warm-up residuals are generated from the same held-out fits without using the target.
        # `_observation` deliberately refuses to classify them until support is adequate; this
        # second pass extracts only the residual and never emits a candidate.
        for row in option_rows:
            if row.instrument_id in observations:
                continue
            key = _option_key(row.instrument_id)
            assert key is not None
            reference = references.get(fold_by_pair[key.strike_pair])
            if reference is None:
                continue
            surface = reference.surface
            band = reference.bands.get(key.expiry)
            if band is None or row.best_bid is None or row.best_ask is None:
                continue
            maturity = (_expiry_timestamp(key.expiry) - now).total_seconds() / SECONDS_PER_YEAR
            fitted_maturity = next(
                (item.maturity_years for item in surface.slices if item.expiry == key.expiry),
                maturity,
            )
            evaluation = surface.evaluate(
                log_moneyness=math.log(key.strike / band.centre),
                maturity_years=fitted_maturity,
            )
            if evaluation.status is EvaluationStatus.DATA_INSUFFICIENT:
                continue
            fair_iv = evaluation.implied_volatility
            if fair_iv is None:
                continue
            observed_mid_iv = implied_volatility(
                price=0.5 * (row.best_bid + row.best_ask),
                forward=band.centre,
                strike=key.strike,
                maturity_years=maturity,
                risk_free_rate=risk_free_rate,
                is_call=key.is_call,
            )
            if observed_mid_iv is None:
                continue
            log_moneyness = math.log(key.strike / band.centre)
            self._append_residual(
                (key.expiry, key.is_call),
                _IVResidualSample(
                    log_moneyness=log_moneyness,
                    log_relative_spread=_log_relative_spread(row.best_bid, row.best_ask),
                    residual_points=(observed_mid_iv - fair_iv) * 100.0,
                ),
            )

        outside_band = {
            instrument_id: item
            for instrument_id, item in preliminary.items()
            if item.direction is not None and item.gross_iv_edge_points > 0
        }
        outside = {
            instrument_id: item
            for instrument_id, item in outside_band.items()
            if item.gross_edge > 0
            and item.net_edge > 0
            and item.lot_size is not None
            and item.displayed_quantity is not None
            and item.displayed_quantity >= item.lot_size
        }
        significant_ids = _bh_significant(
            {
                instrument_id: item.empirical_p_value
                for instrument_id, item in outside.items()
                if item.empirical_p_value is not None
            },
            self.policy.fdr_level,
        )

        exact: dict[str, MispricingObservation] = {}
        exact_cache: dict[
            tuple[date, float], tuple[ESSVISurface, dict[date, _ForwardBand]] | None
        ] = {}
        for instrument_id in significant_ids:
            item = replace(outside[instrument_id], fdr_significant=True)
            observations[instrument_id] = item
            row = row_by_id[instrument_id]
            key = _option_key(instrument_id)
            assert key is not None
            if key.strike_pair not in exact_cache:
                training = tuple(
                    candidate
                    for candidate in fresh
                    if (candidate_key := _option_key(candidate.instrument_id)) is None
                    or candidate_key.strike_pair != key.strike_pair
                )
                exact_cache[key.strike_pair] = self._fit_reference(
                    rows=training,
                    expiries=expiries_tuple,
                    now=now,
                    risk_free_rate=risk_free_rate,
                )
            exact_reference = exact_cache[key.strike_pair]
            if exact_reference is None:
                counter["exact_leave_strike_fit_failed"] += 1
                continue
            surface, bands = exact_reference
            band = bands.get(key.expiry)
            if band is None:
                counter["exact_leave_strike_forward_unavailable"] += 1
                continue
            confirmed, confirmation_reason = self._observation(
                row=row,
                key=key,
                surface=surface,
                forward_band=band,
                now=now,
                risk_free_rate=risk_free_rate,
            )
            if confirmed is None:
                counter[(confirmation_reason or "exact_observation_failed").split(":", 1)[0]] += 1
                continue
            exact_gap_points = abs(confirmed.fair_iv - item.fair_iv) * 100.0
            confirmed = replace(
                item,
                fdr_significant=True,
                exact_leave_strike_confirmed=(
                    confirmed.direction is item.direction
                    and confirmed.net_edge > 0
                    and exact_gap_points <= self.policy.reference_max_raw_smoothed_iv_gap_points
                ),
                exact_fair_iv=confirmed.fair_iv,
                exact_smoothed_iv_gap_points=exact_gap_points,
            )
            observations[instrument_id] = confirmed
            if confirmed.exact_leave_strike_confirmed:
                exact[instrument_id] = confirmed

        self._update_episodes(
            now=now,
            observations=observations,
            qualified=exact,
            ineligible=ineligible_by_contract,
        )

        # Add only non-outside-band held-out residuals after the current decision.  This keeps
        # the uncertainty estimator causal and stops an active dislocation from teaching the
        # detector that the dislocation is ordinary noise.
        for item in observations.values():
            if item.instrument_id in outside_band:
                continue
            assert item.iv_residual_points is not None
            self._append_residual(
                (date.fromisoformat(item.expiry), item.option_type == "CE"),
                _IVResidualSample(
                    log_moneyness=item.log_moneyness,
                    log_relative_spread=item.log_relative_spread,
                    residual_points=item.iv_residual_points,
                ),
            )

        central_forwards: dict[date, float] = {}
        for reference in references.values():
            for expiry, band in reference.bands.items():
                central_forwards.setdefault(expiry, band.centre)
        for expiry, value in central_forwards.items():
            previous = self._last_forward.get(expiry)
            if previous is not None:
                previous_time, previous_value = previous
                elapsed = (now - previous_time).total_seconds()
                if elapsed > 0:
                    forward_history = self._forward_motion[expiry]
                    forward_history.append(abs(value - previous_value) / elapsed)
                    while len(forward_history) > self.policy.residual_history_limit:
                        forward_history.popleft()
            self._last_forward[expiry] = (now, value)

        reasons: list[str] = []
        if failed_folds:
            reasons.append(f"{failed_folds}/{self.policy.cross_fit_folds} strike folds failed")
        warmup = sum(
            count for reason, count in counter.items() if reason == "residual_history_warmup"
        )
        reference_warming = counter.get("reference_smoothing_warmup", 0)
        reference_rejected = counter.get("reference_raw_smoothed_iv_gap_exceeded", 0)
        if warmup:
            reasons.append(f"{warmup} contracts still warming empirical residual history")
        if reference_warming:
            reasons.append(f"{reference_warming} contracts still warming the reference smoother")
        if reference_rejected:
            reasons.append(f"{reference_rejected} contracts rejected for raw-smoothed disagreement")
        if not exact and not self._active:
            reasons.append("no confirmed after-cost surface-relative mispricing")
        status = "active" if self._active else "warming" if warmup or reference_warming else "clear"
        return self._frame(
            now=now,
            status=status,
            reasons=tuple(reasons),
            eligible_count=len(observations),
            ineligible=counter,
            tested_count=len(preliminary),
            outside_count=len(outside_band),
            fdr_count=len(significant_ids),
            exact_count=len(exact),
            reference_warming_count=reference_warming,
            reference_rejected_count=reference_rejected,
            successful_folds=len(references),
            failed_folds=failed_folds,
        )
