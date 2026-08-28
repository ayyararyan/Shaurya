# Research integrity methodology

## 1. Hypotheses

`H-research-integrity-001` asks whether source and availability gates fail closed.
`H-research-integrity-002` asks whether selection, null, multiplicity, stability, ledger, and
lifecycle machinery prevents outcome-driven promotion. These are methodology hypotheses, not
market-alpha claims.

## 2. Source tests and entry points

Primary paths are `research/src/shaurya/research/{source,contracts,walkforward,nulls,multiplicity,
evidence,ledger,state}.py` and the integrity-related tests registered in `test_traceability.csv`.
Important symbols include `verify_completed_source`, `FeatureObservation`, `freeze_historical_folds`,
`complete_miner_empirical_null`, `adjust_hierarchical`, and `assess_lifecycle`.

## 3. Input lineage

Tests create synthetic canonical tapes, immutable registry mappings, fold dates, causal feature and
target rows, and temporary ledgers. No retained real-market result is produced by these tests.

## 4. Feature derivation

Verified from code: `F-source-completion-state` is a conjunction of lifecycle, manifest, hash,
index-binding, coverage, and replay checks. `F-feature-availability-time` enforces
`available_ts_ns <= anchor_ts_ns`. Negative-control and selection features are defined in
`../features.csv`.

## 5. Temporal alignment and leakage

Historical folds are frozen before later rows; inner selection never reads outer targets;
complete-miner null replicates rerun the candidate set; regime predicates use causal feature rows;
and source-keyed controls have no target input. Forged folds, duplicate outer dates, caller-authored
evidence, and target-blind contract violations fail closed.

## 6. Procedure and metrics

Synthetic tests cover recovery of stable injected alpha, structural breaks, complete-family nulls,
hierarchical multiplicity, block bootstrap, lifecycle gates, append-only hash chains, partial-write
rollback, state reconstruction, and deterministic CLI planning. Metrics include outer scores,
adjusted p-values, bootstrap intervals, stability gates, and ledger identities.

## 7. Output interpretation

A pass means the implementation satisfies the tested invariant. It cannot establish false-positive
calibration on real data or support any economic hypothesis; evidence status is `unable to
determine` for that reason.

## 8. Edge cases and quality checks

Incomplete/hash-mismatched sources, future features, duplicate semantic hypotheses, tampered
bootstrap hashes, missing scores, skipped evidence, partial ledger records, and negative controls
are explicit cases.

## 9. Limitations

Synthetic distributions and seeded examples do not reproduce real feed dependence, drift,
missingness, or provider failures. The tests cannot prove absence of every possible leakage path.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q \
  tests/test_adversarial_acceptance.py tests/test_contracts_and_planner.py \
  tests/test_ledger_state_lifecycle_executor.py tests/test_surfaces_nulls_multiplicity.py \
  tests/test_walkforward_and_synthetic.py tests/test_v3_seeded_full_pipeline.py \
  tests/test_v3_source_bound_e2e.py
```

This is a bounded synthetic/temporary-file suite; it does not require live services.

## 11. Researcher decisions

Researchers must define economic families, permitted model/search spaces, evidence thresholds,
negative controls, promotion semantics, and when a registry amendment is allowed.
