# Section 05 — Bounded Local IPC and the Shadow Executor

## Outcome and boundaries

This section exposes the completed ExecutionSession through local, bounded, peer-validated Unix
IPC and supplies the independently runnable `shaurya-executor` command. The executor is a
shadow-only state owner. It receives Dhan-derived `MarketObservation` messages from one Data-owned
publisher, relays validated observations to the connected strategy client, receives broker-neutral
`OrderIntent` messages, and returns correlated `ExecutionEvent` messages. It owns routing, risk,
idempotency, FSM, ledger, paper-broker state, reconciliation, and readiness; it does not acquire
market data, authenticate to Kotak, construct live transport, launch a strategy, or manage AWS.

Prerequisites are the strict contract codecs, resolver, ledger/FSM, risk engine, broker interfaces,
and `ExecutionSession`. This section uses their public APIs and does not redefine their semantics.
All work remains under `execution/`; do not modify Data or Research.

## Tests first

Register the tests in `execution/CMakeLists.txt` before production implementation. Tests use only
temporary directories under `/private/tmp`, injected peer inspectors, fake clocks, deterministic
fixtures, and socketpairs or loopback Unix sockets. They must not contact a network, broker, AWS,
the real home directory, or a real runtime socket.

### Framing and transport tests

Create `execution/tests/test_ipc_transport.cpp`. Cover:

- `SOCK_SEQPACKET` selection on a supported injected platform and bounded length-framed
  `SOCK_STREAM` fallback otherwise;
- the stream frame format: four-byte unsigned big-endian payload length followed by exactly that
  many canonical UTF-8 JSON bytes;
- empty, truncated-prefix, truncated-payload, oversized, extra-byte, multiple-frame, interrupted
  read/write, timeout, and orderly EOF behavior;
- the same maximum payload size for both transports, with rejection before allocation when the
  declared length exceeds the limit;
- bounded write deadlines and no indefinite block when a peer stops reading;
- exact packet boundaries for SEQPACKET and refusal of truncated packets;
- deterministic transport error categories that contain no payload excerpts.

Set a single protocol maximum in the exact runtime configuration and enforce it before JSON parsing.
The initial maximum should be 65,536 bytes, large enough for the defined contracts but small enough
for bounded allocation; tests must fail if configuration attempts to raise it beyond the compiled
safety ceiling.

### Filesystem and peer-validation tests

Create `execution/tests/test_ipc_security.cpp`. Cover:

- runtime parent missing, symlinked, wrong type, wrong owner, group/world writable, or wrong mode;
- socket path pre-exists as a regular file, symlink, foreign socket, active socket, or safely owned
  stale socket;
- sockets are created with mode `0600` inside an executor-owned `0700` directory;
- accepted and refused UID/GID, executable digest, process start identity, configuration digest,
  role, and protocol version;
- Linux peer inspection using injected `SO_PEERCRED` and `/proc` evidence;
- Darwin-compatible injected `getpeereid` behavior and fail-closed handling when production-required
  executable evidence is unavailable;
- time-of-check/time-of-use replacement of parent, socket, executable, or configuration;
- peer disconnect and PID reuse after handshake.

Production Linux configuration requires UID/GID, process start identity, executable digest, and
configuration digest. Platform-isolated fixture mode may inject evidence for Darwin tests, but no
runtime configuration or environment variable may downgrade production validation.

### Protocol, correlation, and replay tests

Create `execution/tests/test_ipc_protocol.cpp` with fixtures under
`execution/tests/fixtures/ipc/`. Cover exact-schema handshake and role negotiation for one
`market_publisher` and one `strategy_client`, then test:

- unknown, missing, duplicate, oversized, wrong-version, wrong-session, and wrong-role fields;
- a Data publisher can send `MarketObservation` only; a strategy can send `OrderIntent` and event
  acknowledgements only;
- the executor relays only successfully validated observations and preserves their source sequence;
- every accepted intent receives correlated events with stable intent/run/session IDs;
- a reconnect request with `after_event_sequence` replays matching ledger-derived events before
  switching to live delivery;
- replay requests ahead of the ledger, across another session, or outside the authorized strategy
  scope are refused;
- duplicate reconnects are idempotent and never resubmit an intent;
- a slow or disconnected strategy cannot cause silent event loss.

The strategy connection is bidirectional. Market observations and execution events carry distinct
message kinds, so D51 can consume the same validated Data observation stream used by paper risk and
fills without sending observations back into Execution.

