# Implement the Shaurya Execution Control Plane

Implement the Shaurya Execution Control Plane completely, using the proven D51 ALO-SMM Kotak workflow as the operational reference.

Use the `deep-plan` skill first and then the `deep-implement` skill. Do not stop after producing a plan: continue through implementation, testing, documentation, commits, and pushing all branches to GitHub.

## Authorization and boundaries

I authorize you to:

- Modify the Shaurya repository.
- Modify the separate `ayyararyan/D51_ALO_SMM_CPP` repository where required to make D51 the first Shaurya Execution client.
- Create clean isolated Git worktrees and `codex/` branches.
- Commit all intentional changes.
- Push all resulting branches and commits to their GitHub remotes.

I do not authorize:

- Live order placement.
- Enabling the live Kotak router.
- Real broker authentication or TOTP entry.
- Starting or stopping AWS services.
- AWS or cloud-infrastructure changes.
- Installing the new CLI into my real home directory.
- Reading, copying, printing, or modifying credentials, tokens, SSH private keys, TOTP seeds, or protected runtime files.
- Merging or force-pushing to `main`.
- Including unrelated pre-existing worktree changes in any commit.

This implementation must finish at a fully tested, portable, shadow-safe execution control plane. Live trading must remain fail-closed and explicitly unfinished.

## Protected Data and Research subsystems

Treat `data/` and `research/` as protected existing subsystems. This implementation must be additive.

- Expect zero changes under `research/`.
- Do not refactor, rename, move, reformat, clean up, or redesign anything under `data/` or `research/`.
- Prefer adapters, routing-snapshot readers, exporters, and compatibility layers inside `execution/`.
- Reuse the existing broker-neutral instrument contracts without modifying Data whenever possible.
- A change under `data/` is permitted only if it is strictly necessary to expose an existing instrument-mapping capability and cannot reasonably be implemented inside `execution/`.
- Every modified file under `data/` must be individually justified in the final report, including the exact file, necessity, and scope.
- Any modification under `research/` is a failure condition unless an unavoidable blocker is demonstrated and explicit user approval is obtained before editing.
- Do not relocate shared contracts merely to make the directory structure aesthetically cleaner.
- Existing Data and Research APIs, commands, tests, package layouts, lockfiles, and dependency environments must remain compatible.
- The root `README.md` may receive the minimum documentation change required to add Execution as the third independent project.

Before committing, run a path-level diff against the starting commit:

- Unexpected changes under `data/` or `research/` are a failure.
- Research should have no changed files.
- Data should have no changed files unless each change satisfies the strict exception above.
- Run the existing Data and Research test suites to prove the additive Execution work caused no regressions.

## Repositories and existing state

Primary repository:

`/Users/aryanayyar/Documents/Shaurya`

Reference and client repository:

`ayyararyan/D51_ALO_SMM_CPP`

The current Shaurya working tree may contain unrelated user changes. Treat all existing modifications and untracked files as user-owned. Do not edit, stage, stash, delete, or commit them.

Start by:

1. Reading all applicable `AGENTS.md` files, repository instructions, READMEs, and security policies.
2. Fetching the current GitHub remotes.
3. Recording the exact starting commit IDs.
4. Creating a clean isolated Shaurya worktree from the verified GitHub default branch.
5. Creating branch `codex/shaurya-execution-control-plane`.
6. Creating a separate clean D51 clone or worktree and branch `codex/shaurya-execution-client`.
7. Confirming both new worktrees are clean before editing.

Do not assume previously observed commit IDs are current.

## Verified architectural intent

Shaurya currently contains Data and Research. Add Execution as a third independently runnable project:

```text
Shaurya/
├── data/
├── research/
└── execution/
    ├── contracts/
    ├── include/
    ├── src/
    ├── ledger/
    ├── ops/
    ├── tests/
    └── docs/
```

Preserve these boundaries:

