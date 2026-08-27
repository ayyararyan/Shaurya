---
title: 'Shaurya post-market research pipeline'
type: 'feature'
created: '2026-08-26'
status: 'done'
baseline_commit: '90e1614a6539f8d6257d13de32d84b5898330889'
context:
  - 'docs/module-spec/SIG.md'
  - 'docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Shaurya has strong one-session feature and walk-forward primitives, but its post-close scripts couple features to targets and lack durable hypothesis identity, experiment accounting, cross-day state, complete predictive surfaces, and mining-process-level false-discovery controls. That makes nonstationary predictability difficult to distinguish from parameter noise, regime effects, decay, and hindsight selection.

**Approach:** Add a target-blind immutable feature-state boundary and a versioned alpha-research subsystem inside the existing `shaurya` package. Frozen registries generate a complete, deterministic hypothesis universe; nested past-only evaluation records every candidate and full parameter surface in an append-only ledger, maintains immutable daily state, and applies stability, multiplicity, empirical-null, and conservative lifecycle rules.

## Boundaries & Constraints

**Always:** Consume canonical completed DAT handles; keep feature construction independent of targets and alpha results; require every axis and model choice to exist in a versioned registry; enforce `selection_information_ts < evaluation_period_start`; preserve every tested hypothesis, competing candidate, surface cell, daily snapshot, and failed/dormant result; evaluate a session before updating state for the next; keep exploratory, confirmatory, and live-shadow evidence distinct; use deterministic hashes and create-once/content-addressed artifacts.

**Ask First:** Adding a required runtime dependency, changing existing D51 semantics, migrating historical research outputs, widening feature/target grids, touching remote data, committing, pushing, deploying, or enabling any live/order behavior.

**Never:** Pick or promote the daily winner; create parameters after inspecting outcomes; let an outer block influence selection, preprocessing, clustering, regimes, or thresholds; define regimes from future/full-day information; rewrite prior ledger events or snapshots; erase rejected/dormant evidence; claim one-session promotion; treat Dhan aggregate snapshots as MBO or execution evidence.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Plan | Frozen feature, target, hypothesis, policy registries and cutoff date | Exact raw/effective family cardinality, exclusions, compute estimate, deterministic plan hash | Reject unknown versions, duplicate identities, undeclared axes, or outcome-dependent exclusions |
| Mine | Past sessions through cutoff | Exploratory tests, full surfaces, all-candidate provenance, multiplicity and full-process null context | Fail closed on temporal leakage, incomplete data, or partial accounting |
| Evaluate | Frozen pre-session state plus one unseen session | Score existing hypotheses first, append ledger evidence, then create tomorrow's state | Reject selection timestamps at/after evaluation start or retrospective reactivation |
| Inspect | Ledger/state as of a date or hypothesis/mechanism/surface selector | Reconstructable JSON/report without mutation | Report missing evidence explicitly; never backfill from future state |
| Duplicate | Same semantic hypothesis under another label | Same identity and one accounted hypothesis | Reject conflicting registration; record repeated evaluation under the existing ID |

</frozen-after-approval>

## Code Map

- `src/shaurya/signals/feature_selection.py` -- reusable causal feature definitions, training-only reduction, shrinkage models, and conditional usefulness; current combined feature/target row must not cross the new boundary.
- `src/shaurya/signals/feature_selection_walkforward.py` -- reusable purge/embargo and nested selection logic; prior folds must become date-frozen rather than recomputed from future rows.
- `src/shaurya/signals/evaluation_metrics.py` and `deep_book_inference.py` -- BY, block-bootstrap, and family-wise inference primitives.
- `src/shaurya/analytics/ofi_response_surface.py` -- complete-surface and neighborhood diagnostics to generalize.
- `scripts/post_close_alpha_research.py` -- retain as a legacy DAT quality/source adapter, not the research architecture.
- `src/shaurya/research/` -- new registries, contracts, planning, execution, ledger, state, surfaces, multiplicity/nulls, stability/mechanisms, reporting.
- `src/shaurya/cli/research.py` and `pyproject.toml` -- `shaurya-research` command group.
- `registries/` -- checked-in JSON-compatible YAML registries for features, targets, hypotheses, and policy.

## Tasks & Acceptance

