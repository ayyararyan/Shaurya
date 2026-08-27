# Section 03 — Append-only ledger, replay/idempotency, and generic order FSM

## Outcome

Implement the authoritative single-writer execution ledger, deterministic replay and idempotency
state, evidence-preserving damaged-tail recovery, and a broker-neutral order lifecycle state
machine. The ledger is the durable source for what Shaurya attempted and learned; broker state is
reconciled against it in Section 04 and never retroactively overwrites it.

This section depends on Section 02's strict `OrderIntent`, `ExecutionEvent`, canonical JSON, UUID,
integer unit, and error-code definitions. It must not implement risk policy, broker transport, IPC,
or session readiness. It exposes pure/durable components consumed by Sections 04 and 05.

## Tests first

### Test files to create

- `execution/tests/ledger/execution_ledger_test.cpp`
- `execution/tests/ledger/ledger_replay_test.cpp`
- `execution/tests/ledger/ledger_repair_test.cpp`
- `execution/tests/ledger/idempotency_test.cpp`
- `execution/tests/fsm/order_state_machine_test.cpp`
- `execution/tests/fixtures/ledger/`
- `execution/tests/fixtures/fsm/`

Use deterministic UUIDs, nanosecond timestamps, payloads, and injected filesystem/durability faults.
Never use real credentials, broker responses, home paths, or wall-clock-dependent expected bytes.
All test ledgers live below the external build/test temporary directory and are removed only after
assertions preserve any deliberately damaged evidence needed by the test.

### Ledger tests

Write these tests before the implementation:

1. append a genesis record and multiple correlated events; verify strictly increasing sequences,
   previous-hash binding, current hashes, canonical bytes, newline termination, and replay equality;
2. reopen a clean ledger and continue at exactly the next sequence/hash;
3. reject a second writer, unsafe permissions, symlinks, non-regular files, unexpected replacement,
   oversized records, unsupported versions, and secret-shaped payload keys;
4. reject duplicate sequence/event ID, a gap, wrong genesis previous hash, broken previous hash,
   wrong record hash, malformed canonical payload, and a tampered middle record;
5. detect an incomplete final record without modifying the file; startup must remain fail-closed;
6. distinguish a truncated final record from malformed newline-terminated final JSON or corruption
   before the final record; only the first is eligible for explicit repair;
7. inject failure before open, during write, before flush, during flush, and during fsync; report the
   factual durable/uncertain boundary and never claim an event persisted without verification;
8. simulate crashes after every submission pipeline boundary and replay the exact last durable
   state;
9. reconstruct orders, cumulative fills, positions, incidents, intent fingerprints, and the fact
   that reconciliation is required, all deterministically;
10. append reconciliation correction events and prove historical records and prior positions remain
    byte-identical;
11. scan keys recursively and reject secret/token/TOTP/private-key/authentication-URL fields before
    append; sanitize errors without echoing rejected payload values.

### Repair tests

1. Make a ledger with valid records plus a partial final line; invoke repair without confirmation
   and assert no output and no source mutation.
2. With exact confirmation, copy every verified record byte-for-byte into a new exclusive segment,
   append a repair incident bound to the damaged segment's full SHA-256 and verified-prefix length,
   and leave the damaged segment byte-identical and read-only as evidence.
3. Reject an output path that exists, aliases input, is a symlink, traverses an unsafe directory, or
   is on a configuration-selected active segment.
4. Reject repair for middle corruption, a complete-but-invalid final record, broken hashes, or an
   unbounded source.
5. Prove the repaired segment is not selected automatically; startup uses it only after an explicit
   configuration/operator selection and then still requires Section 04 reconciliation.

### Idempotency tests

Cover a duplicate intent:

- before mapping/risk/submission;
- after durable `submission_started`;
- after broker acknowledgment;
- after partial fill and fill;
- after cancellation or rejection;
- after process restart and ledger replay;
- after a timeout/ambiguous submission.

The same `intent_id` plus the same semantic fingerprint returns the already recorded state/events
and causes no new broker attempt. The same ID with a different fingerprint appends a safety incident
and blocks submission. The same semantic payload with a different ID is a distinct request that must
pass mapping and risk again. An ambiguous submission is never automatically retried, including
after restart.

### FSM tests

Build a table-driven test for every legal edge and generate an illegal-edge case for every other
state/event pair. Additionally cover:

- partial-fill accumulation and exact completion;
- repeated identical fill/update idempotence;
- cumulative fill regression, fill above order quantity, conflicting duplicate update, and integer
  overflow;
- fills arriving while modify or cancel is pending;
- full fill racing with cancel acknowledgment;
- modify acceptance/rejection after intervening fills;
- broker reject before acknowledgment and contradictory rejection after evidence of a fill;
- ambiguous submit and reconciliation-only resolution;
- repeated terminal events versus conflicting terminal events;
- replaying the same event stream to the byte-identical aggregate;
- multiple instruments and orders without fixed CE/PE or buy/sell slots.

