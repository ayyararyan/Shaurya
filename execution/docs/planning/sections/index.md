<!-- PROJECT_CONFIG
runtime: cxx-cmake
test_command: cmake --build /private/tmp/shaurya-execution-build --parallel && ctest --test-dir /private/tmp/shaurya-execution-build --output-on-failure
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-specification-boundaries
section-02-contracts-routing
section-03-ledger-fsm
section-04-risk-brokers-session
section-05-ipc-executor
section-06-portable-operator-cli
section-07-d51-client-parity
section-08-integration-documentation
END_MANIFEST -->

# Implementation Sections Index

## Dependency graph

| Section | Depends on | Blocks | Parallelizable |
|---|---|---|---|
| 01 specification/boundaries | - | all | No |
| 02 contracts/routing | 01 | 03, 04, 05, 07 | No |
| 03 ledger/FSM | 02 | 04, 05 | Yes with routing follow-up |
| 04 risk/brokers/session | 02, 03 | 05, 07 | No |
| 05 IPC/executor | 03, 04 | 07, 08 | No |
| 06 portable CLI | 01, 05 interfaces | 08 | Yes after interfaces freeze |
| 07 D51 client/parity | 02, 04, 05 | 08 | No |
| 08 integration/docs | 01-07 | - | No |

## Execution order

1. Freeze specification and boundaries.
2. Implement contracts and routing.
3. Implement ledger/FSM, followed by risk/brokers/session.
4. Implement IPC/executor and portable CLI.
5. Migrate D51 and require exact parity.
6. Complete integration evidence, documentation, audits, commits, and pushes.

## Section summaries

### section-01-specification-boundaries

Creates the independently buildable project, full stable requirement specification, architecture,
threat model, live blockers, root README boundary, and negative build controls.

### section-02-contracts-routing

Implements strict versioned wire contracts, canonical JSON/conformance fixtures, routing exporter,
manifest, and C++ resolver without modifying Data.

### section-03-ledger-fsm

Implements the append-only hash-chain ledger, evidence-preserving recovery, replay/idempotency, and
generic order lifecycle state machine.

### section-04-risk-brokers-session

Implements deterministic default-deny risk, reconciliation, paper broker, dormant Kotak fixtures,
position authority, and composed execution session.

### section-05-ipc-executor

Implements bounded peer-validated Unix IPC, queues/safety stops, and the shadow-only executor CLI.

### section-06-portable-operator-cli

Implements manifest-driven `kotak`, release packaging, installer/update/rollback/uninstaller, offline
doctor, hermetic remote checks, audit identities, and two isolated-home portability suites.

### section-07-d51-client-parity

Modifies the separate D51 branch to emit/consume Shaurya contracts, retains explicit rollback, and
requires exact frozen shadow parity before making Shaurya the default.

### section-08-integration-documentation

Runs all project/regression/parity/portability/safety audits, completes runbooks and traceability,
creates logical commits, pushes both branches, and verifies exact remote heads.
