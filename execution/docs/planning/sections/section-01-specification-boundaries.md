# Section 01 — Frozen specification, project boundary, and live-negative build

## Outcome

Create the independently configurable Shaurya Execution C++20 project and freeze the authority,
security, delivery, and traceability rules before adding order-processing behavior. This section
must leave a buildable test harness whose ordinary configuration proves that live routing is absent.
It must not add broker transport, place an order, access credentials, contact a remote host, install
anything into a real home directory, or modify `data/` or `research/`.

The starting Shaurya revision for path-level audits is
`bcb6dea02329f824c82488f29450af0dd0e826ca` on branch
`codex/shaurya-execution-control-plane`, based on `github/main`. Record the separately verified D51
starting revision and branch in the specification when that worktree is available; never copy a
stale identifier from prior notes.

## Dependencies and consumers

This is the first implementation section and has no code dependency on later sections. It freezes
interfaces and policies consumed by all later sections:

- Section 02 implements the contracts and routing seam within these boundaries.
- Sections 03–05 implement the executor without widening authority.
- Section 06 packages the operator CLI while retaining the same secret and live-negative rules.
- Section 07 modifies D51 only after the contract and IPC boundaries are stable.
- Section 08 validates the complete traceability matrix and protected-directory audit.

## Tests first

### Test files to create

- `execution/tests/cmake/live_gate_test.cmake`
- `execution/tests/cmake/project_layout_test.cmake`
- `execution/tests/policy/test_dependency_boundaries.py`
- `execution/tests/policy/test_spec_traceability.py`
- `execution/tests/policy/test_repository_hygiene.py`
- `execution/tests/policy/test_documented_boundaries.py`

Register the CMake scripts with CTest. Run the Python policy tests through a CTest entry that uses a
declared Python interpreter; it must not create a virtual environment, install packages, or access
the network during test execution. Python policy tests must use only the standard library.

### Required failing tests

Write these tests before the implementation that satisfies them:

1. **Default live gate:** configure a fresh out-of-tree Release build without flags and assert the
   generated build attestation states `live_router=off`.
2. **Explicit live refusal:** configure another fresh build with
   `-DSHAURYA_ENABLE_LIVE_ROUTER=ON`; configuration must fail with a stable diagnostic explaining
   that this implementation has no live authority. No target may be generated.
3. **No environment bypass:** set plausible environment variables such as
   `SHAURYA_ENABLE_LIVE_ROUTER`, `LIVE_ROUTER`, and `KOTAK_LIVE`; the ordinary configure result must
   remain OFF. Environment values are never build inputs.
4. **No network-capable linkage:** inspect the default target graph/link command and assert it has no
   HTTP, TLS, AWS, SSH, Dhan, or Kotak transport library. Later fixture-only Kotak parsing remains
   permitted, but live transport does not.
5. **Project isolation:** assert `execution/` has its own `CMakeLists.txt`, source/include/test/docs
   lanes, and an out-of-tree build. It must not depend on either Python package at runtime.
6. **Dependency direction:** parse Python imports under `data/` and `research/`; neither may import
   `shaurya.execution` or files under `execution/`. Parse Execution build/source references and
   reject imports or links to Data/Research runtime code. Allow exactly one exception: the offline
   routing exporter may import Data's public `shaurya.contracts` and `shaurya.data` facades.
7. **Protected paths:** compare the working tree to the recorded Shaurya start commit and assert this
   section changed no path under `data/` or `research/`.
8. **Traceability completeness:** parse the specification table and require at least one stable
   requirement for every prefix `EXE-BND`, `EXE-CON`, `EXE-INS`, `EXE-IDM`, `EXE-FSM`, `EXE-RSK`,
   `EXE-LED`, `EXE-REC`, `EXE-OPS`, `EXE-PORT`, `EXE-SEC`, `EXE-SHD`, `EXE-LIVE`, and `EXE-D51`.
   Reject duplicate IDs, unknown status values, missing implementation/test evidence fields, and a
   row marked complete without both implementation and passing-test evidence.
9. **Facts versus decisions:** require separate machine-detectable headings for verified facts,
   design decisions, unresolved live blockers, and prohibited actions.
10. **Documentation boundary:** assert the root README describes three independent projects only
    after the Execution CMake target and boundary tests exist. It must state the exact permitted
    dependency directions and that Research has no broker or order authority.
11. **Repository hygiene:** reject tracked credentials, private-key/TOTP material, runtime state,
    logs, ledgers, generated manifests, local build output, caches, or absolute personal paths in
    Execution source and documentation, except explicitly marked historical input paths in the
    frozen specification.
12. **Threat/live checklist:** require every live-enablement blocker listed below to remain open.
    No test or documentation edit may silently convert an open blocker to satisfied.

