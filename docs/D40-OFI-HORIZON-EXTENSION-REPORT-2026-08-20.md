# D40 Report — Where Displayed-Mid OFI Predictive Power Peaks

**Run:** `X-D40-OFI-HORIZON-EXTENSION-2026-08-20`
**Date:** 2026-08-20
**Model object:** D39 `C8`, `M=10`, `h1=10 s`
**Forecasted variable:** future displayed-mid return
**Implementation commit:** `0625bbea58a7b14d035a5662dc395e2c482dbc77`

## Owner summary

The original 0.5–10-second curve was monotonically increasing. The extension is not. Predictive
power rises once more from **7.40% at 10 seconds to 15.78% at 20 seconds**, then collapses to
**−0.47% at 30 seconds** and stays negative at every tested horizon through 120 seconds.

**Conclusion:** on this session, the tested peak is **20 seconds**. The first tested decline is at
**30 seconds**. The information in the 10-second multi-level OFI state accumulates into the
displayed mid over roughly the next 20 seconds; it does not retain positive raw OOS predictive
power at 30 seconds or beyond.

**Action encoded for the next session:** keep tomorrow's locked D39 run unchanged, then apply the
already frozen 10–120-second extension to its untouched full-session tape and test whether the
20-second peak and 30-second break repeat.

## Results

### Original D39 short-horizon run

| Horizon | Absolute OOS R² |
|---:|---:|
| 0.5 s | **0.1725%** |
| 1 s | **0.5391%** |
| 2 s | **3.2570%** |
| 5 s | **5.7616%** |
| 10 s | **7.3916%** |

This is the original D39 artifact with its original 120-second embargo and 2,300 common held-out
rows per cell.

### Corrected D40 long-horizon extension

| Horizon | Absolute OOS R² | Train rows | Test rows |
|---:|---:|---:|---:|
| 10 s | **7.4037%** | 4,377 | 2,299 |
| 20 s | **15.7793%** | 4,377 | 2,264 |
| 30 s | **−0.4698%** | 4,377 | 2,224 |
| 45 s | **−8.8594%** | 4,377 | 2,191 |
| 60 s | **−18.7876%** | 4,377 | 2,186 |
| 90 s | **−23.0628%** | 4,377 | 2,161 |
| 120 s | **−22.6148%** | 4,377 | 2,161 |

The D40 10-second value differs from the original D39 value because D40 applies one common
120.5-second embargo—120 seconds of response plus the fixed 0.5-second causal gap—removing one
additional held-out row. The model, anchor universe, training boundary and target definition are
unchanged.

The long-horizon sequence is neither strictly increasing nor nondecreasing. It rises from 10 to
20 seconds, falls below zero at 30 seconds, decreases further through 90 seconds, and remains
negative at 120 seconds.

## Detailed methodology

### 1. Data and causal clock

The run uses the same immutable 15:42 snapshot of the 2026-08-20 late-partial NIFTY August 2026
front-month futures capture as D39. Its SHA-256 is
`93456eda4de33cc22fc1d9d3dc8fb5ca7a7bb8eab7108e3c0ef8859a97759a43`.

Receive time is the causal clock. Depth200 publications supply the predictor anchors and
multi-level book transitions. Depth20 publications supply the displayed best bid and ask used to
construct the response. Windows may not cross a reconnect epoch. Missing right-edge responses are
dropped, never carried backward or replaced by zero.

### 2. Ten-level OFI construction

At each valid transition, the model compares book rank `m` between consecutive depth200 states for
`m=1,...,10`.

For bids:

- a higher price contributes the new displayed quantity;
- an unchanged price contributes new quantity minus old quantity;
- a lower price contributes minus the new displayed quantity.

For asks, the symmetric convention is used. The per-level order-flow increment is bid flow minus
ask flow. Each level's increments are summed over `(t−10 s, t]`.

All ten sums are divided by one common depth scale:

`Q = total displayed bid-plus-ask depth / (2 × 10 levels × valid transitions)`.

This produces ten separate depth-scaled OFI regressors. The run does not cumulatively sum levels
into one scalar and does not give each level its own denominator.

### 3. Fixed predictive model

