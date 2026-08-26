# NIFTY first-hour high-before-low sequence test

**Exploratory full-sample scan.** Predictors use 09:15 through the k-minute decision boundary. The binary target uses strictly future minute stamps from decision+1 through 10:15, preventing the known boundary level from mechanically becoming the target high/low.

## Sample and label

The same 66 cached Still_Water files provide 497,023 minute stamps. There are 1,317 usable days for k=2–30 and 1,315 for k=45. One otherwise eligible first-hour day lacks a required stamp relative to the prior 1,318-day panel; the first two historical dates lack two lagged closes. Initial-window ties are zero. Target ties are zero except two at k=45, which are dropped.

The first occurrence of the window maximum/minimum is used. `high_first=1` when the maximum's first index precedes the minimum's first index. P3 is the full initial-window return, 09:15→decision. Logistic continuous predictors are standardized; significance uses Newey-West HAC(5). Accuracy is in-sample, per Aryan's requested full-sample design.

## Per-k summary

| k | N | Future minutes | Base high/low first | Best univariate contrast | Pseudo-R² | Logistic accuracy vs base | Standout |
|---:|---:|---:|---:|---|---:|---:|---|
| 2 | 1317 | 58 | 50.3% / 49.7% | P1_sign negative: 51.6% vs 49.2% (Δ2.4 pp, p=0.385) | 0.05% | 51.3% vs 50.3% (+0.9 pp) | none |
| 5 | 1317 | 55 | 50.0% / 50.0% | P3_sign negative: 51.4% vs 48.6% (Δ2.7 pp, p=0.321) | 0.21% | 51.1% vs 50.0% (+1.1 pp) | none |
| 10 | 1317 | 50 | 50.7% / 49.3% | initial_sequence low_first: 48.6% vs 52.8% (Δ4.2 pp, p=0.130) | 0.38% | 52.9% vs 50.7% (+2.2 pp) | initial range coefficient p<.05 |
| 15 | 1317 | 45 | 49.0% / 51.0% | P1_sign negative: 51.0% vs 47.2% (Δ3.8 pp, p=0.171) | 0.31% | 51.3% vs 51.0% (+0.3 pp) | initial range coefficient p<.05 |
| 20 | 1317 | 40 | 48.4% / 51.6% | P1_sign negative: 49.7% vs 47.2% (Δ2.5 pp, p=0.366) | 0.11% | 50.8% vs 51.6% (-0.8 pp) | none |
| 30 | 1317 | 30 | 49.9% / 50.1% | P1_sign negative: 52.2% vs 47.8% (Δ4.5 pp, p=0.104) | 0.17% | 52.0% vs 50.1% (+1.9 pp) | none |
| 45 | 1315 | 15 | 48.9% / 51.1% | P1_sign negative: 52.8% vs 45.4% (Δ7.4 pp, p=0.007) | 0.31% | 53.8% vs 51.1% (+2.7 pp) | P1 sign; caution: shortest target |

Base rates stay near 50/50; there is no stable high-first drift to exploit. No target window is under ten minutes; k=45 is shortest at 15 minutes and deserves the most caution.

## Direct initial-sequence persistence

| k | Target high-first after initial high-first | After initial low-first | Difference | p |
|---:|---:|---:|---:|---:|
| 2 | 50.5% (N=658) | 50.2% (N=659) | +0.2 pp | 0.934 |
| 5 | 51.3% (N=663) | 48.6% (N=654) | +2.7 pp | 0.335 |
| 10 | 52.8% (N=661) | 48.6% (N=656) | +4.2 pp | 0.130 |
| 15 | 49.5% (N=657) | 48.5% (N=660) | +1.0 pp | 0.721 |
| 20 | 48.6% (N=660) | 48.1% (N=657) | +0.5 pp | 0.845 |
| 30 | 51.6% (N=661) | 48.2% (N=656) | +3.4 pp | 0.215 |
| 45 | 47.7% (N=675) | 50.2% (N=640) | -2.5 pp | 0.374 |

The most direct hypothesis does not persist reliably. Differences are small, never conventionally significant, and reverse sign at k=45.

## All univariate sign splits

Each cell is target high-first rate for positive/high-first versus negative/low-first, followed by the rate difference and two-proportion p-value.