- Data is the sole Shaurya market-data acquisition plane.
- Dhan remains Shaurya's market-data source.
- Kotak is the sole execution broker.
- Kotak order, trade, and position updates are execution evidence, not market-data ingestion.
- Research must never import Execution or gain broker or order authority.
- Strategies emit broker-neutral intents and never construct Kotak REST requests.
- Execution resolves instruments, applies risk, owns the order state machine, reconciles broker state, and writes the authoritative append-only execution ledger.
- The Mac `kotak` command is an operator control plane. It launches and authorizes an execution session; it is never called once per order.
- Secrets and runtime state must never enter either repository.

Target flow:

```text
Strategy
   |
   | broker-neutral OrderIntent
   v
Shaurya Execution
   |- instrument resolution
   |- deterministic risk gate
   |- idempotency
   |- order lifecycle
   |- broker reconciliation
   |- append-only ledger
   v
Kotak adapter
   |
   v
ACK / REJECT / PARTIAL_FILL / FILL / CANCEL
   |
   v
Shaurya reconciles authoritative state
```

The portable operational flow is:

```text
Versioned `kotak` CLI
   |
   |- doctor
   |- authenticate and preflight
   |- attest deployment
   |- one-shot launch
   v
Shaurya Executor on AWS
   |
   v
Kotak
```

## Phase 1: Freeze the specification

Create `execution/EXECUTION_CONTROL_PLANE_SPEC.md`.

Use stable requirement IDs and a traceability table. Cover at least:

- `EXE-BND-*`: component and authority boundaries.
- `EXE-CON-*`: shared wire contracts.
- `EXE-INS-*`: canonical-to-Kotak instrument resolution.
- `EXE-IDM-*`: idempotency and ambiguous-submit handling.
- `EXE-FSM-*`: order lifecycle state machine.
- `EXE-RSK-*`: deterministic pre-trade and runtime risk.
- `EXE-LED-*`: append-only execution ledger.
- `EXE-REC-*`: crash recovery and broker reconciliation.
- `EXE-OPS-*`: session control and one-shot launch.
- `EXE-PORT-*`: portable Mac CLI and distribution.
- `EXE-SEC-*`: secret handling, attestation, permissions, and threat model.
- `EXE-SHD-*`: paper and shadow behaviour.
- `EXE-LIVE-*`: deliberate live blockers.
- `EXE-D51-*`: D51 migration and parity.

Document verified facts separately from design decisions.

Update the root Shaurya README to describe three projects and their permitted dependency directions. Remove the statement that execution is outside Shaurya only after the new boundary is implemented and tested.

## Phase 2: Define shared contracts

Create versioned, strict contracts usable across Python and C++.

### OrderIntent

Implement these required concepts:

- schema version
- unique `intent_id`
- strategy ID
- strategy-run ID
- execution-session ID
- creation and expiry timestamps
- broker-neutral canonical instrument ID
- action: place, modify, or cancel
- side
- integer quantity in exchange units
- regular LIMIT order only for the initial implementation
- exact integer price representation, preferably paise or validated ticks rather than binary floating-point
- product and time-in-force from a closed allowlist
- target internal order ID for modify or cancel
- optional strategy attribution or tag
- no Kotak token, URL, session, or credential fields

### ExecutionEvent

Support at least:

- intent received
- mapping validated or refused
- risk approved or rejected
- submission started
- broker acknowledged
- partially filled
- filled
- cancel requested
- cancelled
- broker rejected
- ambiguous submission
- reconciliation required
- reconciliation completed
- safety stop
- session started or stopped

Every event must include stable correlation identifiers and timestamps.

### RiskDecision

Include:

- intent ID
- decision
- exact rule-set and configuration version
- rules checked
- limits before and projected after
- explicit rejection reason
- relevant data and session freshness
- deterministic inputs needed for replay

### PositionSnapshot

Keep these meanings distinct:

- strategy-desired position
- Shaurya ledger-reconstructed position
- broker-authoritative position

A mismatch is an execution incident and must block new order submission until reconciled.

### MarketObservation for paper execution

Define a broker-neutral observation contract containing only the information necessary for deterministic paper fills and staleness checks:

