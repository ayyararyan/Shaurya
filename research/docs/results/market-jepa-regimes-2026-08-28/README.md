# Market-JEPA as a learned market-regime representation — 2026-08-28

## Executive conclusion

**JEPA remains promising but unproven.**

The frozen 96-dimensional JEPA adds small, repeatable information to the strongest result that
cannot be matched by the tested PCA/random controls: 30-second signed ATM-IV change. The increment
is +1.03 percentage points of MAE skill on August 26 and +0.75 points on August 27, positive for all
five seeds. Base+JEPA reaches ROC-AUC 0.677/0.718 and balanced accuracy 0.613/0.654. This is a
market-state forecast, not executable option alpha.

The larger five-minute straddle-magnitude and ATM-IV-magnitude improvements are real relative to
the handcrafted base, but base+PCA is slightly better. JEPA therefore receives no unique credit for
those results. Hard K=4 JEPA regimes fail cross-day and cross-seed stability: a representative seed
places 99.87%/99.60% of August 26/27 in one cluster, and median cross-seed adjusted Rand agreement is
approximately zero. Continuous embeddings and transition intensity are more useful than hard
regime labels.

No trading model is promoted. August 19 is discovery, August 21 validation, and August 26/27 are
retrospective diagnostics. The next genuinely unseen completed session remains untouched.

## Protocol

- Frozen architecture: 96-dimensional embedding, two-minute causal context, EMA target encoder,
  and 5/30/60-second latent targets.
- Seeds: 1, 7, 23, 42, 101; no best-seed selection.
- Discovery-only normalization. Absolute futures price and raw ATM strike identifiers are excluded
  from transferable model inputs; relative prices and all causal microstructure/surface variables
  remain.
- Ridge probes select regularization on August 21, refit on August 19+21, and apply unchanged to
  August 26 and 27.
- Fixed comparisons: last state, handcrafted context, flattened context, PCA-32, random projection,
  shuffled JEPA, JEPA, and each relevant representation concatenated with the handcrafted base.
- Targets: signed/absolute futures return, realized volatility, signed/absolute ATM straddle change,
  near-ATM spread change, signed/absolute ATM-IV change, and surface displacement at 30/60/300 s.
- Adjacent samples overlap. Paired uncertainty resamples contiguous 60-second blocks; session-level
  replication is treated as stronger evidence than within-session row count.

## Incremental representation table

Values are five-seed median MAE skill relative to the development median. Increment is
Base+JEPA minus Base.

| Diagnostic | Target | Horizon | Base skill | JEPA-only | Base+JEPA | Increment |
|---|---|---:|---:|---:|---:|---:|
| Aug 26 | Absolute ATM straddle change | 300 s | -1.56% | +8.17% | +18.27% | +19.83 pp |
| Aug 27 | Absolute ATM straddle change | 300 s | -7.00% | +5.82% | +11.08% | +18.07 pp |
| Aug 26 | Absolute ATM-IV change | 300 s | +12.61% | +5.97% | +17.33% | +4.72 pp |
| Aug 27 | Absolute ATM-IV change | 300 s | +11.83% | +5.74% | +17.43% | +5.60 pp |
| Aug 26 | Signed ATM-IV change | 30 s | +5.13% | +0.45% | +6.17% | +1.03 pp |
| Aug 27 | Signed ATM-IV change | 30 s | +8.14% | +0.48% | +8.88% | +0.75 pp |
| Aug 26 | Near-ATM spread change | 60 s | +20.30% | -10.30% | +20.73% | +0.43 pp |
| Aug 27 | Near-ATM spread change | 60 s | +15.18% | -0.03% | +16.72% | +1.54 pp |

## Seed stability

| Target | Diagnostic | Median increment | Range | Positive seeds | Positive block-CI seeds |
|---|---|---:|---:|---:|---:|
| Absolute ATM straddle, 300 s | Aug 26 | +19.83 pp | +16.69 to +22.70 | 5/5 | 5/5 |
| Absolute ATM straddle, 300 s | Aug 27 | +18.07 pp | +15.77 to +22.66 | 5/5 | 5/5 |
| Absolute ATM IV, 300 s | Aug 26 | +4.72 pp | +2.95 to +5.71 | 5/5 | 5/5 |
| Absolute ATM IV, 300 s | Aug 27 | +5.60 pp | +3.75 to +6.67 | 5/5 | 5/5 |
| Signed ATM IV, 30 s | Aug 26 | +1.03 pp | +0.58 to +1.22 | 5/5 | 5/5 |
| Signed ATM IV, 30 s | Aug 27 | +0.75 pp | +0.35 to +0.96 | 5/5 | 5/5 |
| Near-ATM spread, 60 s | Aug 26 | +0.43 pp | unstable | 3/5 | 2/5 |
| Near-ATM spread, 60 s | Aug 27 | +1.54 pp | unstable | 3/5 | 3/5 |

