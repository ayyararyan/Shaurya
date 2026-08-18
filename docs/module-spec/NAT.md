# NAT — Native live engine

## Objective

Generalise the tested Market Making C++ runtime into Shaurya's strategy-agnostic authoritative live engine, wire the sole Kotak order route in the module, provide deterministic C++ replay and parity, and preserve explicit lifecycle/deployment evidence (D4, D5, D15).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Broker order/fill/status and account preflight | Observed | Obtained through EXE/Kotak and recorded canonically. |
| Runtime state, order lifecycle, alerts, replay output | Deterministically derived | Driven by canonical events, configuration, and strategy interface. |
| Numeric model output used in the loop | Derived/estimated according to producer | NAT preserves producer category; native execution does not make an estimate observed. |
| Python mirror output | Non-authoritative research output | Must match C++ where both implement the same computation. |
| Deployment/process health | Observed operational state | Proved by process, artifact, and remote verification evidence—not by a successful build alone. |

## Architecture and contracts

- The native runtime exports `shaurya::` and calls a strategy interface; it contains no Market Making branch.
- Consumes `CON-01` replay rows, `CON-04` configuration, `CON-06` labels, and `CON-07` time semantics; produces `CON-02` ledger rows and `CON-08` run/lifecycle manifests through EXE/DAT-owned contracts.
- EXE owns broker/lifecycle/ledger behaviour; RSK owns the mandatory C++ choke point.
- C++ is authoritative for live orders and deterministic replay. Python is non-authoritative wherever a mirror exists; NAT-06 proves numeric parity.
- Live-loop wiring is implemented here first and only. Market Making receives it later by depending on Shaurya (D15/MIG-01).

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-NAT-01 | Extract/generalise the existing native engine into namespace `shaurya::`, removing Market Making assumptions without rewriting proven machinery. | NAT-01 | TBD `native/` | Ported 91-test baseline plus namespace/dependency audit |
| REQ-NAT-02 | Implement a strategy-agnostic loop that invokes a declared strategy interface. | NAT-02, D5 | TBD native runtime/interface | Fake-strategy lifecycle and no-special-case tests |
| REQ-NAT-03 | Wire the Kotak adapter into the real module live loop, never through an interim Market Making route. | NAT-03, D15 | TBD native live loop | Paper/read-only integration; authorised live-order evidence |
| REQ-NAT-04 | Poll live order status/fills and reconcile cancellation races against the real broker. | NAT-04 | TBD native broker supervisor | Race/reconciliation fixtures; live lifecycle ledger |
| REQ-NAT-05 | Build flat-position preflight from broker reports rather than manual counts. | NAT-05 | TBD native preflight | Flat/non-flat/stale-report tests; preflight record |
| REQ-NAT-06 | Prove Python/C++ numeric parity with a comprehensive sweep, preserving the 8,640-combination precedent. | NAT-06 | TBD parity harness | Reproducible parity report |
| REQ-NAT-07 | Implement authoritative deterministic replay in C++ over DAT-05 tapes. | NAT-07, D14 | TBD native replay | Golden-tape determinism and BKT parity outputs |
| REQ-NAT-08 | Distinguish expected exit, unexpected death, completed task, and stopped component in failures/alerts. | NAT-08 | TBD lifecycle/alerts | Process-exit matrix tests; lifecycle event artifact |
| REQ-NAT-09 | Provide EC2 source-only deployment, systemd operation, runbook, and remote verification. | NAT-09 | TBD deployment/runbooks | Fresh-host/dry-run/remote health evidence |

## Timing, causality, and safety gates

1. Receive canonical market state, call the strategy interface, apply RSK at the single C++ choke point, then route approved orders through EXE/Kotak.
2. The live path cannot start without broker-derived flat preflight, EXE one-time human session authorisation, valid configuration, and healthy required data/risk state.
3. Order-status/fill polling and cancel races update the same canonical state before subsequent decisions.
4. Expected process completion and operator stop are not failures; unexpected death is.
5. C++ replay uses recorded causal ordering and measured BKT latency; it cannot access future tape rows.
6. Deployment verification checks the exact host/process/commit/artifacts and does not itself enable live orders.

## Outputs and acceptance tests

- Exported native library, strategy interface, live runtime, broker-derived preflight, lifecycle ledger, deterministic replay, parity report, process-state events, and EC2 runbook.
- The harvested 91-test baseline is green before and after generalisation; behaviour-changing work is separated from extraction.
- Fake strategies prove the runtime has no Market Making special case.
- Negative live tests prove EXE/RSK/preflight/authorisation gates cannot be bypassed.
- Live verified status requires the new module path, not evidence inherited from the source repository.

## Exclusions

- Building the live route in Market Making before Shaurya.
- Python on the authoritative live-order path.
- Strategy-specific quoting logic inside the module.
- Kotak market-data WebSocket ingestion.
- Deployment success as implicit live-order permission.

## Deferred items

- NAT-01 through NAT-09 remain implementation work. The earlier Monday 09:15 target was explicitly superseded by D15 in favour of reusable module-first construction.