Run focused tests with:

```bash
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build \
  --output-on-failure -R 'ledger|replay|repair|idempotency|order_fsm'
```

## Files and component boundaries

Create:

- `execution/include/shaurya/execution/execution_ledger.hpp`
- `execution/src/execution_ledger.cpp`
- `execution/include/shaurya/execution/ledger_replay.hpp`
- `execution/src/ledger_replay.cpp`
- `execution/include/shaurya/execution/idempotency_store.hpp`
- `execution/src/idempotency_store.cpp`
- `execution/include/shaurya/execution/order_state_machine.hpp`
- `execution/src/order_state_machine.cpp`
- `execution/include/shaurya/execution/reconstructed_state.hpp`
- `execution/src/reconstructed_state.cpp`
- `execution/tools/ledger_repair.cpp`
- `execution/docs/LEDGER_AND_RECOVERY.md`
- `execution/docs/ORDER_LIFECYCLE.md`

The FSM and replay reducer are pure deterministic logic. The ledger owns filesystem I/O and the
single-writer lock. The repair tool is a separate, explicit executable and is never called
automatically by startup. Broker queries, mutation calls, and readiness remain outside these files.

## Ledger record v1

Each newline-delimited canonical JSON record contains:

| Field | Rule |
|---|---|
| `schema_version` | Literal `1.0.0` |
| `sequence` | Positive, strictly increasing unsigned integer; genesis is 1 |
| `event_id` | Unique lowercase UUID |
| `execution_session_id` | Lowercase UUID |
| `strategy_id` | Required when the event originates from a strategy |
| `strategy_run_id` | Required correlated lowercase UUID when applicable |
| `intent_id` | Required for intent/order pipeline events |
| `internal_order_id` | Required once a place intent creates an order aggregate |
| `event_type` | Closed ExecutionEvent variant |
| `timestamp_ns` | UTC Unix nanoseconds, signed 64-bit range |
| `payload` | Strict bounded non-secret event payload |
| `previous_record_hash` | 64 lowercase hex; all-zero digest for sequence 1 |
| `record_hash` | SHA-256 defined below |

Define `record_hash` as SHA-256 over the canonical UTF-8 JSON object containing every record field
except `record_hash`; it therefore includes `previous_record_hash`. Serialize the final object
canonically and append exactly one newline. Verification reserializes the parsed object and requires
both canonical input bytes and matching hash; alternate encodings are rejected rather than silently
normalized.

Set and test a fixed maximum record size. Arbitrary broker payloads are forbidden. Payloads use
typed event variants and allowlisted keys from Section 02. Recursively reject case-insensitive
secret-shaped names including credential, password, access/refresh/session token, TOTP, cookie,
authorization, private key, and authentication URL. Do not reject ordinary non-secret identifiers
such as `instrument_token`; define the allowlist explicitly to avoid both leakage and false policy.

## Append and durability semantics

Open a new segment exclusively with `0600` mode beneath an operator-selected `0700` state
directory. Refuse symlinks and non-regular files. Hold an advisory exclusive writer lock for the
process lifetime and verify device/inode identity before each append so path replacement cannot
redirect evidence.

For every execution event:

1. validate the typed event and secret policy;
2. assign the next sequence and bind the last verified hash;
3. canonicalize and size-check the complete line;
4. append with platform-safe `O_APPEND` semantics;
5. flush and fsync before returning a durable-success result;
6. update in-memory sequence/hash only after durability succeeds.

Any append, flush, fsync, lock, identity, or space failure triggers fail-closed behavior in the
caller. If bytes may have reached storage but durability is uncertain, close authority and require
verification/reconciliation; never append a speculative compensating record to an unverified tail.

The mandatory submission ordering consumed by Section 04 is:

```text
durable intent_received
-> durable mapping_validated or mapping_refused
-> durable RiskDecision
-> durable submission_started
-> exactly one broker mutation attempt
-> durable broker_acknowledged / broker_rejected / ambiguous_submission
```

Ledger failure before the broker mutation means `NO ORDER`. Failure after invocation begins is
ambiguous even if a transport exception appears definite; it triggers a safety stop and permits
reconciliation only. No retry path may bypass the durable `submission_started` evidence.

## Verification, replay, and reconstructed state

Verification streams the segment with bounded memory. It checks file identity and permissions,
line bounds/newline, strict/canonical JSON, version, sequence, event-ID uniqueness, previous/current
hashes, correlation requirements, and event semantics. It returns one of:

- clean and fully verified;
- truncated final record with the exact verified-prefix byte offset;
- corrupt/unsupported/unsafe with a stable reason and record/offset where safe to disclose.

A truncated final record is mechanically repairable but not automatically usable. Normal startup
fails closed on every result other than clean.

Replay applies verified events in sequence to `ReconstructedState`, containing:

