# RV dashboard integration — 2026-09-09

## Forecast-first presentation amendment

User requested a simpler dashboard because RV was not visible. Presentation-only scope:
RV-UI-01 prominent RV/ATM IV/q cards above the chart, responsive on narrow screens;
RV-UI-02 preserve full diagnostics and mispricing monitor in closed expandable sections;
RV-UI-03 server-render initial forecast values and keep updates alive when Plotly is missing;
RV-UI-04 verify desktop/mobile rendering and deployed live API. No model changes.
Server currently returns RV correctly; exact cause of the user's missing panel is unconfirmed.
An old open page retains its old HTML even though its polling fetches new JSON.

Authorized: pull Aryan's `shaurya_02-09-2026` forecaster and integrate the dashboard.
Source: `13c83b8`, merged into isolated `integration/rv-dashboard-20260909` from
main `c3bd026`. Original worktree and collector remain untouched.

## Frozen scope and acceptance

| ID | Requirement | Acceptance |
|---|---|---|
| RV-01 | Use the branch's frozen IV-only NSGVC model without refitting or changing coefficients | Formula and unit tests |
| RV-02 | Display front-expiry annualized forecast RV, ATM IV, q, expiry and horizon | Live API arithmetic and browser render |
| RV-03 | Historical forecasts use that historical frame; missing/failed inputs are unavailable | Historical and invalid-input regression tests |
| RV-04 | Preserve numerical conditioning, all-OTM display, ATM diagnostics and separate reference policy | Patch parity, surface regressions and live API |
| RV-05 | Restart only the read-only dashboard using the existing DAT dataset | Advancing fits, unchanged collector, no orders |

Forecast RV is estimated forward realized volatility, not observed realized volatility.
The target is integrated realized variance; annualized RV is sqrt(predicted RV_int/T).
q is a variance ratio, not a volatility ratio. Exact fitted maturity uses a 365-day
basis in the dashboard. Nearest-weekly NIFTY only; no extension to far expiries,
new training, order gates, or claim of live predictive validation. Existing stale-feed
indicators remain authoritative for the source fit. Full formulas and frozen model
provenance are in VARIANCE_CARRY.md.

## Verification and operational state

All five requirements above are implemented and verified for the NIFTY dashboard.
87 focused tests passed, including independent frozen-formula arithmetic, historical
frame consistency, failed/missing/nonfinite input behavior and prior surface/reference
regressions. Ruff, strict mypy on the three dashboard/forecast modules, and diff checks
passed. The eight original locally corrected files match byte-for-byte in this checkout,
with dashboard.py mapped to the upstream-renamed dashboard_base.py.

Chrome preview rendered the RV band and WebGL surface together. The deployed URL remains
http://100.65.47.57:8767/; live sequences advanced 5 to 10, history API forecast was ok,
both arbitrage checks passed, ATM agreement diagnostics remained populated and reference
include_atm_strikes remained false. Checked forecast: 8.535% annualized RV, 9.874% ATM IV,
q 0.7471, expiry September 15. These values vary with incoming fitted quotes.

Dashboard owner: tmux shaurya-rv-dashboard-20260909, using this isolated checkout.
Previous consumer PID 89572 stopped with SIGINT. Collector PID 83560 was unchanged;
dataset ds-2ee2e2d0d9694db8bd6e5a1da88897d4 remains authoritative.
Original main checkout remains unchanged with its local edits. Nothing pushed.

Evidence: /Users/maheit/.openclaw/workspace/overnight-runs/shaurya-essvi-20260909/
rv-preview.png, rv-preview-state{,-2}.json, rv-live-{1,2}.json,
rv-live-history.json, rv-dashboard.log. No new predictive-performance claim,
model re-estimation, trading authorization or close-finalization verification.

### Forecast-first verification (supersedes presentation state above)
All four RV-UI requirements verified. 57 dashboard/forecast tests, Ruff and targeted
strict mypy passed. Chrome at 1440x1000 and 390x844: RV visible near top, no horizontal
overflow; details expansion, historical forecast playback, dark theme and simulated
missing Plotly checked. Live screenshots: simple-live-{desktop,mobile}.png in evidence
directory. Dashboard now tmux shaurya-simple-dashboard-20260909 / PID 93848; collector
83560 unchanged. Model code and coefficients untouched. User's exact earlier visibility
failure remains unconfirmed; old-tab HTML retention is a possible explanation.