## Baseline ablation table

Five-seed median MAE skill. The relevant comparison is among representations added to the same
handcrafted base.

| Target | Diagnostic | Base | Base+PCA | Base+random | Base+shuffled JEPA | Base+JEPA |
|---|---|---:|---:|---:|---:|---:|
| Absolute straddle, 300 s | Aug 26 | -1.56% | **+19.40%** | +13.88% | -2.33% | +18.27% |
| Absolute straddle, 300 s | Aug 27 | -7.00% | **+12.47%** | +6.08% | -7.85% | +11.08% |
| Absolute ATM IV, 300 s | Aug 26 | +12.61% | **+18.36%** | +17.24% | +12.47% | +17.33% |
| Absolute ATM IV, 300 s | Aug 27 | +11.83% | **+18.11%** | +16.58% | +11.52% | +17.43% |
| Signed ATM IV, 30 s | Aug 26 | +5.13% | +5.43% | +4.72% | +5.02% | **+6.17%** |
| Signed ATM IV, 30 s | Aug 27 | +8.14% | +8.38% | +8.10% | +8.04% | **+8.88%** |
| Near-ATM spread, 60 s | Aug 26 | +20.30% | **+21.50%** | +8.77% | +20.31% | +20.73% |
| Near-ATM spread, 60 s | Aug 27 | +15.18% | +16.06% | +7.21% | +15.17% | **+16.72%** |

PCA explains the large magnitude results at least as well as JEPA. JEPA's defensible unique lead is
the smaller signed-IV increment, not the headline straddle number.

## Classification metrics for the signed-IV lead

| Diagnostic | Horizon | Base+JEPA ROC-AUC | Balanced accuracy | Incremental R2 |
|---|---:|---:|---:|---:|
| Aug 26 | 30 s | 0.677 | 0.613 | +0.0135 |
| Aug 27 | 30 s | 0.718 | 0.654 | +0.0075 |
| Aug 26 | 300 s | 0.692 | 0.594 | +0.0549 |
| Aug 27 | 300 s | 0.726 | 0.623 | +0.0347 |

These are midpoint/surface forecasts. They do not include option fills, hedging, spread, fees,
slippage, or capacity.

## Regime-dependent signal table

| Signal | Target | Horizon | Result | Cross-regime heterogeneity |
|---|---|---:|---|---:|
| 30 s ATM-IV change | Next ATM-IV change | 30 s | Stable mean reversion; strongest continuous JEPA lead | rho range 0.434 / 0.126 |
| Curvature change | Next ATM-IV change | 30 s | Moderate state dependence, small interaction increment | rho range 0.265 / 0.246 |
| Far parity RMS change | Futures return | 30 s | Interaction reduces error but forecast remains unusable | rho range 0.184 / 0.114 |
| Futures microprice | Futures return | 30 s | Heterogeneous but no stable incremental forecast | rho range 0.258 / 0.128 |
| Depth imbalance | Futures return | 30 s | No stable benefit | rho range 0.161 / 0.182 |

Ranges show August 26 / August 27 median maximum-minus-minimum within-regime Spearman correlation
across seeds. They are descriptive because the hard regimes themselves are unstable.

The parity interaction looks impressive if only relative MAE reduction is read. In absolute terms,
it is not: median ROC-AUC is 0.494/0.513 and balanced accuracy is approximately 0.500/0.502. The
model remains worse than a constant forecast, so the earlier parity lead is not replicated here.

## Regime interpretation and transition structure

| Property | Aug 26 | Aug 27 | Interpretation |
|---|---:|---:|---|
| Effective rank | 31.2–36.0 / 96 | 33.8–38.6 / 96 | No representation collapse |
| Median cross-seed adjusted Rand | 0.000 | -0.002 | Hard regimes do not agree across seeds |
| Representative dominant-regime share | 99.87% | 99.60% | K=4 fails to transfer across days |
| Median hard-regime duration | 10 s | 10 s | Labels flicker; poor operational regime state |
| Mean hard-regime duration | 262 s | 90 s | Driven by the single dominant regime |

