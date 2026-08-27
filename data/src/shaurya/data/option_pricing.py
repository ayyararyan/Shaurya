"""Canonical Black-76 and eSSVI primitives shared by data and research.

The high-frequency option features must not create a second discounting, inversion, or
total-variance convention.  This module is therefore the dependency-light DAT authority; the
research surface package imports these functions rather than maintaining its own copy.
"""

from __future__ import annotations

import math

SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0


def normal_cdf(value: float) -> float:
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
    """Return the discounted Black-76 option value under the repository convention."""

    if forward <= 0 or strike <= 0 or maturity_years <= 0 or volatility < 0:
        raise ValueError("Black-76 inputs must be positive (volatility may be zero)")
    discount = math.exp(-risk_free_rate * maturity_years)
    intrinsic = max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    if volatility == 0:
        return discount * intrinsic
    sigma_root_t = volatility * math.sqrt(maturity_years)
    d1 = (math.log(forward / strike) / sigma_root_t) + 0.5 * sigma_root_t
    d2 = d1 - sigma_root_t
    if is_call:
        return discount * (forward * normal_cdf(d1) - strike * normal_cdf(d2))
    return discount * (strike * normal_cdf(-d2) - forward * normal_cdf(-d1))


def implied_volatility(
    *,
    price: float,
    forward: float,
    strike: float,
    maturity_years: float,
    risk_free_rate: float,
    is_call: bool,
    tolerance: float = 1e-12,
    maximum_iterations: int = 120,
) -> float | None:
    """Invert Black-76 by deterministic bisection, returning missing on invalid prices."""

    if price <= 0 or forward <= 0 or strike <= 0 or maturity_years <= 0:
        return None
    discount = math.exp(-risk_free_rate * maturity_years)
    intrinsic = discount * (max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0))
    maximum = discount * (forward if is_call else strike)
    price_tolerance = max(1e-10, maximum * tolerance)
    if price < intrinsic - price_tolerance or price >= maximum:
        return None
    low = 1e-8
    high = 5.0
    if (
        black76_price(
            forward=forward,
            strike=strike,
            maturity_years=maturity_years,
            volatility=high,
            risk_free_rate=risk_free_rate,
            is_call=is_call,
        )
        < price
    ):
        return None
    for _ in range(maximum_iterations):
        middle = 0.5 * (low + high)
        model = black76_price(
            forward=forward,
            strike=strike,
            maturity_years=maturity_years,
            volatility=middle,
            risk_free_rate=risk_free_rate,
            is_call=is_call,
        )
        if abs(model - price) <= price_tolerance:
            return middle
        if model < price:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def essvi_total_variance(log_moneyness: float, *, theta: float, rho: float, psi: float) -> float:
    """Evaluate the repository's ``(theta, rho, psi)`` eSSVI parameterisation."""

    if theta <= 0 or not -0.999 <= rho <= 0.999 or psi <= 0:
        raise ValueError("invalid eSSVI parameters")
    core = math.sqrt((psi * log_moneyness + theta * rho) ** 2 + theta**2 * (1.0 - rho**2))
    return 0.5 * (theta + rho * psi * log_moneyness + core)


def essvi_static_arbitrage_passes(*, theta: float, rho: float, psi: float) -> bool:
    """Apply the pinned sufficient eSSVI butterfly-arbitrage conditions."""

    return (
        theta > 0
        and -0.999 <= rho <= 0.999
        and psi > 0
        and psi * (1.0 + abs(rho)) <= 4.0
        and psi**2 * (1.0 + abs(rho)) <= 4.0 * theta
    )