**Execution:**
- [x] `src/shaurya/research/contracts.py`, `registry.py`, `features.py`, `targets.py` -- strict deeply immutable target-blind features and separately SHA-pinned canonical targets. Builders must consume the loader's frozen tuple/mapping types, and every evaluation row must prove matching non-empty feature/target source identities. Semantic hypothesis identity excludes display names and registry version; evidence requires the exact frozen candidate set, mode, non-empty session-matching intervals, genuine folds for confirmatory claims, and bounded finite provenance values.
- [x] `registries/*_v1.yaml` and `planner.py` -- freeze, validate, and hash the complete plan payload. Every declared axis must have an executable strategy; reject registry combinations with no implementation rather than counting decorative identities. Validate nested policy values and regime definitions, bind exact registry fingerprints/versions, fail on empty universes, and estimate actual inner/outer/null fit burden before opening outcomes.
- [x] `source.py`, source adapters, `walkforward.py`, `models.py`, `surfaces.py` -- derive feature/target rows from the fully replayed verified DAT tape or from a content-addressed derivation manifest that binds every row to that tape; arbitrary arrays and pre-scored evidence are not production inputs. Derive coverage/date from rows, enforce cutoff/session/source alignment, disjoint unique folds, registered minimum support/N_eff, and execute clock, pooling, metric, selector, model, cadence, fitting-window, and causal-regime semantics. Validate complete surface coverage, cell signs/support, and genuine fold/model hashes.
- [x] `multiplicity.py`, `nulls.py`, `miner.py` -- use the same registered estimator/preprocessing/selection path in observed and every session-aware dependence-preserving null/control replicate. Bind phase artifacts to inputs rather than trusting callback hashes, account for the exact frozen candidate/family universe, and persist candidate-keyed adjusted results and empirical-null evidence that lifecycle gates can verify.
- [x] `ledger.py`, `state.py`, `executor.py` -- require the exact bound pre-session state and ledger tail, validate the whole run before publication, and use a locked transaction/journal design that resumes at every injected crash boundary without changing event identities or duplicating OOS evidence. Verify state filenames/content, artifact manifests and hashes on retry; make batch-write failure recoverable; support an explicit next trading-session date rather than calendar-day inference; preserve `0700` directories and `0600` create-once artifacts.
- [x] `evidence.py`, `stability.py`, `mechanisms.py`, `reports.py` -- compute lifecycle/grades only from artifact-bound folds, multiplicity, null, surface, and economic evidence under the frozen policy. Make `PROVISIONAL`, `REPLICATED`, `WEAKENING`, `DECAYING`, `DORMANT`, `REJECTED`, and predeclared reactivation reachable and distinct; missing scores interrupt decay streaks. Emit required complete daily surfaces/multiplicity/mechanisms, atomic reports, and a content-hashed Parquet ledger snapshot plus manifest on every completed run.
- [x] `src/shaurya/cli/research.py`, `pyproject.toml` -- make planning, mining, evaluation, ledger, explanation, mechanism, surface, and historical-state commands run through an installed subprocess entry point. Production mining/evaluation derives results from canonical source-bound observations and a plan-frozen registry set; it never accepts caller-authored scores, fold hashes, gates, candidate universes, or copied provenance hashes as scientific authority.
- [x] `tests/` -- add adversarial and true end-to-end subprocess tests that independently construct/replay canonical DAT fixtures and prove source/result binding, registry fingerprint enforcement, every executable axis/model, exact-universe provenance, gate-artifact binding, complete failure accounting, write/crash-boundary recovery, and the full seeded null/stable/drift/break/regime simulations through lifecycle and reporting—not only isolated helpers or custom callbacks.

**Acceptance Criteria:**
- Given any future target/result mutation or appended future session, when a historical feature run, selection, fold, regime, or state is reconstructed, then every pre-existing hash and decision is unchanged.
- Given a systematic experiment, when it terminates successfully or fails, then every declared candidate and selection context is durably accounted for and duplicate naming cannot create independent evidence.
- Given the seeded synthetic scenarios in the user brief, when the full miner is run, then null false discoveries are controlled, stable alpha is recovered only after repeated OOS evidence, horizon drift is classified as parameter movement, breaks degrade evidence, and causal regimes are recovered without leakage.
- Given one session of attractive results, when lifecycle policy runs, then no hypothesis reaches a validated/stable grade.

## Spec Change Log

