# Effective Touch, Evaluation Metrics, Window Extension and Microprice — Frozen Specification

**ID:** `D38 / TOUCH-METRICS-2026-08-20`
**Status:** Frozen on Aryan's explicit approval, 2026-08-20 14:25 IST — *"I agree with all 4
exactly. Let's get this going immediately."*
**Builds on:** `D37 / CCZ-OFI-MIGRATION-2026-08-20` (commit `2bec2e2`).
**Branch:** `ccz-ofi-migration` in `/Users/maheit/Documents/Shaurya-ccz`.
**Scope class:** exploratory diagnostics. Not SIG-21, not confirmatory, no order authority.

---

## 0. Motivating finding

The 11:30 horse race ranks the model families on future returns as:

```
M2 signed trade imbalance          +1.54 pp over M0
M4 multi-level OFI (raw)           +0.88 pp
M5 depth-adjusted multi-level OFI  +0.21 pp
M3 CKS L1 OFI                      -0.02 pp
M1 static L1 queue imbalance       -0.01 pp   (negative at all five horizons)
```

The two objects the literature rates highest for short-horizon prediction — static queue
imbalance and CKS L1 OFI — fail worst. Amendment `ID-CKS-02` records median displayed spread of
**100–134 ticks** and **42–48% of executions printing strictly inside the displayed best
bid/ask**. Every book-derived predictor is defined *relative to the touch*; if the displayed L1
is not the touch, none of them has yet had a fair test. That is the hypothesis this
specification tests.

---

## A. Effective touch reconstruction

`TOUCH-01` — **Quantify the problem.** For every trade print, classify its price against the
contemporaneous displayed L1: strictly inside, at bid, at ask, strictly outside. Report the
distribution overall, by hour, and by displayed-spread bucket. Confirm or refute the 42–48%
figure from `ID-CKS-02` on the current tape. This is a factual measurement and must be reported
even if it contradicts the hypothesis.

`TOUCH-02` — **Effective touch estimator.** Over a rolling causal window of trade prints,
using the existing `trade_direction` classification:
`effective_ask ≤ min(buyer-initiated prints)`, `effective_bid ≥ max(seller-initiated prints)`.
Strictly causal: only prints **before** the anchor timestamp may be used. Report per-anchor
coverage (share of anchors with a valid effective touch) and staleness (age of the newest print
used). Where the estimator is undefined, emit it as missing — never silently fall back to the
displayed touch.

`TOUCH-03` — **Reference-price ladder.** Four reference prices, evaluated identically and
reported side by side:
(i) displayed depth20 mid — the status quo baseline;
(ii) last traded price;
(iii) effective-touch mid from `TOUCH-02`;
(iv) microprice.
Each is applied on **both** sides of the regression: as the return target, and as the reference
against which predictors are measured. Reporting only one side would confound regressor noise
with dependent-variable noise.

`TOUCH-04` — **Re-derivation.** Recompute CCZ multi-level OFI, L1 queue imbalance and microprice
relative to the effective touch, and rerun the horse race under each reference price in
`TOUCH-03`. The comparison of interest is whether the book-derived families recover once the
reference is corrected.

## B. Evaluation metrics

`METRIC-01` — **Information coefficient.** Pearson and Spearman correlation between prediction
and realised return, with stationary block-bootstrap confidence intervals.

`METRIC-02` — **Sign accuracy.** Hit rate against both a 50% null and the majority-class null;
additionally reported on strictly non-zero realised moves.

`METRIC-03` — **Net-of-cost PnL.** A forecast-based strategy in the spirit of CCZ §4.2.2: take
a position when the forecast exceeds the prevailing spread, self-financed. Report gross PnL,
PnL net of half-spread plus fees, turnover, and PnL per unit risk.

`METRIC-04` — **R² retained, never alone.** Out-of-sample R² stays for continuity with prior
work, but every reported cell must carry `METRIC-01` through `METRIC-03` alongside it. A cell
reporting R² by itself is a defect.

`METRIC-05` — **Same discipline as today.** Every new metric inherits the existing
dependence-aware FDR correction, the past-mirror comparison, and the per-tape sign check. A
metric that improves the headline while failing the past mirror is reported as failing.

## C. Contemporaneous window extension

`WINDOW-01` — Extend the same-window diagnostic grid to include **30 s and 60 s**. 60 s matches
CCZ's contemporaneous frequency (`h = 1 minute`) exactly, and is the only cell directly
comparable to their published numbers.

`WINDOW-02` — Promote the same-window diagnostic from `descriptive_only: true` to a first-class
**replication gate** against CCZ's published contemporaneous figures: 71.16% in-sample and
64.64% out-of-sample for best-level, 87.14% in-sample for integrated. Record the gap explicitly
in the artifact rather than leaving it to be inferred.

`WINDOW-03` — Emit the full R²-versus-window curve at every depth so that a plateau, or its
absence, is directly visible. The 11:30 curve is monotone increasing and still climbing at the
10 s ceiling; whether it flattens is the question.

## D. Microprice arm

`MICRO-01` — Simple imbalance-weighted microprice as a **named predictive arm** (`M7`). It
currently exists only as the control `microprice_tilt_ticks` and has never been raced.

`MICRO-02` — Stoikov (2018, *Quantitative Finance*, "The Micro-Price") **iterated** estimator:
the Markov-chain adjusted fair value over (imbalance, spread) states, fit on training rows only
and applied unchanged out of sample. Named arm `M8`.

`MICRO-03` — Both enter `MODEL_ORDER` as families, not controls, and inherit the full metric
set from section B.

## E. Operational

`OPS-CCZ-02` — The next controller generation must re-check the commit pin and worktree
cleanliness **before every unit**, fail closed, and record the observed HEAD per stage rather
than a constant. The currently running 15:42 unit is unaffected by any edit now, because its
controller module is already loaded in memory; this applies to the next run.

## F. Acceptance tests

- `VAL-TOUCH-01` Effective touch never uses a print at or after the anchor (leakage test).
- `VAL-TOUCH-02` Undefined effective touch propagates as missing, never as displayed touch.
- `VAL-TOUCH-03` Every reference price in `TOUCH-03` produces a complete, comparable cell set.
- `VAL-METRIC-01` IC, hit rate and net PnL are computed on the identical held-out rows as R².
- `VAL-METRIC-02` A cell emitting R² without the companion metrics fails the artifact check.
- `VAL-WINDOW-01` The 60 s same-window cell is present at every depth and labelled as the CCZ
  comparison cell.
- `VAL-MICRO-01` Stoikov state model is fit on training rows only (leakage test).
- `VAL-ALL` Full suite, ruff, strict mypy clean.

## G. Explicit exclusions

- The live capture and the running 15:42 checkpoint are untouched.
- No order path, no SIG-21 credit, no confirmatory status.
- Pre-existing artifacts are preserved and relabelled, never pooled across reference prices
  without an explicit reference-price column.
