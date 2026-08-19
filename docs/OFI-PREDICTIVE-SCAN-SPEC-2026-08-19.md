# Price-keyed OFI → future futures returns — exploratory scan specification

**Scan ID:** `X-OFI-DAT20-03`  
**Status before execution:** frozen exploratory design  
**Confirmatory eligible:** `false`

## Plain-language question

Which construction of order-flow imbalance (OFI) best explains the futures return that follows?
Book depth is one dimension of that search. It is not the research question by itself.

This scan isolates OFI. It does not mix OFI with the 584 book-state and shape variables used in
`X-DEEPBOOK-DAT20-02`.

## Why this is exploratory

The only available depth-200 tapes are the two `DAT-20` recordings whose price paths have already
been inspected. They cover about 22 minutes of one NIFTY futures contract in one falling session.
No result from this scan may be called confirmed, tradeable, economic, or representative of another
session. The complete grid is emitted, including failures and negative results.

## Frozen measurement objects

- **X — price-keyed OFI:** for each consecutive valid depth-200 state, quantities are mapped by
  absolute price. At each price the bid quantity change enters positively and the ask quantity
  change negatively. Prices that merely enter or leave at the outer edge during a one-level window
  slide are excluded and counted. Each price is assigned the shallowest rank it holds in either
  endpoint, so rank changes cannot manufacture a cascade of false level changes.
- **OFI accumulation windows (`h1`):** 0.5, 1, 2, 5, and 10 seconds on the depth-200 publication
  clock. A window is emitted only when its complete past is present inside one valid connection
  epoch.
- **Cumulative depth cutoffs:** top 1, 5, 10, 20, 50, 100, and 200 levels. The scalar at depth D is
  the sum of every price-keyed OFI contribution whose shallowest endpoint rank is at most D.
- **Y:** depth-20 best-bid/best-ask midpoint return, in NIFTY futures ticks (₹0.05).
- **Return horizons (`h2`):** 1, 2, 5, 10, and 30 seconds.
- **Causal gap (`Z`):** 0.5 seconds from the end of the OFI window to the response anchor. This is
  predictive rather than same-window. A same-window diagnostic is reported separately and is never
  ranked as forecasting performance.
- **Stratum:** the same front-month NIFTY future and the two retained mid-afternoon tapes. No regime
  comparison is identified because there is only one session and one direction of travel.

The primary grid therefore contains `5 windows × 7 depths × 5 horizons = 175` OFI constructions.

## Models and ranking

For every grid cell, fit on the first 70% of each tape and score on the later portion after a
120-second embargo:

1. OFI alone.
2. A small state baseline: current spread and microprice tilt.
3. Baseline plus OFI.

Rank constructions by the out-of-sample R² of model 3 against the training-mean return and by its
increment over model 2. Report the OFI-only R² alongside it. Standardisation uses training data
only. The response mean removed from the test target is the training mean, never the test mean.

The nested depth ladder is secondary: at each OFI window and return horizon, add marginal bands
1, 2–5, 6–10, 11–20, 21–50, 51–100, and 101–200 to the same baseline and report each step.

## Dependence, controls, and interpretation

- Compare paired out-of-sample squared errors with Newey–West, stationary block bootstrap, and
  non-overlapping time blocks. No naive standard error is treated as valid.
- Run the same complete grid on the past-mirror return. If the past grid looks as strong as the
  future grid, the scan is measuring session drift or reaction rather than prediction.
- Report the same-window OFI-to-return fit as a construction/data-quality diagnostic only.
- Report the full 175-row grid, not a filtered top list. A short ranked summary is allowed only as
  a pointer into that complete table.
- A positive exploratory cell is a lead for a later registered, held-out test. A null on this tape
  is inconclusive unless the measured sample supports the stated effect size.

