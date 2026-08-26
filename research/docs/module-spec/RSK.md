# RSK — Risk

## Objective

Enforce account-level pre-trade limits through one non-bypassable C++ choke point, while providing a non-authoritative Python research/backtest mirror, tiered kill-switch behaviour, ex-ante sizing, and explicitly separate observed and modelled margin objects (D13).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Broker-reported margin, positions, fills, and limits | Observed | Kotak-reported and authoritative for live gating when received. |
| Portfolio Greeks | Estimated / derived from estimated surfaces | Inherit GRK/SUR model status; never treated as broker-observed. |
| Daily P&L and account aggregation | Deterministically derived from canonical account/ledger state | Aggregate across all strategies by account/position, not strategy identity. |
| SPAN-style margin, ELM/additional-margin scenarios | Estimated / scenario | Used for ex-ante sizing, backtests, and counterfactuals; validated against but never overrides broker margin. |
| Risk decision | Deterministically derived under `CON-04` limits | Binding only when issued by the C++ choke point on the live order path. |

The observed-versus-modelled margin split is permanent and semantic, not an implementation detail. A close fit does not turn REQ-RSK-08 into an observed object.

## Architecture and contracts

- `CON-04` is the single source of limit definitions for Python and C++.
- `CON-06` labels broker margin observed and modelled margin estimated/scenario.
- The C++ pre-trade gate is authoritative. Python is for research/backtest only and must prove parity through REQ-RSK-07.
- Account-level aggregation is Shaurya's one permitted cross-strategy state boundary under D5; it keys on account and position, never strategy identity.
- RSK consumes DAT quality/connectivity state, SUR staleness, EXE order events, and NAT latency/health.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-RSK-01 | Reconcile the two Python risk managers into one explicitly non-authoritative research/backtest implementation. | RSK-01, D13 | TBD `src/shaurya/risk/manager.py` | Harvest/regression tests; reconciliation record |
| REQ-RSK-02 | Size positions against modelled REQ-RSK-08 margin, not broker-reported after-the-fact margin. | RSK-02 | TBD `src/shaurya/risk/sizing.py` | Boundary/scenario tests; sizing decision |
| REQ-RSK-03 | Enforce per-instrument, portfolio-Greek, and max-daily-loss limits pre-trade at a single C++ choke point. | RSK-03, D13 | TBD native risk gate | Bypass-negative and limit-boundary tests; risk decision log |
| REQ-RSK-04 | Read Kotak margin as observed and authoritative for live pre-trade gating; never override it with a model. | RSK-04, D13 | TBD Kotak/risk adapter | Broker-fixture and precedence tests; observed margin record |
| REQ-RSK-05 | Trip on risk, data-quality, connectivity, reject, latency, and staleness events; automatically stop quoting/cancel resting orders, require human authority to flatten, and require manual re-arm. | RSK-05, D13 | TBD native kill switch | Trigger/response/re-arm tests; kill-switch audit |
| REQ-RSK-06 | Aggregate margin, P&L, and portfolio Greeks across strategies at account level without strategy-specific branches. | RSK-06, D13, D5 | TBD native/Python account aggregator | Multi-strategy aggregate fixtures; account risk state |
| REQ-RSK-07 | Prove Python and C++ produce identical limit decisions over a comprehensive parity sweep. | RSK-07 | TBD parity harness | Parity report with zero unexplained mismatches |
| REQ-RSK-08 | Model SPAN-style F&O margin plus ELM/additional margins as estimated/scenario objects, validate against observed broker margin, and revalidate after NSE parameter changes. | RSK-08, D13 | TBD modelled-margin module | Scenario/reference/drift tests; validation report |

## Timing, causality, and safety gates

1. Consolidate the latest account state, broker margin, positions, P&L, Greeks, and data-health state before each order decision.
2. Every live order enters through REQ-RSK-03; post-hoc reporting cannot substitute for pre-trade gating.
3. Broker-reported margin has live precedence. Modelled margin may size or simulate but cannot loosen the observed constraint.
4. A kill-switch trip automatically stops quoting and cancels resting orders. Flattening is a separate, human-authorised act because the book may be disordered.
5. Re-arm is manual only. No cooldown can automatically restore trading.
6. Missing/stale required state fails safe according to the declared gate; it is never treated as zero exposure or infinite capacity.

## Outputs and acceptance tests

- Pre-trade risk-decision log, account risk snapshot, observed-margin record, modelled-margin scenario/validation report, and kill-switch lifecycle audit.
- Negative tests prove all order routes hit the same C++ gate.
- Cross-strategy fixtures show two individually safe strategies can jointly breach account limits.
- Python/C++ parity covers boundary equality, missing state, combined exposures, and kill-switch state.
- Acceptance requires manual-rearm and human-flatten gates to resist scripted invocation.

## Exclusions

- Per-strategy account limits that ignore aggregate exposure.
- Python as a live authority.
- Modelled margin overriding observed broker margin.
- Automatic flatten or automatic re-arm.
- Strategy-specific branches in the account aggregator.

## Deferred items

- Implementation and live verification remain pending. D13 resolves the architecture; no model choice is open.
