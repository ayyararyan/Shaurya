# Data-quality methodology

## 1. Hypotheses

`H-data-quality-001` covers cadence and cross-channel alignment. `H-data-quality-002` covers depth
occupancy, distance activity, containment, skip windows, and the boundary between feed mechanics
and candidate anomalies.

## 2. Source tests and entry points

Tests: `test_cadence_analysis.py`, `test_alignment_analysis.py`,
`test_depth_thinning_analysis.py`, `test_deepbook_normal_activity.py`, and the construction portion
of `test_deep_book_anomaly.py`. Producers are in `analytics/cadence_analysis.py`,
`analytics/alignment_analysis.py`, `analytics/depth_thinning_analysis.py`, and
`signals/deep_book_normal_activity.py`.

## 3. Input lineage

Inputs are standard/Full, depth20, and depth200 `TapeRow`/`BookState` sequences keyed by instrument,
channel, receive timestamp, and connection epoch. Retained documentation references DAT-15/17/20;
this catalogue did not replay those tapes.

## 4. Feature derivation

Verified formulas for publication gaps, receive-age, agreement, occupancy/contiguity, and
distance-normalized activity are in `../features.csv`. `depth_thinning_analysis.py:321` defines
agreement, `:556` skip windows, `:679` occupancy, `:763` containment, and `:895` activity.

## 5. Temporal alignment and leakage

Strict comparisons use last-at-or-before within the same epoch. Phase-tolerant nearby matching is
diagnostic only and must not be used as a causal feature. Distance uses the pre-transition
same-side reference. Reconnects and stale comparands remain exclusions/degradation labels.

## 6. Procedure and metrics

Group exact receive timestamps into bursts; report gap quantiles/change rates. Compare depth tiers
under strict/tolerant clocks, classify skipped intervals, measure containment, occupancy/tick-span,
activity exposure, and duration-matched controls. Metrics are rates, quantiles, counts, Spearman
association, and two-proportion diagnostics.

## 7. Output interpretation

Agreement or activity patterns describe observed feed/book mechanics. They do not prove native
packet completeness or market causality. A normal-activity boundary is a construction input, not
evidence that an event is economically anomalous.

## 8. Edge cases and quality checks

Zero-price padding, sparse ladders, stale as-of states, crossed/partial books, exact-timestamp
bursts, no interior publication, boundary slides, epoch changes, and empty tapes are explicit.

## 9. Limitations

Provider channels are asynchronous aggregates. Short retained runs may not represent full-session,
roll, expiry, regime, or provider-version behavior. Source exchange sequence may be unavailable.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_cadence_analysis.py tests/test_alignment_analysis.py tests/test_depth_thinning_analysis.py tests/test_deepbook_normal_activity.py
```

Do not run retained-tape scripts until their paths and side effects have been reviewed.

## 11. Researcher decisions

Choose causal staleness bounds, acceptable agreement tolerances, session coverage requirements,
distance bands, and how much evidence is needed before calling activity “normal.”
