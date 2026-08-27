# Shaurya Execution Control Plane Implementation Plan

## 1. Baseline, boundaries, and frozen specification

Record both verified remote commits and branch names in the specification. Create the standalone
Execution directory and CMake project without changing Data or Research. Define stable EXE-BND,
CON, INS, IDM, FSM, RSK, LED, REC, OPS, PORT, SEC, SHD, LIVE, and D51 requirements, separating
verified facts from design decisions and mapping every requirement to implementation and tests.
Update the root README only after the third-project boundary exists. Add the threat model and live
checklist at the outset so unsafe capability cannot appear accidentally.

The permitted dependency graph is exact: Data and Research never depend on Execution; Research
never imports Execution; the Execution C++ runtime never imports either Python project; an offline
Execution-owned routing exporter may call Data's public instrument APIs and emits an immutable file
that the runtime consumes read-only. No other cross-project dependency is permitted.

## 2. Strict wire contracts and conformance corpus

Define broker-neutral C++ types and exact JSON codecs for OrderIntent, ExecutionEvent,
RiskDecision, PositionSnapshot, and MarketObservation. Freeze schema version, UUID syntax,
canonical instrument syntax, enum allowlists, integer units, timestamp ranges, packet bounds,
unknown/missing/duplicate rejection, and canonical serialization. Maintain shared valid/invalid
fixtures for cross-language consumers. Intent fingerprints exclude transport metadata and detect
same-ID/different-payload conflicts.

Use lowercase canonical UUID text for intent, run, session, and internal-order IDs. `place` requires
BUY/SELL, positive exchange-unit quantity, positive paise price, product `NRML`, TIF `DAY`, and no
target ID. `modify` adds a target internal order ID. `cancel` requires only target and correlation
fields and forbids price/quantity. Same payload with a new ID is a new request subject to risk; the
same ID with a different fingerprint is a safety incident. Timestamps are UTC Unix nanoseconds in
the signed 64-bit range, and expiry must follow creation.

## 3. Routing snapshot and resolver

Build an Execution-owned Python exporter that imports the existing Data mapping contracts read-
only, joins required lot/tick metadata, rejects malformed/ambiguous/stale input, and writes a
deterministically ordered dated snapshot plus SHA-256 manifest. Build a C++ resolver that validates
exact date, provenance, completeness, hash, token/canonical uniqueness, lot, and tick before
lookup. A missing or unverifiable mapping returns NO ORDER. Do not modify Data.

## 4. Ledger, replay, idempotency, and order FSM

Implement a single-writer append-only ledger with monotonically increasing sequence, previous-hash
binding, canonical payload hashing, bounded records, flush/fsync, verification, and replay. Treat an
incomplete final record as a recoverable truncated tail but reject middle corruption, duplicate
sequence, or broken hashes. Reconstruct intent fingerprints, orders, fills, positions, incidents,
and session readiness. Implement a generic order lifecycle transition table with broker-update
deduplication, cumulative-fill monotonicity, cancel/replace races, terminal-event idempotence, and
ambiguous-submit reconciliation requirements.

The authoritative ledger is never silently truncated or rewritten. A truncated final record makes
startup fail closed. A repair tool copies every verified record into a new segment, preserves the
damaged segment read-only as evidence, records its digest and incident in the new segment, and
requires explicit operator selection of the repaired segment.

Submission ordering is mandatory: durable `intent_received`; mapping result; durable RiskDecision;
durable `submission_started`; exactly one broker attempt; then durable ACK/REJECT or
`ambiguous_submission`. Ledger failure before the call means NO ORDER. Failure after the broker call
is ambiguous, triggers safety stop, and permits reconciliation only—never automatic resubmission.

## 5. Risk, reconciliation, brokers, and session composition

Implement ordered default-deny risk rules over immutable inputs: mapping/date, contract allowlists,
session health, expiry, observation freshness, tick/lot validity, order/position/exposure/Greek
limits, rate, P&L/drawdown, working count, idempotency, kill switch, reconciliation, and exact-token
SELL availability. Include working orders in projected exposure and reject missing required Greek
inputs. Produce a complete RiskDecision for every result.

Define BrokerAdapter queries and mutations. Implement a deterministic PaperBrokerAdapter with a
versioned conservative cross/trade fill model and explicit simulated evidence. Implement a dormant
Kotak adapter whose fixture parser/request builder is compiled and tested but whose transport is
unavailable unless a separate live build is deliberately created. Sanitize all errors. Compose the
resolver, risk gate, ledger, FSM, broker, reconciliation, and startup/shutdown behavior in an
ExecutionSession. Startup is not ready until ledger and broker snapshots agree; unknown or mismatch
emits an incident and blocks submissions.

