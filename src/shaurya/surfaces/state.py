"""REQ-SUR-07: temporal smoothing and strategy-supplied staleness semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .essvi import ESSVISlice, ESSVISurface, SurfaceCalibrationError


@dataclass(slots=True)
class ESSVITemporalSmoother:
    """Online time-decayed parameter smoother for consecutive constrained eSSVI fits.

    The smoother keys slices by absolute expiry, carries the latest time-to-expiry and
    forward, intersects observed strike support, and independently reruns arbitrage checks.
    It never labels a single raw frame as smoothed. If a parameter blend fails the checks,
    it is moved toward the latest accepted raw fit until it becomes feasible; that fallback
    strength is reported in diagnostics.
    """

    half_life_seconds: float = 15.0
    max_history: int = 12
    _history: list[ESSVISurface] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.half_life_seconds <= 0:
            raise ValueError("smoothing half-life must be positive")
        if self.max_history < 2:
            raise ValueError("smoothing history must retain at least two raw fits")

    def reset(self) -> None:
        """Start a new smoothing epoch after a stale gap or instrument-scope change."""

        self._history.clear()

    def update(self, raw_surface: ESSVISurface) -> ESSVISurface:
        if raw_surface.is_temporally_smoothed:
            raise ValueError("smoother accepts raw eSSVI fits, not already-smoothed surfaces")
        if self._history:
            previous = self._history[-1]
            if raw_surface.instrument_scope != previous.instrument_scope:
                raise ValueError("instrument scope changed; reset the smoother first")
            if raw_surface.surface_timestamp <= previous.surface_timestamp:
                raise ValueError("raw surface timestamps must increase strictly")
            if {item.expiry for item in raw_surface.slices} != {
                item.expiry for item in previous.slices
            }:
                raise ValueError("expiry set changed; reset the smoother first")
        self._history.append(raw_surface)
        self._history = self._history[-self.max_history :]
        if len(self._history) == 1:
            return raw_surface

        newest_timestamp = raw_surface.surface_timestamp
        decay_rate = math.log(2.0) / self.half_life_seconds
        raw_weights = [
            math.exp(
                -decay_rate
                * max(0.0, (newest_timestamp - item.surface_timestamp).total_seconds())
            )
            for item in self._history
        ]
        weight_sum = sum(raw_weights)
        weights = tuple(value / weight_sum for value in raw_weights)
        candidate_slices = self._weighted_slices(weights)
        fallback_alpha = 0.0
        candidate = self._build_surface(
            raw_surface=raw_surface,
            slices=candidate_slices,
            weights=weights,
            fallback_alpha=fallback_alpha,
        )
        if not self._acceptable(candidate):
            low = 0.0
            high = 1.0
            latest_by_expiry = {item.expiry: item for item in raw_surface.slices}
            for _ in range(40):
                middle = 0.5 * (low + high)
                blended = tuple(
                    self._blend_slice(item, latest_by_expiry[item.expiry], middle)
                    for item in candidate_slices
                )
                attempt = self._build_surface(
                    raw_surface=raw_surface,
                    slices=blended,
                    weights=weights,
                    fallback_alpha=middle,
                )
                if self._acceptable(attempt):
                    high = middle
                    candidate = attempt
                else:
                    low = middle
            fallback_alpha = high
            candidate = self._build_surface(
                raw_surface=raw_surface,
                slices=tuple(
                    self._blend_slice(item, latest_by_expiry[item.expiry], fallback_alpha)
                    for item in candidate_slices
                ),
                weights=weights,
                fallback_alpha=fallback_alpha,
            )
        if not self._acceptable(candidate):
            raise SurfaceCalibrationError(
                "temporal eSSVI smoothing could not preserve no-arbitrage"
            )
        return candidate

    def _weighted_slices(self, weights: tuple[float, ...]) -> tuple[ESSVISlice, ...]:
        slices_by_surface = [
            {fitted_slice.expiry: fitted_slice for fitted_slice in surface.slices}
            for surface in self._history
        ]
        latest = self._history[-1]
        result: list[ESSVISlice] = []
        for latest_slice in latest.slices:
            expiry = latest_slice.expiry
            components = [value[expiry] for value in slices_by_surface]
            lower = max(item.min_log_moneyness for item in components)
            upper = min(item.max_log_moneyness for item in components)
            if lower >= upper:
                raise SurfaceCalibrationError(
                    f"no common strike support remains for smoothed expiry {expiry.isoformat()}"
                )
            theta = sum(
                weight * item.theta
                for weight, item in zip(weights, components, strict=True)
            )
            rho = sum(
                weight * item.rho
                for weight, item in zip(weights, components, strict=True)
            )
            psi = sum(
                weight * item.psi
                for weight, item in zip(weights, components, strict=True)
            )
            result.append(
                ESSVISlice(
                    expiry=expiry,
                    maturity_years=latest_slice.maturity_years,
                    forward=latest_slice.forward,
                    theta=theta,
                    rho=rho,
                    psi=psi,
                    min_log_moneyness=lower,
                    max_log_moneyness=upper,
                    quote_count=min(item.quote_count for item in components),
                )
            )
        return tuple(result)

    @staticmethod
    def _blend_slice(
        candidate: ESSVISlice, latest: ESSVISlice, alpha: float
    ) -> ESSVISlice:
        return ESSVISlice(
            expiry=candidate.expiry,
            maturity_years=latest.maturity_years,
            forward=latest.forward,
            theta=((1.0 - alpha) * candidate.theta) + (alpha * latest.theta),
            rho=((1.0 - alpha) * candidate.rho) + (alpha * latest.rho),
            psi=((1.0 - alpha) * candidate.psi) + (alpha * latest.psi),
            min_log_moneyness=candidate.min_log_moneyness,
            max_log_moneyness=candidate.max_log_moneyness,
            quote_count=candidate.quote_count,
        )

    def _build_surface(
        self,
        *,
        raw_surface: ESSVISurface,
        slices: tuple[ESSVISlice, ...],
        weights: tuple[float, ...],
        fallback_alpha: float,
    ) -> ESSVISurface:
        source_metrics = dict(raw_surface._fit_metrics)
        source_metrics["fit_status"] = "temporally_smoothed"
        source_metrics["smoothing"] = {
            "method": "time_decayed_parameter_ewma",
            "half_life_seconds": self.half_life_seconds,
            "component_count": len(self._history),
            "component_surface_timestamps": [
                item.surface_timestamp.isoformat() for item in self._history
            ],
            "normalized_weights_oldest_to_newest": list(weights),
            "latest_raw_fallback_alpha": fallback_alpha,
            "support_rule": "intersection",
            "arbitrage_rechecked": True,
        }
        return ESSVISurface(
            _slices=slices,
            _observations=raw_surface._observations,
            _surface_timestamp=raw_surface.surface_timestamp,
            _instrument_scope=raw_surface.instrument_scope,
            _fit_metrics=source_metrics,
            _policy=raw_surface._policy,
            _temporally_smoothed=(
                len(self._history) >= 2 and fallback_alpha < (1.0 - 1e-9)
            ),
        )

    @staticmethod
    def _acceptable(surface: ESSVISurface) -> bool:
        previous_theta = -math.inf
        for fitted_slice in surface.slices:
            butterfly_one = fitted_slice.psi * (1.0 + abs(fitted_slice.rho))
            butterfly_two = (fitted_slice.psi**2) * (1.0 + abs(fitted_slice.rho))
            if butterfly_one > 4.0 + 1e-10:
                return False
            if butterfly_two > (4.0 * fitted_slice.theta) + 1e-10:
                return False
            if fitted_slice.theta < previous_theta - 1e-10:
                return False
            previous_theta = fitted_slice.theta
        return surface.arb_check().passed


def staleness_measurement(*, age_seconds: float, threshold_seconds: float) -> bool:
    """Return the flag under a caller-supplied tolerance; Shaurya chooses no threshold."""

    if age_seconds < 0 or threshold_seconds < 0:
        raise ValueError("surface age and staleness threshold must be non-negative")
    return age_seconds > threshold_seconds