### Queue and safety-stop tests

Create `execution/tests/test_executor_queues.cpp`. Use small injected capacities to saturate each
stage deterministically: market receive, strategy receive, risk work, broker submission, broker
update, ledger command, and outbound event delivery. Assert:

- every queue is fixed-capacity and exposes depth/high-water counters;
- overflow revokes new place/modify authority immediately;
- the first overflow wins the stable safety-stop reason and later failures cannot overwrite it;
- a pre-broker ledger/submission-stage overflow sends NO ORDER;
- an overflow after a broker attempt records ambiguity or reconciliation requirement and never
  retries automatically;
- failure to deliver an event leaves it replayable from the ledger;
- observation overflow marks market data untrustworthy and blocks risk approval;
- broker-update overflow is a safety stop, not a dropped update;
- cancellation remains available through the risk-reducing path when transport health permits;
- shutdown drains only bounded already-accepted work and finishes by its configured deadline.

### Executor command tests

Create `execution/tests/test_executor_cli.cpp` or a hermetic Python/shell harness under
`execution/tests/ops/`. Test these exact commands:

- `shaurya-executor version`;
- `shaurya-executor validate-config --config PATH`;
- `shaurya-executor verify-ledger --ledger PATH`;
- `shaurya-executor replay --config PATH --ledger PATH`;
- `shaurya-executor serve --config PATH --launch-attestation PATH`.

Help, version, validation, and replay must not open IPC listeners or construct broker/network
objects. Unknown commands/options, duplicate options, missing values, relative protected paths,
unknown configuration fields, and `--mode live` must fail closed. Test all live-mode entry paths and
prove refusal occurs before socket creation, ledger mutation, thread start, or broker construction.

Add a hermetic end-to-end fixture that starts the executor in a temporary runtime directory,
connects fake Data and strategy peers, establishes readiness, sends observations and intents,
receives simulated events, disconnects/reconnects with an event cursor, verifies ledger replay, and
shuts down cleanly.

## Files and interfaces

Create:

- `execution/include/shaurya/execution/ipc_transport.hpp`
- `execution/src/ipc_transport.cpp`
- `execution/include/shaurya/execution/peer_identity.hpp`
- `execution/src/peer_identity.cpp`
- `execution/include/shaurya/execution/ipc_protocol.hpp`
- `execution/src/ipc_protocol.cpp`
- `execution/include/shaurya/execution/executor.hpp`
- `execution/src/executor.cpp`
- `execution/src/main.cpp`
- `execution/tests/test_ipc_transport.cpp`
- `execution/tests/test_ipc_security.cpp`
- `execution/tests/test_ipc_protocol.cpp`
- `execution/tests/test_executor_queues.cpp`
- `execution/tests/fixtures/ipc/` fixture files.

Update `execution/CMakeLists.txt` to build an internal IPC library, the `shaurya-executor`
executable, the CTests, and an install rule for the binary. Keep platform-specific socket and peer
inspection behind narrow source files selected by CMake; contract, queue, and executor logic must be
platform-independent.

The conceptual interfaces are:

- `IpcTransport::{listen, accept, read_frame, write_frame, close}` with injected deadline/peer
  inspection support;
- `PeerInspector::inspect(accepted_socket) -> PeerEvidence`;
- `Executor::{initialize, run, request_stop}` around one `ExecutionSession`;
- bounded channels whose `try_push` returns an explicit accepted/overflow result.

These are responsibilities, not required full signatures. Use RAII for descriptors and threads,
single ownership for session mutation, and `std::stop_token` or an equivalent explicit stop path.

## Exact runtime topology

The executor owns two configurable Unix sockets inside one protected runtime directory:

- `market.sock`: accepts exactly one attested `market_publisher`. The publisher is owned by Shaurya
  Data and is the sole producer of Dhan-derived `MarketObservation` packets.
- `strategy.sock`: accepts exactly one attested `strategy_client` for the initial release. It sends
  validated observations and execution events to the strategy and receives neutral intents and
  event acknowledgements.

The executor validates and sequences each observation once, then feeds the same immutable value to
risk/paper execution and the strategy outbound stream. The strategy cannot inject market data.
Supporting more clients later requires a new schema version and explicit fan-out policy; do not
silently generalize this release.

