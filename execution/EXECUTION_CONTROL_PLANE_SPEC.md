# Shaurya Execution Control Plane Specification

## Verified facts

- On 2026-08-27, Shaurya GitHub `main` resolved to
  `bcb6dea02329f824c82488f29450af0dd0e826ca`; this branch starts there.
- On 2026-08-27, D51 GitHub `main` resolved to
  `dd06e55e51c2ffa691c6e9f0ba61e38de019cd87`.
- Data exposes broker-neutral `InstrumentId` plus dated Kotak mapping/master/index semantics.
- D51's reference shadow flow has strict SSH, hidden TOTP, a single-use in-memory claim, a bounded
  watcher, and an unconditional protected-build live refusal.

## Design decisions

- `DEC-001`: money is signed 64-bit paise and quantity is positive exchange units.
- `DEC-002`: JSON is strict, versioned, bounded, duplicate-key rejecting, and canonicalized.
- `DEC-003`: ambiguous submission permits reconciliation only, never automatic retry.
- `DEC-004`: the runtime consumes dated immutable routing snapshots; only an offline exporter may
  use Data's public instrument APIs.
- `DEC-005`: shadow observations come from Data/Dhan and paper evidence is explicitly simulated.
- `DEC-006`: ordinary builds contain no live broker transport.

## Authority and dependency boundary

```text
Shaurya Data -> observed Dhan data and immutable replay
Shaurya Research -> consumes Data; no broker or order authority
Strategy client -> broker-neutral intent only
Shaurya Execution -> routing, risk, idempotency, FSM, reconciliation, ledger, session authority
Kotak adapter -> sole potential execution edge; transport absent in ordinary builds
Operator kotak CLI -> launches and authorizes one session, never one command per order
```

Data depends on neither Research nor Execution. Research may depend on Data, never Execution. The
C++ Execution runtime depends on neither Python project. The offline routing exporter is the sole
exception and may use only public Data instrument types/indexes. D51 may consume versioned
Execution contracts; Execution never imports D51 strategy logic.

## Prohibited actions

No live orders, live build, real broker authentication, TOTP entry, AWS/service action, real-home
installation, credential/private-key access, runtime artifact commit, Research edit, or unapproved
Data edit is allowed. No merge or force-push to `main` is allowed.

## Wire and state decisions

IDs are lowercase canonical UUIDs. Timestamps are UTC Unix nanoseconds in signed 64-bit range.
Initial orders are regular `LIMIT`, product `NRML`, TIF `DAY`. Place/modify use positive paise price
and positive exchange-unit quantity; cancel uses a target internal order ID and forbids price and
quantity. Position snapshots preserve strategy-desired, ledger-reconstructed, and broker-authority
values separately. Any mismatch blocks new submission.

Ledger ordering is durable intent receipt, mapping result, RiskDecision, durable submission start,
one broker attempt, then ACK/REJECT/ambiguous outcome. A pre-call ledger failure means NO ORDER. A
post-call persistence failure means ambiguous, safety stop, and reconciliation only. Damaged ledgers
are preserved; repair copies verified records to a new explicitly selected segment.

## Requirement traceability