| k | gap +/− | P1 +/− | P3 +/− | Initial high/low first |
|---:|---:|---:|---:|---:|
| 2 | 49.6/51.4, Δ-1.8, p=0.528 | 49.2/51.6, Δ-2.4, p=0.385 | 50.0/50.5, Δ-0.5, p=0.869 | 50.5/50.2, Δ+0.2, p=0.934 |
| 5 | 49.4/50.8, Δ-1.5, p=0.598 | 48.9/51.1, Δ-2.2, p=0.424 | 48.6/51.4, Δ-2.7, p=0.321 | 51.3/48.6, Δ+2.7, p=0.335 |
| 10 | 50.6/50.8, Δ-0.2, p=0.949 | 49.9/51.6, Δ-1.7, p=0.544 | 49.5/51.9, Δ-2.5, p=0.367 | 52.8/48.6, Δ+4.2, p=0.130 |
| 15 | 48.7/49.4, Δ-0.7, p=0.815 | 47.2/51.0, Δ-3.8, p=0.171 | 48.0/49.9, Δ-1.9, p=0.492 | 49.5/48.5, Δ+1.0, p=0.721 |
| 20 | 48.8/47.7, Δ+1.1, p=0.687 | 47.2/49.7, Δ-2.5, p=0.366 | 49.0/47.7, Δ+1.3, p=0.646 | 48.6/48.1, Δ+0.5, p=0.845 |
| 30 | 49.0/51.2, Δ-2.2, p=0.426 | 47.8/52.2, Δ-4.5, p=0.104 | 48.6/51.2, Δ-2.7, p=0.336 | 51.6/48.2, Δ+3.4, p=0.215 |
| 45 | 48.9/48.9, Δ+0.0, p=1.000 | 45.4/52.8, Δ-7.4, p=0.007 | 50.3/47.4, Δ+2.9, p=0.293 | 47.7/50.2, Δ-2.5, p=0.374 |

P1 is the only split with a consistent direction: after a negative prior day, high-first is more common at every k. The contrast grows from 2.4 pp at k=2 to 7.4 pp at k=45; only k=45 is clearly significant univariately, after searching seven k values.

## Logistic coefficients

Continuous-feature coefficients are per one-standard-deviation increase; the sequence flag is high-first versus low-first. Each cell is coefficient / HAC z / p.

| k | gap | P1 | P3 | Initial range ratio | Initial high-first flag |
|---:|---:|---:|---:|---:|---:|
| 2 | -0.043 / -0.79 / 0.428 | 0.030 / 0.57 / 0.572 | -0.023 / -0.30 / 0.761 | -0.014 / -0.26 / 0.791 | -0.026 / -0.17 / 0.865 |
| 5 | -0.052 / -1.00 / 0.319 | -0.007 / -0.14 / 0.890 | -0.035 / -0.42 / 0.673 | -0.092 / -1.66 / 0.098 | 0.056 / 0.35 / 0.724 |
| 10 | -0.029 / -0.57 / 0.572 | -0.009 / -0.16 / 0.871 | -0.006 / -0.07 / 0.945 | -0.125 / -2.10 / 0.036 | 0.170 / 1.08 / 0.282 |
| 15 | 0.000 / 0.00 / 0.996 | -0.028 / -0.47 / 0.635 | -0.108 / -1.37 / 0.170 | -0.119 / -1.99 / 0.046 | -0.094 / -0.62 / 0.534 |
| 20 | 0.012 / 0.22 / 0.823 | -0.027 / -0.47 / 0.638 | -0.043 / -0.54 / 0.590 | -0.069 / -1.15 / 0.249 | -0.031 / -0.21 / 0.834 |
| 30 | -0.043 / -0.75 / 0.450 | -0.059 / -1.05 / 0.292 | 0.003 / 0.04 / 0.969 | -0.018 / -0.30 / 0.764 | 0.143 / 0.87 / 0.383 |
| 45 | -0.023 / -0.42 / 0.677 | -0.109 / -1.97 / 0.049 | 0.073 / 0.92 / 0.356 | -0.035 / -0.64 / 0.522 | 0.010 / 0.06 / 0.950 |

Only three coefficient cells reach unadjusted p<.05: initial range at k=10 and k=15 (both negative), and P1 at k=45 (negative). None represents a broad, stable improvement across the sweep, and all seven pseudo-R² values are below 0.4%.

## Verdict

**No sizeable general sequencing edge appears.** The cheap persistence rule—initial high-first predicts remaining-hour high-first—does not work consistently. Logistic accuracy improves on the majority-class base rate by at most 2.7 percentage points and pseudo-R² never reaches 0.4%.

The one plausible lead is **k=45 with P1**: following a positive prior day, target high-first is 45.4%; following a negative prior day it is 52.8% (7.4 pp contrast, unadjusted p≈.007). The multivariate P1 coefficient is −0.109 (HAC p=.049), and the full model improves accuracy from 51.1% to 53.8%. That is noticeable but not convincing after selecting the best of seven k values, especially because only a 15-minute target remains. Treat it as a pre-specification candidate for a fresh sample, not a current edge.

## Caveats

- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.
- Ties use first argmax/argmin; only flat-window same-index ties are dropped.
- Accuracy and coefficient inference are full-sample by explicit request. They are not out-of-sample performance claims.
- Seven k values and multiple predictors/splits are scanned without multiple-testing adjustment; isolated p≈.04–.05 results may be chance.
- P0 is the previous session's final available spot stamp, a close proxy rather than an official NSE closing index value.
