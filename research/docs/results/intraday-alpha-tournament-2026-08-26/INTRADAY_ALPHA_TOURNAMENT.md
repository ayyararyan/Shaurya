# Intraday directional-alpha tournament

**Index-return proxy only; no executable option-P&L claim.**

Verdict: **no directional proxy survived costs, correction, and both holdouts**

Strategies tested: 22
Survivors: none

| strategy | 2025 net bps/day | 2025 Sharpe | 2026 net bps/day | 2026 Sharpe | 10bp 2026 bps/day |
|---|---:|---:|---:|---:|---:|
| gap_continuation | -4.83 | -1.39 | -4.06 | -1.01 | -8.06 |
| gap_fade | -7.17 | -2.05 | -7.94 | -1.97 | -11.94 |
| session_momentum | -16.14 | -3.88 | -25.40 | -5.34 | -42.52 |
| opening_range_breakout | -16.99 | -5.74 | -20.89 | -6.30 | -34.47 |
| opening_range_fade | -23.82 | -11.49 | -19.85 | -7.83 | -33.43 |
| session_reversal | -27.73 | -11.05 | -25.96 | -8.28 | -43.08 |
| ridge_return | -23.30 | -11.14 | -29.17 | -12.05 | -50.37 |
| momentum_60m | -56.37 | -14.77 | -59.39 | -14.44 | -98.21 |
| breakout_60m | -23.11 | -21.54 | -23.85 | -17.92 | -40.05 |
| breakout_fade_60m | -20.22 | -20.93 | -24.76 | -19.71 | -40.97 |
| reversal_60m | -57.07 | -24.93 | -57.10 | -20.50 | -95.93 |
| hist_return | -26.73 | -18.29 | -29.90 | -21.40 | -51.00 |
| momentum_30m | -85.47 | -21.47 | -88.75 | -21.40 | -145.98 |
| breakout_fade_30m | -33.73 | -26.16 | -37.13 | -23.51 | -62.64 |
| breakout_30m | -38.85 | -26.97 | -39.38 | -24.55 | -64.88 |
| momentum_15m | -121.32 | -29.81 | -123.50 | -26.10 | -205.07 |
| breakout_fade_15m | -53.50 | -34.81 | -55.19 | -28.23 | -94.22 |
| breakout_15m | -57.56 | -31.82 | -61.91 | -31.66 | -100.94 |
| reversal_30m | -84.96 | -36.95 | -82.91 | -33.96 | -140.14 |
| reversal_15m | -121.49 | -48.66 | -121.24 | -36.79 | -202.82 |
| momentum_5m | -240.54 | -53.55 | -235.37 | -47.99 | -386.81 |
| reversal_5m | -216.87 | -87.32 | -218.95 | -71.12 | -370.39 |

A survivor must be positive after the 6bp round-trip hurdle in both 2025 and 2026, and pass Holm correction on 2025 daily P&L. Full cost ladders, turnover, drawdown, and Tuesday-regime slices are in the JSON.
