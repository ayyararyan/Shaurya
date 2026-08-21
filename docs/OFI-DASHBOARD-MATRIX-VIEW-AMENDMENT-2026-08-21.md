# OFI dashboard matrix-view amendment

**ID:** `D45 / ANL-06-MATRIX-VIEW-2026-08-21`

**Amends:** `docs/OFI-DASHBOARD-SPEC-2026-08-20.md` and the dashboard portion of
`docs/D38-D39-D40-LIVE-AMENDMENT-2026-08-21.md`.

**Directed by Aryan Ayyar:** 2026-08-21. The default dashboard must be a simple spreadsheet-style
table, not a collection of cards, leaderboards, diagnostic grids or narrative summaries.

**Superseded value source:** D46 (`OFI-DASHBOARD-ROLLING-30M-AMENDMENT-2026-08-21.md`) replaces
the fixed D39/D40 70/30 values below with causal 30-minute rolling live forecasts. This file still
governs the simple table presentation; its original D39/D40 mapping is retained as historical
traceability, not as the current dashboard estimator.

## 1. Default table

`DASH-UX-01`: the default screen contains one matrix and no other research panel.

- columns: OFI sampling/lookback horizon `h1 = {0.5,1,2,5,10,20}` seconds;
- rows: predicted/future horizon `h2 = {0.5,1,2,5,10,20}` seconds; and
- cell: C8 absolute held-out OOS R-squared, displayed as a percentage.

The 25 D39 `displayed_mid / M=10` cells populate the 0.5–10 second square. D40 supplies the
`h1=10, h2=20` cell. No other D39/D40 combination involving a 20-second lookback or a different
lookback at the 20-second future horizon was specified or estimated. Those cells display `—` and
are never zero-filled or inferred.

## 2. Minimal context

`DASH-UX-02`: above the table, show only source-prefix time, D39 progress, D40 progress and the
exploratory label. Below it, define `—` and state that the closed-session recomputation is
authoritative. D38, ANL-06 leaderboards, honesty cards, full model grids and technical counters do
not appear on the default screen. They remain unchanged in the read-only APIs and persisted
artifacts.

## 3. Compact read-only delivery

`DASH-UX-03`: `GET /api/overview` remains the browser polling route and contains the primary D39
slice plus D40 rows. `/api/state`, `/api/live-studies`, `/api/cells` and `/api/history` remain
unchanged and complete. No write method, socket, credential or order path is added.

## 4. Acceptance

- `DASH-UX-VAL-01`: the table has the exact six row and six column horizon labels.
- `DASH-UX-VAL-02`: D39 C8 values map by `(h1,h2)`; D40 maps only to `h1=10` and its declared `h2`.
- `DASH-UX-VAL-03`: unspecified combinations render `—`, never zero or a carried value.
- `DASH-UX-VAL-04`: the root page contains no default leaderboard, evidence cards, D38 panel or
  full ANL-06 grid.
- focused/full tests, Ruff, strict mypy, compileall, browser render and live endpoint checks pass
  before a completion claim.
