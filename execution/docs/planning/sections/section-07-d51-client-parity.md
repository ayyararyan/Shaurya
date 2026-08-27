# Section 07 — D51 Client Migration and Exact Shadow Parity

## Purpose and safety boundary

This section changes the separate D51 ALO-SMM branch so that D51 acts as a strategy client of the Shaurya executor. D51 continues to own option selection, surface fitting, online models, policy decisions, quote selection, and research outputs. Shaurya owns execution contracts, IPC, routing resolution, risk, order lifecycle, paper fills, reconciliation, and the authoritative execution ledger.

The migration is shadow-only. It must not add a broker credential to D51, call a Kotak order endpoint, or weaken the existing compile-time live-routing refusal. The existing authenticated SFeed research route remains available only as an explicit rollback path. Shaurya may become the default shadow execution route only after the complete parity suite below passes with no unexplained mismatch.

Work in the clean D51 worktree and branch designated for this migration. Do not modify the Shaurya Data or Research projects. This section depends on the frozen contracts and routing outputs from Section 02, the paper-broker/event semantics from Section 04, and the bounded strategy/observation IPC from Section 05. Those interfaces must be stable before this work begins.

## Tests first

Add the following tests before production changes and register the native executables with D51's `CMakeLists.txt`. All tests must be hermetic: use temporary directories, Unix-socket fixtures or in-process transports, frozen clocks and UUID sources, and fixture packets. They must never contact Kotak, Dhan, AWS, SSH, DNS, or the public network.

### Contract conversion and client-state tests

Create `tests/test_shaurya_client.cpp` for the neutral client and conversion boundary.

Cover these cases:

- Convert an enabled D51 BUY quote and an inventory-authorized SELL quote into the frozen OrderIntent schema. Assert lowercase canonical UUIDs; the canonical instrument from the MarketObservation; `place`; BUY/SELL; positive exchange-unit quantity; positive paise price; `NRML`; `DAY`; creation/expiry timestamps; run/session correlation; and absence of broker token, broker symbol, credentials, floating-point price, D51 Greeks, model scores, and transport metadata.
- Convert price to integer paise deterministically. Reject non-finite, non-positive, overflowed, non-tick-aligned, or lossy values rather than rounding an ambiguous value. Quantity is the exact exchange-unit quantity derived from whole D51 lots and must pass the observation/routing lot size.
- Do not invent a canonical instrument from a D51 trading symbol or token. The selected action must retain the canonical identity and routing-date provenance from the observation that produced it. A missing, stale, or mismatched observation produces no intent.
- Convert quote withdrawal or replacement to canonical cancel/modify semantics using the previously correlated Shaurya internal-order ID. Cancel forbids price and quantity. Modify requires the target ID. A token/canonical-instrument change cancels the old order and creates a distinct place intent; it never modifies an order into another instrument.
- Generate a new intent ID for every genuinely new request. Replaying the same pending request after a reconnect retains its original ID and fingerprint. Reusing an ID with a different payload triggers a local safety incident and no send.
- Decode and correlate ACK, REJECT, working, partial fill, complete fill, cancel-pending, cancelled, ambiguous-submission, reconciliation, incident, and safety-stop ExecutionEvents. Unknown versions, fields, enums, IDs, instruments, impossible transitions, and malformed or oversized packets fail closed.
- Apply cumulative fills by positive delta only. Repeated or out-of-order cumulative quantities are idempotent; decreasing quantity, overfill, wrong side/instrument, or a fill for an unknown order triggers safety stop. Pass only validated fill deltas to D51 inventory accounting.
- Preserve exact-token long-only inventory. Owning one CE/PE or strike never authorizes a SELL for another token/canonical instrument. Partial and final SELL fills cannot take the exact instrument below zero.
- Exercise bounded outbound/inbound queues, write backpressure, peer disconnect, session expiry, response timeout, reconnect replay, and correlation loss. Overflow or unresolvable state must stop new intents and request reconciliation; it must never drop, guess, or automatically resubmit an ambiguous request.
- Verify the rollback selector. The Shaurya backend and legacy backend are mutually exclusive for one run, the selected backend is recorded factually, an unknown value refuses startup, and a backend cannot change while a session is active.

### Frozen cross-path parity replay

Create `tests/test_shaurya_parity.cpp`, `tests/fixtures/shaurya_parity/`, and a small test-only replay harness. Fixtures are immutable, versioned, deterministically ordered, and covered by `tests/fixtures/shaurya_parity/MANIFEST.sha256`. Each scenario contains the input observations, frozen D51 selected actions, legacy normalized outcomes, Shaurya request/event packets, and expected terminal state. Do not place credentials, real account identifiers, private paths, or captured private broker payloads in fixtures.

