# D41 Mid-Return Lags versus CCZ OFI — Frozen Exploratory Specification

**ID:** `D41 / MID-LAG-OFI-INCREMENTAL-2026-08-20`
**Claim:** `EF-11/H1`
**Scan:** `X-D41-MID-LAG-OFI-2026-08-20`
**Authorisation:** Aryan Ayyar's 2026-08-20 instruction to test whether current/past displayed-mid
returns forecast later displayed-mid moves, whether they beat CCZ OFI, and whether CCZ OFI adds
after the return history is controlled for.

This document is frozen and pushed before the D41 outcome code is executed. The tape has already
been inspected in D39/D40, so the exercise is permanently retrospective and exploratory even
though its new comparison is frozen before execution. It cannot change tomorrow's locked D39/D40
full-session tests, establish a signal, or authorise an order.

## `D41-OBJ-01` — Questions and hypotheses

On identical chronological held-out rows, answer:

1. Do trailing displayed-mid returns predict the future displayed-mid return?
2. Are trailing returns more accurate than depth-scaled ten-level CCZ OFI alone?
3. Does CCZ OFI improve the forecast after the complete return-lag bank is included?
4. Conversely, do return lags improve the forecast after CCZ OFI is included?

The redundancy criterion is predictive and out of sample. OFI is called **incrementally
redundant on this tape** only if the combined model has no positive OOS-R-squared increment over
the lag bank and its one-sided Clark--West test does not reject after horizon-family adjustment.
Return lags are called incrementally redundant by the symmetric combined-versus-OFI criterion.
Coefficient correlation by itself never establishes redundancy.

## `D41-DATA-01` — Immutable input and clock

Use only the validated 15:42 snapshot of the 2026-08-20 NIFTY August 2026 front-month futures
late-partial capture:

`/Users/maheit/.openclaw/workspace/overnight-runs/ofi-partial-live-20260820/snapshots/1542.jsonl`

Required SHA-256:
`93456eda4de33cc22fc1d9d3dc8fb5ca7a7bb8eab7108e3c0ef8859a97759a43`.

Receive time is the causal clock. Depth200 publications define predictor anchors and CCZ flow;
depth20 best bid and ask define displayed mid. No window may cross a reconnect epoch. Missing
endpoints are missing, never zero-filled or carried backward.

## `D41-TARGET-01` — Future displayed-mid return

For anchor `t`, causal gap `Z = 0.5 seconds`, and
`h in {0.5, 1, 2, 5, 10, 20, 30}` seconds,

`Y_h(t) = [mid(t + Z + h) - mid(t + Z)] / tick_size`.

No last-trade, microprice, effective-touch, price-level, spread, depth, queue, trade-flow, PnL, or
other fitted benchmark enters D41. The training-target mean appears only in the denominator of the
standard absolute OOS-R-squared definition.

## `D41-X-01` — Past displayed-mid returns

For `k in {0.5, 1, 2, 5, 10, 20, 30}` seconds,

`R_k(t) = [mid(t) - mid(t-k)] / tick_size`.

Estimate and report seven univariate `L_k` models plus one primary ridge `L_ALL` model containing
all seven `R_k`. This is the operational meaning of "current return or a lag combination". The
current price level is deliberately excluded because the target is a price *move*: placing the
level on the right-hand side would change the question into level prediction and mechanically
inflate fit.

## `D41-X-02` — CCZ OFI alone

For `w in {0.5, 1, 2, 5, 10}` seconds and ranks `m=1,...,10`, construct faithful D37 CCZ Eq. (2)
rank-keyed order flow over `(t-w,t]`. Divide all ten level flows by the one common D37 Eq. (3)
depth denominator `Q^{10,w}`. The ten scaled levels enter separately in ridge model `O_w`.

`O_w` contains no spread, depth, lagged return, microprice or other state control. This is the
requested OFI-alone object, not D39 `C8`, which also contained spread and level-one depth.

## `D41-EST-01` — Nested model panel

For every `(w,h)` estimate on identical rows:

- `L_ALL`: the seven-return lag bank;
- `O_w`: the ten depth-scaled CCZ OFI levels;
- `LO_w`: the exact union of `L_ALL` and `O_w`.