The model is exactly D39 competitor `C8`. Its regressors are:

1. displayed spread in futures ticks at anchor `t`;
2. `log1p` of displayed level-one bid-plus-ask quantity at `t`;
3. the ten depth-scaled OFI regressors accumulated over the previous 10 seconds.

A separate ridge regression is fitted for each response horizon. Regressors are standardised on
training rows only. The target is centred by its training mean. Ridge penalty selection uses the
unchanged chronological inner-validation grid inside training data only. The fitted training
means, scales, coefficients and penalty are then applied unchanged to held-out rows.

### 4. Displayed-mid target

For each anchor `t` and horizon `h`, define

`mid(u) = [best_bid(u) + best_ask(u)] / 2`

and

`y_t(h) = [mid(t + 0.5 s + h) − mid(t + 0.5 s)] / futures_tick_size`.

Thus the predictor ends at `t`, there is a fixed 0.5-second causal gap, and the forecasted object
is the subsequent displayed-mid return over `h`. No last-trade-price target is constructed in the
D40 output.

### 5. Chronological out-of-sample design

The underlying D39 anchor universe is preserved exactly: custom 20/45/60/90/120-second responses
are added to the original response map rather than replacing it. The chronological 70% training
boundary is therefore the same timestamp as D39:
`1787214062292458000` nanoseconds.

D40 applies a 120.5-second embargo between the last training anchor and the first test anchor.
This covers the full 120-second response plus the 0.5-second causal gap. Within each horizon, the
common-row contract is retained: all D39 panel estimators are evaluated on the same available
rows, and this report extracts only C8's absolute OOS R².

### 6. Metric

For held-out targets `y_i`, forecasts `yhat_i`, and the training-target mean `ybar_train`:

`OOS R² = 1 − Σ(y_i − yhat_i)² / Σ(y_i − ybar_train)²`.

The report uses the absolute value emitted by that definition—not an increment relative to
another fitted model. No external benchmark enters the result or conclusion.

## Incident and correction

The first D40 artifact was invalidated before interpretation. Custom horizons initially replaced
the original response map, so final anchors lacking a 10-second response were removed before the
70/30 split. That shifted the training boundary and violated the requirement to preserve D39's
sample construction.

The invalid artifact was isolated at
`overnight-runs/d40-ofi-horizon-extension-20260820-invalid-anchor-split`. The builder was corrected
so custom horizons are additive. A regression now asserts that adding long responses leaves the
entire original anchor timestamp sequence unchanged. The authoritative corrected run is
`overnight-runs/d40-ofi-horizon-extension-20260820-r2`.

## Reproducibility and verification

- Corrected full artifact SHA-256:
  `e291e0f84625946c7d95d3d5785af7f1c9f6e9b27d3c679700430691a414d034`
- Corrected compact summary SHA-256:
  `37a37e421f4b682144d51946a9363ea15ca3abfa89a11158ae493238310a233b`
- Original D39 full artifact SHA-256:
  `c1a56d8f566033a601b0bea66e8774cd55d3194bb33f0b0b1ff3bd39991a903c`
- Corrected implementation commit: `0625bbea58a7b14d035a5662dc395e2c482dbc77`
- Corrected cells estimated: 7/7
- Reference-price axis: `displayed_mid` only
- Level axis: `M=10` only
- OFI accumulation window: 10 seconds only
- Future horizons: 10/20/30/45/60/90/120 seconds
- Every cell records its held-out row count and row hash.
- Focused D40/D39/horse-race acceptance: 32 tests passed.
- Whole repository: 676 tests passed.
- Whole-repository Ruff: passed.
- Canonical strict mypy: 65 source files passed.
- Python compile check over `src`, `scripts` and `tests`: passed.
- Artifact axes, seven-cell completeness, C8 feature count, implementation commit, split boundary,
  committed-summary parity and hashes: passed.

Machine-readable committed result:
`docs/results/D40-OFI-HORIZON-EXTENSION-2026-08-20.json`.

Full local artifact:
`/Users/maheit/.openclaw/workspace/overnight-runs/d40-ofi-horizon-extension-20260820-r2/artifacts/full.json`.
