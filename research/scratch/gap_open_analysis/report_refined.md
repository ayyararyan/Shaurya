# Refined NIFTY opening-state → next-10-minute panel

**Exploratory, non-overlapping design.** All predictors are known at the target-window boundary. The source is the already-staged Still_Water Dhan-derived NIFTY `spot` series; no API or order path was used.

## Design and sample

The source has 497,023 minute stamps from 2021-01-01T09:15:00+05:30 through 2026-05-14T15:29:00+05:30. Each k panel has **1,318 days** after requiring two prior daily closes and all intraday endpoints.

- `P1`: yesterday's final spot / day-before-yesterday's final spot − 1.
- `gap`: today's 09:15 spot / yesterday's final spot − 1; `P0_close` is retained in the panel as context.
- `P2`: 09:15→09:16 return. `P3`: 09:16→09:(15+k) return.
- Target: the strictly subsequent 10-minute close-to-close return. Range uses the maximum/minimum of the 11 stamped boundary levels from target start through target end. Because `T_range_ratio-1` is an affine transform of the ratio, its correlations, standardized betas and R² are identical.
- OLS variables are standardized; coefficient p-values use Newey-West HAC(5). The 70/30 split is chronological and OOS R² uses the training target mean as baseline.

## Marginal correlations — full sample

| k | Predictor | T_ret Pearson (p) | T_ret Spearman (p) | T_range Pearson (p) | T_range Spearman (p) |
|---:|---|---:|---:|---:|---:|
| 5 | P1 | -0.068 (0.014) | 0.003 (0.911) | -0.173 (<0.001) | -0.166 (<0.001) |
| 5 | gap | 0.006 (0.839) | 0.025 (0.359) | -0.217 (<0.001) | -0.128 (<0.001) |
| 5 | P2 | -0.061 (0.026) | 0.030 (0.270) | 0.051 (0.064) | -0.053 (0.054) |
| 5 | P3 | -0.084 (0.002) | -0.056 (0.042) | -0.215 (<0.001) | -0.065 (0.019) |
| 10 | P1 | -0.089 (0.001) | -0.043 (0.118) | -0.168 (<0.001) | -0.175 (<0.001) |
| 10 | gap | 0.017 (0.543) | 0.035 (0.202) | -0.173 (<0.001) | -0.126 (<0.001) |
| 10 | P2 | -0.014 (0.600) | 0.024 (0.385) | 0.022 (0.430) | -0.041 (0.141) |
| 10 | P3 | -0.063 (0.022) | -0.038 (0.163) | -0.186 (<0.001) | -0.120 (<0.001) |
| 20 | P1 | 0.049 (0.077) | 0.063 (0.022) | -0.209 (<0.001) | -0.157 (<0.001) |
| 20 | gap | -0.033 (0.228) | -0.033 (0.229) | -0.150 (<0.001) | -0.132 (<0.001) |
| 20 | P2 | 0.014 (0.601) | 0.028 (0.314) | 0.005 (0.866) | -0.014 (0.622) |
| 20 | P3 | -0.042 (0.123) | 0.005 (0.852) | -0.105 (<0.001) | -0.139 (<0.001) |
| 30 | P1 | -0.037 (0.182) | -0.049 (0.074) | -0.132 (<0.001) | -0.152 (<0.001) |
| 30 | gap | -0.003 (0.914) | 0.010 (0.723) | -0.119 (<0.001) | -0.098 (<0.001) |
| 30 | P2 | 0.005 (0.846) | -0.042 (0.124) | 0.056 (0.044) | -0.020 (0.460) |
| 30 | P3 | -0.094 (<0.001) | -0.030 (0.280) | -0.177 (<0.001) | -0.130 (<0.001) |

Return marginals are small and inconsistent. Range magnitude is more systematic: negative P1, gap and P3 tend to precede larger next-window ranges, while P2 contributes little on its own.

## Multivariate and chronological validation

| k | Target | Full R² | Train-70% R² | OOS R² | OOS Pearson (p) | OOS Spearman (p) | OOS direction hit |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | T_ret | 1.58% | 3.47% | -9.35% | -0.091 (0.071) | -0.112 (0.026) | 42.8% |
| 5 | T_range_magnitude | 11.51% | 14.36% | -6.14% | 0.224 (<0.001) | 0.084 (0.095) | — |
| 10 | T_ret | 1.24% | 1.79% | -0.83% | 0.037 (0.463) | -0.007 (0.894) | 48.9% |
| 10 | T_range_magnitude | 8.98% | 11.01% | 0.64% | 0.198 (<0.001) | 0.126 (0.012) | — |
| 20 | T_ret | 0.52% | 1.45% | -3.15% | -0.070 (0.163) | -0.065 (0.196) | 48.7% |
| 20 | T_range_magnitude | 7.74% | 10.21% | -1.45% | 0.148 (0.003) | 0.177 (<0.001) | — |
| 30 | T_ret | 1.03% | 1.43% | -0.94% | 0.021 (0.679) | -0.015 (0.759) | 51.3% |
| 30 | T_range_magnitude | 6.70% | 9.23% | -2.17% | 0.119 (0.018) | 0.109 (0.030) | — |