Also report every univariate `L_k` at every `h`. Features are standardised on training rows only.
Targets are centred by the training mean. Ridge penalties come from the existing declared grid
`{0, 0.01, 0.1, 1, 10, 100}` and chronological inner validation on training data only. Test rows
cannot select a lag, OFI window, penalty or sign.

The full declared output contains 49 univariate-lag cells and 35 cells for each of `O_w` and
`LO_w`, plus seven `L_ALL` cells: 126 future-prediction model cells. No cell is dropped after its
result is seen.

## `D41-INST-01` — Contemporaneous construction check

Independently confirm the established mechanical relation by regressing the same-window
displayed-mid return on the matching ten-level CCZ OFI vector for
`w in {0.5, 1, 2, 5, 10, 30}` seconds. Report chronological held-out absolute OOS R-squared and
HAC inference. This is a descriptive construction check only; it is not pooled with or used to
rank the future forecasts.

## `D41-OOS-01` — Chronological held-out design

Preserve the D39 anchor universe and 70% training boundary by making the new 20/30-second response
horizons additive to the canonical response map. Use a common 30.5-second embargo, covering the
0.5-second gap plus the longest target. Require 30 seconds of clean past history for every future
model so `L_k`, `L_ALL`, `O_w`, and `LO_w` share the exact same train and test row hashes within a
horizon. Each test target is scored once.

Absolute OOS R-squared is

`1 - sum((Y-Yhat)^2) / sum((Y-Ybar_train)^2)`.

## `D41-INF-01` — Dependence-aware significance

Forecast-loss inference uses the ordered held-out loss differential. The Newey--West lag is
`ceil(max(30, h+0.5) / median_test_anchor_spacing)` so both the 30-second lag bank and overlapping
future target are covered. Report the HAC t-statistic, effective sample size implied by the HAC
variance, raw p-value, and Holm-adjusted p-value within each named seven-horizon question family.

- Predictiveness of `L_ALL` and `O_w`: one-sided loss improvement over the training-mean forecast.
- `L_ALL` versus `O_w`: two-sided Diebold--Mariano test of equal held-out squared-error loss.
- `LO_w` versus `L_ALL`: one-sided Clark--West test for incremental OFI information.
- `LO_w` versus `O_w`: one-sided Clark--West test for incremental lag information.

The primary OFI comparison is pre-named `w=10 seconds`, inherited from D40. The other four OFI
windows are the complete declared robustness surface. Holm adjustment is performed separately for
each question across its seven target horizons; the 35-cell OFI-window surface is additionally
adjusted as one family before any non-primary window is highlighted.

## `D41-OUT-01` — Required outputs

1. Full immutable JSON artifact with tape, code, split, row, feature, fit and inference identities.
2. Compact JSON containing the contemporaneous curve, 49 lag cells and the 35-row three-model
   future comparison.
3. Plain-English report answering the four `D41-OBJ-01` questions first, with OOS R-squared and
   significance tables behind it.
4. `SIG-19` trial row, task-ledger status, traceability, changelog and committed hashes.

## Acceptance requirements

- `D41-VAL-01`: synthetic future dependence in lags and OFI is recovered; null features are not.
- `D41-VAL-02`: every past return ends at or before `t`; every future response starts at `t+0.5s`.
- `D41-VAL-03`: `LO_w` is the exact feature union of `L_ALL` and `O_w`.
- `D41-VAL-04`: all compared models share identical train/test row identities within horizon.
- `D41-VAL-05`: test targets cannot alter feature selection, standardisation or ridge penalty.
- `D41-VAL-06`: HAC lag covers both 30-second history and the response overlap; Holm families are
  complete and deterministic.
- `D41-VAL-07`: the committed compact result reproduces the full artifact exactly.
- `D41-VAL-ALL`: focused and full pytest, Ruff, strict mypy, compile, artifact/hash and secret
  checks pass before the empirical result is committed.

## Claim boundary

`sample_role = retrospective_partial_session_exploration`, `confirmatory_eligible = false`,
`registered_replication_eligible = false`, `order_entry_enabled = false`. A significant result on
this tape is evidence about this saved session and a frozen candidate for tomorrow; it is not a
confirmed signal.
