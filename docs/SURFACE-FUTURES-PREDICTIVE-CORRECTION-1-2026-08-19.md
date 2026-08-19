# Correction 1 — exact OFI/LOB reconciliation for the eSSVI predictive scan

**Parent scan:** `X-SURFACE-FUT5-20260819-06`

**Correction ID:** `X-SURFACE-FUT5-RECONCILE-20260819-07`

**Directed by Aryan:** 2026-08-19, after rejecting the reported negative OFI/LOB comparison as
inconsistent with `X-OFI-HORSERACE-DAT20-05`

**Evidence class:** post-outcome exploratory correction; permanently `confirmatory_eligible=false`

## Previous claim being corrected

The parent report called its five-level `L/O/LO` rows a comparison with the earlier OFI horse race
and used their negative held-out R² values to contextualise the surface result. That comparison was
not model-equivalent:

1. the horse race used two contemporaneous 11-minute DAT-20 tapes, depth200 predictor anchors and a
   depth20 target, while the parent scan used the full-session Quote/Full tape and five-second
   surface-fit anchors;
2. the horse-race lead was `M3b`, an unpenalised three-variable model containing log L1 depth,
   spread and depth-normalised L1 CKS, while the parent `O` omitted the state baseline and `LO` was a
   34-variable Ridge model;
3. the horse-race headline was `h1=2s, h2=2s`; for the five-second target its fixed strongest
   candidates were `M3b h1=1s` and primary `M4 h1=2s`, whereas the parent comparison ranked only a
   five-second lookback; and
4. the parent LOB block omitted the horse race's exact `log1p(q_bid1+q_ask1)` state variable.

The parent full-session surface correlations and target construction are not automatically
invalidated by this discrepancy. The cross-model comparison and any wording implying it reproduced
or contradicted the earlier OFI result are invalid until this correction is complete.

## Locked correction design

### A. Exact reproduction gate

Rerun `X-OFI-HORSERACE-DAT20-05` on its two immutable tapes with seed `20260819` and 400 bootstrap
replicates. The seven non-summary artifact hashes must exactly match the committed hashes. Record
the exact five-second-target cells for:

- `M0`: log L1 depth + spread;
- `M3b h1=1s`: the prior horse-race strongest depth-normalised CKS candidate at `h2=5s`;
- `M4 h1=2s`: the prior horse-race primary multi-level OFI winner at `h2=5s`; and
- `M3b h1=5s`, to distinguish lookback mismatch from data/sample mismatch.

### B. Same-anchor surface reconciliation

Join each horse-race depth200 anchor to the latest successful displayed surface frame at or before
the anchor. Refuse future frames, cross-epoch joins and a carried-frame age above six seconds. Keep
the exact horse-race target, within-tape 70/30 split, 120-second embargo, pooled training mean,
training-only transformations and test rows.

Fit and report:

- exact `M0`, `M3b h1=1s` and `M4 h1=2s` unchanged;
- `S`, the 72 surface-economic variables;
- `M0+S`, `M3b+S` and `M4+S`.

Models containing the 72-variable surface block use the frozen Ridge alpha grid and horse-race
training-only expanding folds. Report OOS R², RMSE, alpha, per-tape R², paired squared-error
increments, the three dependence-aware checks, unique displayed surface frames and carry ages.
The primary surface increment is `M3b+S minus M3b`; `M4+S minus M4` is the multilevel robustness
comparison. Repeated anchors sharing a displayed frame are not independent confirmations.

### C. Full-session five-level correction

Restore exact L1 total displayed depth and `log1p` L1 depth to each surface-fit observation. On the
parent full-session target `mid(t+5.5s)-mid(t+0.5s)`, add separately labelled horse-aligned
five-level rows:

- `H0`: log L1 depth + spread;
- `H1`: H0 + static L1 queue imbalance;
- `H3` and `H3b` at lookbacks 0.5/1/2/5/10 seconds;
- five-level `H4` and `H5` analogues using marginal bands 1 and 2–5, explicitly not called the
  seven-band depth200 M4/M5; and
- fixed candidate rows `H3b h1=1s` and `H4-five-level h1=2s` with and without the surface block.

Preserve the parent chronological split clock and five-second target. Rows for optional lookbacks
use their honest available support and never redefine the parent common sample. The exact
depth200 M4 cannot be claimed on a five-level tape.

### D. Global adjacent-component audit

Audit target units and endpoints, anchor clocks, L1-depth construction, CKS numerator and depth
denominator, marginal-band definitions, model intercept and drift handling, alpha selection,
within-tape versus pooled splits, common-case support, target benchmark, per-tape scores, surface
as-of causality and artifact/report labels. Add regression tests for the exact omitted M0/M3b
mapping and for refusal to label the five-level analogue as depth200 M4.

## Outputs and correction rule

- Machine reconciliation bundle under gitignored `artifacts/surface-futures-reconciliation/`, with
  source/code/output hashes and deterministic replay.
- Committed compact JSON and model table under `docs/results/`.
- A corrected parent report that begins with the discrepancy, separates same-DAT20 reconciliation
  from full-session generalisation, and explicitly retracts the earlier comparison wording.
- Updated coverage, `TASKS.md` and `CHANGELOG.md`.

The correction is complete only after both exact-sample reconciliation and the corrected
full-session replay are verified, every required artifact is deterministic, tests/static checks
pass, and the final clean commit is pushed with local `HEAD == origin/main`.
