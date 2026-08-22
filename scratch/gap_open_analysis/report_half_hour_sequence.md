# NIFTY opening-half-hour high-before-low sequence test

**Exploratory full-sample scan, capped at 09:45.** Predictors include minute levels through the k-minute decision boundary. Targets begin at decision+1 and end at 09:45, so the known boundary level cannot mechanically become the target high or low.

## Sample

The same 66 cached Still_Water files provide 497,023 minute stamps. Every k panel has **1,318 days** after requiring two lagged close proxies and all opening-half-hour levels. Initial- and target-window tie counts are zero at every k.

The target windows are 28, 25, 20, 15, 10 and 5 minutes for k=2,5,10,15,20,25. No k is below the five-minute floor, but k=25 is exactly at it and is flagged as thin. The label uses first argmax/argmin indices of minute-stamped spot levels.

## Per-k summary

| k | N | Future minutes | Base high/low first | Best univariate contrast | Pseudo-R² | Logistic accuracy vs base | Standout |
|---:|---:|---:|---:|---|---:|---:|---|
| 2 | 1318 | 28 | 50.1% / 49.9% | P3_sign positive: 47.4% vs 52.5% (Δ5.1 pp, p=0.064) | 0.37% | 53.0% vs 50.1% (+2.9 pp) | conditional initial-sequence flag p=.017 |
| 5 | 1318 | 25 | 49.8% / 50.2% | P1_sign negative: 52.1% vs 47.7% (Δ4.4 pp, p=0.112) | 0.13% | 53.0% vs 50.2% (+2.8 pp) | none |
| 10 | 1318 | 20 | 51.6% / 48.4% | P1_sign negative: 54.0% vs 49.4% (Δ4.6 pp, p=0.096) | 0.10% | 50.8% vs 51.6% (-0.8 pp) | none |
| 15 | 1318 | 15 | 48.6% / 51.4% | P1_sign negative: 51.8% vs 45.7% (Δ6.1 pp, p=0.027) | 0.29% | 52.7% vs 51.4% (+1.3 pp) | P1 sign split p=.027 only |
| 20 | 1318 | 10 | 48.6% / 51.4% | P1_sign negative: 51.1% vs 46.4% (Δ4.7 pp, p=0.087) | 0.18% | 53.0% vs 51.4% (+1.7 pp) | none |
| 25 | 1318 | 5 | 48.9% / 51.1% | P1_sign negative: 51.1% vs 46.8% (Δ4.3 pp, p=0.120) | 0.21% | 51.1% vs 51.1% (+0.0 pp) | minimum 5-minute target |

Base rates remain close to 50/50, ranging from 48.6% to 51.6% high-first. No structural opening-half-hour ordering bias dominates the classification null.

## Direct initial-sequence persistence

| k | Target high-first after initial high-first | After initial low-first | Difference | p |
|---:|---:|---:|---:|---:|
| 2 | 52.5% (N=659) | 47.6% (N=659) | +4.9 pp | 0.078 |
| 5 | 49.4% (N=664) | 50.2% (N=654) | -0.8 pp | 0.784 |
| 10 | 52.3% (N=662) | 50.9% (N=656) | +1.4 pp | 0.624 |
| 15 | 48.3% (N=658) | 48.8% (N=660) | -0.5 pp | 0.867 |
| 20 | 47.9% (N=660) | 49.4% (N=658) | -1.5 pp | 0.583 |
| 25 | 49.6% (N=674) | 48.1% (N=644) | +1.4 pp | 0.607 |

The direct persistence effect is largest at k=2: 52.5% after an initial high-first versus 47.6% after initial low-first (+4.9 pp, p=.078). It vanishes or reverses at k=5–25, so it is not a stable univariate rule.

## All univariate sign splits

Each cell is high-first rate for positive/high-first versus negative/low-first, then the rate difference and two-proportion p-value.