- canonical instrument ID
- best bid and ask
- last-trade price
- cumulative volume
- exchange and receive timestamps
- source and provenance
- quality flags

Paper fills must be labelled explicitly as simulated or proxy, never broker-confirmed.

Use strict parsing throughout:

- reject unknown fields
- reject duplicate fields
- reject missing fields
- reject invalid enum values
- reject overflow, invalid timestamps, invalid tick prices, and nonpositive quantities
- version every schema

## Phase 3: Instrument-resolution seam

Reuse the semantics of Shaurya's existing:

- `InstrumentId`
- `KotakInstrumentMapping`
- `KotakInstrumentMaster`
- `KotakInstrumentIndex`

Prefer an adapter under `execution/` that consumes the existing mapping output. Only modify Data if an adapter cannot satisfy the requirement.

Implement a deterministic, date-stamped routing snapshot consumed read-only by Execution.

The routing snapshot must:

- map canonical IDs to Kotak token, segment, and trading symbol
- include trading date and source provenance
- include a SHA-256 manifest
- reject stale, partial, duplicate, ambiguous, missing, or tampered mappings
- never guess a token or symbol
- fail with `NO ORDER` when the mapping cannot be proven
- remain routing-only and never introduce Kotak market-data ingestion into Shaurya

Add tests for expiry changes, stale dates, duplicate mappings, malformed masters, and hash tampering.

## Phase 4: Implement the C++20 execution core

Create a standalone C++20 Execution project.

Implement clear interfaces for:

- `BrokerAdapter`
- `PaperBrokerAdapter`
- dormant `KotakBrokerAdapter`
- `RiskEngine`
- `OrderStateMachine`
- `ExecutionLedger`
- `InstrumentResolver`
- `ExecutionSession`
- local strategy-to-executor IPC

The broker interface must support:

- place
- modify
- cancel
- query orders
- query trades and fills
- query positions
- session-health state

Use local Unix-domain IPC with a bounded protocol and strict peer and configuration validation. Prefer `SOCK_SEQPACKET` where supported and provide testable platform isolation.

Do not retain D51's strategy-specific four-slot `CE/PE x buy/sell` router. The working-order store must be generic and keyed by stable internal order ID and canonical instrument ID.

Implement:

- bounded queues
- explicit overflow safety stops
- generic multi-instrument order tracking
- partial-fill accumulation
- deduplication of broker updates
- out-of-order event handling
- cancel and replace race handling
- terminal-state validation
- no silent retry following an ambiguous broker submission
- no swallowed cancel failure
- explicit uncertain or reconciliation-required state
- configurable rate limits
- orderly shutdown
- fail-closed session loss
- kill switch
- cancel-all attempt with factual per-order outcomes
- no new order authority after a ledger or broker mismatch

The live Kotak implementation may contain harvested place, modify, cancel, and order-update parsing code, but:

- it must compile OFF by default
- normal builds must prove `live_router=off`
- shadow configuration must not construct a live router
- no configuration typo or environment variable may bypass the compile-time gate
- do not perform a real broker call

## Phase 5: Append-only ledger and recovery

Implement an authoritative append-only execution ledger.

Each record must contain:

- schema version
- strictly increasing sequence
- event ID
- session ID
- strategy, run, intent, and order correlation IDs
- event type
- timestamp
- non-secret payload
- previous-record hash
- current-record hash

Requirements:

- append semantics only
- durable flush policy
- strict replay
- truncated-tail detection
- tamper and hash-chain detection
- duplicate-event detection
- deterministic reconstruction of orders and positions
- no secret, session token, or order-authentication URL in ledger records
- explicit correction and reconciliation events instead of rewriting history

Startup sequence must be:

```text
validate ledger
   +
reconstruct local state
   +
obtain broker-authoritative orders, trades, and positions
   +
reconcile
   |
   |- exact agreement -> execution may become ready
   `- disagreement or unknown -> block orders and emit incident
