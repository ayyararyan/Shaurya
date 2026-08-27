# Execution Control Plane Research

## Baselines

- Shaurya starts at `bcb6dea02329f824c82488f29450af0dd0e826ca` on GitHub `main`.
- D51 starts at `dd06e55e51c2ffa691c6e9f0ba61e38de019cd87` on GitHub `main`.
- Both implementation branches were created from clean remote defaults. The source checkout's
  Research edits remain user-owned and untouched.
- No applicable `AGENTS.md` exists in either repository.

## Shaurya findings

Shaurya currently has independent Data and Research Python projects. Data owns Dhan acquisition,
immutable storage, validation, and replay. Research imports only Data's public facade and has no
broker authority. Execution must be a third independent C++20 project; neither existing project
may import it.

The existing `InstrumentId`, `KotakInstrumentMapping`, `KotakInstrumentMaster`, and
`KotakInstrumentIndex` establish the canonical identity and same-day duplicate/staleness rules.
Execution can consume those semantics through an Execution-owned exporter and needs no Data edits.
The exporter must enrich its routing snapshot with lot and tick metadata required by risk.

Data's useful integrity conventions are deterministic compact JSON, SHA-256 manifests, append-only
files, fsync, permanent evidence, and explicit partial/orphaned states. Data and Research use `uv`,
pytest, Ruff, and strict mypy. Their regression environments must remain outside the repository,
with bytecode disabled.

## D51 findings

D51 is a C++20 shadow engine. Its reusable operational ideas are exact-schema bounded Unix sockets,
single-use in-memory session claims, peer/executable/hash attestation, strict non-PTY SSH, hidden
TOTP input, exact confirmations, local and remote locks, a finite watcher, factual markers, and a
compile-time live gate.

D51 strategy components—surface fitting, policy, features, SFeed market data, fixed CE/PE slots,
research statistics, names, service paths, and instrument preparation—must remain in D51. Its
four-slot router, floating-point intent, broker-specific token fields, response-body error messages,
and swallowed cancel failures must not be copied.

The installed Mac `kotak` command matches the current D51 repository source byte-for-byte. It is a
reference only; this implementation will not overwrite or install into the real home directory.

## Frozen technical decisions

- Strict UTF-8 JSON, maximum packet sizes, duplicate/unknown/missing field refusal, and canonical
  serialization are shared across Python/C++ fixture corpora.
- Money uses signed 64-bit paise; quantity uses positive exchange units; timestamps use bounded
  UTC Unix nanoseconds. Overflow and invalid ticks fail closed.
- An ambiguous submission is never automatically resubmitted. It blocks the session until
  authoritative reconciliation proves the outcome.
- The ledger is single-writer, append-only, length-bounded canonical JSON with a SHA-256 chain,
  fsync on safety-relevant boundaries, verifiable replay, and explicit truncated-tail handling.
- The order store is generic and keyed by internal order ID and canonical instrument ID.
- The new paper path consumes broker-neutral Data/Dhan observations. Legacy D51 SFeed remains only
  behind a rollback path. Paper fills are always labelled simulated/proxy.
- `SOCK_SEQPACKET` is preferred; a bounded length-framed stream transport is the portable test
  fallback. Peer and filesystem ownership/mode checks fail closed.
- The Kotak adapter is an interface plus sanitized deterministic fixtures behind a default-OFF
  compile gate. No broker authentication or request occurs in this work.
- Portable releases disable native CPU tuning. Two isolated temporary Mac-like homes test install
  identity; they do not claim cross-architecture coverage.
- Checksum verification is called checksum verification unless a genuine signing key and trust
  policy are introduced.

## Testing

Execution uses CMake/CTest with small C++ test executables and hermetic Python/shell tests for
export, operations, release, and portability. CMake is obtained as an ephemeral tool outside the
repository when it is absent from PATH. Builds and caches live under `/private/tmp`.

D51 retains its six CTest binaries plus hermetic broker, watcher, and shadow-launch suites. New D51
tests use frozen observations and event transcripts for intent/fill/inventory/cancel parity.

Final verification includes Execution Release build and CTest, Data and Research pytest/Ruff/mypy,
D51 build/tests and operational suites, two isolated installs, live-negative controls, secret and
personal-path scans, and exact protected-directory diffs.