| k | gap +/− | P1 +/− | P3 +/− | Initial high/low first |
|---:|---:|---:|---:|---:|
| 2 | 49.5/50.8, Δ-1.3, p=0.648 | 48.3/52.1, Δ-3.8, p=0.167 | 47.4/52.5, Δ-5.1, p=0.064 | 52.5/47.6, Δ+4.9, p=0.078 |
| 5 | 48.9/51.0, Δ-2.1, p=0.451 | 47.7/52.1, Δ-4.4, p=0.112 | 49.1/50.4, Δ-1.3, p=0.639 | 49.4/50.2, Δ-0.8, p=0.784 |
| 10 | 50.1/53.8, Δ-3.7, p=0.186 | 49.4/54.0, Δ-4.6, p=0.096 | 50.4/52.8, Δ-2.4, p=0.387 | 52.3/50.9, Δ+1.4, p=0.624 |
| 15 | 48.5/48.6, Δ-0.1, p=0.968 | 45.7/51.8, Δ-6.1, p=0.027 | 48.6/48.5, Δ+0.2, p=0.955 | 48.3/48.8, Δ-0.5, p=0.867 |
| 20 | 49.2/47.9, Δ+1.3, p=0.650 | 46.4/51.1, Δ-4.7, p=0.087 | 49.2/48.0, Δ+1.2, p=0.665 | 47.9/49.4, Δ-1.5, p=0.583 |
| 25 | 49.9/47.3, Δ+2.6, p=0.353 | 46.8/51.1, Δ-4.3, p=0.120 | 48.0/49.7, Δ-1.7, p=0.530 | 49.6/48.1, Δ+1.4, p=0.607 |

P1 again has the most consistent direction: negative prior days are followed by more high-first labels at every k. The largest contrast is k=15: 51.8% after P1− versus 45.7% after P1+ (6.1 pp, unadjusted p=.027), but P1 is not significant in the multivariate model at that k.

## Logistic coefficients

Continuous coefficients are per one-standard-deviation increase; the flag is initial high-first versus low-first. Each cell is coefficient / HAC z / p.

| k | gap | P1 | P3 | Initial range ratio | Initial high-first flag |
|---:|---:|---:|---:|---:|---:|
| 2 | 0.027 / 0.48 / 0.633 | -0.003 / -0.06 / 0.955 | 0.135 / 1.61 / 0.107 | 0.065 / 1.24 / 0.217 | 0.384 / 2.38 / 0.017 |
| 5 | -0.002 / -0.04 / 0.967 | -0.022 / -0.38 / 0.704 | -0.075 / -0.94 / 0.350 | 0.045 / 0.82 / 0.409 | -0.139 / -0.91 / 0.364 |
| 10 | -0.032 / -0.61 / 0.544 | -0.040 / -0.72 / 0.470 | 0.008 / 0.10 / 0.918 | -0.059 / -0.99 / 0.324 | 0.067 / 0.42 / 0.676 |
| 15 | 0.058 / 1.03 / 0.305 | -0.068 / -1.19 / 0.235 | 0.116 / 1.53 / 0.126 | 0.030 / 0.53 / 0.593 | 0.137 / 0.89 / 0.371 |
| 20 | 0.017 / 0.29 / 0.773 | -0.072 / -1.21 / 0.227 | 0.001 / 0.01 / 0.993 | 0.055 / 0.92 / 0.355 | -0.067 / -0.43 / 0.665 |
| 25 | 0.033 / 0.62 / 0.536 | -0.044 / -0.78 / 0.435 | -0.127 / -1.57 / 0.116 | 0.012 / 0.22 / 0.826 | -0.128 / -0.83 / 0.405 |

Only one multivariate coefficient reaches unadjusted p<.05: the initial high-first flag at k=2 (coefficient 0.384, HAC p=.017). Its implied conditional odds ratio is about 1.47, but the full model's pseudo-R² is only 0.37% and accuracy uplift is 2.9 pp. This is the best candidate in the tighter window, not proof of a stable effect.

## Verdict

**The half-hour cap produces one plausible local lead, but still no broad sequencing edge.** At k=2, the initial high/low ordering has the expected persistence direction, and its conditional logistic coefficient is significant. Yet the univariate contrast is only borderline, no adjacent k confirms it, pseudo-R² remains below 0.4%, and the largest accuracy uplift is only 2.9 percentage points in sample.

The k=15 P1 sign split is also noticeable but does not survive multivariate conditioning. Because six k values and several predictors were scanned, neither result should be called real without pre-specifying it and testing a fresh period. If choosing one candidate, freeze **k=2 initial-sequence persistence** for prospective validation; do not optimize further on this sample.

## Caveats

- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.
- Accuracy and coefficient inference use the full sample by explicit instruction; they are not OOS performance claims.
- Six k values and multiple splits/coefficient tests are unadjusted for multiple scanning.
- k=25 has only a five-minute target; its ordering label is especially sensitive to one-minute resolution.
- P0 is the previous session's final available spot stamp, not an official NSE close.
