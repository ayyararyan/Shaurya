# Causal short-horizon predictor horse race — frozen exploratory specification

**Scan ID:** `X-OFI-HORSERACE-DAT20-05`

**Frozen:** 2026-08-19, before inspecting any new horse-race outcome table

**Confirmatory eligible:** `false`

**Evidence boundary:** exploratory predictive comparison on two already-inspected tapes; never causal,
confirmed, tradeable, economic, or representative.

## Claim and estimand

The predictive claim is: among seven causally available depth, state and flow predictor families,
identify which has the largest held-out incremental explanatory power for a later NIFTY-futures
midpoint return, conditional on the depth-only baseline, and whether its sign and improvement repeat
on both retained tapes. The unit is a valid depth200 publication anchor. The estimand is held-out OOS
R2 relative to the training-mean target, plus incremental OOS R2 relative to M0 and the prior nested
model. This is predictive, not causal: time ordering does not identify a structural counterfactual.

## DATA — frozen sample and timing

- **DATA-01:** Use only the two pinned front-month NIFTY futures `DAT-20` tapes and hashes already
  permitted by `X-OFI-DAT20-03`. No new capture or subscription.
- **DATA-02:** Predictor lookbacks `h1 = {0.5, 1, 2, 5, 10}` seconds. Future depth20 BBO-midpoint
  return horizons `h2 = {0.5, 1, 2, 5, 10}` seconds where coverage supports 0.5 seconds. Units are
  NIFTY ticks (Rs 0.05). A 30-second arm is outside the ranked family unless `GATE-01` opens it.
- **DATA-03:** Gap `Z = 0.5` seconds. Every predictor ends at anchor `t`; future return is
  `mid(t + Z + h2) - mid(t + Z)`, resolved as-of without crossing a connection epoch.
- **DATA-04:** Reuse `X-OFI-DAT20-03` quality/epoch filters, causal as-of resolution, complete-window
  guards, 70/30 within-tape chronological split and 120-second embargo. The response mean removed
  from test outcomes is the pooled training mean, never the test mean.
- **DATA-05:** Score every identified model on one common complete-case sample within each `h1 x h2`
  cell. Report model-specific construction/support loss before intersection. Missing signed trades
  are never replaced by zero. If M2 is unidentified, report its support explicitly and use the
  common sample among the remaining identified models; M2 receives no fabricated score.
- **DATA-06:** Standardisation, penalty choice and all fitted transformations use training data only.
  No cross-epoch windows, future depth, future trades, test-set tuning or test-set standardisation.

## STATE/FLOW — exact predictor objects

- **M0 / STATE-01 — depth only:** `log1p(q_bid1 + q_ask1)` and current spread. Both are terminal
  causal book states. No imbalance, order flow, microprice tilt or return enters M0.
- **M1 / STATE-02 — static queue imbalance:** terminal L1
  `(q_bid1 - q_ask1) / (q_bid1 + q_ask1)`, with zero denominator mapped to missing, not zero. The
  fitted model nests M0. Optional multi-level static imbalance may be emitted only as a separately
  labelled robustness arm and never replaces M1.
- **M2 / FLOW-01 — signed trade imbalance:** over `(t-h1, t]`, sum capture-time classified
  buyer-initiated last-trade quantity minus seller-initiated last-trade quantity. Require positive
  volume increment, `quote-mid-tick-v1`, valid classifier/alignment version, non-degraded sign, and
  exclude coalesced intervals because unseen excess volume has no identified sign. Also emit the
  predeclared normalised sub-arm `(buy-sell)/(buy+sell)` when denominator is positive. If the tapes
  predate these fields or support is inadequate, classify M2 `Blocked/Unidentified` and do not infer
  signs from midpoint or substitute VPIN.
- **M3 / FLOW-02 — exact L1 CKS OFI:** aggregate the Cont-Kukanov-Stoikov BBO event increment over
  `(t-h1,t]`: bid contribution is `+q_b` when bid rises, `q_b-q_b_prev` when unchanged, and
  `-q_b_prev` when it falls; ask contribution is `-q_a` when ask falls, `q_a_prev-q_a` when
  unchanged, and `+q_a_prev` when ask rises. Reuse the canonical implementation from
  `X-CKS-L1-OFI-DAT20-04` after it lands; no duplicate formula survives integration. Raw is primary;
  trailing-average L1-depth normalisation is a labelled sub-arm.
- **M4 / FLOW-03 — regularised multi-level OFI:** price-keyed vector net flow from existing OFI
  machinery in marginal rank bands `1`, `2-5`, `6-10`, `11-20`, `21-50`, `51-100`, `101-200`.
  Standardised Ridge includes M0 and selects `alpha in {0, 0.01, 0.1, 1, 10, 100}` by mean squared
  error on three expanding, embargoed inner training folds. Deterministic lowest-alpha tie-break.
  Emit coefficients, per-training-SD effects, band contributions, VIF/correlation and sign stability.
- **M5 / FLOW-04 — depth-adjusted multi-level OFI:** divide each band flow by its causal lookback-
  average displayed quantity in that marginal band, measured only on states in `(t-h1,t]`.
  Denominator floor is one contract; an empty band is missing. The result is dimensionless net flow
  per displayed contract. Use the same Ridge protocol and bands as M4. M5 nests M0 but is compared
  incrementally to M4 using held-out errors; it is not M4 plus a depth covariate.