The operator launch workflow starts a preinstalled, manifest-pinned one-shot orchestration unit.
That unit is responsible for arranging the Data publisher, executor, and expected D51 client
processes; the executor itself never invokes systemd or spawns them. In this implementation all
remote orchestration is verified with fixtures only. Readiness requires both expected peers, but the
executor remains the sole execution authority.

## IPC framing and handshake

Prefer Unix `SOCK_SEQPACKET` where the platform supports it. Otherwise use `SOCK_STREAM` with the
four-byte network-order length prefix described in the tests. Do not fall back to TCP. Reject
ancillary descriptors, extra bytes, unsupported socket types, or packet truncation.

Before accepting application messages, require a canonical handshake containing schema version,
role, execution-session ID, peer configuration digest, peer executable digest, process start
identity, and a fresh nonce supplied by the executor. Validate kernel peer credentials and compare
all configured bindings using constant-time digest comparison. A handshake asserts identity but
never contains a credential or private key.

The runtime configuration has an exact schema and includes:

- schema/configuration version and digest;
- shadow mode only and trading date;
- runtime directory and the two socket basenames;
- maximum packet, per-stage queue capacities, I/O deadlines, reconnect window, and shutdown
  deadline;
- expected UID, GID, executable digest, and configuration digest for each peer role;
- routing snapshot/manifest, risk configuration, ledger root, and paper-model paths;
- launch-attestation path and expected digest;
- required initial observation freshness and expected strategy ID.

Paths must be absolute, normalized, beneath their configured protected roots, and opened without
following symlinks. Unknown/duplicate fields or environment overrides are refused.

## Ordering, queues, and event replay

Use one state-owner thread for `ExecutionSession` mutation. Reader threads validate framing and
schema before placing immutable messages into fixed-capacity channels. The state owner captures the
risk snapshot and uses acknowledged ledger commands around broker work. Broker callbacks enter a
separate bounded update channel. Outbound delivery is bounded and recoverable from the ledger.

Assign executor source sequence numbers to accepted observations and ledger event sequence numbers
to execution events. Preserve FIFO order within each source; cross-source ordering is decided by the
state-owner dequeue rule and recorded in the ledger. Use a deterministic priority: safety/broker
updates, accepted intents, then observations. Do not use wall-clock thread scheduling as business
ordering.

On strategy reconnect, authenticate the peer again and accept an `after_event_sequence` cursor.
Filter replay by execution session and configured strategy identity, stream durable events in
sequence, then attach to live delivery without a gap. The ledger is the source of replay; an
in-memory buffer is only an optimization. An unacknowledged event never causes intent resubmission.

## Lifecycle and readiness

Initialization proceeds in this exact order:

1. parse command and reject live mode;
2. strictly validate configuration, launch attestation, file ownership/modes, and artifact digests;
3. open/verify the ledger and reconstruct state;
4. load and validate the routing snapshot;
5. construct the paper broker only;
6. query and reconcile paper orders, fills, and positions;
7. create protected sockets and start bounded workers;
8. authenticate the expected Data and strategy peers;
9. receive a fresh valid observation;
10. durably record session start/readiness and emit an allowlisted readiness marker.

Before step 10, place and modify are refused. If a peer disconnects, an observation becomes stale,
a queue overflows, the ledger fails, or the paper broker becomes unknown, revoke readiness and emit
one stable safety-stop reason. A reconnect may restore message delivery but cannot restore order
authority until explicit reconciliation succeeds.

The non-secret launch attestation supplies operator ID, device ID, public-key fingerprint, CLI
release/version digest, deployment-manifest digest, executor commit/build digest, requested shadow
mode, confirmation type, launch timestamp, and invocation ID. Validate its digest and exact schema,
then pass it unchanged into the session-start ledger event. It never contains TOTP, SSH private-key
material, broker session fields, or credentials.

Shutdown rejects new intents, invokes the session’s factual cancellation/reconciliation sequence,
stops accepting peers, drains bounded durable work, closes and unlinks only the executor-owned socket
inodes, fsyncs required ledger state, and exits with a factual terminal marker. Never unlink a
foreign or replaced path.

## Completion evidence

This section is complete when the Release build and all IPC/executor CTests pass, the hermetic E2E
fixture proves observation-to-intent-to-event flow plus reconnect replay, live negative controls
prove no socket/network/broker construction, and filesystem inspection shows no runtime artifacts
inside the repository or real home. Record exact transport mode coverage and any Darwin behavior
tested only through injected platform fixtures.
