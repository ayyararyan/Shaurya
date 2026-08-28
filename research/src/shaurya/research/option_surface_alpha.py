"""Causal intraday option-surface factors and guarded research evaluation.

The module deliberately separates representation quality from trading claims.  Surface
parameters are computed from quotes available at the current timestamp.  Candidate models are
selected on a discovery session, calibrated on a later validation session, and may only inspect a
final session after the validation gates pass.
"""

# ruff: noqa: UP045 - the remote Apple research environment uses Python 3.9.

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np
from numpy.typing import NDArray
from scipy import stats

FloatArray = NDArray[np.float64]


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black76_price(
    *,
    forward: float,
    strike: float,
    maturity_years: float,
    volatility: float,
    risk_free_rate: float,
    is_call: bool,
) -> float:
    discount = math.exp(-risk_free_rate * maturity_years)
    sigma_root_t = volatility * math.sqrt(maturity_years)
    if sigma_root_t <= 0.0:
        intrinsic = max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
        return discount * intrinsic
    d1 = math.log(forward / strike) / sigma_root_t + 0.5 * sigma_root_t
    d2 = d1 - sigma_root_t
    if is_call:
        return discount * (forward * _normal_cdf(d1) - strike * _normal_cdf(d2))
    return discount * (strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1))


def _implied_volatility(
    *,
    price: float,
    forward: float,
    strike: float,
    maturity_years: float,
    risk_free_rate: float,
    is_call: bool,
) -> Optional[float]:
    if price <= 0.0:
        return None
    discount = math.exp(-risk_free_rate * maturity_years)
    intrinsic = discount * (
        max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    )
    maximum = discount * (forward if is_call else strike)
    if price < intrinsic - max(1e-10, maximum * 1e-12) or price >= maximum:
        return None
    low, high = 1e-6, 5.0
    if _black76_price(
        forward=forward,
        strike=strike,
        maturity_years=maturity_years,
        volatility=high,
        risk_free_rate=risk_free_rate,
        is_call=is_call,
    ) < price:
        return None
    for _ in range(80):
        middle = 0.5 * (low + high)
        fitted = _black76_price(
            forward=forward,
            strike=strike,
            maturity_years=maturity_years,
            volatility=middle,
            risk_free_rate=risk_free_rate,
            is_call=is_call,
        )
        if fitted < price:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


@dataclass(frozen=True)
class SurfaceQuote:
    strike: float
    is_call: bool
    bid: float
    ask: float
    depth_imbalance: float = 0.0


@dataclass(frozen=True)
class SurfaceFactors:
    atm_iv: float
    variance_skew: float
    variance_curvature: float
    fit_rmse_iv: float
    quote_count: int
    median_relative_spread: float
    median_depth_imbalance: float
    parity_residual_rms_to_forward: float

    def values(self) -> tuple[float, ...]:
        return (
            self.atm_iv,
            self.variance_skew,
            self.variance_curvature,
            self.fit_rmse_iv,
            float(self.quote_count),
            self.median_relative_spread,
            self.median_depth_imbalance,
            self.parity_residual_rms_to_forward,
        )


SURFACE_FACTOR_NAMES = (
    "atm_iv",
    "variance_skew",
    "variance_curvature",
    "fit_rmse_iv",
    "quote_count",
    "median_relative_spread",
    "median_depth_imbalance",
    "parity_residual_rms_to_forward",
)