PositionSnapshot carries strategy-desired, ledger-reconstructed, and broker-authoritative
quantities separately per canonical instrument. Readiness requires exact agreement of broker order,
trade/fill, and position snapshots with replayed state; missing or extra items are mismatches.
Reconciliation corrections are append-only events, never in-place ledger edits.

## 6. Bounded local IPC and executable

Implement a platform-isolated Unix transport using SEQPACKET where supported and bounded framed
streams otherwise. Validate socket parent, owner/mode, peer identity, executable/config bindings,
packet size, message schema, correlation, backpressure, and reconnect replay. Queue overflow or
peer/session loss triggers a safety stop. Provide a shadow-only executor CLI for fixture replay,
configuration validation, ledger verification, and local IPC service. Negative live invocation
must fail before any network-capable object is created.

The shadow topology is explicit: a Data-owned publisher is the sole producer of Dhan-derived
MarketObservation packets; the Shaurya executor owns observation and strategy sockets, routing,
risk/FSM/ledger/paper broker, and readiness; D51 is a strategy client consuming observations and
submitting neutral intents; the operator CLI starts one remote shadow executor session and waits for
attested readiness. Shadow needs no Kotak credential. Frozen fixtures replace the Data publisher in
hermetic E2E tests. Readiness follows configuration/routing attestation, ledger replay,
reconciliation-fixture agreement, peer validation, and fresh observations.

## 7. Portable Kotak operator control plane

Place canonical CLI/helper/release sources under `execution/ops`. Move all non-secret target,
service, remote path, compatibility, and digest values into an exact-schema deployment manifest.
Implement help, version, offline doctor, bounded one-attempt remote doctor, auth, status, prepare,
preflight, shaurya-shadow-launch, and shadow-launch alias. Help/version/dry-run/malformed/missing-
confirmation paths perform no network action. Actual stateful paths require exact confirmations,
strict host verification, hidden TOTP stdin, locks, bounded deadlines, and allowlisted markers.

Add reproducible packaging, manifest verification, prefix/user installer, validated update and
rollback, and manifest-scoped uninstaller with traversal/symlink/pre-existing-file defenses. Test
two independent temporary Mac-like homes and prefixes, identical installed hashes, offline doctor,
all dry-runs, tamper refusal, clean restore, and uninstall. Never target the real home.

`shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH` is the canonical no-broker-auth shadow
command. In the Shaurya release, `shadow-launch` is a syntax-compatible alias with the same token,
exit codes, and marker grammar. During migration D51's existing wrapper retains its legacy
authenticated feed-only behavior behind the explicit legacy route. `auth` remains separate and is
never implicit in the new shadow command. Remote/AWS behavior is verified with hermetic fixtures
only; no real remote command is run.

Every session-start record includes operator ID, device ID, non-secret public-key fingerprint, CLI
version/digest, deployment-manifest digest, executor commit/build digest, requested mode,
confirmation type, timestamp, and factual outcome. Logs allowlist only non-secret audit fields and
markers.

## 8. D51 client migration and parity

In the separate D51 branch, add a neutral Shaurya client library that maps selected D51 quote
actions to canonical integer OrderIntent values and consumes ExecutionEvent messages. Remove Kotak
request construction from the new path. Keep D51's strategy, model, surface, and legacy SFeed
research behavior. Add an explicit rollback flag; make Shaurya the default shadow execution route
only when parity fixtures pass; keep legacy routing live-disabled.

Freeze representative observation/action fixtures and compare selected intents, acknowledgements,
partial/full paper fills, exact-token inventory, cancellations, and final reconstructed state.
Document any deliberate semantic difference; do not waive failures silently. Preserve the existing
`kotak shadow-launch` behavior as the Shaurya alias contract.

A parity mismatch blocks making Shaurya the D51 default and blocks completion. Only explicit user
approval in a later request may authorize an intentional difference; this workflow cannot
synthesize that approval.

## 9. Integration, documentation, audit, and delivery

Run clean Release/CTest suites, Execution Python/shell suites, all Data and Research checks, all D51
tests and hermetic operational suites, cross-repository parity, portability twice, and live-negative
controls. Scan tracked content for secret/private-key/TOTP shapes, response-body logging, personal
paths, runtime/build/cache output, and unexpected dependency directions. Diff Data and Research
against the starting Shaurya commit and require zero paths.

Complete the Execution README, contract docs, lifecycle diagram, ledger/recovery guide, risk rules,
threat model, install/restore/shadow runbooks, D51 migration/parity report, and live checklist.
Create logical commits, inspect every staged diff, push only the two named branches without force,
and verify remote branch heads exactly match local commits.
