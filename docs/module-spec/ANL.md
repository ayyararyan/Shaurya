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

- All ANL implementation remains not started; D15 fixes the ownership and decomposition.
