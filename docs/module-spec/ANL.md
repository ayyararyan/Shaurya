# ANL — Analytics and reporting

## Objective

Produce canonical post-trade measurement: decomposed P&L, markouts, run/day reports, read-only dashboards, and notifications. ANL builds markout once for both reporting and SIG adverse-selection targets (D15).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Ledger events, fills, fees, positions, and market marks | Observed when sourced from broker/tape | Retain source/run identity and quality. |
| Markout and P&L decomposition | Deterministically derived from observed/estimated inputs | Greek components inherit GRK/SUR estimation labels. |
| Simulated-run attribution | Scenario/proxy | Inherits proxy fill labels; never mixed with realised P&L. |
| Dashboard/report | Presentation artifact | Does not raise the evidence level of its inputs. |
| ATM implied volatility at k = 0 | Estimated | The SUR-01 fit, after SUR-07 smoothing where smoothing applied, evaluated at log-moneyness zero on each fitted maturity. Read at the *forward*, so it moves when the forward moves even if no option reprinted; inherits the fit's labels and its smoothing state. Null with a reason when the slice cannot support the money — never filled in. |

Gross P&L alone is insufficient: delta, gamma, vega, theta, spread capture, adverse selection, and fees must remain separately visible.

## Architecture and contracts

- Consumes `CON-02` ledger rows, GRK surface-consistent Greeks, and market marks.
- Exposes one markout implementation to SIG-08; SIG does not duplicate it.
- Consumes `CON-03` for surface dashboards.
- Dashboards and servers are read-only; notifications report state but cannot authorise or place orders.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-ANL-01 | Compute markouts and decompose P&L into delta, gamma, vega, theta, spread capture, adverse selection, and fees. | ANL-01, D15 | TBD `src/shaurya/analytics/attribution.py` | Hand-reconciled ledger fixtures; attribution artifact |
| REQ-ANL-02 | Produce per-run and per-day summaries from canonical attribution. | ANL-02 | TBD reporting module | Aggregate/reconciliation tests; run/day reports |
| REQ-ANL-03 | Provide a read-only dashboard/server for surface and trading analytics. | ANL-03 | TBD dashboard/server | Read-only and rendering/API tests; dashboard views |
| REQ-ANL-04 | Provide notifications and alerts with explicit component/run state. | ANL-04 | TBD notifier | Routing/deduplication/lifecycle tests; alert record |
| REQ-ANL-05 | Redesign ANL-03's presentation using the approved muted visual system, with a light/dark theme, preserving every measured field, object label, threshold and the arbitrage banner exactly. Aesthetic work may change layout, typography, colour and hierarchy only; it may not change model meaning or the value of any displayed number. **Amended 2026-08-19 on Aryan's explicit instruction:** the sustained-latency chart and the forward-source table are no longer drawn on screen. Both remain published in full at `/api/state`, so the forward choice per expiry stays a stated, retrievable model object under §7.1 — it is no longer a visible disclosure. No other panel may be dropped without the same explicit approval. **Extended 2026-08-19 on Aryan's instruction:** the dashboard must (a) let the viewer rotate, pan and zoom the surface freely while it keeps updating, holding the viewer's camera across every refresh until they reset it, and (b) display at-the-money implied volatility live as a hero number with its change since the previous fitted frame. ATM IV is the ledger's estimated k = 0 object above, not a new measurement. | ANL-05, ANL-03 | `src/shaurya/analytics/dashboard.py`, `src/shaurya/analytics/surface_feed.py` | Rendering/snapshot/accessibility tests; before/after field-parity audit; ATM-vs-grid parity test; headless camera-persistence probe; dashboard screenshots |

## Outputs and acceptance tests

- Per-fill/per-cycle markouts, decomposed attribution, per-run/day summaries, read-only dashboard output, and alert audit records.
- Component sums reconcile to total P&L and fees; missing components are explicit, not zero-filled.
- Real and simulated results remain segregated and visibly labelled.
- SIG consumes the same markout output proven against ledger fixtures.
- Alerts distinguish expected completion, invalidation, degradation, and failure.

## Exclusions

- Gross-only performance reporting.
- A second markout implementation inside SIG.
- Order placement, risk re-arm, or live authorisation through dashboards/notifications.
- Treating simulated fills or fitted Greeks as observed.

## Deferred items

- ANL-03 is Live verified for the surface-dashboard scope. ANL-05 is Implemented and
  Tested (27 dashboard tests, dry-run screenshots in both themes and in the degraded
  state, an ATM-vs-grid parity check and a headless camera-persistence probe); it is not
  yet Live verified, because no live session has run against the redesigned shell. ANL-01, ANL-02 and ANL-04 remain not started; D15 fixes
  attribution/markout ownership and decomposition.