- **M6 / EST-01 — combined model:** M0 plus M1, identified M2 raw, M3 raw, all M4 band flows and all
  M5 adjusted band flows. Use the same training-only Ridge grid/folds. Report leave-family-out OOS
  ablations. Model flexibility is never assessed by in-sample R2 alone.

## EST/OOS — fair evaluation

- **EST-02:** For every supported `h1 x h2 x model`, emit pooled and per-tape total, train, embargo
  and test support; in-sample R2/adjusted R2; OOS R2 versus training-mean target; incremental OOS R2
  over M0 and the prior meaningful nested model; RMSE; MAE; coefficient/sign; effect per training SD;
  raw-unit effect where defined; selected alpha; and standardisation parameters.
- **EST-03:** Fit pooled coefficients on pooled training rows, while preserving within-tape splits.
  Per-tape scores use the pooled fit and the pooled training target mean. A supplementary per-tape
  fit may diagnose direction but does not replace the common model.
- **OOS-01:** Report complete model/cell output. Rankings are compact pointers into that output, not
  a filtered winner table. Multiplicity covers all `5 x 5` cells, models and declared sub-arms.
- **OOS-02:** Rank by future incremental OOS R2 over M0, then require per-tape reproduction and a
  stable sign. Negative OOS R2 remains visible.

## ROB — dependence, controls and diagnostics

- **ROB-01:** For paired held-out squared-error improvement, report Newey-West/HAC with lag at least
  the response overlap, within-tape stationary block bootstrap, and non-overlapping calendar blocks
  where support permits. No iid significance claim.
- **ROB-02:** Run the full model/cell horse race on a past-mirror return with identical horizon and
  gap geometry. Future predictive improvement must be compared directly with this placebo.
- **ROB-03:** Run same-window fits only as a construction diagnostic, clearly separated from ranked
  future results.
- **ROB-04:** Report band collinearity, Ridge coefficient/contribution stability, common-sample
  attrition, epoch/coverage failures, and the limits of two roughly 11-minute tapes in one falling
  session.

## GATE — conditional 30-second robustness arm

- **GATE-01:** Open `h2=30` only if at `h2=10` at least one non-combined model M1-M5 satisfies all:
  (a) pooled held-out incremental OOS R2 over M0 is strictly positive; (b) incremental improvement
  is non-negative in each tape; (c) coefficient/direction is stable across tapes; and (d) its future
  incremental improvement is strictly greater than its past-mirror incremental improvement. The
  evaluated `h1` is that model's strongest 10-second future cell by pooled increment, with stable
  deterministic tie-break: smaller `h1`, then earlier model number. If none qualifies, emit exact
  failing conditions and `gate_passed=false`; do not rank, fit or interpret a 30-second family.
- **GATE-02:** Same-window fit cannot open the gate. M6 cannot open it.

## Literature benchmark and language boundary

The report distinguishes CKS BBO OFI (Cont, Kukanov & Stoikov), static next-tick queue imbalance
(Gould & Bonart), multi-level OFI (Xu, Gould & Howison), flow-based multi-horizon forecasting (Kolm,
Turiel & Westray), and deeper additions/cancellations/shape at meso horizons (Bechler & Ludkovski).
VPIN appears only as toxicity/volatility context and is not a directional predictor. Agreement with
literature is descriptive benchmarking, never validation. Contemporaneous impact results do not
prove future-return prediction.

## OUT/VAL — artifacts and completion gates

- **OUT-01:** Compact JSON summary; complete JSONL cells; compact CSV ranking, ablation, intensity,
  support and gate tables; deterministic hashes and exact CLI. Large outputs remain gitignored but
  compact summaries are committed.
- **OUT-02:** Plain-English report `docs/OFI-HORSERACE-2026-08-19.md` with claim-evidence ledger,
  exact results, per-horizon ranking, per-tape stability, controls, adjacent-scan comparison,
  literature benchmark, limitations and bottom line.
- **VAL-01:** Hand-worked tests cover every predictor sign/definition; zero/missing support; causal
  alignment; common complete cases; train-only standardisation/Ridge; split/embargo; gate; sibling
  CKS reuse; deterministic output.
- **VAL-02:** Acceptance requires targeted tests, relevant/full Python tests as feasible, Ruff,
  strict mypy, compilation/static check, diff check, staged secret scan and deterministic replay/hash.
- **VAL-03:** Update `TASKS.md` and `CHANGELOG.md` with scan ID and Level-3 machinery / exploratory
  empirical evidence. Do not edit `H-SIG21.md`.

## Explicit exclusions

No orders, credentials, capture, subscriptions, live decisions, transaction-cost claim, strategy
promotion, causal interpretation, confirmation claim, VPIN substitution, outcome-driven grid change,
or independent 0.1/0.25-second observation. No result changes immutable `H-SIG21`.

## Completion criterion

The scan is complete only when all identified arms and supported 0.5/1/2/5/10-second cells are
emitted, M2 is honestly scored or classified unidentified, the 30-second gate is mechanically
resolved, artifacts replay deterministically, tests and static checks are reported, and all
appropriate code/docs/summaries are committed and pushed with local `HEAD == origin/main` clean.
