# Rolling-252 NSGVC falsification audit

This audit attempted to disprove the exploratory rolling-252 NSGVC result. It reconstructed 09:20-close and 09:21-open entries directly from raw option minutes, stressed costs and concentration, evaluated a 125-cell parameter neighborhood, separated the two gates, checked regimes, used iid and four-expiry moving-block bootstraps, and simulated the frozen one-lot 20%-risk hierarchy from Rs 1 lakh.

## What survived

The primary 52-trade result remained +26.60 option points per trade after six points of cost. Delaying execution did not erase it: at a ten-point deduction, 09:20 close averaged +22.93 and 09:21 open averaged +22.65 points. Even a 20-point deduction left all three entry conventions near +12.6 to +12.9 points per trade.

The sign was positive in each available year: +15.58 in 2024, +31.92 in 2025 and +34.51 in partial 2026. Of 115 nearby parameter cells with at least 20 trades, 65.22% were positive and their median mean was +10.86 points. The primary cell was at the 87.83rd percentile of that neighborhood rather than at its maximum.

The gates have useful interaction. Ungated first-expiry entries averaged -16.15 points; RR-only averaged -16.74 and q-only +7.60, while both gates together averaged +26.60. This is consistent with RR400 acting as a veto conditional on forecast-cheap realized variance, not as a standalone directional predictor.

The Rs 1 lakh sequential risk simulation admitted 51 preferred 500-point trades and one 400-point fallback, skipped none, and ended at Rs 189,729.25. Its maximum peak-to-trough drawdown was 30.51%, which is economically substantial.

## What failed

Sampling uncertainty still includes zero. The one-sided t-test is p=0.101; the iid bootstrap 95% interval is `[-13.53,+66.36]`, and the four-expiry moving-block interval is `[-9.87,+62.56]`. This fails the strict positive-lower-bound criterion.

The result is also concentrated. Removing the best trade lowers the mean to +21.78 points; removing the best three lowers it to +12.16; removing the best five leaves only +2.90 points per trade with p=0.442. Nearby parameters are not uniformly profitable: 34.78% of adequately populated cells are negative, the neighborhood median is much lower than the primary result, and cell means range from -16.42 to +51.97 points.

## Decision

Six of seven audit criteria passed, but the required uncertainty criterion failed. Rolling-252 NSGVC is therefore a credible research candidate, not a confirmed trading alpha. Its delayed-entry and gate-interaction behavior are encouraging; its confidence interval, top-trade concentration, parameter dispersion and 30.5% drawdown prevent promotion.

Do not alter the existing NSGVC v1.0 prospective freeze. If rolling-252 is pursued, register it as a separate v1.1 shadow candidate before any later observations are inspected.