All four return models fail calibrated OOS validation: OOS R² is negative and direction hit is only 42.8–51.3%. Range predictions retain positive OOS ranking correlations at every k, but calibrated OOS R² is weak: only k=10 is slightly positive.

## Full-sample standardized OLS coefficients

Each cell is beta / HAC t / p.

| k | Target | P1 | gap | P2 | P3 |
|---:|---|---:|---:|---:|---:|
| 5 | T_ret | -0.061 / -1.25 / 0.211 | 0.022 / 0.39 / 0.693 | -0.064 / -0.90 / 0.369 | -0.091 / -2.01 / 0.045 |
| 5 | T_range_magnitude | -0.171 / -4.04 / <0.001 | -0.195 / -3.82 / <0.001 | 0.067 / 0.67 / 0.504 | -0.185 / -3.02 / 0.003 |
| 10 | T_ret | -0.088 / -2.25 / 0.025 | 0.023 / 0.65 / 0.517 | -0.012 / -0.30 / 0.764 | -0.064 / -1.62 / 0.105 |
| 10 | T_range_magnitude | -0.165 / -3.56 / <0.001 | -0.165 / -4.30 / <0.001 | 0.036 / 0.49 / 0.626 | -0.177 / -2.53 / 0.012 |
| 20 | T_ret | 0.047 / 1.08 / 0.282 | -0.034 / -0.83 / 0.409 | 0.010 / 0.26 / 0.793 | -0.038 / -1.04 / 0.299 |
| 20 | T_range_magnitude | -0.213 / -4.87 / <0.001 | -0.141 / -3.84 / <0.001 | 0.028 / 0.84 / 0.403 | -0.110 / -2.88 / 0.004 |
| 30 | T_ret | -0.039 / -0.96 / 0.337 | -0.001 / -0.02 / 0.982 | 0.005 / 0.09 / 0.928 | -0.094 / -2.64 / 0.008 |
| 30 | T_range_magnitude | -0.138 / -3.90 / <0.001 | -0.117 / -3.11 / 0.002 | 0.069 / 1.09 / 0.277 | -0.175 / -3.91 / <0.001 |

## Top-1% |T_ret| exclusion

The cutoff is descriptive and computed within each full k panel; 14 of 1,318 days are removed. This prevents election/crash days from dominating, but the trimmed OOS figures are not a deployable ex-ante filter because future target size is unknowable.

| k | cutoff | Return full/OOS R², OOS corr/hit | Range full/OOS R², OOS Pearson/Spearman |
|---:|---:|---:|---:|
| 5 | 56.44 bp | 0.40% / -1.21%, -0.027/46.0% | 6.03% / -10.64%, 0.066/0.105 |
| 10 | 48.86 bp | 0.33% / -0.56%, 0.003/47.8% | 5.59% / 1.06%, 0.162/0.108 |
| 20 | 45.55 bp | 0.54% / -1.74%, -0.038/49.2% | 5.59% / 0.65%, 0.133/0.153 |
| 30 | 38.34 bp | 0.65% / 0.62%, 0.080/54.8% | 5.80% / 2.20%, 0.175/0.145 |

After tail removal, return R² falls to 0.3–0.7%. Range full-sample R² remains 5.6–6.0%. The k=10/20/30 trimmed range models retain small positive OOS R² (1.06%, 0.65%, 2.20%) and OOS Pearson correlations of 0.162, 0.133 and 0.175; k=5's Pearson ranking does not survive trimming.

## Sign-interaction buckets

Bucket order is sign(P1), sign(P2), sign(P3). Consistency compares T_ret with the three-sign majority. Exact-zero predictors are excluded from this eight-bucket view.