def fit_surface_factors(
    quotes: list[SurfaceQuote],
    *,
    forward: float,
    maturity_years: float,
    risk_free_rate: float = 0.06,
    moneyness_limit: float = 0.03,
) -> Optional[SurfaceFactors]:
    """Fit compact weighted total-variance factors from current OTM quotes only."""

    if forward <= 0.0 or maturity_years <= 0.0:
        return None
    observations: list[tuple[float, float, float, float, float]] = []
    parity: dict[float, dict[bool, float]] = {}
    relative_spreads: list[float] = []
    imbalances: list[float] = []
    discount = math.exp(-risk_free_rate * maturity_years)
    for quote in quotes:
        if quote.strike <= 0.0 or quote.bid <= 0.0 or quote.ask <= quote.bid:
            continue
        log_moneyness = math.log(quote.strike / forward)
        if abs(log_moneyness) > moneyness_limit:
            continue
        mid = 0.5 * (quote.bid + quote.ask)
        relative_spread = (quote.ask - quote.bid) / mid
        relative_spreads.append(relative_spread)
        imbalances.append(quote.depth_imbalance)
        parity.setdefault(quote.strike, {})[quote.is_call] = mid
        is_otm = (quote.is_call and quote.strike >= forward) or (
            not quote.is_call and quote.strike <= forward
        )
        if not is_otm:
            continue
        mid_iv = _implied_volatility(
            price=mid,
            forward=forward,
            strike=quote.strike,
            maturity_years=maturity_years,
            risk_free_rate=risk_free_rate,
            is_call=quote.is_call,
        )
        bid_iv = _implied_volatility(
            price=quote.bid,
            forward=forward,
            strike=quote.strike,
            maturity_years=maturity_years,
            risk_free_rate=risk_free_rate,
            is_call=quote.is_call,
        )
        ask_iv = _implied_volatility(
            price=quote.ask,
            forward=forward,
            strike=quote.strike,
            maturity_years=maturity_years,
            risk_free_rate=risk_free_rate,
            is_call=quote.is_call,
        )
        if mid_iv is None or not math.isfinite(mid_iv):
            continue
        iv_width = (
            max(ask_iv - bid_iv, 1e-5)
            if bid_iv is not None and ask_iv is not None
            else max(relative_spread * mid_iv, 1e-5)
        )
        weight = min(1.0 / (iv_width * iv_width), 1e8)
        observations.append(
            (log_moneyness, mid_iv * mid_iv * maturity_years, weight, mid_iv, iv_width)
        )
    if len(observations) < 5 or len({round(item[0], 8) for item in observations}) < 5:
        return None
    x = np.asarray([item[0] for item in observations], dtype=np.float64)
    total_variance = np.asarray([item[1] for item in observations], dtype=np.float64)
    weights = np.asarray([item[2] for item in observations], dtype=np.float64)
    design = np.column_stack((np.ones_like(x), x, x * x))
    root_weight = np.sqrt(weights / np.max(weights))
    coefficients, *_ = np.linalg.lstsq(
        design * root_weight[:, None], total_variance * root_weight, rcond=None
    )
    fitted_variance = design @ coefficients
    fitted_iv = np.sqrt(np.maximum(fitted_variance, 1e-12) / maturity_years)
    observed_iv = np.asarray([item[3] for item in observations], dtype=np.float64)
    atm_variance = max(float(coefficients[0]), 1e-12)
    parity_residuals = []
    for strike, pair in parity.items():
        if True in pair and False in pair:
            expected = discount * (forward - strike)
            parity_residuals.append((pair[True] - pair[False] - expected) / forward)
    return SurfaceFactors(
        atm_iv=math.sqrt(atm_variance / maturity_years),
        variance_skew=float(coefficients[1]),
        variance_curvature=float(coefficients[2]),
        fit_rmse_iv=float(np.sqrt(np.mean(np.square(observed_iv - fitted_iv)))),
        quote_count=len(observations),
        median_relative_spread=float(np.median(relative_spreads)),
        median_depth_imbalance=float(np.median(imbalances)),
        parity_residual_rms_to_forward=(
            float(np.sqrt(np.mean(np.square(parity_residuals)))) if parity_residuals else math.nan
        ),
    )


@dataclass(frozen=True)
class SelectionGate:
    minimum_validation_samples: int = 250
    minimum_validation_skill: float = 0.0
    maximum_validation_p_value: float = 0.05
    minimum_seed_pass_rate: float = 0.6


DEFAULT_SELECTION_GATE = SelectionGate()


@dataclass(frozen=True)
class ValidationResult:
    name: str
    discovery_skill: float
    validation_skill: float
    validation_p_value: float
    validation_samples: int
    seed_pass_rate: float
    promoted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mae_skill(y_true: FloatArray, prediction: FloatArray, baseline: FloatArray) -> float:
    denominator = float(np.mean(np.abs(y_true - baseline)))
    if denominator <= 0.0:
        return 0.0
    return 1.0 - float(np.mean(np.abs(y_true - prediction))) / denominator


