# Ledger, replay, and recovery

The execution ledger is the local durable authority for what the executor attempted and learned.
It is not broker truth, and replay never performs network I/O. Broker-authoritative comparison and
readiness remain separate reconciliation responsibilities.

## Segment format and durability

Each segment is canonical JSON Lines. A record contains the `ExecutionEvent` fields plus a positive
`sequence`, `previous_record_hash`, and `record_hash`. Sequence 1 binds to 64 zeroes. Every later
record binds to the prior `record_hash`. `record_hash` is SHA-256 of the canonical record object
without the `record_hash` member. The final serialized object is canonical UTF-8 followed by exactly
one newline. Records are limited to 64 KiB and a verification pass is bounded to 64 MiB per segment.

Create a segment only below an operator-selected directory owned by the process user with mode
`0700`. The segment is created exclusively as `0600`, without symlink following, and remains locked
by one writer. Before every append the writer checks path/device/inode identity and re-verifies the
durable prefix. It writes with append semantics and calls `fsync` before advancing its in-memory
sequence/hash or reporting success. A failed append exposes a factual durability boundary:
`NotWritten` (zero bytes), `Uncertain` (some/all bytes written without confirmed durable path
identity), or `Durable` (the record was fsynced before a later injected/process failure). Every
failure closes writer authority. Callers verify and reconcile instead of inferring persistence.

The required submission ordering is:

```text
intent_received -> mapping decision -> risk decision -> submission_started
-> one broker mutation attempt -> acknowledgement, rejection, or ambiguity
```

An event is validated through the closed `ExecutionEvent` contract before append. Payload members
are variant-specific, bounded, and recursively screened for secret-shaped keys. The ledger must
never contain credentials, tokens, cookies, authorization material, private keys, raw broker HTTP
bodies, or authentication URLs.

## Verification and startup

`verify_ledger` streams bounded records and returns one of four results. Its default metadata mode
does not retain record bodies; replay uses the same verified visitor path and reduces one record at
a time:

- `Clean`: every complete line is canonical; versions, sequences, event IDs, correlations, hashes,
  and event semantics verify.
- `TruncatedTail`: a valid prefix is followed by a syntactically incomplete, non-newline-terminated
  JSON value. The exact byte length of the verified prefix is returned.
- `Corrupt`: a complete invalid record, missing final newline on a complete JSON value, duplicate or
  discontinuous identity, noncanonical bytes, broken chain, or mismatched hash.
- `Unsafe`: the path is missing, a symlink/non-regular file, has unsafe ownership/permissions, changes
  identity, cannot be read safely, or exceeds the bounded segment size.

Normal startup accepts only `Clean`. It must not truncate, normalize, skip, or automatically repair
any other result. Replay accepts only a clean verification result and deterministically rebuilds
intent fingerprints/dispositions, order aggregates and broker update evidence, signed positions,
session lifecycle, safety stops, incidents, and reconciliation-required facts. BUY fill deltas are
positive and SELL deltas negative. Cumulative fill evidence is applied through the generic order FSM
exactly once; regressions, overfills, conflicting duplicate updates, illegal transitions, and
position overflow fail closed.

`IdempotencyStore` is rebuilt from replay. Registration accepts the ledger and a typed
`intent_received` event, appends/fsyncs that event first, and mutates memory only after durable
success. An unseen intent ID is new. The same ID and semantic
fingerprint returns the recorded disposition without another broker attempt. The same ID with a
different fingerprint durably appends a typed `safety_stop` incident and blocks new intents. An
ambiguous intent always returns
`ReconciliationRequired`, including after restart, and is never retried automatically.

## Evidence-preserving truncated-tail repair

Repair is an explicit offline operation. Stop the active writer and use a new output path in a safe
state directory:

```text
shaurya-ledger-repair INPUT OUTPUT CONFIGURED_ACTIVE_SEGMENT \
  REPAIR_TRUNCATED_LEDGER EXECUTION_SESSION_UUID EVENT_UUID TIMESTAMP_NS
```

The configured active segment is mandatory and repair refuses when it aliases the input. Before
invocation, the damaged source must already be preserved as owner-readable and non-writable
(`0400`); the tool refuses writable evidence and never changes its mode. The tool proceeds only for
`TruncatedTail`. It reads the bounded source, computes the SHA-256 of all
damaged bytes, copies exactly the verified complete-record prefix to a newly created `0600` output,
verifies that copy, and appends a closed `ledger_repair_recorded` event. That incident records the
damaged digest and byte length, verified-prefix length, basename-only source label, tool version,
and confirmation type. The output segment and parent directory are `fsync`ed.

The damaged segment is never truncated, rewritten, renamed, deleted, or selected automatically.
Repair rejects existing/aliased output, the configured active input, any symlinked path ancestor,
unsafe output directories, complete-but-invalid final records, and any corruption in the verified
prefix. Operators must separately select the repaired
segment in configuration. Selection does not clear the recorded incident: startup remains blocked
until reconciliation confirms broker-authoritative state.

## Operational boundaries

- No component here contains a broker client, network transport, credentials, or live-routing gate.
- Do not place ledgers in source control or shared project directories.
- Retain damaged segments and repair outputs together with their external incident record.
- Treat a successfully copied segment as recovery evidence, not proof of broker agreement.
- Never edit JSONL manually; create a new segment through the repair workflow.
