from __future__ import annotations

from shaurya.surfaces.arbitrage import ArbitrageKind, check_arbitrage


def test_flat_smiles_with_increasing_variance_are_arbitrage_free() -> None:
    report = check_arbitrage(
        total_variance=lambda _k, maturity: 0.02 + (0.1 * maturity),
        maturities_years=(0.1, 0.2),
        log_moneyness_grid=(-0.2, -0.1, 0.0, 0.1, 0.2),
    )
    assert report.passed
    assert report.min_butterfly_density_factor == 1.0
    assert report.min_calendar_total_variance_spread is not None
    assert report.min_calendar_total_variance_spread > 0


def test_checker_reports_butterfly_and_calendar_violations_separately() -> None:
    def invalid_surface(log_moneyness: float, maturity: float) -> float:
        calendar_offset = -0.01 if maturity > 0.1 else 0.0
        return 0.10 - (5.0 * log_moneyness**2) + calendar_offset

    report = check_arbitrage(
        total_variance=invalid_surface,
        maturities_years=(0.1, 0.2),
        log_moneyness_grid=(-0.1, -0.05, 0.0, 0.05, 0.1),
    )
    assert not report.passed
    assert {item.kind for item in report.violations} == {
        ArbitrageKind.BUTTERFLY,
        ArbitrageKind.CALENDAR,
    }