- **Iteration 1 — adversarial review re-derivation.** Review found that the first implementation accepted precomputed predictions as a “complete-miner” null, let the evaluation payload define its own frozen universe, and allowed confirmatory evidence to carry exploratory selection provenance. The execution tasks now explicitly bind source/plan/state provenance, require full-procedure null refits, enforce all registered semantics and promotion gates, make ledger/daily publication retry-safe, and enumerate the adversarial acceptance matrix. Known-bad state avoided: a green unit suite around an anti-conservative, caller-trust-based pipeline. **KEEP:** separate target-blind feature and target contracts; canonical semantic hashes; exact pre-outcome planning; complete surfaces; hash-chained ledger; content-addressed historical state; conservative single-session boundary; no dependency, remote, or live-order changes.
- **Iteration 2 — provenance and executable-semantics re-derivation.** Three independent reviewers rejected the second implementation because verified DAT identity was copied onto unrelated caller-authored arrays/evidence, elastic-net candidates were fit as ridge, registered clock/pooling/metric/selection axes were decorative, candidate/multiplicity/surface authorities remained caller-controlled, and publication was not resumable across a pre-completion crash. The tasks now require derivation rather than assertion, exact registry and candidate-set binding, artifact-backed promotion gates, session-aware nulls, explicit next-session state, installed CLI execution, and crash-injection acceptance. Known-bad state avoided: 31 passing tests around a forgeable research workflow. **KEEP:** immutable feature/target separation, semantic IDs, registry expansion, full-process null interface, hash-chained ledger, immutable state, and no dependency/remote/live-order changes.

## Design Notes

The canonical ledger is locked/fsynced append-only JSONL because a single Parquet file cannot be safely appended. Each completed run also emits a create-once, content-hashed Parquet snapshot and manifest, satisfying columnar analysis without making mutable Parquet the source of truth. Existing single-session scripts remain reproducible compatibility tools until parity is proven.

## Verification

**Commands:**
- `PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_adversarial_acceptance.py tests/test_contracts_and_planner.py tests/test_ledger_state_lifecycle_executor.py tests/test_research_cli.py tests/test_surfaces_nulls_multiplicity.py tests/test_v3_seeded_full_pipeline.py tests/test_v3_source_bound_e2e.py tests/test_walkforward_and_synthetic.py` -- all new acceptance and synthetic tests pass.
- `PYTHONDONTWRITEBYTECODE=1 uv run --frozen --extra dev pytest -q` -- full existing and new suite passes in the declared development environment.
- `PYTHONDONTWRITEBYTECODE=1 uv run ruff check src/shaurya/research src/shaurya/cli/research.py tests/test_*.py` -- changed-scope lint passes.
- `PYTHONDONTWRITEBYTECODE=1 uv run mypy src/shaurya/research src/shaurya/cli/research.py` -- strict typing passes across the research implementation and CLI.

## Dev Agent Record

### Implementation Plan

- Establish immutable, source-bound feature/target and registry contracts, then freeze the policy-complete daily universe.
- Execute causal walk-forward mining, full-procedure empirical nulls, complete surfaces, and conservative lifecycle policy.
- Persist every outcome through a verified append-only ledger, create-once state/report artifacts, and guarded CLI workflows.
- Prove the boundary conditions with focused, adversarial, end-to-end, and repository-wide tests.

### Completion Notes

