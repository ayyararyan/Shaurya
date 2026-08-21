# OFI dashboard five-minute rolling win-score amendment

**ID:** `D47 / ANL-06-ROLLING-WIN-SCORE-5M`

**Directed and approved by Aryan Ayyar:** 2026-08-21. Every horizon/lookback cell must report a
simple points score over the latest rolling five minutes of matured forecasts.

For forecast `p` ticks and realised displayed-mid change `y` ticks:

- if `p > 0`: `+1` when `y >= p`, `-1` when `y <= -p`, otherwise `0`;
- if `p < 0`: `+1` when `y <= p`, `-1` when `y >= -p`, otherwise `0`; and
- if `p = 0`: `0`, because the model expressed no direction or positive magnitude threshold.

Exact equality qualifies. Thus a point is awarded only when the realised move reaches or exceeds
the forecast magnitude. A smaller same-direction move is neutral, as is any opposite move smaller
than the forecast magnitude.

The displayed value is the arithmetic mean of these `{-1,0,+1}` points for outcomes whose
response-end timestamps lie in `(latest_market_timestamp - 300 seconds, latest_market_timestamp]`.
Each cell also retains the window's observation count and `+1/0/-1` counts. The window follows
market-data time rather than wall-clock time. D46 cumulative OOS R-squared remains unchanged and
cumulative from corrected-worker launch.

On worker restart or code upgrade, reconstruct the trailing five-minute score from the existing
append-only outcome receipts; do not reset, duplicate, or rescore the cumulative R-squared.

Acceptance:

- `SCORE-DEF-01`: exact positive/negative/equality/zero cases implement the rule above.
- `SCORE-WIN-01`: only response ends in the trailing market-time 300 seconds contribute.
- `SCORE-RESTORE-01`: restart restores and de-duplicates recent outcome receipts.
- `SCORE-OUT-01`: every dashboard cell visibly shows the five-minute mean and sample count;
  hover/API retains `+1/0/-1` counts.