At minimum include:

1. no eligible quote and no order;
2. one BUY place and ACK with no fill;
3. conservative post-placement trade/cross causing a partial then full paper fill;
4. repeated and out-of-order fill events that remain idempotent;
5. quote replacement on the same instrument;
6. cancellation before fill and cancellation racing with a partial fill;
7. ATM/token change requiring cancel then a new place;
8. exact-token inventory preventing an unauthorized SELL;
9. authorized SELL reducing only the matching position;
10. reject, ambiguous submission, IPC loss, and safety-stop cases;
11. restart/replay followed by exact reconciliation;
12. market/session cutoff with factual terminal state.

For every scenario run the frozen legacy shadow harness and the Shaurya client plus PaperBroker harness from the same normalized inputs. Compare, in deterministic sequence order:

- selected canonical intents and intent fingerprints;
- ACK/REJECT and internal-order correlation;
- partial and full fills, including cumulative and delta quantities;
- cancel/replace requests and terminal order states;
- exact-token inventory after every event;
- incidents, safety-stop state, and final reconstructed orders/positions.

Exclude only transport-envelope fields declared non-semantic by the frozen contract, such as fixture-assigned packet sequence or receive timestamp. Keep an explicit allowlist of those exclusions in the test harness. Do not normalize away action, price, quantity, instrument, event order, fill evidence, inventory, or terminal-state differences.

Write a machine-readable parity result to the test build directory, never the source tree. It must contain fixture-manifest digest, D51 commit, Shaurya protocol/schema digest, PaperBroker model version, scenario count, mismatch count, and pass/fail. A mismatch count greater than zero fails CTest and prevents the default-backend assertion from passing. There is no waiver flag. An intentional semantic difference requires explicit approval in a later user request and a newly frozen expected fixture; this implementation cannot infer approval.

### Live-negative and dependency tests

Extend the existing negative controls to prove:

- configuring D51 with `ALO_ENABLE_LIVE_ROUTER=ON` still fails at CMake configuration;
- the Shaurya client accepts only the shadow protocol/mode and refuses live session metadata before constructing a transport;
- the explicit legacy backend cannot instantiate `KotakRestClient`, `OrderRouter`, or `OrderUpdateClient` for order execution and remains live-disabled;
- ordinary Shaurya-shadow tests run successfully with all Kotak credential variables unset;
- no new D51 source builds a Kotak place/modify/cancel request, imports Shaurya Data/Research, or reads their runtime directories;
- parity fixtures and tests contain no secret-like values, response bodies, personal absolute paths, or mutable runtime artifacts.

Keep the existing D51 native and operational suites passing. In particular, retain the long-only, SFeed decoder, shadow-session, watcher, broker, and composite-launch coverage as regression tests for the rollback path.

## Client library and adapter boundary

Add these D51-owned files:

- `include/alosmm/shaurya_client.hpp` — public shadow client, backend-neutral callbacks, connection/readiness state, and bounded queue interface;
- `src/shaurya_client.cpp` — strict contract codec use, bounded IPC, reconnect/replay, correlation, and event dispatch;
- `include/alosmm/execution_adapter.hpp` — D51 quote-action to neutral intent adapter and execution-event to validated fill/event adapter;
- `src/execution_adapter.cpp` — deterministic unit conversion and D51-side correlation state;
- `tests/test_shaurya_client.cpp` and `tests/test_shaurya_parity.cpp`;
- `tests/fixtures/shaurya_parity/` and its SHA-256 manifest.

Use the contract version, enum values, field names, packet bound, canonical serializer, and fixture digest frozen by Shaurya. D51 may vendor only the small client-facing contract/codec artifact needed to compile independently; record its upstream schema digest and verify it against the shared conformance corpus in CTest. Do not copy the Shaurya executor, ledger, risk engine, routing resolver, broker adapters, or paper-fill engine into D51.

The public interface should expose intent submission and event delivery without exposing broker concepts. Signatures may use stubs such as `submit(const NeutralIntent&)`, `poll_event()`, `reconcile()`, and `stop()`, but the implementation must preserve these invariants:

- one D51 strategy thread remains the sole owner of model and simulated/observed inventory state;
- the client transport thread owns socket I/O only and communicates through bounded queues;
- readiness is false until the Shaurya executor has attested configuration/routing, replayed its ledger, reconciled its paper snapshot, validated the D51 peer, and delivered a fresh observation;
- loss of readiness prevents new quote intents immediately;
- execution events are applied on the D51 state-owner thread in authoritative sequence order;
- reconnect sends only protocol replay/correlation requests and never reconstructs or guesses an order from local quote state.