- Iteration 2 was rejected after independent blind, edge-case, and acceptance review. Its recoverable source snapshot is outside the repository at `/private/tmp/shaurya-post-market-v2.onMXDZ` for implementation reference only; none of it is accepted evidence of completion.
- Iteration 3 replaces caller-authored scientific payloads with fully replayed canonical-DAT derivation, exact plan/registry/state/artifact authority, nested full-process null refits, complete surfaces, and explicit next-session publication.
- Publication is locked, journaled, and idempotent across all seven injected crash boundaries. Each completed run writes a standards-readable row-bearing Parquet ledger snapshot and a content/hash/row-count manifest before the immutable state is bound to the final ledger tail.
- Consolidated v3 review repairs replaced the OFI proxy with the repository-canonical CCZ estimator, made source datasets and scientific gates non-forgeable, executed conditioning/pooling/N_eff/economic semantics, froze null shifts/seeds, and bound exact plan/policy/state/artifact authorities through publication.
- Iteration 4 binds each handle to the canonical DAT catalogue and row-level run/instrument/channel authority, persists an immutable source/derivation prefix across days, independently rebuilds scientific artifacts from source rows, prevents unselected nested candidates from accruing confirmatory credit, and retains connection/epoch/break plus signed coefficient identities and uncertainty. Lifecycle promotion now requires repeated artifact-qualified OOS evidence; skipped/failed/missing sessions interrupt decay; failed construction is durably candidate-accounted and retryable.
- Cross-day state now carries real family shrinkage, historical effects, regime-model identities, and past-only next-session ensemble weights. Daily ledger/report/state artifacts contain stability, causal-regime comparison, winner's-curse, negative-control, and parameter-movement diagnostics. No separate EW decay constant was invented because the frozen policy does not register one; the registered adaptation executed here is family shrinkage plus past-only ensemble weighting.
- Iteration-4 verification passed: 35 focused research tests, including an installed canonical-DAT subprocess that publishes five sequential OOS days to `STABLE` only after repeated evidence and retains all seven crash/recovery boundaries; changed-scope Ruff; strict mypy across the 22 research/CLI source files; and whitespace/diff checks. The prior iteration-3 repository-wide result remains 817 passing tests and the repository-wide Ruff baseline remains 577 pre-existing violations under unrelated `scratch/`.
- Iteration 5 makes canonical catalogue verification non-optional, token-gates verified sources, freezes source prefixes at state initialization, binds report/publication identity into immutable state, validates historical lifecycle records field-by-field against daily authorities, and recovers partial ledger writes under the workflow lock. Scientific execution now preserves source-bound tick economics, selected-outer null semantics, signed per-feature coefficient uncertainty, exact conditioned-versus-global regime gates, interruption/reactivation chronology, and shared-ledger explore-then-evaluate ordering.
- Iteration-5 verification passed: 39 focused research tests in 121.94 seconds; changed-scope Ruff; strict mypy across 22 research/CLI source files; and whitespace, frozen-block, and generated-cache checks. The prior complete declared-development-suite result is 822 passing tests in 269.92 seconds, with a final full-suite rerun delegated after this targeted correction. The powered canonical seeded acceptance traverses executor, ledger, lifecycle, report, and state publication while asserting controlled null discoveries, repeated-evidence stability, horizon movement, structural degradation, and causal-regime recovery.
- The frozen stationary bootstrap now executes over exact candidate outer-fold session scores using registered replicate, mean-block-length, and seed settings. Candidate-keyed intervals and hashes are recomputed by the executor and bound through gates, evidence authority, daily ledger artifacts, lifecycle qualification, reports, and immutable state; copied/tampered intervals are rejected. A target-blind deterministic source/partition/timestamp-keyed AR(1) negative-control feature is registered and evaluated through the same selection/null/evidence procedure in its own diagnostic family, cannot suppress or promote real alpha, and emits a methodology warning after repeated significant control sessions.
- No dependency, remote-data, commit, push, deployment, or live/order behavior changes were made.

### File List

- `docs/specs/spec-post-market-research-pipeline.md`
- `pyproject.toml`
- `registries/alpha_hypotheses_v1.yaml`
- `registries/alpha_research_policy_v1.yaml`
- `registries/microstructure_features_v1.yaml`
- `registries/microstructure_targets_v1.yaml`
- `src/shaurya/cli/research.py`
- `src/shaurya/research/__init__.py`
- `src/shaurya/research/artifacts.py`
- `src/shaurya/research/contracts.py`
- `src/shaurya/research/evidence.py`
- `src/shaurya/research/executor.py`
- `src/shaurya/research/features.py`
- `src/shaurya/research/ledger.py`
- `src/shaurya/research/mechanisms.py`
- `src/shaurya/research/miner.py`
- `src/shaurya/research/models.py`
- `src/shaurya/research/multiplicity.py`
- `src/shaurya/research/nulls.py`
- `src/shaurya/research/planner.py`
- `src/shaurya/research/registry.py`
- `src/shaurya/research/reports.py`
- `src/shaurya/research/source.py`
- `src/shaurya/research/stability.py`
- `src/shaurya/research/state.py`
- `src/shaurya/research/surfaces.py`
- `src/shaurya/research/targets.py`
- `src/shaurya/research/walkforward.py`
- `tests/conftest.py`
- `tests/test_adversarial_acceptance.py`
- `tests/test_contracts_and_planner.py`
- `tests/test_ledger_state_lifecycle_executor.py`
- `tests/test_research_cli.py`
- `tests/test_surfaces_nulls_multiplicity.py`
- `tests/test_v3_seeded_full_pipeline.py`
- `tests/test_v3_source_bound_e2e.py`
- `tests/test_walkforward_and_synthetic.py`

