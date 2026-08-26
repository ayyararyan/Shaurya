"""REQ-SUR-02/05/06/08: synchronized constrained eSSVI calibration."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from pydantic.types import JsonValue
from scipy.optimize import minimize
from shaurya.contracts.tape import QualityFlag, TapeRow
from shaurya.contracts.timing import IST

from shaurya.research_contracts.surface import FitDiagnostic, SurfaceParameter

from .arbitrage import ArbitrageKind, ArbitrageReport, ArbitrageViolation, check_arbitrage
from .base import EvaluationStatus, SurfaceEvaluation, SurfaceFitRequest, VolatilitySurface
from .interpolation import SurfaceInterpolationPolicy

SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
_CALENDAR_GRID_POINTS = 31
_ARBITRAGE_GRID_POINTS = 81
_PARAMETER_TOLERANCE = 1e-8


class SurfaceCalibrationError(RuntimeError):
    """Calibration failed or produced a surface that failed its acceptance gates."""


class InsufficientSurfaceData(SurfaceCalibrationError):
    """The observed chain cannot identify all requested maturity slices."""


@dataclass(frozen=True, slots=True)
class ESSVISlice:
    expiry: date
    maturity_years: float
    forward: float
    theta: float
    rho: float
    psi: float
    min_log_moneyness: float
    max_log_moneyness: float
    quote_count: int

    def total_variance(self, log_moneyness: float) -> float:
        return ESSVISurface.total_variance(
            log_moneyness,
            theta=self.theta,
            rho=self.rho,
            psi=self.psi,
        )


@dataclass(frozen=True, slots=True)
class _Observation:
    expiry: date
    maturity_years: float
    forward: float
    log_moneyness: float
    total_variance: float
    weight: float
    instrument_id: str
    receive_timestamp: datetime


@dataclass(frozen=True, slots=True)
class _OptionIdentity:
    scope: str
    expiry: date
    strike: float
    is_call: bool


def _total_variance_array(
    log_moneyness: NDArray[np.float64], *, theta: float, rho: float, psi: float
) -> NDArray[np.float64]:
    core = np.sqrt(
        ((psi * log_moneyness) + (rho * theta)) ** 2
        + (theta**2 * (1.0 - rho**2))
    )
    return np.asarray(
        0.5 * (theta + (rho * psi * log_moneyness) + core), dtype=np.float64
    )


def _option_identity(instrument_id: str) -> _OptionIdentity | None:
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
    return _OptionIdentity(
        scope=":".join(parts[:3]),
        expiry=expiry,
        strike=strike,
        is_call=option_type == "CE",
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black76_price(
    *,
    forward: float,
    strike: float,
    maturity_years: float,
    volatility: float,
    risk_free_rate: float,
    is_call: bool,
) -> float:
    """Discounted Black-76 price, also used by deterministic synthetic fixtures."""

    if forward <= 0 or strike <= 0 or maturity_years <= 0 or volatility < 0:
        raise ValueError("Black-76 inputs must be positive (volatility may be zero)")
    discount = math.exp(-risk_free_rate * maturity_years)
    intrinsic = max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    if volatility == 0:
        return discount * intrinsic
    sigma_root_t = volatility * math.sqrt(maturity_years)
    d1 = (math.log(forward / strike) / sigma_root_t) + (0.5 * sigma_root_t)
    d2 = d1 - sigma_root_t
    if is_call:
        return discount * ((forward * _normal_cdf(d1)) - (strike * _normal_cdf(d2)))
    return discount * ((strike * _normal_cdf(-d2)) - (forward * _normal_cdf(-d1)))


def _implied_volatility(
    *,
    price: float,
    forward: float,
    strike: float,
    maturity_years: float,
    risk_free_rate: float,
    is_call: bool,
) -> float | None:
    if price <= 0:
        return None
    discount = math.exp(-risk_free_rate * maturity_years)
    intrinsic = discount * (
        max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    )
    maximum = discount * (forward if is_call else strike)
    tolerance = max(1e-10, maximum * 1e-12)
    if price < intrinsic - tolerance or price >= maximum:
        return None
    low = 1e-6
    high = 5.0
    if black76_price(
        forward=forward,
        strike=strike,
        maturity_years=maturity_years,
        volatility=high,
        risk_free_rate=risk_free_rate,
        is_call=is_call,
    ) < price:
        return None
    for _ in range(100):
        middle = 0.5 * (low + high)
        model_price = black76_price(
            forward=forward,
            strike=strike,
            maturity_years=maturity_years,
            volatility=middle,
            risk_free_rate=risk_free_rate,
            is_call=is_call,
        )
        if model_price < price:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def implied_volatility(
    *,
    price: float,
    forward: float,
    strike: float,
    maturity_years: float,
    risk_free_rate: float,
    is_call: bool,
) -> float | None:
    """Public Black-76 inversion used by analytics outside the surface fitter.

    Returning ``None`` preserves the fitter's existing explicit data-insufficient semantics
    for prices outside discounted intrinsic/maximum bounds.
    """

    return _implied_volatility(
        price=price,
        forward=forward,
        strike=strike,
        maturity_years=maturity_years,
        risk_free_rate=risk_free_rate,
        is_call=is_call,
    )


def _latest_rows(rows: tuple[TapeRow, ...]) -> tuple[TapeRow, ...]:
    latest: dict[str, TapeRow] = {}
    for row in rows:
        incumbent = latest.get(row.instrument_id)
        if incumbent is None or (row.receive_ts, row.receive_sequence) > (
            incumbent.receive_ts,
            incumbent.receive_sequence,
        ):
            latest[row.instrument_id] = row
    return tuple(latest.values())


def _extract_observations(
    request: SurfaceFitRequest,
) -> tuple[tuple[_Observation, ...], tuple[str, ...], dict[str, int]]:
    excluded: Counter[str] = Counter()
    observations: list[_Observation] = []
    scopes: set[str] = set()
    invalid_flags = {QualityFlag.CROSSED_BOOK, QualityFlag.INVALID_DEPTH}

    for row in _latest_rows(request.tape_rows):
        identity = _option_identity(row.instrument_id)
        if identity is None:
            excluded["not_option_contract"] += 1
            continue
        if identity.expiry not in request.forward_by_expiry:
            excluded["expiry_not_requested"] += 1
            continue
        if invalid_flags.intersection(row.quality_flags):
            excluded["invalid_book_quality"] += 1
            continue
        bid = row.best_bid
        ask = row.best_ask
        if bid is None or ask is None or bid <= 0 or ask < bid:
            excluded["missing_or_crossed_bbo"] += 1
            continue
        forward = request.forward_by_expiry[identity.expiry]
        if (identity.is_call and identity.strike < forward) or (
            not identity.is_call and identity.strike > forward
        ):
            excluded["in_the_money_quote"] += 1
            continue
        expiry_timestamp = request.expiry_timestamp_by_expiry[identity.expiry]
        maturity = (
            expiry_timestamp - request.valuation_timestamp
        ).total_seconds() / SECONDS_PER_YEAR
        mid = 0.5 * (bid + ask)
        mid_iv = _implied_volatility(
            price=mid,
            forward=forward,
            strike=identity.strike,
            maturity_years=maturity,
            risk_free_rate=request.risk_free_rate,
            is_call=identity.is_call,
        )
        if mid_iv is None or not math.isfinite(mid_iv):
            excluded["implied_volatility_failure"] += 1
            continue
        bid_iv = _implied_volatility(
            price=bid,
            forward=forward,
            strike=identity.strike,
            maturity_years=maturity,
            risk_free_rate=request.risk_free_rate,
            is_call=identity.is_call,
        )
        ask_iv = _implied_volatility(
            price=ask,
            forward=forward,
            strike=identity.strike,
            maturity_years=maturity,
            risk_free_rate=request.risk_free_rate,
            is_call=identity.is_call,
        )
        variance_width = (
            maturity * max((ask_iv**2) - (bid_iv**2), 1e-8)
            if bid_iv is not None and ask_iv is not None
            else max((ask - bid) / mid, 1e-4)
        )
        observations.append(
            _Observation(
                expiry=identity.expiry,
                maturity_years=maturity,
                forward=forward,
                log_moneyness=math.log(identity.strike / forward),
                total_variance=(mid_iv**2) * maturity,
                weight=min(1.0 / (variance_width**2), 1e10),
                instrument_id=row.instrument_id,
                receive_timestamp=row.receive_ts.astimezone(IST),
            )
        )
        scopes.add(identity.scope)

    if len(scopes) != 1:
        raise InsufficientSurfaceData(
            "one eSSVI surface must represent exactly one broker-neutral underlying scope"
        )

    grouped: dict[date, list[_Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.expiry].append(observation)
    missing = {
        expiry: len(grouped.get(expiry, ()))
        for expiry in request.forward_by_expiry
        if len(grouped.get(expiry, ())) < request.min_quotes_per_slice
    }
    if missing:
        detail = ", ".join(
            f"{expiry.isoformat()}={count}" for expiry, count in sorted(missing.items())
        )
        raise InsufficientSurfaceData(
            f"insufficient usable OTM quotes per requested expiry ({detail}); "
            f"minimum={request.min_quotes_per_slice}; excluded={dict(excluded)}"
        )

    normalized: list[_Observation] = []
    for expiry in sorted(grouped):
        slice_rows = grouped[expiry]
        weight_sum = sum(item.weight for item in slice_rows)
        normalized.extend(replace(item, weight=item.weight / weight_sum) for item in slice_rows)
    return tuple(normalized), tuple(sorted(scopes)), dict(sorted(excluded.items()))


@dataclass(frozen=True, slots=True)
class ESSVISurface(VolatilitySurface):
    """Multi-maturity eSSVI surface calibrated in one constrained optimization."""

    _slices: tuple[ESSVISlice, ...]
    _observations: tuple[_Observation, ...]
    _surface_timestamp: datetime
    _instrument_scope: tuple[str, ...]
    _fit_metrics: dict[str, object]
    _policy: SurfaceInterpolationPolicy = SurfaceInterpolationPolicy()
    _temporally_smoothed: bool = False

    @staticmethod
    def total_variance(
        log_moneyness: float,
        *,
        theta: float,
        rho: float,
        psi: float,
    ) -> float:
        """eSSVI total variance using ``psi = theta * phi(theta)``."""

        core = math.sqrt(
            ((psi * log_moneyness) + (rho * theta)) ** 2
            + (theta**2 * (1.0 - rho**2))
        )
        return 0.5 * (theta + (rho * psi * log_moneyness) + core)

    @classmethod
    def fit(cls, request: SurfaceFitRequest) -> ESSVISurface:
        observations, scopes, excluded = _extract_observations(request)
        by_expiry: dict[date, list[_Observation]] = defaultdict(list)
        for observation in observations:
            by_expiry[observation.expiry].append(observation)
        expiries = tuple(sorted(by_expiry, key=lambda value: by_expiry[value][0].maturity_years))

        initial_values: list[float] = []
        previous_theta = 0.0
        for expiry in expiries:
            rows = by_expiry[expiry]
            atm = min(rows, key=lambda item: abs(item.log_moneyness))
            theta = max(atm.total_variance, previous_theta + 1e-5, 1e-5)
            rho = -0.30
            butterfly_cap = math.sqrt((4.0 * theta) / (1.0 + abs(rho)))
            psi = min(0.10, 0.5 * butterfly_cap, 2.0 / (1.0 + abs(rho)))
            initial_values.extend((theta, rho, max(psi, 1e-4)))
            previous_theta = theta
        initial = np.asarray(initial_values, dtype=np.float64)

        calendar_grids: list[tuple[int, int, NDArray[np.float64]]] = []
        for earlier_index, later_index in zip(
            range(len(expiries)), range(1, len(expiries)), strict=False
        ):
            earlier_rows = by_expiry[expiries[earlier_index]]
            later_rows = by_expiry[expiries[later_index]]
            lower = max(
                min(item.log_moneyness for item in earlier_rows),
                min(item.log_moneyness for item in later_rows),
            )
            upper = min(
                max(item.log_moneyness for item in earlier_rows),
                max(item.log_moneyness for item in later_rows),
            )
            if lower >= upper:
                raise InsufficientSurfaceData(
                    "adjacent maturities need overlapping log-moneyness support for calendar checks"
                )
            calendar_grids.append(
                (
                    earlier_index,
                    later_index,
                    np.asarray(
                        np.linspace(lower, upper, _CALENDAR_GRID_POINTS),
                        dtype=np.float64,
                    ),
                )
            )

        def unpack(values: NDArray[np.float64], index: int) -> tuple[float, float, float]:
            return float(values[3 * index]), float(values[(3 * index) + 1]), float(
                values[(3 * index) + 2]
            )

        def objective(values: NDArray[np.float64]) -> float:
            squared_error = 0.0
            for index, expiry in enumerate(expiries):
                theta, rho, psi = unpack(values, index)
                for row in by_expiry[expiry]:
                    model = cls.total_variance(
                        row.log_moneyness, theta=theta, rho=rho, psi=psi
                    )
                    squared_error += row.weight * ((model - row.total_variance) ** 2)
            return squared_error / len(expiries)

        def constraints(values: NDArray[np.float64]) -> NDArray[np.float64]:
            margins: list[float] = []
            for index in range(len(expiries)):
                theta, rho, psi = unpack(values, index)
                margins.extend(
                    (
                        4.0 - (psi * (1.0 + abs(rho))),
                        (4.0 * theta) - ((psi**2) * (1.0 + abs(rho))),
                    )
                )
                if index:
                    earlier_theta, _, _ = unpack(values, index - 1)
                    margins.append(theta - earlier_theta - 1e-8)
            for earlier_index, later_index, grid in calendar_grids:
                earlier = unpack(values, earlier_index)
                later = unpack(values, later_index)
                early_w = _total_variance_array(
                    grid, theta=earlier[0], rho=earlier[1], psi=earlier[2]
                )
                late_w = _total_variance_array(
                    grid, theta=later[0], rho=later[1], psi=later[2]
                )
                margins.extend(float(value) for value in late_w - early_w)
            return np.asarray(margins, dtype=np.float64)

        bounds = [
            bound
            for _ in expiries
            for bound in ((1e-8, 5.0), (-0.999, 0.999), (1e-8, 4.0))
        ]
        result: Any = minimize(
            objective,
            initial,
            method="SLSQP",
            bounds=bounds,
            constraints=({"type": "ineq", "fun": constraints},),
            options={"maxiter": 2000, "ftol": 1e-14, "disp": False},
        )
        if not bool(result.success):
            raise SurfaceCalibrationError(f"eSSVI constrained calibration failed: {result.message}")
        fitted_values = np.asarray(result.x, dtype=np.float64)
        minimum_margin = float(np.min(constraints(fitted_values)))
        if minimum_margin < -_PARAMETER_TOLERANCE:
            raise SurfaceCalibrationError(
                f"eSSVI optimizer returned infeasible parameters: margin={minimum_margin}"
            )

        slices: list[ESSVISlice] = []
        for index, expiry in enumerate(expiries):
            rows = by_expiry[expiry]
            theta, rho, psi = unpack(fitted_values, index)
            slices.append(
                ESSVISlice(
                    expiry=expiry,
                    maturity_years=rows[0].maturity_years,
                    forward=rows[0].forward,
                    theta=theta,
                    rho=rho,
                    psi=psi,
                    min_log_moneyness=min(item.log_moneyness for item in rows),
                    max_log_moneyness=max(item.log_moneyness for item in rows),
                    quote_count=len(rows),
                )
            )

        fit_metrics = cls._fit_diagnostics(
            slices=tuple(slices),
            observations=observations,
            previous_surface=request.previous_surface,
            excluded=excluded,
            objective_value=float(result.fun),
            iterations=int(result.nit),
            minimum_constraint_margin=minimum_margin,
        )
        surface = cls(
            _slices=tuple(slices),
            _observations=observations,
            _surface_timestamp=min(item.receive_timestamp for item in observations),
            _instrument_scope=scopes,
            _fit_metrics=fit_metrics,
        )
        report = surface.arb_check()
        if not report.passed:
            raise SurfaceCalibrationError(
                "eSSVI fit failed independent no-arbitrage checks: "
                f"{len(report.violations)} violations"
            )
        return surface

    @classmethod
    def _fit_diagnostics(
        cls,
        *,
        slices: tuple[ESSVISlice, ...],
        observations: tuple[_Observation, ...],
        previous_surface: VolatilitySurface | None,
        excluded: dict[str, int],
        objective_value: float,
        iterations: int,
        minimum_constraint_margin: float,
    ) -> dict[str, object]:
        slice_by_expiry = {item.expiry: item for item in slices}
        residual_rows: list[tuple[_Observation, float]] = []
        for observation in observations:
            fitted = slice_by_expiry[observation.expiry].total_variance(
                observation.log_moneyness
            )
            residual_rows.append((observation, observation.total_variance - fitted))
        weight_sum = sum(item.weight for item, _ in residual_rows)
        weighted_mean = (
            sum(item.weight * item.total_variance for item, _ in residual_rows) / weight_sum
        )
        weighted_sse = sum(item.weight * residual**2 for item, residual in residual_rows)
        weighted_sst = sum(
            item.weight * ((item.total_variance - weighted_mean) ** 2)
            for item, _ in residual_rows
        )
        weighted_r_squared = 1.0 - (weighted_sse / weighted_sst) if weighted_sst > 0 else None
        weighted_rmse = math.sqrt(weighted_sse / len(slices))

        buckets: dict[str, list[tuple[_Observation, float]]] = defaultdict(list)
        for item, residual in residual_rows:
            k = item.log_moneyness
            bucket = (
                "deep_put"
                if k < -0.10
                else "put_wing"
                if k < -0.025
                else "atm"
                if k <= 0.025
                else "call_wing"
                if k <= 0.10
                else "deep_call"
            )
            buckets[bucket].append((item, residual))
        residual_diagnostics: dict[str, object] = {}
        for name in ("deep_put", "put_wing", "atm", "call_wing", "deep_call"):
            values = buckets.get(name, [])
            residual_diagnostics[name] = {
                "count": len(values),
                "mean_total_variance_residual": (
                    sum(residual for _, residual in values) / len(values) if values else None
                ),
                "max_abs_total_variance_residual": (
                    max((abs(residual) for _, residual in values), default=None)
                ),
            }

        stability: dict[str, object]
        if isinstance(previous_surface, ESSVISurface):
            previous = {item.expiry: item for item in previous_surface._slices}
            changes: dict[str, object] = {}
            magnitudes: list[float] = []
            for fitted_slice in slices:
                prior = previous.get(fitted_slice.expiry)
                if prior is None:
                    continue
                delta = {
                    "theta": fitted_slice.theta - prior.theta,
                    "rho": fitted_slice.rho - prior.rho,
                    "psi": fitted_slice.psi - prior.psi,
                }
                changes[fitted_slice.expiry.isoformat()] = delta
                magnitudes.extend(abs(value) for value in delta.values())
            stability = {
                "status": "available" if changes else "no_common_expiries",
                "common_expiry_count": len(changes),
                "max_absolute_parameter_change": max(magnitudes, default=None),
                "changes_by_expiry": changes,
            }
        else:
            stability = {
                "status": "not_available",
                "reason": "no_previous_essvi_surface",
                "common_expiry_count": 0,
            }

        return {
            "fit_status": "converged",
            "weighted_r_squared": weighted_r_squared,
            "weighted_rmse_total_variance": weighted_rmse,
            "residuals_by_moneyness": residual_diagnostics,
            "parameter_stability": stability,
            "optimizer": {
                "method": "SLSQP",
                "joint_maturity_fit": True,
                "objective": objective_value,
                "iterations": iterations,
                "minimum_constraint_margin": minimum_constraint_margin,
                "constraints": [
                    "butterfly_sufficient_conditions",
                    "theta_nondecreasing",
                    "calendar_grid_nondecreasing_total_variance",
                ],
            },
            "input": {
                "used_quote_count": len(observations),
                "excluded_latest_row_counts": excluded,
            },
        }

    def _slice_for_exact_maturity(self, maturity_years: float) -> ESSVISlice | None:
        return next(
            (
                item
                for item in self._slices
                if abs(item.maturity_years - maturity_years) <= 1e-10
            ),
            None,
        )

    def evaluate(self, *, log_moneyness: float, maturity_years: float) -> SurfaceEvaluation:
        if not math.isfinite(log_moneyness) or not math.isfinite(maturity_years):
            raise ValueError("surface coordinates must be finite")
        if maturity_years <= 0:
            return SurfaceEvaluation(
                None,
                None,
                EvaluationStatus.DATA_INSUFFICIENT,
                "maturity must be positive",
            )
        exact = self._slice_for_exact_maturity(maturity_years)
        if exact is not None:
            if not (exact.min_log_moneyness <= log_moneyness <= exact.max_log_moneyness):
                return SurfaceEvaluation(
                    None,
                    None,
                    EvaluationStatus.DATA_INSUFFICIENT,
                    "strike extrapolation is disabled outside observed support",
                )
            variance = exact.total_variance(log_moneyness)
            return SurfaceEvaluation(
                variance,
                math.sqrt(variance / maturity_years),
                (
                    EvaluationStatus.SMOOTHED
                    if self._temporally_smoothed
                    else EvaluationStatus.FITTED
                ),
            )

        outside_maturity_support = (
            maturity_years < self._slices[0].maturity_years
            or maturity_years > self._slices[-1].maturity_years
        )
        if outside_maturity_support:
            return SurfaceEvaluation(
                None,
                None,
                EvaluationStatus.DATA_INSUFFICIENT,
                "maturity extrapolation is disabled outside fitted support",
            )
        for earlier, later in zip(self._slices, self._slices[1:], strict=False):
            if not (earlier.maturity_years < maturity_years < later.maturity_years):
                continue
            lower = max(earlier.min_log_moneyness, later.min_log_moneyness)
            upper = min(earlier.max_log_moneyness, later.max_log_moneyness)
            if not (lower <= log_moneyness <= upper):
                return SurfaceEvaluation(
                    None,
                    None,
                    EvaluationStatus.DATA_INSUFFICIENT,
                    "maturity interpolation requires overlapping strike support",
                )
            fraction = (maturity_years - earlier.maturity_years) / (
                later.maturity_years - earlier.maturity_years
            )
            variance = ((1.0 - fraction) * earlier.total_variance(log_moneyness)) + (
                fraction * later.total_variance(log_moneyness)
            )
            return SurfaceEvaluation(
                variance,
                math.sqrt(variance / maturity_years),
                (
                    EvaluationStatus.SMOOTHED
                    if self._temporally_smoothed
                    else EvaluationStatus.INTERPOLATED
                ),
            )
        return SurfaceEvaluation(
            None,
            None,
            EvaluationStatus.DATA_INSUFFICIENT,
            "no fitted maturity interval covers the request",
        )

    @property
    def params(self) -> tuple[SurfaceParameter, ...]:
        values: list[SurfaceParameter] = []
        for fitted_slice in self._slices:
            prefix = fitted_slice.expiry.isoformat()
            values.extend(
                (
                    SurfaceParameter(
                        name=f"{prefix}.theta", value=Decimal(str(fitted_slice.theta))
                    ),
                    SurfaceParameter(name=f"{prefix}.rho", value=Decimal(str(fitted_slice.rho))),
                    SurfaceParameter(name=f"{prefix}.psi", value=Decimal(str(fitted_slice.psi))),
                )
            )
        return tuple(values)

    @property
    def diagnostics(self) -> tuple[FitDiagnostic, ...]:
        support = [
            {
                "expiry": item.expiry.isoformat(),
                "maturity_years": item.maturity_years,
                "forward": item.forward,
                "min_log_moneyness": item.min_log_moneyness,
                "max_log_moneyness": item.max_log_moneyness,
                "quote_count": item.quote_count,
            }
            for item in self._slices
        ]
        values = {
            **self._fit_metrics,
            "support": support,
            "interpolation_policy": self._policy.to_dict(),
            "arbitrage": self.arb_check().to_dict(),
        }
        return tuple(
            FitDiagnostic(name=name, value=cast(JsonValue, value))
            for name, value in values.items()
        )

    def arb_check(self) -> ArbitrageReport:
        violations: list[ArbitrageViolation] = []
        butterfly_count = 0
        calendar_count = 0
        butterfly_minima: list[float] = []
        calendar_minima: list[float] = []

        for fitted_slice in self._slices:
            width = fitted_slice.max_log_moneyness - fitted_slice.min_log_moneyness
            step = min(1e-4, width / 1000.0)
            strike_grid = tuple(
                float(value)
                for value in np.linspace(
                    fitted_slice.min_log_moneyness + step,
                    fitted_slice.max_log_moneyness - step,
                    _ARBITRAGE_GRID_POINTS,
                )
            )

            def slice_variance(
                log_moneyness: float,
                _maturity: float,
                current: ESSVISlice = fitted_slice,
            ) -> float:
                return current.total_variance(log_moneyness)

            report = check_arbitrage(
                total_variance=slice_variance,
                maturities_years=(fitted_slice.maturity_years,),
                log_moneyness_grid=strike_grid,
                derivative_step=step,
            )
            butterfly_count += report.butterfly_checked_points
            if report.min_butterfly_density_factor is not None:
                butterfly_minima.append(report.min_butterfly_density_factor)
            violations.extend(report.violations)

        for earlier, later in zip(self._slices, self._slices[1:], strict=False):
            lower = max(earlier.min_log_moneyness, later.min_log_moneyness)
            upper = min(earlier.max_log_moneyness, later.max_log_moneyness)
            calendar_grid = tuple(
                float(value) for value in np.linspace(lower, upper, _ARBITRAGE_GRID_POINTS)
            )

            def pair_variance(
                log_moneyness: float,
                maturity: float,
                earlier_slice: ESSVISlice = earlier,
                later_slice: ESSVISlice = later,
            ) -> float:
                current = (
                    earlier_slice
                    if maturity == earlier_slice.maturity_years
                    else later_slice
                )
                return current.total_variance(log_moneyness)

            report = check_arbitrage(
                total_variance=pair_variance,
                maturities_years=(earlier.maturity_years, later.maturity_years),
                log_moneyness_grid=calendar_grid,
            )
            calendar_count += report.calendar_checked_points
            if report.min_calendar_total_variance_spread is not None:
                calendar_minima.append(report.min_calendar_total_variance_spread)
            violations.extend(
                item for item in report.violations if item.kind is ArbitrageKind.CALENDAR
            )

        return ArbitrageReport(
            calendar_required=len(self._slices) > 1,
            butterfly_checked_points=butterfly_count,
            calendar_checked_points=calendar_count,
            min_butterfly_density_factor=min(butterfly_minima, default=None),
            min_calendar_total_variance_spread=min(calendar_minima, default=None),
            violations=tuple(violations),
        )

    @property
    def model_name(self) -> str:
        return "eSSVI"

    @property
    def surface_timestamp(self) -> datetime:
        return self._surface_timestamp

    @property
    def instrument_scope(self) -> tuple[str, ...]:
        return self._instrument_scope

    @property
    def is_temporally_smoothed(self) -> bool:
        return self._temporally_smoothed

    @property
    def slices(self) -> tuple[ESSVISlice, ...]:
        """Read-only calibrated slices for diagnostics and downstream adapters."""

        return self._slices
