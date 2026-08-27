# Section 08 — Integration, Documentation, Audit, and Delivery

## Purpose and entry conditions

This is the release gate for the shadow-safe Shaurya Execution control plane and its first D51 client. Begin only after Sections 01–07 are implemented and their focused tests pass. The two delivery branches are exactly:

- Shaurya: `codex/shaurya-execution-control-plane`
- D51: `codex/shaurya-execution-client`

This section does not add execution behavior. It proves the combined system, completes operator and engineering documentation, audits repository boundaries, creates logical commits, pushes only the two named branches to their verified GitHub remotes without force, and confirms that each remote head equals its local head.

All validation is hermetic. Do not authenticate to a broker, contact AWS, run a real SSH command, install into the real home or system prefix, start a real service, or place/modify/cancel an order. Use `PYTHONDONTWRITEBYTECODE=1`; keep build trees, virtual environments, dependency caches, installer homes, generated reports, and test runtime data under `/private/tmp`, not in either repository or Google Drive.

## Tests and audits first

### Clean Execution validation

Delete only a task-specific build directory under `/private/tmp`, configure a fresh Release build with live routing disabled and tests enabled, build, and run CTest with failure output. Use the project-supported options established earlier; the canonical build location is `/private/tmp/shaurya-execution-build`.

The negative control must configure a separate `/private/tmp/shaurya-execution-live-refusal` tree with live routing requested and assert that configuration fails before any broker, socket, or network-capable object is constructed. A successful live-enabled configuration is a release-blocking failure.

Run the complete Execution Python and shell suites through their checked-in hermetic runners. They must cover contracts, routing, ledger/recovery, FSM, risk, reconciliation, PaperBroker, dormant Kotak fixtures, IPC, executor modes, portable CLI, installer/update/rollback/uninstall, watcher/broker behavior, and live-negative controls. Run shell syntax checks and Python tests with bytecode disabled. No validation script may install dependencies implicitly.

Create `execution/scripts/validate_integration.sh` as the single documented orchestration entrypoint. It must use explicit repository roots, fail on the first failed gate, preserve each command's exit status, print concise non-secret stage markers, and write an optional machine-readable summary only to a caller-selected path under `/private/tmp`. It must invoke existing focused runners rather than duplicate their test logic.

### Protected Data and Research regression suites

Use isolated uv environments and caches:

```text
PYTHONDONTWRITEBYTECODE=1
UV_CACHE_DIR=/private/tmp/shaurya-uv-cache
UV_PROJECT_ENVIRONMENT=/private/tmp/shaurya-data-venv
uv sync --project data --extra dev --frozen
uv run --project data pytest
uv run --project data ruff check .
uv run --project data mypy

UV_PROJECT_ENVIRONMENT=/private/tmp/shaurya-research-venv
uv sync --project research --extra dev --frozen
uv run --project research pytest
uv run --project research ruff check .
uv run --project research mypy
```

Do not update either lockfile. A failure is investigated in the additive Execution/D51 changes; do not weaken or edit protected subsystem tests to obtain a pass.

### D51 regression and parity suites

Build D51 from a clean `/private/tmp/d51-shaurya-client-build` directory with live routing OFF and tests ON. Run its complete CTest suite, Python preparation tests, broker tests, watcher tests, composite shadow-launch tests, and the D51-to-Shaurya parity suite. The parity result must report zero semantic mismatches and identify the D51 commit, Shaurya protocol digest, PaperBroker model version, and fixture-manifest digest.

Run a separate live-enabled D51 configuration attempt and require refusal. Prove both the Shaurya backend and explicit `--legacy-execution` rollback remain unable to construct a live router. If parity has any mismatch, keep `legacy-shadow` as the D51 default, mark delivery incomplete, and report exact fixture/field differences; do not waive or normalize them away.

### Portability and operational safety

Run the portable release install suite twice using two independently created temporary Mac-like homes and prefixes under `/private/tmp`. Assert byte-for-byte identical installed-file hashes and deterministic manifest metadata. Each installation must pass offline `kotak help`, `version`, `doctor`, every dry-run, update, rollback, and manifest-scoped uninstall. Verify clean restoration of pre-existing files and complete removal of only installer-owned files.

Run fixture-backed tests for one bounded remote doctor, host-key refusal, wrong executor version, manifest tampering, concurrent update, traversal, symlink replacement, owner/mode drift, watcher readiness and malformed readiness, auth failure on the explicit legacy route, claim expiry, duplicate/replay, interrupted/result transport, start rejection, single consume, exact peer/process/hash binding, secret non-disclosure, and absence of persistent broker/timer units. Assert the SSH fixture is invoked exactly once for `doctor --remote`; no real SSH executable or remote alias may be reached.

### Repository audits

Add `execution/scripts/audit_release.sh` and run it against the tracked files of both worktrees. It must fail on:

- credentials, private keys, six-digit TOTP fixtures outside clearly synthetic test generators, session tokens, or secret-bearing environment files;
- response-body logging or unsanitized broker/network error text;
- personal absolute paths, real home paths, mutable remote runtime values, or undocumented host-specific constants outside the exact-schema deployment manifest;
- tracked `.env`, `.pyc`, `__pycache__`, `.venv`, build, cache, log, state, stats, ledger, socket, installer-output, or runtime files;
- imports from Data or Research into the Execution C++ runtime, imports from Execution into Data/Research, Research imports of Execution, or any cross-project dependency other than the Execution-owned offline routing exporter calling Data's public instrument API;
- an executable live transport in an ordinary build;
- tests that can invoke real network, broker, AWS, SSH, system installation, dependency installation, or real-home targets.

