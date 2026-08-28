# JEPA market surprise and latent disequilibrium — 2026-08-28

## Technical summary

**The evidence does not support a broad JEPA market-physics promotion.** Continuous velocity replicates, 30-second surprise improves a weak surface model beyond velocity, and near-to-far disequilibrium adds a small repeatable term-structure increment. Cross-market direction, call-put disequilibrium, curvature, and the stress taxonomy fail the stronger baseline or stability tests. This is retrospective research, not a trading or executable-PnL result.

Only four already-seen sessions are used: Aug 19 discovery, Aug 21 validation, and Aug 26/27 diagnostics (2,342/4,477 common endpoints). The existing prospective outer-test bundle was verified read-only and remains unconsumed.

## 1. JEPA surprise

Thirty-second raw L2 surprise adds median MAE skill beyond velocity for surface displacement of +6.75 pp on 2026-08-26 and +9.14 pp on 2026-08-27, positive in all five seeds. However, raw rank correlations change sign across seeds and the resulting surface model still has negative skill on Aug 27. For absolute ATM-IV change the increment is only +0.33 pp/+0.33 pp. Conclusion: surprise contains information beyond velocity, but not yet a robust standalone forecast. Retain for more data.

Raw L2, unit-L2, and cosine error are all reported. Unit/cosine diagnostics prevent embedding-norm drift from receiving automatic credit.

## 2. Futures versus options

No stable leader emerges. Among large futures-to-options discrepancies, median futures-led shares are 23.7%/25.9%, versus options-led 24.4%/23.1%. Persistent disagreement is larger at 33.8%/32.9%. The latent feature loses to Base+PCA for surface displacement in every seed. Retain the question, not the current feature.

## 3. Near versus far expiry

The data do not identify a reliable first mover: far-led and near-led event shares are 24.0% vs 23.4% on 2026-08-26, and 25.1% vs 23.1% on 2026-08-27. Persistent disagreement is the largest class. Still, near-to-far disequilibrium adds +1.00 pp/+1.27 pp over Base+PCA for signed term-structure IV change, positive in all five seeds. Promote only as an experimental research feature.

## 4. Calls versus puts

Call-put disequilibrium does not improve parity restoration beyond the explicit call-minus-put/parity benchmark (-1.33 pp/-1.31 pp) and is seed-unstable for relative correction. Reject the current latent call-put feature.

## 5. Latent acceleration and curvature

Velocity remains the useful trajectory statistic: its 30-second Spearman correlation with surface displacement is 0.199/0.173, with positive 60-second block intervals in all five seeds. Five-second acceleration adds only +0.94 pp/+0.96 pp beyond velocity; longer acceleration and curvature generally add nothing or hurt. Keep velocity; retain 5-second acceleration for more data; reject curvature as an early-turn claim.

## 6. Cross-seed disagreement

After discovery-only Procrustes alignment, 5-second disagreement adds just +0.19 pp/+0.18 pp beyond surprise+velocity for absolute ATM-IV change and degrades surface forecasts. Retain for more sessions; do not promote.

## 7. Stress taxonomy

The taxonomy fails transfer. Cross-market dislocation absorbs median shares of 85.5%/80.9%; stable, orderly-transition, and information-shock states do not survive as usable diagnostic classes. This reflects subsystem mapping distribution shift, not a discovered universal stress law. Reject the current taxonomy.

## 8. Baseline comparison

The strongest genuinely incremental result is near-to-far disequilibrium for signed term-structure IV change: about +1.00/+1.27 percentage points over Base+PCA, positive in all seeds and both diagnostic sessions. Surprise produces larger relative improvements for surface displacement but does not rescue negative Aug 27 model skill, so it receives no promotion credit. Futures-options disequilibrium loses to PCA; call-put is explained by or worse than explicit residuals.

## 9. Scientific recommendation

| feature | decision | reason |
|---|---|---|
| Latent velocity | Promote to experimental research feature | Replicated surface/IV magnitude association across seeds and sessions. |
| 30-second surprise | Retain for more data | Adds beyond velocity, but primary rank evidence is seed-dependent and surface skill remains negative on Aug 27. |
| 5-second acceleration | Retain for more data | Small all-seed surface increment; longer lags fail. |
| Curvature | Reject | No stable incremental value beyond velocity. |
| Futures-options disequilibrium | Retain for more data | Descriptive association, no PCA increment and unstable correction attribution. |
| Near-far disequilibrium | Promote to experimental research feature | Small all-seed, two-session increment over PCA for term-structure IV change. |
| Call-put disequilibrium | Reject | Fails explicit parity/residual baselines. |
| Cross-seed disagreement | Retain for more data | Tiny 5-second ATM-IV increment; not broad or stable enough. |
| Stress taxonomy | Reject | Mapping shift collapses most observations into one class. |

## Statistical and operational caveats

- Correlations use 60/120/300-second rank-transformed moving-block bootstrap intervals; model comparisons use paired contiguous-block loss resampling.
- Normalization, mappings, Procrustes alignment, quintiles, and taxonomy thresholds are fit on discovery/validation only.
- Two diagnostic sessions are insufficient for production or trading promotion. No IID shuffle inference is used, but cross-session replication remains the binding limitation.
- No fill-level adverse-selection labels were available. Results are midpoint/surface research without spread, fees, slippage, hedging, queue position, or capacity.
- The Aug 28/later genuinely unseen outer-test targets were not opened.
