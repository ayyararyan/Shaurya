# Surface-linked alpha methodology

## 1. Hypothesis

`H-surface-alpha-001` asks whether causal option-surface state improves five-second NIFTY-futures
forecasting beyond Full-book LOB and CCZ OFI features.

## 2. Source tests and entry points

`test_surface_futures_predictive.py` and `test_surface_ofi_reconciliation.py`; producer
`signals/surface_futures_predictive.py` with `surface_economic_features`, `lob_features`,
`trailing_ofi_features`, `chronological_split`, and `build_scan_artifact`.

## 3. Input lineage

Causal eSSVI snapshots cover three declared expiries. Full futures `BookState` supplies five-level
LOB and canonical CCZ features. Target is the future's displayed-mid movement after 0.5s gap and
5s response.

## 4. Feature derivation

Surface predictors include theta/rho/psi, ATM IV/skew/curvature, changes/velocities, adjacent-expiry
terms, quality fields, and lag placebo. LOB uses five-level prices/sizes; OFI reuses canonical CCZ
signs. Exact formulas and constants are pinned in `surface_futures_predictive.py:30-99,459-821`.

## 5. Temporal alignment and leakage

Surface as-of matching enforces age, epoch, and right edge. Split is chronological 70/30 with a
120s embargo; preprocessing and ridge alpha are training-only. Freshness filters preserve split
positions. A 300s same-epoch lag surface is an explicit placebo.

## 6. Procedure and metrics

Fit LOB-only, LOB+OFI, and LOB+OFI+surface families on identical test rows. Report OOS R2,
correlations with HAC, paired error inference, coefficients, freshness cuts, lag placebo,
collinearity rank, coverage, and deterministic replay hashes.

## 7. Output interpretation

Verified from existing documentation: the located exploratory result does not support incremental
surface value for this design; the lag/freshness/collinearity diagnostics reinforce caution. The
catalogue labels this `rejects hypothesis` only for the tested source/sample, not universally.

## 8. Edge cases and quality checks

Stale/no-prior/cross-epoch surfaces, missing denominators, optional OFI windows, insufficient
freshness, target right-edge, training-vocabulary isolation, collinearity, and lag wraparound are
tested.

## 9. Limitations

One exploratory sample, high surface collinearity, three fixed expiries, displayed-mid target, and
no cost/fill analysis limit generalization.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_surface_futures_predictive.py tests/test_surface_ofi_reconciliation.py
```

Do not run the retained-tape scan without reviewing source paths and output writes.

## 11. Researcher decisions

Decide whether to retire, redesign, or preregister replication; choose source freshness, expiry
universe, surface representation, target horizon/reference, and minimum incremental effect.
