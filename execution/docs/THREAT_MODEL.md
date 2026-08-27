# Execution Threat Model

## Assets and trust boundaries

Assets are intent integrity, authoritative order/position state, routing provenance, the execution
ledger, operator/device attribution, and the absence of secret material. Boundaries exist at the
strategy and observation sockets, routing snapshot, broker adapter, operator CLI, deployment
manifest, release installer, and ledger filesystem.

## Threats, mitigations, and verification

| Threat | Mitigation | Verification |
|---|---|---|
| Credentials, TOTP, keys, or broker bodies leak | Handle-only configuration and marker allowlists | Secret-shape and log tests |
| Unauthorized local peer | Peer, executable, owner, mode, and configuration binding | IPC peer fixtures |
| Duplicate, replayed, conflicting, malformed, or oversized packets | Exact schemas, IDs, fingerprints, bounds, monotonic sequences | Contract and IPC rejection corpus |
| Stale, partial, ambiguous, missing, or tampered routing | Same-date join, canonical manifest, no guessing | Resolver tamper fixtures |
| Ambiguous submission | Durable pre-call event, safety stop, reconcile-never-resubmit | Crash-cut tests |
| Ledger truncation, tamper, rollback, or concurrent writers | Single writer, hash chain, fsync, fail-closed repair segment | Ledger fault tests |
| Environment injection or live-option typo | CMake cache default OFF and fatal ON | Live-gate CTest |
| Symlink, traversal, unsafe mode, or manifest substitution | No-follow/path containment and exact manifests | Installer and ledger filesystem tests |
| Operator/device impersonation | Non-secret identity and digest attestation | Session audit tests |
| Queue overflow, disconnect, stale data, or clock anomaly | Bounded queues and deterministic safety stop | Saturation/frozen-clock tests |
| Test contacts network, broker, AWS, or real home | Hermetic fixtures and explicit temporary prefixes | No-network and portability tests |
| Supply-chain or build/test dependency fetch | No FetchContent and no test-time installation | CMake policy tests |

Credential directories must be mode `0700` and credential files `0600`. Tests never read secret
values. Contracts, logs, ledgers, crash text, and broker errors must not contain them.
