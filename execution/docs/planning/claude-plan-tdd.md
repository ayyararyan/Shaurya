# TDD Plan

## 1. Baseline, boundaries, and frozen specification

- Test the independent CMake project configures with live routing OFF and refuses ON.
- Test dependency scans prohibit Data/Research imports of Execution and prohibit the C++ runtime
  importing Python projects; allow only the offline exporter to use Data's public API.
- Test requirement traceability contains every required EXE prefix and no unresolved implementation
  row can be marked complete.

## 2. Strict wire contracts and conformance corpus

- Start with valid round-trip tests for every schema and action/event variant.
- Add failing cases for unknown, duplicate, missing, invalid-enum/version, overflow, malformed UUID,
  invalid timestamp/tick/quantity, expired intent, and modify/cancel target requirements.
- Add canonical serialization and same-ID/conflicting-payload fingerprint golden tests.

## 3. Routing snapshot and resolver

- Start with valid option/future snapshot export and lookup fixtures.
- Add stale date, expiry change, duplicate canonical/token, missing mapping, malformed master, partial
  inputs, invalid lot/tick, manifest mismatch, and data hash tampering failures.
- Assert every refusal produces no broker call and no guessed token/symbol.

## 4. Ledger, replay, idempotency, and order FSM

- Test append/replay, hash chain, ordering, truncated tail, tampered middle, duplicate sequence, crash
  cut points, position reconstruction, reconciliation corrections, and secret-field refusal.
- Test truncated-tail startup refusal and evidence-preserving new-segment repair without modifying
  the damaged segment.
- Cover every legal and illegal FSM edge, cumulative/repeated/out-of-order fills, rejection,
  cancel/replace races, ambiguous submit, terminal replay, and broker-update deduplication.
- Cover duplicate intents before submit, after ACK/fill, after restart, retry after timeout,
  different IDs/same payload, and conflicting payload/same ID.

## 5. Risk, reconciliation, brokers, and session composition

- Test each risk rule independently and combined precedence: stale/tampered mapping/data, unsupported
  contract, expiry, tick/lot, order/position/exposure/Greek caps, exact-token SELL, rates, losses,
  drawdown, working count, kill switch, session loss, duplicate, and unreconciled startup.
- Test PaperBroker place/modify/cancel, crosses, post-placement trades, partial/final fills, volume
  resets, tied timestamps, rejects, and explicit simulated provenance.
- Test Kotak fixtures for ACK/fill/reject/malformed/HTTP/queue/session cases and prove live transport
  is absent in ordinary builds.
- Test startup query agreement, mismatch/unknown blocking, crash recovery, factual cancel-all, and
  readiness only after exact reconciliation.
- Inject ledger failure immediately before and after broker submission; prove durable
  `submission_started` precedes transport, pre-call failure sends no order, and post-call failure is
  ambiguous with no automatic retry after timeout or restart.

## 6. Bounded local IPC and executable

- Test packet size/framing, exact schema, peer/config mismatch, mode/ownership refusal, queue
  overflow, disconnect, reconnect/replay, response correlation, and supported transport selection.
- Test shadow fixture replay and ledger verification CLI modes.
- Test all live-mode entry paths fail before socket/network/broker construction.
- Saturate queues during receive, risk, submission, broker update, and ledger phases and verify
  deterministic safety-stop ordering.

## 7. Portable Kotak operator control plane

- Port D51 hermetic tests for single-consume sessions, watcher readiness/malformed/auth failure,
  claim expiry, duplicate/replayed launch, interrupted/result transport, start refusal, secret
  non-disclosure, non-persistent watcher/timer, and exact helper/process/hash binding.
- Test offline help/version/doctor, all dry-runs, malformed/missing confirmation no-network paths,
  one bounded remote-doctor fixture, host-key refusal, manifest tamper/wrong executor, audit fields,
  and absence of personal paths.
- Assert `doctor --remote` invokes the SSH fixture exactly once with bounded options, and
  operator/device audit fields appear in the ledger and marker-only logs.
- Test install/update/rollback/uninstall independently in two temporary homes/prefixes and compare
  installed hashes exactly.
- Add duplicate-manifest-field, traversal, symlink race, ownership/mode change, concurrent update,
  deterministic metadata/order/timestamp/mode, and pre-existing-file preservation cases.

## 8. D51 client migration and parity

- Test quote-action conversion to integer canonical intents, event correlation, partial/full fill
  application, cancel behavior, exact-token inventory, IPC backpressure, and rollback selection.
- Add golden replays comparing legacy and Shaurya paths for intents, events, paper fills, inventory,
  cancellations, and terminal state; any mismatch blocks default migration and completion pending
  a later explicit user approval.
- Prove both D51 paths remain unable to enable live routing.

## 9. Integration, documentation, audit, and delivery

- Run clean Execution Release build/CTest and Python/shell suites.
- Run complete Data and Research pytest/Ruff/mypy and complete D51 CTest/operational suites.
- Run parity, two-install portability, live-negative, secret, runtime-artifact, personal-path,
  dependency-boundary, and protected-directory diff audits.
- Prove tests cannot contact real networks, brokers, AWS, the real-home installer target, or install
  dependencies as part of the test suite.
- Verify every documented command and requirement/test traceability row against actual outputs before
  commits and remote-head verification.