```

For the shadow build, implement a deterministic broker simulator and reconciliation fixture. Specify the live query requirements but keep live disabled.

## Phase 6: Deterministic risk engine

Default-deny every intent.

Implement versioned rules for:

- valid current instrument mapping
- supported order type, product, and time-in-force
- session health
- intent expiry
- market-data freshness
- valid tick and lot quantity
- per-order size
- per-instrument position
- gross premium exposure
- inventory and Greek limits where supplied
- order-rate limit
- daily loss
- drawdown
- outstanding-order count
- duplicate or idempotent intent
- kill switch
- reconciliation state
- SELL availability for the exact instrument token

Every approval and rejection must produce a `RiskDecision` and ledger event.

Do not substitute a start-flat acknowledgement for broker-position reconciliation.

## Phase 7: Harvest and generalize the D51 Kotak workflow

Inspect the current `ayyararyan/D51_ALO_SMM_CPP` default branch and the installed Mac CLI only as references.

Harvest reusable components rather than copying the whole strategy:

- safe local `kotak` wrapper
- hidden TOTP prompt
- non-PTY batch SSH transport
- strict host-key handling
- local and remote locks
- helper and deployment attestation
- preflight
- one-shot watcher
- single-use in-memory session broker
- bounded deadlines
- factual terminal markers
- Kotak REST adapter
- order-update parser
- rate limiter
- shadow and live compile gate
- relevant hermetic operational tests

Do not bring into Shaurya Execution:

- D51 surface fitting
- D51 policy or model
- strategy-specific feature state
- strategy-specific SFeed market-data logic
- fixed call and put working-order slots
- D51-specific filenames, tags, service names, or paths

Preserve D51's current safe `shadow-launch` behaviour as a backward-compatible alias while introducing the Shaurya command.

## Phase 8: Make `kotak` portable across Macs

The canonical CLI source and distribution must live under Shaurya Execution.

Implement these commands:

- `kotak help`
- `kotak version`
- `kotak doctor`
- `kotak doctor --remote`
- `kotak auth`
- `kotak status`
- `kotak prepare`
- `kotak preflight`
- `kotak shaurya-shadow-launch`
- backward-compatible `kotak shadow-launch`
- `--dry-run` for every relevant operation

Requirements:

- `doctor` is local and offline by default.
- `doctor --remote` performs only one bounded read-only SSH compatibility check.
- Help, version, dry-run, malformed arguments, and missing confirmation must not contact the network.
- Stateful commands require exact confirmation tokens before network access.
- TOTP is entered through a hidden terminal prompt.
- TOTP must never appear in arguments, environment, files, logs, shell history, or output.
- Stable Kotak credentials remain on the protected remote host.
- No local Mac needs a Kotak API credential bundle.
- Local SSH identity provisioning is separate from the CLI package.
- Strict host verification is mandatory.
- Paths must use the installation prefix, `$HOME`, or XDG locations; there must be no `/Users/aryanayyar/...` dependency.
- Remote paths, service names, SSH target, expected commits, and compatibility versions belong in an exact-schema non-secret deployment manifest.
- CLI and helper hashes come from a signed or checksummed release manifest.
- Releases are reproducible and checksum-verifiable.
- Actual logs are mode 0600 and contain only non-secret markers.
- Local state and locks use `$XDG_STATE_HOME/kotak` or `$HOME/.local/state/kotak`.
- Non-secret configuration uses `$XDG_CONFIG_HOME/kotak` or `$HOME/.config/kotak`.
- Installation must not overwrite an existing version without validation and a recoverable previous-version path.

Add:

- a user-level installer
- an uninstaller that removes only files installed by the matching manifest
- a release-packaging script
- a manifest verifier
- a portability and restore runbook
- a `doctor` compatibility report

Do not run the installer against my real home directory. Test installation using temporary HOME and prefix directories.

Portability acceptance test:

```text
new temporary Mac-like HOME
  -> install exact release
  -> provision non-secret deployment-config fixture
  -> run `kotak doctor`
  -> verify CLI, helper, and manifest hashes
  -> run all dry-runs
  -> uninstall safely