| k | Bucket | N | Mean T_ret (bp) | Mean p | Majority consistency | Trimmed N / mean (bp) / consistency |
|---:|---|---:|---:|---:|---:|---:|
| 5 | --- | 160 | 2.41 | 0.146 | 50.0% | 157 / 1.00 / 51.0% |
| 5 | --+ | 150 | -1.46 | 0.327 | 53.3% | 148 / -0.70 / 52.7% |
| 5 | -+- | 147 | 0.97 | 0.583 | 44.5% | 143 / 0.71 / 44.4% |
| 5 | -++ | 162 | -1.92 | 0.150 | 51.2% | 160 / -1.99 / 51.2% |
| 5 | +-- | 150 | 0.38 | 0.751 | 46.3% | 149 / -0.03 / 46.6% |
| 5 | +-+ | 154 | -3.17 | 0.015 | 42.9% | 154 / -3.17 / 42.9% |
| 5 | ++- | 223 | -0.09 | 0.939 | 54.3% | 221 / 1.02 / 54.8% |
| 5 | +++ | 164 | 1.08 | 0.320 | 59.8% | 164 / 1.08 / 59.8% |
| 10 | --- | 168 | 2.10 | 0.158 | 51.5% | 165 / 1.51 / 51.8% |
| 10 | --+ | 143 | 0.38 | 0.794 | 42.0% | 140 / 0.70 / 41.4% |
| 10 | -+- | 146 | 0.34 | 0.829 | 54.8% | 142 / -0.48 / 55.6% |
| 10 | -++ | 166 | -0.70 | 0.540 | 51.8% | 165 / -0.34 / 52.1% |
| 10 | +-- | 146 | -1.19 | 0.255 | 55.5% | 146 / -1.19 / 55.5% |
| 10 | +-+ | 158 | -3.59 | <0.001 | 38.9% | 157 / -3.29 / 39.1% |
| 10 | ++- | 198 | 1.13 | 0.234 | 54.5% | 198 / 1.13 / 54.5% |
| 10 | +++ | 191 | -1.16 | 0.259 | 51.8% | 189 / -0.62 / 52.4% |
| 20 | --- | 159 | -2.13 | 0.067 | 56.6% | 158 / -2.45 / 57.0% |
| 20 | --+ | 152 | -3.18 | 0.028 | 53.9% | 148 / -2.57 / 53.4% |
| 20 | -+- | 159 | -1.32 | 0.394 | 52.8% | 153 / -1.17 / 52.9% |
| 20 | -++ | 153 | 0.02 | 0.988 | 53.6% | 151 / -0.19 / 53.6% |
| 20 | +-- | 162 | 0.57 | 0.550 | 48.8% | 162 / 0.57 / 48.8% |
| 20 | +-+ | 142 | 0.16 | 0.855 | 57.0% | 142 / 0.16 / 57.0% |
| 20 | ++- | 183 | 0.84 | 0.401 | 53.6% | 182 / 1.15 / 53.8% |
| 20 | +++ | 205 | 1.22 | 0.140 | 54.6% | 205 / 1.22 / 54.6% |
| 30 | --- | 173 | 3.89 | <0.001 | 42.2% | 169 / 2.84 / 43.2% |
| 30 | --+ | 138 | 1.06 | 0.397 | 44.2% | 136 / 1.26 / 44.1% |
| 30 | -+- | 159 | -0.53 | 0.640 | 52.8% | 157 / -0.63 / 52.9% |
| 30 | -++ | 153 | -0.85 | 0.356 | 45.8% | 153 / -0.85 / 45.8% |
| 30 | +-- | 151 | -0.23 | 0.837 | 51.7% | 148 / -0.61 / 52.0% |
| 30 | +-+ | 153 | -0.28 | 0.772 | 52.9% | 152 / 0.06 / 53.3% |
| 30 | ++- | 169 | -0.06 | 0.956 | 50.3% | 167 / -0.20 / 50.3% |
| 30 | +++ | 220 | -0.37 | 0.591 | 50.0% | 220 / -0.37 / 50.0% |

Bucket means change sign across k and weaken materially after tail removal. No fixed P1×P2×P3 sign combination is a stable directional rule across target start times.

## Verdict

**Direction:** no robust linear or sign-combination edge in this specification. Small in-sample return relationships do not survive the chronological holdout.

**Range/magnitude:** there is a modest, non-mechanical signal worth a prospective test, especially for k=10–30. Negative prior-day return, negative overnight gap and negative P3 generally predict a wider following 10-minute window. The ranking relationship survives OOS and the 1% tail check at k=10/20/30, but calibration is weak—OOS R² is only about 0.6–2.2% after trimming. This supports a volatility/range-screening hypothesis, not yet a tradable directional rule or a proven net-of-cost edge.

## Caveats

- `spot` is a Dhan-derived level embedded in ATM option files. T_high/T_low are extrema of minute-stamped spot levels, not intraminute index OHLC extrema.
- P0 is the prior session's final available spot stamp; this is a close proxy, including special evening sessions, rather than an official NSE closing index value.
- Marginal p-values are unadjusted for the 32 scans. HAC inference addresses short daily serial dependence but not all regime changes or data-snooping.
- The 70/30 split is one holdout, not repeated walk-forward validation. Any next step should freeze the selected k/range rule before prospective testing.
