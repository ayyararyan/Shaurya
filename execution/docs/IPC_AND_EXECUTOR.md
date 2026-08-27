# Local IPC and shadow executor

`shaurya-executor` is a shadow-only local execution authority. It exposes two protected Unix-domain
sockets: one for the single Data-owned market publisher and one for the single configured strategy.
There is no TCP fallback, process spawning, cloud integration, broker authentication, or live-order
transport in this component. `version` always attests `kotak_live=off`; attempts to enter through a
live-mode command or configuration fail before socket creation.

The preferred transport is Unix `SOCK_SEQPACKET`. Platforms without it use Unix `SOCK_STREAM` with
a four-byte big-endian size followed by exactly one canonical JSON payload. Both modes enforce the
compiled 65,536-byte ceiling, reject empty/truncated frames, and use bounded I/O deadlines. Runtime
directories must already be executor-owned real directories with mode `0700`; socket files are
owned by the executor with mode `0600`, and shutdown only removes the inode it created.

Peers complete a strict versioned handshake and are checked against kernel UID/GID evidence,
process-start identity, executable digest, configuration digest, role, session, and nonce. Linux
production inspection uses kernel peer credentials and `/proc` evidence. Darwin fixture tests may
inject equivalent evidence; production-required validation fails closed if executable evidence is
unavailable.

Reader workers validate framing, role, and schema before placing immutable messages into bounded
market and strategy ingress channels. The server loop is the sole state owner and processes an
already-accepted safety-fault market message before strategy/risk/broker work. Risk and broker-submission work
traverse their bounded stages. Immediately before a broker mutation, a typed ledger command verifies
and acknowledges the exact durable sequence containing the submission boundary; another verifies
the durable outcome after the attempt. Actual paper-fill updates traverse the separately bounded
broker-update channel before the state owner applies them. An overflow immediately revokes order
authority, records a stable first failure reason, and never triggers automatic broker retry.
Execution events carry monotonically increasing sequences and remain replayable for the exact
session and strategy scope after reconnect; replay never resubmits an intent. Events are appended
to the hash-chained execution ledger before delivery. Startup verifies that ledger and reconstructs
the replay cursor from its records, so process restart does not depend on an in-memory buffer.

The persistent server owns one state-mutating loop. It challenges and authenticates each peer before
reading application messages. The Data peer sends a strict `strategy_book_observation` containing
one to five actual, ordered levels per side, with integer-paise prices, positive displayed quantities
and order counts, and explicit last-trade quantity and open interest. Missing levels are never padded
and missing required D51 fields fail closed. The executor assigns the source sequence and the SHA-256
digest of the unchanged canonical book payload, deterministically derives the frozen aggregate
`MarketObservation` for risk and `PaperBroker`, and relays the unchanged full book with the same
sequence/digest to the strategy. Events for prior orders caused by an observation are delivered
before the triggering book. At bootstrap, the first book is delivered before the following
`session_started` readiness event. A strategy cannot inject either market representation. A strategy
disconnect requires a new challenge and handshake; an authorized event cursor is replayed before
live delivery resumes. Either peer disconnect immediately revokes order authority. Reauthentication
may restore delivery but cannot restore readiness without an explicit reconciliation. Explicit
shutdown stops new work, completes the session shutdown sequence,
delivers every shutdown-generated durable event, and accepts final event acknowledgements under
one absolute shutdown deadline. Factual success requires empty bounded queues, no reserved broker
update capacity, and an acknowledgement cursor covering the final durable sequence;
the server then closes descriptors and removes only the listener inodes it created.

Supported commands are `version`, `validate-config --config PATH`, `verify-ledger --ledger PATH`,
`replay --config PATH --ledger PATH`, and `serve --config PATH --launch-attestation PATH`.
The exact version line contains `commit=<40-hex HEAD>`, `source_state=clean|dirty`, and
`source_tree_sha256=<64-hex digest>` before the opened-executable `build_sha256`. Before every
normal build, the attestation generator re-derives HEAD and hashes the exact bytes of every tracked
or untracked execution input. `clean` means those bytes match that Git commit; any change is
reported as `dirty`, and the attestation translation unit is rebuilt before dependent binaries, so
a development build never presents a clean or stale identity for different source bytes.
Protected paths must be absolute and normalized. Every protected ancestor is opened without
following symlinks and checked for safe ownership/write policy; protected roots are exact mode
`0700`. The executor configuration digest is recomputed from canonical bytes with its digest field
removed, peer configuration digests are verified against their protected canonical artifacts, and
serve hashes the opened running executable and requires equality with the pinned executor-build
digest. Configuration and launch-attestation documents
use exact schemas, reject unknown fields, and permit only `mode=shadow`. Configuration pins a
protected `0700` attestation root, maximum attestation age, and expected CLI-release, deployment,
and executor-build digests. Each invocation supplies a canonical `<invocation-uuid>.json` file with
mode `0600` strictly inside that root. It is opened relative to a no-follow root descriptor and its
owner, mode, inode, size, and timestamps must remain stable. The payload invocation must match the
filename and must bind the execution session, shadow mode, confirmation type, immutable digests,
and freshness. The executor computes the attestation digest itself and durably includes that digest
and every non-secret attestation field in the single `session_started` event.

On restart, the verified execution ledger is also the sole source for rebuilding paper requests,
routing records, orders, fills, positions, and correlation sequence. Recovery fails closed on
incomplete broker evidence. For restored working orders, the first valid post-restart observation
establishes a new cumulative-volume baseline and cannot fill; only later volume deltas may fill.
The frozen `d51_proxy_v1` preserves its full-fill-on-qualifying-cross semantics; partial-fill
accumulation remains available only through the fixture-authorized scripted lifecycle model.
