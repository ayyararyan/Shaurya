# Requirements Traceability

The exhaustive requirement-level table is the seven-column table in
`EXECUTION_CONTROL_PLANE_SPEC.md`; every `EXE-*` ID records source evidence, implementation path,
test evidence, status, and live boundary. This index provides the release-level cross-check.

| Requirement family | Implementation | Primary evidence |
|---|---|---|
| EXE-BND | root/Execution READMEs, project layout | `execution.project_layout`, dependency policy tests |
| EXE-CON | `contracts/v1`, canonical JSON and contracts | `execution.canonical_json`, `execution.contracts` |
| EXE-INS | routing snapshot and resolver | `execution.instrument_resolver`, routing exporter |
| EXE-IDM | idempotency store and event fingerprints | `execution.idempotency`, session tests |
| EXE-FSM | order state machine and legal-edge fixture | `execution.order_fsm`, replay tests |
| EXE-RSK | `risk.cpp`, `RISK_RULES.md` | `execution.risk_engine` |
| EXE-LED | execution ledger and verification | ledger, replay, repair tests |
| EXE-REC | reconstructed state and reconciliation | reconciliation and executor restart tests |
| EXE-OPS | session/executor/operator state | executor CLI/E2E and operator suites |
| EXE-PORT | package, install, update, rollback, uninstall | portable release and path-safety suites |
| EXE-SEC | peer identity, bounded IPC, threat controls | IPC security/transport/queue tests and audit script |
| EXE-SHD | PaperBroker and shadow launch | paper/session/parity/operator tests |
| EXE-LIVE | unconditional compile-time refusals | Shaurya and D51 live-gate negative tests; all open |
| EXE-D51 | neutral adapter and frozen comparator | D51 client tests and 17-scenario zero-mismatch report |

Optimized (`python -O`) policy tests independently parse the canonical specification table so
assert removal cannot turn missing traceability into a pass. `VERIFICATION_REPORT.md` records the
dated release-gate outcomes.