### Initial verification commands

Use an external build directory; do not build inside the repository:

```bash
cmake -S execution -B /private/tmp/shaurya-execution-build \
  -DCMAKE_BUILD_TYPE=Release \
  -DSHAURYA_ENABLE_LIVE_ROUTER=OFF
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build --output-on-failure
```

The explicit negative configuration is a passing test only when CMake exits nonzero:

```bash
cmake -S execution -B /private/tmp/shaurya-execution-live-negative \
  -DCMAKE_BUILD_TYPE=Release \
  -DSHAURYA_ENABLE_LIVE_ROUTER=ON
```

If CMake/CTest is absent on the host, record that as a tool prerequisite; do not place a compiler or
dependency cache in the repository or Google Drive. Installing build tooling is outside this
section's code changes.

## Project files and build contract

Create this minimum tracked structure:

- `execution/CMakeLists.txt`
- `execution/cmake/ShauryaBuildOptions.cmake`
- `execution/cmake/ShauryaWarnings.cmake`
- `execution/include/shaurya/execution/build_attestation.hpp.in`
- `execution/src/build_attestation.cpp`
- `execution/tests/CMakeLists.txt`
- `execution/docs/` for the specification and security documents listed below
- `execution/contracts/`, `execution/ledger/`, and `execution/ops/` as source/fixture lanes, not
  runtime-output directories

The CMake project must:

- require CMake at a documented, tested minimum version and compile as C++20 with extensions off;
- default to Release-safe warnings and register CTest without running package installation;
- keep all generated headers, test fixtures, binaries, and reports under the selected build tree;
- make warnings-as-errors an explicit developer/CI option, not a source portability hazard;
- avoid `FetchContent`, package downloads, and network activity during configure/build/test;
- expose `SHAURYA_ENABLE_LIVE_ROUTER` only as a cache option defaulting to OFF, followed immediately
  by a fatal configuration error when true in this delivery;
- generate a non-secret build attestation containing project version, source revision supplied at
  configure time, compiler identity, build type, and the literal `live_router=off`;
- never consult environment variables for live authority;
- install nothing unless an explicit staging prefix is supplied. No test invokes install against
  the user's real home.

The ordinary target may initially be a small build-attestation library plus tests. Do not add a
fake broker interface merely to populate the project; later sections add concrete interfaces after
their tests define behavior.

## Frozen architecture and authority model

Write `execution/EXECUTION_CONTROL_PLANE_SPEC.md` as the binding specification. It must state the
following authority graph:

```text
Shaurya Data -> observed Dhan market data and immutable replay only
Shaurya Research -> consumes Data, produces research/strategy decisions, no order authority
Strategy client -> broker-neutral intents only
Shaurya Execution -> routing, risk, idempotency, FSM, reconciliation, ledger, session authority
Kotak adapter -> sole potential execution-broker edge; transport absent in ordinary builds
Operator `kotak` CLI -> launches/authorizes one session, never invoked per order
```

Permitted dependencies are exact:

- Data depends on neither Research nor Execution.
- Research may depend on Data's public catalogue/replay facade, never Execution.
- The Execution C++ runtime depends on neither Python project.
- An Execution-owned, offline routing exporter may import only Data's public instrument types and
  indexes and may emit an immutable file for read-only C++ consumption.
- D51 may depend on Execution wire/IPC contracts after Section 07; Execution never imports D51
  strategy logic.
- Kotak order/trade/position updates are execution evidence, never Shaurya market-data ingestion.

Separate two explicit sections in the specification:

- **Verified facts:** observed repository/build state, exact start revisions, existing Data mapping
  APIs, verified D51 reference behavior, and test evidence. Include date and evidence path.
- **Design decisions:** new contract choices, state semantics, risk precedence, IPC, packaging, and
  recovery policy. Each decision gets a stable identifier and rationale.

Never promote an assumption or a historical observation to a verified fact. Provider endpoints,
packet headers, remote targets, installed CLI state, AWS state, and remote commits are staleable and
must remain blockers until reverified in an explicitly authorized future workflow.

## Requirement and traceability format

Assign stable, never-reused IDs under all required prefixes. Each requirement row must contain:

| Field | Meaning |
|---|---|
| Requirement ID | Stable `EXE-<AREA>-NNN` identifier |
| Requirement | Normative, independently testable behavior |
| Authority | Verified user requirement or explicitly identified design decision |
| Implementation evidence | Exact source/document paths, initially `Pending` |
| Test evidence | Exact test name/path and result, initially `Pending` |
| Status | `Specified`, `Implemented`, `Tested`, `Blocked`, or `Live-unverified` |
| Notes | Safety qualifications and approved deviations only |

