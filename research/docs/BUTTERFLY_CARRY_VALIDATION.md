# Butterfly dashboard acceptance — 2026-09-09

## Owner summary
Implemented the authorized nearest-weekly NIFTY short iron butterfly dashboard with
400/500-point wings each side. Prices are indicative current BBO; carry/P&L rankings
are conditional simulations, not empirically validated forecasts of strategy returns.
No orders or futures hedges. Original RV coefficients and eSSVI/reference policy unchanged.

Canonical scope: BUTTERFLY_CARRY_DESIGN.md (iron-carry-v1).

## Specification traceability

| ID | Status | Evidence |
|---|---|---|
| BFLY-01 | Implemented / live verified | Both widths, four signed legs, master-derived lot size 65; terminal payoff fixtures |
| BFLY-02 | Implemented / live verified | Stale/future/missing/depth/crossed/unsupported tests; live candidate rejects explicit |
| BFLY-03 | Implemented / live verified | BBO vs mid vs model, fees/slippage separated; independent live credit arithmetic |
| BFLY-04 | Implemented / tested | Signed forward Greeks; canonical scalar Black parity, flat-vol theta/gamma identity |
| BFLY-05 | Implemented / simulated | Next-open and terminal ledger; exact hold payoff and exercise-tax test |
| BFLY-06 | Implemented / simulated | Recenter boundary and no-future-lookahead tests; September 14 holiday skipped |
| BFLY-07 | Implemented / simulated | Five scenarios, monotonic friction cost, independent antithetic-pair MC SE |
| BFLY-08 | Implemented / live rendered | Carry/risk, expiry, local carry, next-open, cost sorts; per-lot metrics |
| BFLY-09 | Implemented / browser verified | Desktop/mobile, filter, row selection, legs/scenarios, centre tracker |
| BFLY-10 | Implemented / live verified | Existing surface/RV/reference tests; historical frames and stale marker; no Plotly fallback |

Required 10 / implemented 10 / missing 0. Correctness: 118 focused tests passed in
3.55 seconds; Ruff and strict targeted mypy passed. Full repository suite not run;
no claim that pre-existing catalogue-inventory failures are resolved.

## Live and UI evidence

- URL: http://100.65.47.57:8767/?view=butterflies
- Consumer: tmux shaurya-butterfly-dashboard-20260909, PID 97293, worktree
  /Users/maheit/Documents/Shaurya-rv-dashboard (integration/rv-dashboard-20260909).
- Prior dashboard PID 93848 stopped with SIGINT. Collector PID 83560 unchanged;
  dataset ds-2ee2e2d0d9694db8bd6e5a1da88897d4 remains authoritative.
- Live sequences 13 -> 27; 17 eligible candidates, both widths. One observed fit
  including analytics took 0.173 seconds. Feed live, surface fresh, arbitrage passed;
  ATM quote-agreement diagnostics preserved, reference include_atm_strikes=false.
- Butterfly RV equals dashboard RV to 1e-12 relative tolerance. Candidate credit
  independently reconstructed from bids/asks; terminal payoff checked at centre
  and outside both wings; costs and recenter-count bounds checked across scenarios.
- Chrome CDP: 1440x1100 desktop and 390x844 mobile, no page horizontal overflow.
  Wing filter, cost/overnight sorting, leg selection, historical frame playback,
  stale warning and missing-Plotly behavior verified; zero JavaScript exceptions.
  Centre tracker confirmed -400-point drift breaches 200-point threshold, target
  nearest 50-point centre, next check September 10 15:15; explicitly no order action.
- At one checked snapshot the top carry/risk candidate was 23,300 / 400, with
  recentered scenario mean about Rs2,014 and MC SE Rs309, but p05 about -Rs12,724.
  These are time-varying diagnostics, not an instruction to enter that trade.

## Important interpretation boundaries

- Actual daily recentering through expiry has NOT occurred. Its P&L is simulated;
  live verification means current quotes/forecasts are correctly fed into that simulation.
- Flat future ATM IV and calendar-time variance allocation are explicit assumptions,
  not predicted smiles or a trained overnight model. +/-2% gaps are stress scenarios.
- Static loss is before exercise tax and does not bound a recentered sequence. Tail
  means and loss probabilities are conditional on the assumed paths, not guarantees.
- Informational DAT flags (source sequence unavailable, coalesced print or trade
  classification degraded) are retained in leg evidence. They do not invalidate BBO;
  crossed/invalid/stale/partial flags do. An initial all-flags filter was corrected
  after it rejected valid live quotes; dedicated regression covers this distinction.
- API zero brokerage assumed from Kotak pricing; manual Rs10/order cost sensitivity
  separately displayed. Actual account margin, personal taxes and future fillability
  are not identified. No brokerage authentication or order path was invoked.

Artifacts under /Users/maheit/.openclaw/workspace/overnight-runs/shaurya-essvi-20260909:
bfly-live-{1,2}.json; bfly-{desktop,mobile,details}.png; butterfly-dashboard.log;
bfly-preview2-state.json. Browser harness: /tmp/check_bfly_ui.py.
