# NSGVC historical stability matrix

The frozen NSGVC definitions were tested with a 500-point iron fly and a six-option-point completed-structure cost. Every refit retained the same two-variable IV-state model family, `q <= 0.70`, development RR400 60th-percentile rule, 09:20 entry convention, and first qualifying observation per expiry. Training labels were restricted to already-matured prior expiries.

## Main findings

Eight fixed training starts were tested. The 2025 validation mean was positive for six of eight starts and negative for starts 2023-03-01 and 2023-04-01. Partial 2026 was positive for all eight, although most alternative starts produced only +11.19 points per trade versus +32.16 for the published 2023-01-23 start. Thus the sign often survives, but the reported magnitude and chosen trades remain training-window sensitive.

Quarterly expanding-origin tests produced seven evaluable blocks from 2024Q4 through partial 2026Q2. Three were positive, three negative and one generated no trade. Across 37 trades the mean was +16.42 points, win rate 56.76%, one-sided t-test p=0.283 and bootstrap 95% mean interval `[-39.00, +71.01]`. The quarterly result is not statistically distinguishable from zero.

Strict expiry-by-expiry expanding-history walk-forward produced 47 trades at +15.82 points/trade, 55.32% wins, p=0.250 and bootstrap interval `[-29.50, +60.93]`. Its 2024 subset lost 28.63 points/trade.

Strict rolling-252-session expiry walk-forward was the best stability result: 52 trades at +26.60 points/trade, 57.69% wins, p=0.101 and bootstrap interval `[-13.53, +66.36]`. Annual means were +15.58 in 2024, +31.92 in 2025 and +34.51 in partial 2026. It remained +22.60 points/trade under a ten-point cost deduction. At the package's normalized 65-unit lot, the six-point total is Rs 89,904.75, but this is a research normalization rather than an executable P&L statement.

## Decision

These tests improve the case that NSGVC may contain a recurring variance-carry effect, particularly with a rolling training window. They do not establish a reliable alpha: every aggregate confidence interval includes zero, quarterly signs are inconsistent, the expanding version fails in 2024, and the rolling-252 variant was examined after the original result and is therefore exploratory. Historical bid/ask and broker-margin observations are still unavailable.

Keep the existing prospective freeze unchanged. Treat rolling-252 NSGVC as a separately versioned candidate only if it is frozen before evaluating any later observations.
