# OFI dashboard multi-beta-window amendment

**ID:** `D48 / ANL-06-MULTI-WINDOW-C8`

**Directed and approved by Aryan Ayyar:** 2026-08-21. The main dashboard must show five identical
C8 grids whose only difference is how much immediately preceding data estimates the betas:
`2, 5, 10, 15, 30` minutes.

Each grid retains D46/D47's exact axes and objects:

- columns: OFI sampling horizon `h1 in {0.5,1,2,5,10}` seconds;
- rows: displayed-mid forecast horizon `h2 in {0.5,1,2,5,10,20}` seconds;
- model: C8, displayed mid, M=10, 0.5-second causal response gap;
- fit: training-only standardisation and training-only ridge selection; and
- outputs: cumulative genuine OOS R2 plus the trailing-five-market-minute D47 score and n.

For beta window `W`, forecast anchor `t` admits only same-epoch training anchors
`s in [t-W,t]` satisfying `s+0.5+h2<=t`. No panel pools observations or coefficients across beta
windows.

## Migration and evidence

The existing 30-minute grid keeps its cumulative forecasts, pending outcomes, R2 accumulators and
recent win scores. The new 2/5/10/15-minute grids begin only after the D48 worker launches; they
must not be backfilled from outcomes already known at launch. Until a new cell's first forecast
matures, it displays `—`.

The forecast target cadence remains five seconds. Exact ridge-path factorisations may be shared
across candidate penalties and independent beta windows may be evaluated with bounded concurrency;
these are computation-only optimisations and must produce the same coefficients/predictions as
the original per-cell C8 estimator.

The five grids become the default/main dashboard. D38/D39/D40 and the older single-grid objects
remain preserved through read-only APIs and artifacts. Order authority remains absent.

Acceptance:

- `MW-AXIS-01`: exact beta windows `{2,5,10,15,30}` minutes and 30 cells per window.
- `MW-CAUSAL-01`: each cell uses only its own trailing window and causally mature labels.
- `MW-PARITY-01`: batched ridge-path predictions equal the original per-cell C8 fit.
- `MW-MIGRATE-01`: old unqualified state maps only to the 30-minute keys; new windows start empty.
- `MW-CADENCE-01`: active-tape fit for all 150 cells completes inside the five-second cadence
  budget after initial buffer bootstrap.
- `MW-OUT-01`: main page and compact API expose five ordered grids with correct labels and values.