- intent ID to semantic fingerprint and recorded disposition;
- internal order ID to order aggregate;
- broker update deduplication keys;
- cumulative fills and signed ledger position by canonical instrument and exact route token;
- unresolved ambiguous submissions and reconciliation-required incidents;
- kill/safety-stop facts and last session lifecycle facts.

Replay performs the same invariant checks as online FSM application. It must never trust a stored
derived total when it can deterministically reconstruct it from typed events. Position deltas are
BUY positive and SELL negative, applied exactly once from accepted fill deltas, with checked integer
arithmetic. Section 04 compares this reconstructed state to broker-authoritative snapshots.

## Evidence-preserving repair

The repair executable accepts explicit input segment, new output segment, and exact confirmation
token. It performs a full verification and proceeds only for a partial, non-newline-terminated final
record following a completely valid prefix.

It calculates the full damaged-file SHA-256 and byte length, copies verified complete records
byte-for-byte to a newly created segment, verifies the copied chain, and appends a typed
`ledger_repair_recorded` incident containing the damaged segment digest, total bytes, verified-prefix
bytes, original path label without personal-directory disclosure, repair-tool version, and operator
confirmation type. It fsyncs the output and parent directory. It never truncates, rewrites, chmods,
deletes, renames, or selects the damaged source.

Selection of the repaired segment is a separate explicit configuration operation. Even after
selection, executor startup remains blocked until Section 04 reconciliation agrees with broker or
the shadow reconciliation fixture.

## Idempotency model

`IdempotencyStore` is rebuilt exclusively from verified ledger events. It maps `intent_id` to:

- semantic fingerprint from Section 02;
- first received sequence;
- current disposition and correlated internal order ID;
- last safely replayable response/events;
- whether submission is ambiguous or reconciliation is required.

On receipt:

- unseen ID: durably append `intent_received`, then register it;
- seen ID with identical fingerprint: return recorded disposition without mapping, risk, or broker
  mutation and optionally replay already durable correlated events to the client;
- seen ID with conflicting fingerprint: append a typed safety incident if the ledger remains
  writable, activate fail-closed state, and reject;
- ambiguous ID: return reconciliation-required and never resubmit.

Do not deduplicate across different IDs. Rate/risk policy may separately reject a new ID with the
same payload in Section 04.

## Generic order lifecycle FSM

Use one generic `OrderAggregate` keyed by stable internal order UUID and canonical instrument ID.
Do not retain D51's four fixed `CE/PE x buy/sell` working slots. The aggregate includes original and
current terms, exact route/token digest, broker order ID if known, cumulative filled quantity,
working remainder, state, pending mutation, and deduplication evidence.

Freeze these primary states:

- `prepared` — validated internal order exists, no broker call begun;
- `submission_started` — durable pre-call evidence exists;
- `acknowledged` — broker accepted and order may work;
- `partially_filled` — positive cumulative fill below effective quantity;
- `ambiguous_submission` — call outcome cannot be established;
- `reconciliation_required` — only reconciliation evidence may resolve uncertainty;
- `filled`, `cancelled`, and `rejected` — terminal states.

Track `modify_requested` and `cancel_requested` as explicit pending-mutation facts rather than
discarding the underlying acknowledged/partially-filled state. This permits fills during broker
mutation races. A cancel failure is never swallowed: it clears no risk or working exposure and
forces reconciliation unless authoritative evidence proves the order remains in a known state.

The pure transition operation conceptually accepts the aggregate plus a typed event and returns a
new aggregate and typed effects/error; it performs no I/O. Rules include:

- cumulative fill is monotonic, bounded by effective quantity, and converted to a delta exactly
  once;
- identical broker updates are idempotent by stable update ID or canonical evidence fingerprint;
- same deduplication key with different content is an incident;
- partial fills may arrive while modify/cancel is pending;
- a full fill wins a race with later cancel acknowledgment; the later compatible terminal update is
  retained as evidence but does not change position twice;
- accepted modify terms cannot reduce quantity below already filled quantity and become effective
  only on authoritative acknowledgment;
- ambiguous submission accepts no ordinary ACK/fill transition until an explicit reconciliation
  event establishes broker identity and state;
- repeated compatible terminal evidence is idempotent; contradictory terminal evidence is an
  incident requiring reconciliation;
- every illegal transition returns a stable error and leaves the aggregate unchanged.

Document the full state/event matrix and race examples in `execution/docs/ORDER_LIFECYCLE.md`.
Tests must derive expected legality from the frozen matrix so adding an enum without updating the
matrix fails visibly.

## Completion criteria

This section is complete only when focused CTest passes; ledger hashes and golden bytes are stable;
all corruption and crash-cut tests fail closed; damaged-tail repair preserves source evidence;
replay reconstructs identical orders/fills/positions/idempotency state; every legal/illegal FSM edge
is covered; ambiguous submissions never retry; the ordinary build still reports
`live_router=off`; and no path under `data/` or `research/` changed.
