# Feature-selection methodology

## 1. Hypotheses

`H-feature-selection-001` asks whether registered clusters are conditionally useful and stable.
`H-feature-selection-002` asks whether aggregate futures state adds to option-state controls for
five/30-second option markouts.

## 2. Source tests and entry points

Feature registry/gating/reduction/models/usefulness/stability are in
`signals/feature_selection.py` and tests `test_feature_*.py`. The quality-aware daily pipeline is
`analytics/post_close_alpha_research.py` with `test_post_close_alpha_research.py`.

## 3. Input lineage

D51 combines a completed futures tape and later-starting surface capture on a common causal grid.
The post-close pipeline consumes a completed catalogue handle for one future plus option chain,
replays quality intervals, and builds a five-second grid. Existing D51 CSVs are referenced in
`../feature_data/manifest.csv` rather than copied.

## 4. Feature derivation

D51 registers price lags, CCZ OFI, LOB, surface economic/quality, interactions, and regimes; gates
coverage/range, clusters training-only correlations, and computes conditional deltas. Post-close
features include log mids, relative spreads, microprice dislocations, five-level imbalance,
10s log volume-increment intensity, and 30s realized volatility; targets are half-spread markouts.

## 5. Temporal alignment and leakage

All gates/maps/transforms/config selection occur inside each training boundary; outer tests are
apply-only. Post-close uses 60/20/20 chronology, 30s embargo, development-only clipping/scaling,
and exact outcome support. Quality buffers surround reconnects/partial/stale/invalid intervals.

## 6. Procedure and metrics

D51 evaluates elastic net/tree/baselines, cluster/family ablation, grouped block permutation,
regime slices, selection frequency, and promotion guards. Post-close compares baseline versus
augmented ridge with OOS R2/MAE deltas, HAC intervals, 60s block reweighting, quality buffers, and
development-defined tail checks.

## 7. Output interpretation

D51 is inconclusive: one session, every stability row insufficient, surface economic fields mostly
failed coverage, mirror/economic guards unavailable. Post-close is mixed: a small distinguishable
30s signed incremental R2, no 5s support, worse squared error for absolute proxies, and augmented
absolute R2 still below the test-mean benchmark.

## 8. Edge cases and quality checks

Missing/stale surface frames, affine duplicates, zero variance, sparse clusters, unmatched common
rows, changing selected configs, insufficient sessions/folds/regimes, crossed/partial books,
reconnect windows, malformed counts, short coverage, and half-spread floors are explicit.

## 9. Limitations

Both located result families are single-session exploratory evidence. Aggregate feed rows lack
orders/fills. Multiple comparisons, tail sensitivity, source packet completeness, costs, latency,
capacity, and cross-session stability remain unresolved.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_feature_selection.py tests/test_feature_correlation_reduction.py tests/test_feature_conditional_usefulness.py tests/test_feature_stability_selection.py tests/test_post_close_alpha_research.py
```

The full D51/post-close runs are data-heavy and write artifacts; do not launch them as catalogue
validation.

## 11. Researcher decisions

Set promotion effect size, session/fold minimums, mirror/economic guards, model identity pooling,
surface coverage remediation, markout economics, and preregistered replication design.