## D51 engine integration

Modify `include/alosmm/config.hpp`, `src/config.cpp`, `include/alosmm/engine.hpp`, `src/engine.cpp`, `include/alosmm/types.hpp`, `src/main.cpp`, and `CMakeLists.txt` only as required to insert the adapter cleanly.

Introduce a validated execution-backend setting with exactly `shaurya` and `legacy-shadow`. Also expose an explicit command-line rollback flag, `--legacy-execution`, which may select `legacy-shadow` only in shadow mode. Reject the flag in live/replay modes, reject conflicting configuration/CLI selections, print the chosen non-secret backend in startup provenance, and never allow a runtime switch.

Migration occurs in two reviewable stages:

1. Add the Shaurya client and parity suite while `legacy-shadow` remains the configured default.
2. After all frozen parity scenarios pass, change the checked-in shadow example/default to `shaurya` in the same reviewed change that records the passing fixture-manifest and protocol digests. The `--legacy-execution` flag remains available for bounded rollback.

For the Shaurya backend:

- consume Shaurya MarketObservation packets instead of constructing market observations from the legacy authenticated feed inside the execution path;
- retain D51's existing book/surface/model/policy decision cycle unchanged behind the observation adapter;
- carry the observation's canonical instrument identity into each selected quote action;
- submit enabled quote actions, replacements, and withdrawals through `ExecutionAdapter`;
- consume correlated ExecutionEvents and apply only validated fill deltas to the existing exact-token inventory logic;
- treat Shaurya's ledger/FSM state as execution authority and D51's model/inventory view as a checked projection;
- on disagreement, stop submitting, emit a non-secret incident, and require Shaurya reconciliation;
- do not invoke `submit_live`, `KotakRestClient`, `OrderRouter`, or the order-update WebSocket.

For `legacy-shadow`, preserve the current authenticated SFeed and D51 counterfactual/shadow-fill research behavior without enabling broker orders. Isolate it behind the backend interface so Shaurya code cannot accidentally fall through to legacy authentication. The existing compile-time live gate remains unconditional.

D51 research artifacts may retain strategy decisions, model features, and normalized execution correlations, but broker credentials, raw session packets, response bodies, and private account fields must never be written. Add run/session IDs, selected backend, protocol digest, parity-fixture digest, and Shaurya ledger/session correlation to non-secret run provenance.

## Operator compatibility and rollback

Do not reimplement the portable operator control plane in D51. Consume the installed Shaurya `kotak` command contract produced by Section 06.

The canonical command is:

```text
kotak shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH
```

In the Shaurya release, this has the syntax-compatible alias:

```text
kotak shadow-launch --confirm SHAURYA_SHADOW_LAUNCH
```

Both commands are no-broker-auth shadow launches with identical exit codes and allowlisted marker grammar. D51 tests must verify compatibility against the hermetic CLI fixture, not a real remote host.

Retain D51's existing authenticated feed-only composite launch behind an explicit `legacy-shadow-launch` route with an unambiguous legacy confirmation token and marker naming. It must remain shadow-only and live-disabled. Do not silently redirect a legacy invocation, reuse the Shaurya confirmation token for the authenticated path, or make `auth` implicit in the Shaurya launch. Document the rollback command in D51's operator help and identify it as temporary migration support.

Rollback changes only which D51 observation/execution adapter is selected for a new stopped session. It does not rewrite the Shaurya ledger, mutate routing snapshots, reuse an in-flight session, or translate open orders between backends. Refuse rollback while either backend reports an active or unreconciled session. The operator must end the current session factually and start a new explicitly selected session.

## Completion criteria

This section is complete only when all of the following are true:

- the new D51 client compiles independently against the pinned Shaurya client contract;
- conversion, event-correlation, exact-token inventory, backpressure, reconnect, rollback, and live-negative tests pass;
- every frozen parity scenario produces zero semantic mismatches;
- the parity result records the exact fixture, protocol, PaperBroker, and commit identities;
- Shaurya is the checked-in default shadow backend and `--legacy-execution` remains an explicit rollback;
- both paths remain incapable of live routing;
- ordinary Shaurya shadow runs require no Kotak credential;
- the legacy SFeed research path and its regression tests remain intact;
- no strategy, model, surface, or research code has moved into Shaurya;
- `git diff` in the Shaurya Data and Research projects is empty.

If any parity mismatch remains, leave `legacy-shadow` as the default, report the exact fixture and field-level differences, and mark this section incomplete. Do not weaken the comparator or claim migration completion.