`Specified` is not completion. `Implemented` requires a path; `Tested` requires a passing named
test. `Blocked` and `Live-unverified` remain visibly incomplete. A parity difference cannot be
approved by editing this table; it requires later explicit user approval.

## Threat model and security policy

Create `execution/docs/THREAT_MODEL.md`. Enumerate assets, trust boundaries, threats, mitigations,
and verification for at least:

- credential/TOTP/private-key disclosure through arguments, environment, logs, ledger, crashes, or
  broker response bodies;
- an intent, update, or replay packet from an unauthorized local peer;
- duplicate, replayed, conflicting, oversized, or malformed messages;
- stale, partial, ambiguous, missing, or tampered routing data;
- same-ID/different-payload intent conflicts and ambiguous broker submission;
- ledger truncation, middle-record tampering, concurrent writers, rollback, or secret-shaped data;
- configuration typo, environment injection, symlink/path traversal, unsafe permissions, or
  manifest substitution;
- operator/device impersonation and attestation mismatch;
- queue overflow, disconnect, clock anomalies, stale observations, and process crash;
- accidental network, broker, AWS, or real-home activity during tests;
- supply-chain/network fetches during build or test.

The binding secret rule is handle-only: stable credentials remain outside both repositories;
credential directories are `0700`, credential files are `0600`, and secret values are never read
by tests, copied to artifacts, placed in JSON contracts, or written to logs or ledgers. Error paths
must allowlist factual markers rather than dumping broker or transport bodies.

## Shadow and live boundaries

Create `execution/docs/LIVE_ENABLEMENT_CHECKLIST.md` with every item open and a statement that this
branch cannot satisfy or waive them. At minimum include:

- current Kotak endpoints, headers, rate limits, static-IP rules, and authentication verified with
  separately authorized provider evidence;
- real-account order-update contract captured and fixture-tested;
- place/modify/cancel and cancel-race reconciliation verified;
- automatic startup order/trade/position reconciliation proven against broker authority;
- exact-token SELL availability and end-of-day inventory policy approved;
- network and order-stream loss handling verified;
- hard daily loss, drawdown, exposure, inventory, and Greek kills approved and tested;
- one-lot non-strategy harness completed under separate live authorization;
- contract-note reconciliation completed;
- separate live build/release process and explicit operator authorization approved.

Create `execution/docs/SHADOW_SAFETY.md` stating that shadow fills are simulated/proxy evidence,
never broker-confirmed; shadow needs no Kotak credential; ordinary builds cannot construct a live
router; and negative live invocation must fail before constructing a socket, HTTP client, broker
adapter, or authentication object.

## Root documentation and ignore policy

Update `README.md` minimally after the Execution project and boundary tests pass:

- describe `data/`, `research/`, and `execution/` as independently runnable projects;
- show the permitted dependency graph and the one offline routing-export exception;
- remove the sentence saying execution is outside the repository;
- retain prohibitions on tracked credentials, runtime state, and generated outputs;
- link to `execution/README.md`, initially containing build/test and safety-boundary instructions.

Review `.gitignore` without broad cleanup. Existing global ignores cover build output, logs, state,
secret-shaped files, and `*.jsonl`. Add only narrowly scoped rules needed for Execution runtime
lanes. If versioned JSONL fixtures are later required, add exact fixture-path negations rather than
unignoring JSONL repository-wide.

## Completion criteria

This section is complete only when:

- the default out-of-tree C++20 Release configuration builds and CTest passes;
- `SHAURYA_ENABLE_LIVE_ROUTER=ON` reliably fails configuration;
- every required specification prefix and traceability field exists;
- threat, shadow-safety, and open live-checklist documents exist and are tested structurally;
- the root README describes the implemented three-project boundary accurately;
- dependency scans permit only the offline exporter exception;
- `git diff --name-only bcb6dea02329f824c82488f29450af0dd0e826ca -- data research` is empty;
- no credentials, runtime output, caches, build directories, or unrelated changes are staged.

## Implemented result

Implemented the planned standalone CMake scaffold, build attestation, negative live gate, policy
tests, root boundary documentation, binding specification, threat model, shadow-safety document,
and open live checklist. The policy suite was hardened during review so Release/optimized execution
cannot remove checks, attestation fields reject injection, hygiene reads tracked/staged blobs only,
and the requirement table contains independently testable rows rather than umbrella placeholders.

Actual focused verification: Release configure/build passed and 11/11 CTests passed. The explicit
`SHAURYA_ENABLE_LIVE_ROUTER=ON` configure failed with the required stable refusal. The protected
`data/` and `research/` diff was empty. No planned source path moved; workflow state and generated
section prompts are ignored while the plan, TDD sections, and reviewable specification are tracked.