| Requirement ID | Requirement | Authority | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|
| EXE-BND-001 | Preserve the authority and dependency graph | User requirement | README.md; execution CMake | test_dependency_boundaries.py | Tested | Offline exporter exception only |
| EXE-BND-002 | Keep Data and Research source paths unchanged | User requirement | execution/tests/policy | test_repository_hygiene.py | Tested | Path-level baseline audit |
| EXE-BND-003 | Build Execution independently as C++20 | User requirement | execution/CMakeLists.txt | execution.build_attestation | Tested | Out-of-tree build only |
| EXE-CON-001 | Provide strict versioned broker-neutral contracts | User requirement | Pending | test_contracts.cpp | Specified | No broker fields in intent |
| EXE-CON-002 | Reject duplicate unknown and missing fields | User requirement | Pending | test_contracts.cpp | Specified | Bounded UTF-8 JSON |
| EXE-CON-003 | Represent price quantity and time as exact integers | Design decision | Pending | test_contracts.cpp | Specified | No binary floating money |
| EXE-CON-004 | Support all required ExecutionEvent variants | User requirement | Pending | test_contracts.cpp | Specified | Stable correlation on every event |
| EXE-CON-005 | Preserve three distinct position authorities | User requirement | Pending | test_contracts.cpp | Specified | Mismatch is incident |
| EXE-CON-006 | Define broker-neutral MarketObservation provenance | User requirement | Pending | test_contracts.cpp | Specified | Paper fills only |
| EXE-INS-001 | Resolve only same-date hash-verified mappings | User requirement | Pending | test_instrument_resolver.cpp | Specified | Failure means NO ORDER |
| EXE-INS-002 | Reject duplicate ambiguous partial or tampered mappings | User requirement | Pending | test_instrument_resolver.cpp | Specified | Never guess token or symbol |
| EXE-INS-003 | Join Kotak routing to lot and tick metadata by canonical ID | Design decision | Pending | test_export_routing_snapshot.py | Specified | Same trading date required |
| EXE-IDM-001 | Make intent processing idempotent across restart | User requirement | Pending | test_idempotency.cpp | Specified | Conflicting payload is incident |
| EXE-IDM-002 | Persist intent fingerprint before any submission | Design decision | Pending | test_idempotency.cpp | Specified | Duplicate returns prior outcome |
| EXE-IDM-003 | Reconcile ambiguous submits without automatic retry | User requirement | Pending | test_idempotency.cpp | Specified | Session blocked meanwhile |
| EXE-FSM-001 | Enforce explicit legal order transitions | User requirement | Pending | test_order_state_machine.cpp | Specified | Generic order store |
| EXE-FSM-002 | Handle partial fills and cumulative fill deduplication | User requirement | Pending | test_order_state_machine.cpp | Specified | Overfill is incident |
| EXE-FSM-003 | Handle rejection cancel and replace races | User requirement | Pending | test_order_state_machine.cpp | Specified | Terminal replay idempotent |
| EXE-FSM-004 | Key working orders by internal and canonical IDs | User requirement | Pending | test_order_state_machine.cpp | Specified | No CE PE slots |
| EXE-RSK-001 | Apply deterministic default-deny risk | User requirement | Pending | test_risk_engine.cpp | Specified | Decision emitted for every result |
| EXE-RSK-002 | Check session mapping intent and observation freshness | User requirement | Pending | test_risk_engine.cpp | Specified | Ordered precedence |
| EXE-RSK-003 | Enforce tick lot order position and exposure limits | User requirement | Pending | test_risk_engine.cpp | Specified | Working orders projected |
| EXE-RSK-004 | Enforce exact-token SELL rate loss drawdown and kills | User requirement | Pending | test_risk_engine.cpp | Specified | Missing required input denies |
| EXE-LED-001 | Maintain an append-only hash-chain ledger | User requirement | Pending | test_ledger.cpp | Specified | No silent truncation |
| EXE-LED-002 | Use single-writer sequence and durable submission ordering | Design decision | Pending | test_ledger.cpp | Specified | Fsync at safety boundaries |
| EXE-LED-003 | Verify replay and reconstruct orders fills and positions | User requirement | Pending | test_ledger.cpp | Specified | Secret fields forbidden |
| EXE-LED-004 | Preserve damaged evidence during repair | Design decision | Pending | test_ledger.cpp | Specified | New segment selected explicitly |
| EXE-REC-001 | Reconcile orders, trades, and positions before readiness | Design decision | Pending | test_reconciliation.cpp | Specified | Exact agreement required |
| EXE-REC-002 | Block on missing extra or mismatched broker evidence | User requirement | Pending | test_reconciliation.cpp | Specified | Incident is append-only |
| EXE-REC-003 | Produce factual per-order cancel-all outcomes | User requirement | Pending | test_reconciliation.cpp | Specified | No swallowed failures |
| EXE-OPS-001 | Launch one attested bounded execution session | User requirement | Pending | test_operator_cli.py | Specified | Never per order |
| EXE-OPS-002 | Provide all required help doctor auth status and launch commands | User requirement | Pending | test_operator_cli.py | Specified | Exact confirmations |
| EXE-OPS-003 | Keep help version dry-run and malformed paths offline | User requirement | Pending | test_operator_cli.py | Specified | No prompt or lock side effect |
| EXE-OPS-004 | Bind operator device release manifest and executor identity | User requirement | Pending | test_operator_cli.py | Specified | Non-secret audit fields only |
| EXE-PORT-001 | Install and restore identically in isolated Mac homes | User requirement | Pending | test_portability.py | Specified | Real home forbidden |
| EXE-PORT-002 | Verify release checksums before install or update | User requirement | Pending | test_portability.py | Specified | Deterministic package metadata |
| EXE-PORT-003 | Roll back recoverably and uninstall only owned files | User requirement | Pending | test_portability.py | Specified | Preserve pre-existing files |
| EXE-SEC-001 | Keep secrets outside contracts, logs, ledger, and repository | User requirement | docs/THREAT_MODEL.md | test_repository_hygiene.py | Tested | Handle-only configuration |
| EXE-SEC-002 | Validate peers paths modes and exact manifests | User requirement | Pending | test_ipc.cpp; test_portability.py | Specified | Refuse symlink traversal |
| EXE-SEC-003 | Sanitize broker and transport errors to marker allowlists | Design decision | Pending | test_kotak_adapter.cpp | Specified | No response bodies |
| EXE-SHD-001 | Label paper fills simulated/proxy, never confirmed | User requirement | docs/SHADOW_SAFETY.md | test_documented_boundaries.py | Tested | No broker credential needed |
| EXE-SHD-002 | Use only Data-derived broker-neutral observations | User requirement | Pending | test_paper_broker.cpp | Specified | Kotak updates are execution evidence |
| EXE-SHD-003 | Make paper fill behavior deterministic and versioned | User requirement | Pending | test_paper_broker.cpp | Specified | Conservative cross/trade model |
| EXE-LIVE-001 | Ordinary and explicit-ON builds fail closed | User requirement | cmake/ShauryaBuildOptions.cmake | execution.live_gate | Live-unverified | Negative control passes |
| EXE-LIVE-002 | Keep real endpoint and account contracts unresolved | User requirement | docs/LIVE_ENABLEMENT_CHECKLIST.md | test_documented_boundaries.py | Live-unverified | Separate authorization required |
| EXE-LIVE-003 | Require separate live build and operator authorization | User requirement | docs/LIVE_ENABLEMENT_CHECKLIST.md | test_documented_boundaries.py | Live-unverified | Cannot be waived here |
| EXE-D51-001 | Make D51 the first client only after exact parity | User requirement | Pending | test_shaurya_parity.cpp | Specified | Mismatch needs user approval |
| EXE-D51-002 | Keep strategy model surface and research logic in D51 | User requirement | Pending | test_shaurya_client.cpp | Specified | Execution owns order authority |
| EXE-D51-003 | Preserve explicit legacy rollback while live stays disabled | User requirement | Pending | test_shaurya_client.cpp | Specified | No runtime backend switch |

## Unresolved live blockers

Every item in `docs/LIVE_ENABLEMENT_CHECKLIST.md` is unresolved and `Live-unverified`. Provider,
account, endpoint, remote target, installed state, and cloud facts are staleable and must be
reverified only in a separately authorized workflow.