Because the hard clusters collapse out of sample, naming them “high-volatility”, “liquidity”, or
“surface” regimes would be misleading. The required regime-interpretation table therefore records
the failed transfer rather than assigning economic names to arbitrary labels.

Continuous transition intensity is more stable. The norm of the JEPA embedding change has
five-seed-positive rank correlation with subsequent 30-second surface displacement:

- Aug 26: rho approximately 0.17–0.19 across 5/30/60-second embedding-change windows.
- Aug 27: rho approximately 0.16–0.18 across those windows.
- Absolute ATM-IV change: rho approximately 0.12–0.15, positive for all five seeds.

This supports retaining continuous JEPA transition shock as an experimental surface-state feature.

## Time-of-day confounding

Clock fraction predicted from JEPA has median R2 -0.588 on August 26 and -0.047 on August 27. Its
MAE skill is -10.0% and +24.9%, respectively, so some clock information is present on August 27 even
though squared-error generalization is poor. Every handcrafted baseline and Base+JEPA comparison
already includes explicit cyclic time and session-fraction controls. The signed-IV increment
survives those controls, but more full sessions are needed before excluding time-of-day completely.

## Decision

- Keep JEPA only as an **experimental learned market-state representation**.
- Do not use hard K=4 clusters; they fail cross-day and cross-seed stability.
- Preserve 30-second and 300-second signed ATM-IV change as preregistered downstream targets.
- Preserve continuous JEPA transition shock for surface displacement and ATM-IV magnitude.
- Use PCA as the default magnitude-model benchmark; JEPA has not beaten it there.
- Do not promote parity/OFI interactions or any trading strategy from this retrospective run.
- Freeze this implementation before the next completed, genuinely unseen session.

## Prospective outer-test lock

**Superseded without being consumed.** This narrow signed-IV-only lock was replaced by the complete
three-hypothesis prospective protocol in `market-jepa-prospective-2026-08-28`. Its fingerprint is
retained below for audit history, but it must not be used for the final test.

The implementation is now frozen. Bundle fingerprint:
`c3350aa8ea7dfa984e19773975040caf6672af67756c2ce906ab5b907b836f28`.

The bundle contains the five JEPA checkpoints, discovery normalization, discovery-fitted PCA,
seeded random projections, and ridge probes whose regularization was selected on August 21. The
probes were refitted once on August 19+21. Every artifact and every source file needed to apply the
test is SHA-256 locked in `outer-test-freeze-manifest.json`.

The apply-only runner accepts exactly one session and enforces all of the following:

- trading date strictly after August 28, 2026 and strictly before the current date in India;
- no development or retrospective-diagnostic date;
- exact frozen input schema and at least 50 contiguous endpoints;
- unchanged bundle artifacts and source code;
- no overwrite and no second use after the bundle writes its consumption seal.

The predeclared hurdle is intentionally hard: at both 30 seconds and 300 seconds, Base+JEPA must
have higher signed ATM-IV MAE skill than both the handcrafted base and Base+PCA in at least four of
five seeds. Passing means only that JEPA remains worth researching. Failing means JEPA is dropped
from alpha research. Neither outcome is a trading-profit claim.

After a genuinely unseen session is complete, run on the Office Mac:

```bash
cd /Users/maheit/Documents/Shaurya-2026-08-28-research/research
/opt/homebrew/bin/uv run python experiments/apply_market_jepa_outer_test.py \
  --bundle /Users/maheit/Documents/Shaurya-research/2026-08-28-market-jepa-outer-freeze \
  --session /absolute/path/to/the/completed/surface-states-YYYY-MM-DD.npz \
  --output /Users/maheit/Documents/Shaurya-research/market-jepa-outer-test-YYYY-MM-DD.json
```

## Reproduction

Machine artifacts are stored outside Git at:

`/Users/maheit/Documents/Shaurya-research/2026-08-28-market-jepa-regimes`

The repository retains the reusable analysis module, deterministic runner, tests, compact JSON/CSV
summaries, and this report. Raw model checkpoints and row-level regime labels remain outside Git.

The prospective bundle is stored outside Git at:

`/Users/maheit/Documents/Shaurya-research/2026-08-28-market-jepa-outer-freeze`

Its compact, auditable manifest is retained beside this report.