```

Run this independently for at least two temporary HOME directories and prove that the installed hashes are identical.

## Phase 9: Operator and device auditability

Portability must not weaken auditability.

Create a non-secret operator and device identity contract.

A launch or session record should include:

- configured operator ID
- device ID
- SSH public-key fingerprint or another non-secret device-key fingerprint
- CLI release version and digest
- deployment-manifest digest
- executor commit and build digest
- requested mode
- confirmation type
- launch timestamp
- factual outcome

Never store private-key material or TOTP.

Include these fields in session-start ledger events and operational logs.

## Phase 10: D51 becomes client number one

Modify the D51 repository so its strategy emits Shaurya `OrderIntent` and consumes Shaurya execution events through the local IPC contract.

Requirements:

- D51 must not construct Kotak REST order requests.
- D51 keeps its surface, model, strategy, and research-specific code.
- Shaurya owns routing, risk approval, idempotency, order state, fills, positions, and the execution ledger.
- Add a compatibility flag for rollback during migration.
- The Shaurya client path must be the default for shadow integration once parity passes.
- Legacy in-process routing must remain live-disabled.
- Preserve the existing D51 shadow-fill semantics through an explicitly versioned paper-fill model, or prove and document any deliberate change.
- Add golden replay and parity fixtures comparing old and new selected intents, acknowledgements, partial and full fills, inventory, cancellations, and final reconstructed state.
- Never claim broker-confirmed fills in shadow mode.
- Update D51's documentation so the control-plane ownership is unambiguous.

## Test requirements

Add comprehensive automated tests before declaring completion.

### Contracts

- valid and invalid intents
- unknown and duplicate fields
- invalid enum and version
- expired intent
- price and tick overflow
- invalid quantities
- modify and cancel references
- schema round-trip

### State machine

- every legal transition
- every illegal transition
- partial fills
- repeated fills
- out-of-order updates
- rejection
- cancel and replace race
- ambiguous submit
- terminal-event replay

### Idempotency

- duplicate intent before submission
- duplicate after acknowledgement
- duplicate after fill
- retry after timeout
- restart and replay
- same payload with a different ID
- conflicting payload with the same ID

### Ledger

- append and replay
- hash-chain verification
- truncated tail
- tampered middle record
- duplicate sequence
- crash recovery
- position reconstruction
- reconciliation correction
- absence of secret-shaped fields

### Risk

- stale, missing, or tampered mapping
- stale market data
- invalid lot or tick
- position and exposure limits
- exact-token SELL protection
- rate limit
- loss and drawdown limit
- kill switch
- unreconciled startup
- shadow and live mode boundary

### Broker adapters

- place, modify, and cancel fixtures
- partial and complete fill parsing
- rejects
- HTTP errors
- malformed responses
- order-update queue overflow
- session loss
- cancel-all factual outcomes
- live compile gate OFF

### Operations and portability

Preserve and port the existing D51 operational suites covering:

- broker-session single-consume behaviour
- watcher-readiness failure
- malformed readiness
- authentication failure
- claim expiry
- duplicate or replayed launch
- interrupted transport
- result-transport failure
- start rejection
- secret non-disclosure
- no persistent broker or timer unit
- exact helper, process, cgroup, and hash binding

Also test:

- two temporary Mac installations
- clean uninstall
- update and rollback
- offline doctor
- bounded remote-doctor fixture
- host-key refusal
- manifest tampering
- wrong executor version
- operator and device audit fields
- absence of hard-coded personal paths

### Integration

- clean C++ Release build
- CTest suite
- Shaurya Data tests
- Shaurya Research tests
- Execution tests
- D51 tests
- D51-to-Shaurya shadow replay and parity test
- negative-control live launch must fail closed

Use `PYTHONDONTWRITEBYTECODE=1`. Keep dependency caches, bytecode, temporary build trees, and virtual environments out of Google Drive and the repositories. Use `/private/tmp` for ephemeral caches and builds.

Do not weaken tests merely to make them pass.

## Required documentation

Create or update:

- root Shaurya README
- `execution/README.md`
- `execution/EXECUTION_CONTROL_PLANE_SPEC.md`
- contract documentation
- order-lifecycle diagram
- ledger and recovery documentation
- risk-rule documentation
- threat model
- portable CLI installation guide
- new-Mac restore runbook
- shadow operations runbook
- D51 migration and parity report
- live-enablement checklist

The live checklist must retain these blockers:

- current endpoint, header, rate, and static-IP verification
- real-account order-update contract capture
- place, modify, cancel, and cancel-race reconciliation
- automatic startup order, trade, and position reconciliation
- exact-token SELL availability
- end-of-day inventory policy
- network and order-stream loss handling
- daily loss, drawdown, exposure, and Greek hard kills
- one-lot non-strategy harness
- contract-note reconciliation
- separate explicit live build and operator authorization

## Definition of done

Do not call the work complete unless:

1. Shaurya has an independently buildable and testable `execution/` project.
2. The shared contracts are strict, versioned, and documented.
3. Instrument mapping is date-stamped and fail-closed.
4. The order state machine, risk engine, ledger, replay, and reconciliation work in shadow tests.
5. Live routing remains compiled OFF and negative controls prove it.
6. The portable `kotak` release installs identically in two temporary Mac environments.
7. `kotak doctor` verifies local compatibility without network by default.
8. The one-shot attested launch workflow and secret-handling guarantees remain intact.
9. D51 operates as the first shadow client through Shaurya Execution.
10. D51 parity tests pass, or every intentional difference is explicitly documented and approved; do not silently waive parity.
11. All relevant Shaurya and D51 tests pass.
12. No credentials, secrets, runtime data, caches, build outputs, or unrelated user changes are committed.
13. Documentation and traceability are complete.
14. Every intentional change is committed and pushed to GitHub.
15. `research/` has zero changes, and `data/` has zero changes unless a minimal, individually justified shared-contract exception was unavoidable. The final report must include a path-level diff audit confirming this.

## Git and GitHub completion

Use logical commits. A preferred sequence is:

### Shaurya

1. `docs: specify execution control plane`
2. `feat: add execution contracts and instrument routing`
3. `feat: add execution state machine risk and ledger`
4. `feat: add paper and dormant Kotak adapters`
5. `feat: add portable Kotak operator CLI`
6. `test: add execution and portability integration coverage`
7. `docs: add execution operations and recovery runbooks`

### D51

1. `feat: integrate Shaurya execution client`
2. `test: add Shaurya execution parity coverage`
3. `docs: document Shaurya control-plane migration`

Before every commit:

- inspect `git status`
- inspect staged diffs
- confirm that no secret-shaped or unrelated files are present
- run the relevant focused tests

Before pushing:

- run the complete required validation suite
- confirm that both worktrees are clean except for intentional committed changes
- scan tracked files for credentials and private keys
- inspect every commit's contents

Push:

- Shaurya branch `codex/shaurya-execution-control-plane`
- D51 branch `codex/shaurya-execution-client`

Use the verified GitHub remote. Do not force-push and do not push to `main`.

After pushing, verify with the remote that each branch head exactly matches the local commit. Do not merely assume that the push succeeded.

## Final report

Return a concise but evidence-backed completion report containing:

- what was implemented
- architecture and safety boundaries
- exact Shaurya branch and commit IDs
- exact D51 branch and commit IDs
- confirmation that the remote branch heads match
- tests run and exact outcomes
- skipped tests and reasons
- parity result
- portable CLI installation-test result
- confirmation that live routing remains disabled
- confirmation that no real broker or AWS action occurred
- a path-level audit of all changes under `data/` and `research/`
- an individual justification for every changed Data file, if any
- remaining live-enablement blockers
- links to the main specification, README, migration report, and runbooks

Do not stop at planning, partial scaffolding, uncommitted changes, or local-only commits. Continue until the shadow-safe implementation is complete, all required checks pass, and every intentional change has been committed and pushed to GitHub.
