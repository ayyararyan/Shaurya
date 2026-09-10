"""Surface-derived NIFTY variance-carry state.

Two model generations intentionally coexist here:

* the legacy frozen NSGVC IV-only mapping, retained byte-for-byte for historical
  reproducibility; and
* the explicit RV-V2 Day + Gamma-night adapter, which requires the complete
  causal 10:00 feature state and therefore fails closed when those inputs are not
  supplied.

Neither object places orders. Trading consumers must choose the model version
explicitly; the presence of legacy ``NSGVC_Q_THRESHOLD = 0.70`` does not redefine
RV-V2's calibrated ``q < 0.825`` rule.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from shaurya.analytics.rv_model import (
    RV_V2_Q_THRESHOLD,
    FrozenRVFeatures,
    FrozenRVForecast,
    forecast_frozen_rv,
)
from shaurya.surfaces.essvi import ESSVISlice, ESSVISurface

NSGVC_Q_MODEL_VERSION = "nsgvc_iv_only_2023_2025_v1"
NSGVC_Q_MODEL_SCOPE = "nearest_weekly_only"
NSGVC_Q_THRESHOLD = 0.70
NSGVC_RR400_THRESHOLD = 0.0270810062

NSGVC_LOG_PRED_INTERCEPT = -0.8941884292
NSGVC_LOG_IV_INT_COEF = 0.9083950192
NSGVC_LOG_T_COEF = 0.0481227276

NIFTY_STRIKE_STEP = 50.0
RR400_WING_POINTS = 400.0


@dataclass(frozen=True, slots=True)
class RealizedVolatilityForecast:
    """Legacy NSGVC nearest-weekly RV forecast in variance and vol units."""

    atm_iv: float
    maturity_years: float
    implied_integrated_variance: float
    forecast_integrated_realized_variance: float
    forecast_annualized_realized_variance: float
    forecast_annualized_realized_volatility: float
    q_ratio: float
    rv_iv_vol_ratio: float
    q_reference_threshold: float
    q_below_reference: bool
    model_version: str = NSGVC_Q_MODEL_VERSION
    model_scope: str = NSGVC_Q_MODEL_SCOPE

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def nearest_strike(value: float, *, step: float = NIFTY_STRIKE_STEP) -> float:
    """Round to the nearest NIFTY strike with deterministic half-up ties."""

    if not math.isfinite(value) or value <= 0.0 or step <= 0.0:
        raise ValueError("value and strike step must be finite and positive")
    return step * math.floor((value / step) + 0.5)


def forecast_integrated_realized_variance(
    *, implied_integrated_variance: float, maturity_years: float
) -> float:
    """Legacy frozen NSGVC IV-only nearest-weekly mapping."""

    if (
        not math.isfinite(implied_integrated_variance)
        or not math.isfinite(maturity_years)
        or implied_integrated_variance <= 0.0
        or maturity_years <= 0.0
    ):
        raise ValueError("integrated variance and maturity must be finite and positive")
    log_prediction = (
        NSGVC_LOG_PRED_INTERCEPT
        + NSGVC_LOG_IV_INT_COEF * math.log(implied_integrated_variance)
        + NSGVC_LOG_T_COEF * math.log(maturity_years)
    )
    return math.exp(log_prediction)


def realized_volatility_forecast(
    *, atm_iv: float, maturity_years: float
) -> RealizedVolatilityForecast:
    """Evaluate the legacy NSGVC ATM-IV-only forecast.

    New trading code should use ``frozen_rv_v2_forecast_from_slice`` with a
    complete :class:`FrozenRVFeatures` state. This function remains intentionally
    unchanged in its economics so old research/tests stay reproducible.
    """

    if (
        not math.isfinite(atm_iv)
        or not math.isfinite(maturity_years)
        or atm_iv <= 0.0
        or maturity_years <= 0.0
    ):
        raise ValueError("ATM IV and maturity must be finite and positive")
    implied_integrated = (atm_iv**2) * maturity_years
    forecast_integrated = forecast_integrated_realized_variance(
        implied_integrated_variance=implied_integrated,
        maturity_years=maturity_years,
    )
    annualized_variance = forecast_integrated / maturity_years
    annualized_volatility = math.sqrt(annualized_variance)
    ratio = forecast_integrated / implied_integrated
    return RealizedVolatilityForecast(
        atm_iv=atm_iv,
        maturity_years=maturity_years,
        implied_integrated_variance=implied_integrated,
        forecast_integrated_realized_variance=forecast_integrated,
        forecast_annualized_realized_variance=annualized_variance,
        forecast_annualized_realized_volatility=annualized_volatility,
        q_ratio=ratio,
        rv_iv_vol_ratio=math.sqrt(ratio),
        q_reference_threshold=NSGVC_Q_THRESHOLD,
        q_below_reference=ratio <= NSGVC_Q_THRESHOLD,
    )


def frozen_rv_v2_forecast_from_slice(
    slice_: ESSVISlice,
    *,
    features: FrozenRVFeatures,
) -> FrozenRVForecast:
    """Evaluate the production-candidate RV-V2 forecast from one front eSSVI slice.

    The eSSVI slice supplies only the frozen IV anchor ``theta`` and maturity.
    Historical/current-session state is required explicitly. No legacy fallback is
    permitted because that would silently change the model whenever a feature is
    unavailable.
    """

    if slice_.maturity_years <= 0.0 or slice_.theta <= 0.0:
        raise ValueError("front eSSVI slice must have positive maturity and theta")
    return forecast_frozen_rv(
        implied_integrated_variance=slice_.theta,
        maturity_years=slice_.maturity_years,
        features=features,
    )


def front_frozen_rv_v2_forecast(
    surface: ESSVISurface,
    *,
    features: FrozenRVFeatures,
) -> FrozenRVForecast:
    """Evaluate RV-V2 on the nearest fitted eSSVI expiry."""

    if not surface.slices:
        raise ValueError("eSSVI surface has no fitted slices")
    front = min(surface.slices, key=lambda item: item.maturity_years)
    return frozen_rv_v2_forecast_from_slice(front, features=features)


def q_ratio(*, implied_integrated_variance: float, maturity_years: float) -> float:
    """Legacy NSGVC forecast RV / IV ratio in integrated-variance units."""

    prediction = forecast_integrated_realized_variance(
        implied_integrated_variance=implied_integrated_variance,
        maturity_years=maturity_years,
    )
    return prediction / implied_integrated_variance


def _slice_iv_at_strike(slice_: ESSVISlice, strike: float) -> tuple[float | None, str | None]:
    if strike <= 0.0 or slice_.maturity_years <= 0.0:
        return None, "invalid_strike_or_maturity"
    log_moneyness = math.log(strike / slice_.forward)
    if (
        log_moneyness < slice_.min_log_moneyness
        or log_moneyness > slice_.max_log_moneyness
    ):
        return None, "strike_outside_fitted_support"
    total_variance = slice_.total_variance(log_moneyness)
    if not math.isfinite(total_variance) or total_variance <= 0.0:
        return None, "invalid_surface_total_variance"
    return math.sqrt(total_variance / slice_.maturity_years), None


@dataclass(frozen=True, slots=True)
class VarianceCarryState:
    """Legacy front-expiry NSGVC q and 400-point risk reversal state."""

    expiry: str
    maturity_days: float
    forward: float
    atm_strike: float
    atm_iv: float
    implied_integrated_variance: float
    forecast_integrated_realized_variance: float
    forecast_annualized_realized_variance: float
    forecast_annualized_rv: float
    q_ratio: float
    rv_iv_vol_ratio: float
    q_reference_threshold: float
    q_below_reference: bool
    put_400_iv: float | None
    call_400_iv: float | None
    rr400: float | None
    rr400_reference_threshold: float
    rr400_below_reference: bool | None
    rr400_reason: str | None
    q_model_version: str = NSGVC_Q_MODEL_VERSION
    q_model_scope: str = NSGVC_Q_MODEL_SCOPE
    rr400_role: str = "regime_conditioned_state_not_master_veto"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def variance_carry_state_from_slice(slice_: ESSVISlice) -> VarianceCarryState:
    """Build the legacy weekly NSGVC carry state from the front eSSVI slice.

    ``q`` uses ATM integrated variance ``theta`` from eSSVI. ``RR400`` is
    ``IV(K_atm-400) - IV(K_atm+400)`` where ``K_atm`` is the nearest 50-point
    strike to the slice forward. RR400 is unavailable rather than extrapolated
    when either wing lies outside observed eSSVI support.
    """

    if slice_.maturity_years <= 0.0 or slice_.theta <= 0.0 or slice_.forward <= 0.0:
        raise ValueError("front eSSVI slice must have positive maturity, theta, and forward")

    atm_iv = math.sqrt(slice_.theta / slice_.maturity_years)
    forecast = realized_volatility_forecast(
        atm_iv=atm_iv,
        maturity_years=slice_.maturity_years,
    )

    strike0 = nearest_strike(slice_.forward)
    put_strike = strike0 - RR400_WING_POINTS
    call_strike = strike0 + RR400_WING_POINTS
    put_iv, put_reason = _slice_iv_at_strike(slice_, put_strike)
    call_iv, call_reason = _slice_iv_at_strike(slice_, call_strike)

    rr400_value: float | None
    rr400_reason: str | None
    if put_iv is None or call_iv is None:
        rr400_value = None
        reasons = sorted(
            {
                reason
                for reason in (put_reason, call_reason)
                if reason is not None
            }
        )
        rr400_reason = "+".join(reasons) or "rr400_unavailable"
    else:
        rr400_value = put_iv - call_iv
        rr400_reason = None

    return VarianceCarryState(
        expiry=slice_.expiry.isoformat(),
        maturity_days=slice_.maturity_years * 365.25,
        forward=slice_.forward,
        atm_strike=strike0,
        atm_iv=forecast.atm_iv,
        implied_integrated_variance=forecast.implied_integrated_variance,
        forecast_integrated_realized_variance=forecast.forecast_integrated_realized_variance,
        forecast_annualized_realized_variance=forecast.forecast_annualized_realized_variance,
        forecast_annualized_rv=forecast.forecast_annualized_realized_volatility,
        q_ratio=forecast.q_ratio,
        rv_iv_vol_ratio=forecast.rv_iv_vol_ratio,
        q_reference_threshold=forecast.q_reference_threshold,
        q_below_reference=forecast.q_below_reference,
        put_400_iv=put_iv,
        call_400_iv=call_iv,
        rr400=rr400_value,
        rr400_reference_threshold=NSGVC_RR400_THRESHOLD,
        rr400_below_reference=(
            rr400_value <= NSGVC_RR400_THRESHOLD if rr400_value is not None else None
        ),
        rr400_reason=rr400_reason,
    )


def front_variance_carry_state(surface: ESSVISurface) -> VarianceCarryState:
    """Return legacy NSGVC q/RR400 for the nearest fitted expiry."""

    if not surface.slices:
        raise ValueError("eSSVI surface has no fitted slices")
    front = min(surface.slices, key=lambda item: item.maturity_years)
    return variance_carry_state_from_slice(front)


__all__ = [
    "NSGVC_Q_MODEL_VERSION",
    "NSGVC_Q_MODEL_SCOPE",
    "NSGVC_Q_THRESHOLD",
    "NSGVC_RR400_THRESHOLD",
    "NSGVC_LOG_PRED_INTERCEPT",
    "NSGVC_LOG_IV_INT_COEF",
    "NSGVC_LOG_T_COEF",
    "RV_V2_Q_THRESHOLD",
    "FrozenRVFeatures",
    "FrozenRVForecast",
    "forecast_frozen_rv",
    "frozen_rv_v2_forecast_from_slice",
    "front_frozen_rv_v2_forecast",
    "forecast_integrated_realized_variance",
    "realized_volatility_forecast",
    "q_ratio",
    "nearest_strike",
    "VarianceCarryState",
    "variance_carry_state_from_slice",
    "front_variance_carry_state",
]
