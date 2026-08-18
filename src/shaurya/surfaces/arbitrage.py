"""REQ-SUR-05: independent butterfly and calendar no-arbitrage diagnostics."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class ArbitrageKind(StrEnum):
    BUTTERFLY = "butterfly"
    CALENDAR = "calendar"


@dataclass(frozen=True, slots=True)
class ArbitrageViolation:
    kind: ArbitrageKind
    log_moneyness: float
    maturity_years: float
    value: float
    threshold: float
    later_maturity_years: float | None = None

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "kind": self.kind.value,
            "log_moneyness": self.log_moneyness,
            "maturity_years": self.maturity_years,
            "later_maturity_years": self.later_maturity_years,
            "value": self.value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class ArbitrageReport:
    butterfly_checked_points: int
    calendar_checked_points: int
    min_butterfly_density_factor: float | None
    min_calendar_total_variance_spread: float | None
    violations: tuple[ArbitrageViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations and self.butterfly_checked_points > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "butterfly_checked_points": self.butterfly_checked_points,
            "calendar_checked_points": self.calendar_checked_points,
            "min_butterfly_density_factor": self.min_butterfly_density_factor,
            "min_calendar_total_variance_spread": (
                self.min_calendar_total_variance_spread
            ),
            "violations": [item.to_dict() for item in self.violations],
        }


def check_arbitrage(
    *,
    total_variance: Callable[[float, float], float | None],
    maturities_years: Sequence[float],
    log_moneyness_grid: Sequence[float],
    derivative_step: float = 1e-4,
    butterfly_tolerance: float = 1e-7,
    calendar_tolerance: float = 1e-10,
) -> ArbitrageReport:
    """Check risk-neutral density and term monotonicity on a declared grid.

    The Gatheral-Jacquier density factor ``g(k)`` is evaluated with centered numerical
    derivatives of total variance. Calendar checks compare the same log-moneyness across
    adjacent fitted maturities. Unsupported cells are omitted rather than treated as zero.
    """

    if derivative_step <= 0:
        raise ValueError("derivative_step must be positive")
    maturities = tuple(sorted(set(float(value) for value in maturities_years)))
    strikes = tuple(sorted(set(float(value) for value in log_moneyness_grid)))
    violations: list[ArbitrageViolation] = []
    butterfly_values: list[float] = []
    calendar_values: list[float] = []

    for maturity in maturities:
        for log_moneyness in strikes:
            center = total_variance(log_moneyness, maturity)
            left = total_variance(log_moneyness - derivative_step, maturity)
            right = total_variance(log_moneyness + derivative_step, maturity)
            if center is None or left is None or right is None or center <= 0:
                continue
            first = (right - left) / (2.0 * derivative_step)
            second = (right - (2.0 * center) + left) / (derivative_step**2)
            first_term = (1.0 - (log_moneyness * first / (2.0 * center))) ** 2
            second_term = 0.25 * first**2 * ((1.0 / center) + 0.25)
            density_factor = first_term - second_term + (0.5 * second)
            if not math.isfinite(density_factor):
                continue
            butterfly_values.append(density_factor)
            if density_factor < -butterfly_tolerance:
                violations.append(
                    ArbitrageViolation(
                        kind=ArbitrageKind.BUTTERFLY,
                        log_moneyness=log_moneyness,
                        maturity_years=maturity,
                        value=density_factor,
                        threshold=-butterfly_tolerance,
                    )
                )

    for earlier, later in zip(maturities, maturities[1:], strict=False):
        for log_moneyness in strikes:
            early_variance = total_variance(log_moneyness, earlier)
            late_variance = total_variance(log_moneyness, later)
            if early_variance is None or late_variance is None:
                continue
            spread = late_variance - early_variance
            if not math.isfinite(spread):
                continue
            calendar_values.append(spread)
            if spread < -calendar_tolerance:
                violations.append(
                    ArbitrageViolation(
                        kind=ArbitrageKind.CALENDAR,
                        log_moneyness=log_moneyness,
                        maturity_years=earlier,
                        later_maturity_years=later,
                        value=spread,
                        threshold=-calendar_tolerance,
                    )
                )

    return ArbitrageReport(
        butterfly_checked_points=len(butterfly_values),
        calendar_checked_points=len(calendar_values),
        min_butterfly_density_factor=min(butterfly_values, default=None),
        min_calendar_total_variance_spread=min(calendar_values, default=None),
        violations=tuple(violations),
    )
