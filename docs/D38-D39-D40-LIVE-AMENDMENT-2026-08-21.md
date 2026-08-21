# D38/D39/D40 intraday execution and dashboard — owner amendment

**Amends:**

- `docs/TOUCH-METRICS-SPEC-2026-08-20.md` (`D38`)
- `docs/D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md` (`D39`)
- `docs/D40-OFI-HORIZON-EXTENSION-SPEC-2026-08-20.md` (`D40`)
- `docs/OFI-DASHBOARD-SPEC-2026-08-20.md` (`ANL-06`)

**Directed and approved by Aryan Ayyar:** 2026-08-21. The owner correction is binding:
`D38`, `D39`, and `D40` must execute while the market session is growing and their findings must
appear on the live dashboard. Post-close execution remains a final recomputation and acceptance
check; it is not the first time these objects are evaluated.

**Order authority:** none. The live study worker reads only through the DAT data-access gateway,
opens no broker socket, imports no credential or order path, and cannot place an order.

## 1. Corrected execution boundary

The earlier wiring that left D39/D40 waiting for an accepted close receipt was an implementation
error relative to the owner's intended monitoring design. The corrected lifecycle is:

1. follow the active DAT dataset as an append-only growing tape;
2. freeze a complete-line byte prefix and identify it by dataset ID, byte offset, SHA-256, last
   receive timestamp, and wall-clock snapshot time;
3. compute and publish D38 on that prefix;
4. compute and publish D40's exact seven-horizon curve on that prefix, one cell at a time;
5. compute and publish D39's complete 600-cell reference x level-count x lookback x horizon sweep,
   one cell at a time, with all thirteen competitors inside each cell;
6. repeat on a later complete prefix after a full cycle; and
7. after close, recompute on the accepted closed tape and retain the original acceptance gates.

The dashboard must never hide a long-running fit. It displays the active stage, completed/total
cells, source-prefix timestamp and age, last error, and the most recent complete cell while the
next cell is fitting.

## 2. Evidence boundary for a growing prefix

An intraday prefix result is `growing_prefix_exploration`, is non-confirmatory, and has no order
authority. The chronological 70/30 split, causal gap, embargo, training-only standardisation,
ridge selection, common-row checks, past mirror, companion metrics, and frozen model definitions
are unchanged. Because successive prefixes overlap and their 70/30 boundary moves, intraday
refreshes are repeated provisional views and are not independent replications. The dashboard
must state that limitation beside the numbers.

The closed-session recomputation remains the authoritative result for that session. A prefix can
falsify an optimistic interpretation early; it cannot establish a session-level signal.

## 3. D38 live contract

For every complete prefix, publish the unchanged `TOUCH-01` print-location distribution and
`TOUCH-02` effective-touch coverage for every declared rolling window. Required dashboard fields:
classified-print count, strictly-inside/at-touch/outside shares, displayed-spread median, effective
touch coverage by window, source-prefix timestamp, and update time.

## 4. D39 live contract

Run the complete frozen axes, not a reduced primary slice:

- six reference prices;
- `M in {1,5,10,20}`;
- `h1,h2 in {0.5,1,2,5,10}` seconds;
- competitors `C0..C12`; and
- 399 stationary-block bootstrap replicates and all frozen companion metrics.

This is 600 outer cells. The live worker evaluates `displayed_mid/M=10` first so the owner's main
CCZ question appears promptly, then completes every remaining cell. Each completed cell is
appended to an immutable JSONL artifact and an atomic compact state is refreshed for the
dashboard. Partial progress is labelled partial and never represented as the complete D39 grid.

## 5. D40 live contract

Run the unchanged displayed-mid `C8`, `M=10`, `h1=10 s` model at
`h2 in {10,20,30,45,60,90,120}` seconds. Publish each completed horizon immediately, including
absolute OOS R-squared, row support, selected ridge penalty and common-row hash. Once all seven
exist, publish the peak, first decline and monotonicity fields from the frozen D40 summary.

## 6. Dashboard and API contract

`GET /api/live-studies` returns the atomic D38/D39/D40 state. `GET /api/state` embeds the same
object. The HTML surface shows:

- D38 live touch measurements;
- the seven-row D40 horizon curve;
- D39 completed/600 progress and a `displayed_mid/M=10` C2/C8/C12 comparison table; and
- exact freshness/stage/error labels.

During a long ANL-06 refit the HTTP layer serves the last complete immutable ANL-06 frame and the
current live-study sidecar state. HTTP responsiveness must not depend on acquiring the estimator's
fit lock.

### 6.1 Owner decision-view amendment

`docs/OFI-DASHBOARD-MATRIX-VIEW-AMENDMENT-2026-08-21.md` supersedes the first screen's visual
hierarchy. The default view is one C8/displayed-mid/M10 OOS R-squared matrix: sampling/lookback
horizon across columns and predicted horizon down rows. D38, D39/D40 detail and full-grid
diagnostics remain available through complete read-only APIs; no measured field or artifact is
deleted.

## 7. Acceptance requirements

- `LIVE-OPS-01`: complete-line prefix hashing refuses a torn trailing row.
- `LIVE-OPS-02`: the worker uses a DAT dataset handle and has no socket, credential, or order path.
- `LIVE-D38-01`: a prefix produces all D38 declared measurements and provenance.
- `LIVE-D39-01`: callbacks publish all requested axes without changing cell results.
- `LIVE-D39-02`: partial progress is explicit and a complete claim requires 600/600 cells.
- `LIVE-D40-01`: all seven exact frozen horizons appear and summary parity matches D40.
- `LIVE-OUT-01`: `/api/state` and `/api/live-studies` expose the same state.
- `LIVE-OUT-02`: the HTML contains D38, D39, D40, source-prefix freshness, and the
  exploratory/non-independent-prefix warning.
- `LIVE-OUT-03`: cached HTTP remains responsive while the ANL-06 engine is fitting.
- focused tests, full pytest, Ruff, strict mypy, compileall, diff and secret checks pass before a
  completion claim.

## 8. Explicit exclusions

No model definition, competitor, reference price, grid arm, bootstrap count, causal gap, embargo,
metric, verdict rule, or post-close acceptance gate is removed. No prefix result is promoted to a
signal, confirmation, economic recommendation, or order decision.
