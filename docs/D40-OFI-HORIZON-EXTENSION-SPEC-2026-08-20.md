# D40 Displayed-Mid OFI Horizon Extension — Frozen Specification

**ID:** `D40 / OFI-HORIZON-EXTENSION-2026-08-20`

**Authorisation:** Aryan Ayyar's 2026-08-20 instruction to extend the exact displayed-mid
multi-level OFI construction from the completed D39 retrospective replay beyond ten seconds.

**Relationship to D39:** this is a separately identified retrospective extension. It does not
change `docs/D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md`, tomorrow's horizon grid, its competitor
panel, or its prospective sample.

**Order authority:** none. Read-only analysis only.

## D40-OBJ-01 — Research question

Measure the absolute held-out predictive power of the unchanged D39 `C8`, `M=10`, `h1=10 s`
specification for displayed-mid returns at

`h2 in {10, 20, 30, 45, 60, 90, 120} seconds`.

Report only `C8`'s absolute OOS R-squared and the shape of that horizon curve. Do not rank it
against another model or an external benchmark. Do not construct a last-trade-price target.

## D40-DATA-01 — Immutable input

Use exactly the validated 15:42 snapshot from the 2026-08-20 late-partial NIFTY front-month
futures capture:

`/Users/maheit/.openclaw/workspace/overnight-runs/ofi-partial-live-20260820/snapshots/1542.jsonl`

The artifact must record and verify the tape SHA-256. The tape is opened read-only and never
modified. The sample remains `retrospective_partial_session_exploration`.

## D40-STATE-01 — Causal anchor and book state

Use receive time as the causal clock. Each candidate anchor `t` is a valid depth200 publication
whose preceding 10-second predictor window remains inside one connection epoch. Invalid or
reconnect-spanning transitions are refused. The response is measured from the depth20 displayed
best bid and ask on their native publication clock.

## D40-EST-01 — Exact multi-level OFI construction

For each rank `m = 1,...,10` and each consecutive pair of depth200 book states, construct the
Cont-Cucuringu-Zhang rank-keyed order-flow increment. On the bid side, a price improvement enters
the new displayed quantity, an unchanged price enters the quantity change, and a retreat enters
the negative new quantity. The ask side uses the symmetric sign convention. Level OFI is bid flow
minus ask flow.

Sum each level's increments over the half-open trailing window `(t-10 s, t]`. Scale all ten level
sums by the same mean displayed depth denominator

`Q^(10,10s) = total displayed bid-plus-ask depth / (2 × 10 × valid transitions)`.

This yields ten depth-scaled OFI regressors. Levels are not accumulated into one scalar and are
not divided by separate per-level denominators.

## D40-EST-02 — Fixed C8 model

The feature vector is exactly D39 competitor `C8`:

1. displayed spread in futures ticks at `t`;
2. `log1p` of displayed level-one bid-plus-ask quantity at `t`;
3. the ten depth-scaled CCZ OFI level regressors from `D40-EST-01`.

For each response horizon, fit a separate ridge regression. Centre the training target by its
training mean. Standardise regressors using training rows only. Choose the ridge penalty from the
unchanged D39 grid by chronological inner validation on training data only. Apply the fitted
intercept, scales, coefficients, and penalty unchanged to the held-out test rows.

## D40-TARGET-01 — Displayed-mid return only

Let `mid(u) = (best_bid(u) + best_ask(u))/2`, resolved causally as of receive time `u`. For each
horizon `h`, the target is

`y_t(h) = [mid(t + 0.5 s + h) - mid(t + 0.5 s)] / futures_tick_size`.

Endpoints beyond observed coverage are missing. They are never extrapolated, carried backward,
or converted to zero. No last-trade-price return is built or reported.

## D40-OOS-01 — Chronological held-out evaluation

Split anchors chronologically 70/30. All parameter selection and standardisation use only the
training side. Use one common embargo of 120.5 seconds: the larger of the original 120-second D39
embargo and `0.5-second causal gap + 120-second longest target`. Test rows begin only after that
embargo. Each horizon then drops only rows lacking its own right-edge response coverage; every
model fitted within a horizon uses that horizon's identical rows.

## D40-METRIC-01 — Raw predictive power

For test targets `y_i`, predictions `yhat_i`, and the training-target mean `ybar_train`, report

`OOS R2 = 1 - sum_i (y_i - yhat_i)^2 / sum_i (y_i - ybar_train)^2`.

The required result table contains horizon, absolute OOS R-squared, its percentage form, training
row count, test row count, row hash, and selected ridge penalty. No model-relative increment and
no external benchmark enter the conclusion.

## D40-OUT-01 — Required outputs

1. a full machine-readable artifact outside Git containing all fitted-cell detail;
2. a compact machine-readable summary committed under `docs/results/`;
3. a plain-English methodology and results report committed under `docs/`;
4. a next-session prompt that asks tomorrow's full-session run to validate the observed horizon
   shape without changing its locked D39 test.

The summary must state whether the sequence is strictly increasing, the peak horizon and R-squared,
and the first horizon at which R-squared declines, if any.

## Acceptance requirements

- `D40-VAL-01`: custom response horizons are materialised by the canonical observation builder.
- `D40-VAL-02`: an embargo shorter than causal gap plus longest target is refused.
- `D40-VAL-03`: exactly seven displayed-mid, `M=10`, `h1=10 s` cells are estimated.
- `D40-VAL-04`: every reported row is `C8` absolute OOS R-squared; no last-trade result or model
  comparison appears in the compact summary or report.
- `D40-VAL-05`: tape hash, code commit, split, row support, row hashes, and full-artifact hash are
  recorded.
- Focused pytest, full pytest, Ruff, strict mypy, compile, diff, and staged-secret checks pass
  before the completion claim.