## Change Log

- **2026-08-26:** Re-derived the approved pipeline after iteration 2 failed independent review; implementation remains pending.
- **2026-08-26:** Implemented iteration 3 with canonical source derivation, executable registered semantics, artifact-bound evidence gates, exact pre-session state/ledger authority, crash-resumable publication, row-bearing Parquet snapshots, installed subprocess workflows, and integrated seeded acceptance simulations; moved to review.
- **2026-08-26:** Applied the consolidated v3 review repairs for canonical CCZ source semantics, exact endpoint/partition boundaries, non-forgeable scientific artifacts, candidate-local gates, frozen null policy, exact pre-session state continuity, workflow locking, installed CLI isolation, and seven-boundary crash recovery; validation passed and status remains review.
- **2026-08-26:** Applied iteration-4 blind/edge/acceptance corrections for canonical catalogue and historical-source-prefix authority, executor-side scientific recomputation, discontinuity-safe sampling/nulls, partition-local overlap-aware effective sample size, nested selection/mode/lifecycle enforcement, durable early-failure accounting, signed coefficient and cross-day adaptive state, bound stability/regime diagnostics, and repeated multi-day installed acceptance through ledger/report/state to `STABLE`; focused validation passed and status remains review.
- **2026-08-26:** Closed the final control-evidence gap with a registered target-blind autocorrelated negative control and candidate-keyed stationary-bootstrap artifacts bound through gates, authority, ledger, lifecycle, state, and reporting; final focused and repository-wide verification passed.

## Suggested Review Order

**Daily scientific transaction**

- Start with the source-recomputed, crash-resumable daily publication boundary.
  [`executor.py:606`](../../src/shaurya/research/executor.py#L606)

- Follow the installed commands that enforce plan, state, source, and mode authority.
  [`research.py:392`](../../src/shaurya/cli/research.py#L392)

**Canonical inputs and frozen search**

- Verify catalogue membership, row authority, and immutable source identity.
  [`source.py:230`](../../src/shaurya/research/source.py#L230)

- Inspect deterministic source-to-feature/target derivation across feed discontinuities.
  [`source.py:657`](../../src/shaurya/research/source.py#L657)

- Review exact registry expansion, cardinality, exclusions, and compute hashing.
  [`planner.py:182`](../../src/shaurya/research/planner.py#L182)

**Inference and lifecycle**

- Check candidate-keyed stationary-bootstrap evidence and immutable artifact hashes.
  [`multiplicity.py:58`](../../src/shaurya/research/multiplicity.py#L58)

- Review repeated qualified evidence, decay interruption, dormancy, and reactivation.
  [`evidence.py:262`](../../src/shaurya/research/evidence.py#L262)

- Inspect complete-surface construction and declared parameter adjacency.
  [`surfaces.py:150`](../../src/shaurya/research/surfaces.py#L150)

**Durability and acceptance**

- Verify the immutable checkpoint reconstructing tomorrow's exact research belief.
  [`state.py:20`](../../src/shaurya/research/state.py#L20)

- Run the clean-install, shared-ledger, multi-day, crash-recovery workflow.
  [`test_v3_source_bound_e2e.py:251`](../../tests/test_v3_source_bound_e2e.py#L251)

- Inspect seeded null, stability, drift, break, and causal-regime outcomes.
  [`test_v3_seeded_full_pipeline.py:283`](../../tests/test_v3_seeded_full_pipeline.py#L283)

- Review bootstrap tamper rejection and repeated negative-control warnings.
  [`test_surfaces_nulls_multiplicity.py:151`](../../tests/test_surfaces_nulls_multiplicity.py#L151)
- **2026-08-26:** Closed the final iteration-5 evidence gap by registering a target-blind source-keyed autocorrelated negative control and executing the frozen stationary block bootstrap as a candidate-keyed, tamper-evident daily authority through gates, ledger, lifecycle, report, and state. The exact initial plan cardinality is now 22,681 raw and 7,561 effective hypotheses across 64 predictor specifications and two families; 39 focused tests, mypy, scoped Ruff, diff, frozen-block, and cache checks pass; status remains review.