def block_bootstrap_p_value(
    candidate_losses: FloatArray,
    baseline_losses: FloatArray,
    *,
    block_size: int = 12,
    replicates: int = 2_000,
    seed: int = 42,
) -> float:
    """One-sided paired stationary-block approximation for lower candidate loss."""

    improvement = baseline_losses - candidate_losses
    improvement = improvement[np.isfinite(improvement)]
    if len(improvement) < 2:
        return 1.0
    observed = float(np.mean(improvement))
    centered = improvement - observed
    rng = np.random.default_rng(seed)
    starts = np.arange(len(centered))
    simulated = np.empty(replicates, dtype=np.float64)
    blocks_needed = math.ceil(len(centered) / block_size)
    for index in range(replicates):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate(
            [centered[(start + np.arange(block_size)) % len(centered)] for start in chosen]
        )[: len(centered)]
        simulated[index] = np.mean(sample)
    return float((1 + np.count_nonzero(simulated >= observed)) / (replicates + 1))


def validate_candidate(
    *,
    name: str,
    discovery_target: FloatArray,
    discovery_prediction: FloatArray,
    discovery_baseline: FloatArray,
    validation_target: FloatArray,
    validation_predictions: list[FloatArray],
    validation_baseline: FloatArray,
    gate: SelectionGate = DEFAULT_SELECTION_GATE,
) -> ValidationResult:
    """Apply a frozen multi-seed gate without reading a final-test target."""

    if not validation_predictions:
        raise ValueError("at least one validation prediction is required")
    skills = [
        mae_skill(validation_target, prediction, validation_baseline)
        for prediction in validation_predictions
    ]
    median_prediction = np.median(np.stack(validation_predictions), axis=0)
    candidate_losses = np.abs(validation_target - median_prediction)
    baseline_losses = np.abs(validation_target - validation_baseline)
    p_value = block_bootstrap_p_value(candidate_losses, baseline_losses)
    pass_rate = float(np.mean(np.asarray(skills) > gate.minimum_validation_skill))
    median_skill = float(np.median(skills))
    promoted = bool(
        len(validation_target) >= gate.minimum_validation_samples
        and median_skill > gate.minimum_validation_skill
        and p_value <= gate.maximum_validation_p_value
        and pass_rate >= gate.minimum_seed_pass_rate
    )
    return ValidationResult(
        name=name,
        discovery_skill=mae_skill(
            discovery_target, discovery_prediction, discovery_baseline
        ),
        validation_skill=median_skill,
        validation_p_value=p_value,
        validation_samples=len(validation_target),
        seed_pass_rate=pass_rate,
        promoted=promoted,
    )


def holm_rejections(p_values: dict[str, float], alpha: float = 0.05) -> set[str]:
    """Return hypotheses rejected by Holm's step-down family-wise correction."""

    ordered = sorted(p_values.items(), key=lambda item: item[1])
    rejected: set[str] = set()
    for index, (name, p_value) in enumerate(ordered):
        threshold = alpha / (len(ordered) - index)
        if p_value > threshold:
            break
        rejected.add(name)
    return rejected


def paired_t_diagnostic(candidate_losses: FloatArray, baseline_losses: FloatArray) -> float:
    """Secondary diagnostic only; block bootstrap remains the promotion statistic."""

    result = stats.ttest_rel(baseline_losses, candidate_losses, alternative="greater")
    return float(result.pvalue) if math.isfinite(float(result.pvalue)) else 1.0


def conformal_positions(
    prediction: FloatArray,
    calibration_errors: FloatArray,
    round_trip_cost_bps: FloatArray,
    *,
    error_rate: float = 0.10,
) -> NDArray[np.int8]:
    """Trade only when a split-conformal error bound still clears quoted costs."""

    if not 0.0 < error_rate < 1.0:
        raise ValueError("error_rate must be strictly between zero and one")
    errors = calibration_errors[np.isfinite(calibration_errors)]
    if len(errors) < 20:
        return np.zeros(len(prediction), dtype=np.int8)
    quantile = float(np.quantile(errors, 1.0 - error_rate, method="higher"))
    edge = np.abs(prediction) - quantile - round_trip_cost_bps
    return np.where(edge > 0.0, np.sign(prediction), 0.0).astype(np.int8)


def executable_straddle_pnl_bps(
    positions: NDArray[np.int8],
    *,
    entry_bid_to_forward: FloatArray,
    entry_ask_to_forward: FloatArray,
    exit_bid_to_forward: FloatArray,
    exit_ask_to_forward: FloatArray,
) -> FloatArray:
    """Realized long/short straddle P&L using the adverse side at entry and exit."""

    long_pnl = (exit_bid_to_forward - entry_ask_to_forward) * 10_000.0
    short_pnl = (entry_bid_to_forward - exit_ask_to_forward) * 10_000.0
    return np.where(positions > 0, long_pnl, np.where(positions < 0, short_pnl, 0.0))