Record the exact Shaurya starting commit in `execution/docs/BUILD_PROVENANCE.json`. Audit paths with `git diff --name-only <recorded-start>...HEAD -- data research` and require no output. Also inspect staged and untracked paths. Research must have zero changes. Data must have zero changes unless the previously authorized minimal shared-contract exception was unavoidable; any such file requires an individual technical justification and full Data regression evidence. Without that authorization, any Data path blocks delivery.

Run `git diff --check`, tracked-file secret/runtime scans, and dependency-direction scans in both repositories. Confirm the original unrelated worktrees were never staged, stashed, reset, cleaned, or included.

## Required documentation

Create or complete these Shaurya files with commands verified against the final binaries and scripts:

- root `README.md` — three independent projects and the exact permitted dependency graph;
- `execution/README.md` — build, fixture replay, ledger verification, local shadow IPC, and safe operator entrypoints;
- `execution/EXECUTION_CONTROL_PLANE_SPEC.md` — frozen EXE-BND, CON, INS, IDM, FSM, RSK, LED, REC, OPS, PORT, SEC, SHD, LIVE, and D51 requirements;
- `execution/docs/CONTRACTS.md` — schema versions, canonical units/UUIDs/instruments, packet bounds, fingerprints, and conformance corpus;
- `execution/docs/ORDER_LIFECYCLE.md` — lifecycle and cancel/replace/ambiguous-submit diagram plus transition rules;
- `execution/docs/LEDGER_AND_RECOVERY.md` — append ordering, verification, replay, truncated-tail refusal, evidence-preserving repair, and reconciliation corrections;
- `execution/docs/RISK_RULES.md` — ordered default-deny rules, inputs, precedence, decisions, limits, and safety-stop behavior;
- `execution/docs/THREAT_MODEL.md` — assets, trust boundaries, attackers, credential/session handling, IPC and installer threats, mitigations, and residual risk;
- `execution/docs/INSTALL.md` — package verification, prefix/user install, offline doctor, update, rollback, and scoped uninstall;
- `execution/docs/RESTORE_NEW_MAC.md` — clean-machine restore using a verified package, two-device identity setup, no credential copying, and validation;
- `execution/docs/SHADOW_OPERATIONS.md` — prepare, preflight, `shaurya-shadow-launch`, readiness, status, shutdown, incident, ledger verification, and rollback procedures;
- `execution/docs/D51_MIGRATION_PARITY.md` — adapter boundary, fixture identities, exact parity outcome, rollback flag, and any approved semantic difference;
- `execution/docs/LIVE_ENABLEMENT_CHECKLIST.md` — explicit blockers; it must state that this release is not live-ready;
- `execution/docs/REQUIREMENTS_TRACEABILITY.md` — every frozen requirement mapped to implementation paths, test names, and final pass evidence;
- `execution/docs/VERIFICATION_REPORT.md` — dated commands, exact outcomes, audit results, parity/install evidence, skipped checks, and reasons.

The live checklist must retain current endpoint/header/rate/static-IP verification, real-account order-update capture, place/modify/cancel/cancel-race reconciliation, automatic startup order/trade/position reconciliation, exact-token SELL availability, end-of-day inventory policy, network/order-stream loss handling, loss/drawdown/exposure/Greek hard kills, a separate one-lot non-strategy harness, contract-note reconciliation, and a separate explicit live build plus operator authorization.

Documentation must distinguish verified facts from future work. Every command shown must be executed exactly or be labelled illustrative. No document may imply that fixture-backed testing contacted a broker or AWS.

## Commit and delivery procedure

Before each commit, inspect `git status --short`, the staged path list, `git diff --cached --check`, and the complete staged diff; run focused tests and the staged-content secret/runtime scan. Stage only explicit intended paths, never broad unrelated changes.

Use logical commits. Preferred Shaurya subjects are:

1. `docs: specify execution control plane`
2. `feat: add execution contracts and instrument routing`
3. `feat: add execution state machine risk and ledger`
4. `feat: add paper and dormant Kotak adapters`
5. `feat: add portable Kotak operator CLI`
6. `test: add execution and portability integration coverage`
7. `docs: add execution operations and recovery runbooks`

Preferred D51 subjects are:

1. `feat: integrate Shaurya execution client`
2. `test: add Shaurya execution parity coverage`
3. `docs: document Shaurya control-plane migration`

After all commits, rerun the full integration command and audits from clean trees. Revalidate that Shaurya's GitHub remote is the intended `ayyararyan/Shaurya` repository and D51's is `ayyararyan/D51_ALO_SMM_CPP`; do not rely on a remembered remote name or URL. Push only `codex/shaurya-execution-control-plane` and `codex/shaurya-execution-client`, never `main`, and never force-push.

After each push, query the corresponding remote branch with `git ls-remote --heads`, compare the returned object ID byte-for-byte with local `git rev-parse HEAD`, and record both values in the verification report. A successful push message without this comparison is insufficient. Finish with both local worktrees clean.

## Completion report and release gate

Report: implemented architecture and safety boundaries; exact local and matching remote branch heads; every test command and outcome; skipped checks and reasons; zero-mismatch parity identity; two-install hash comparison and uninstall outcome; live-routing refusal evidence; confirmation that no real broker/AWS/SSH action occurred; path-level Data/Research audit and any individually justified Data exception; documentation links; and remaining live-enablement blockers.

Do not declare completion while any test, audit, parity scenario, documentation command, traceability row, push, remote-head comparison, or clean-tree check is incomplete. Local-only commits, partial scaffolding, unverified remote state, or a nonzero protected-directory diff are not completion.
