# VRP on NIFTY opening-range breakouts

**Date:** 2026-08-23 · **Status:** exploratory offline analysis · **Frozen specification:** `VRP_BREAKOUT_SPEC.md`  
**No broker, credentials, order path, live trading, or Gate A/Gate B change.**

## Owner summary

This test asks whether the volatility delivered after an opening-range break exceeds the ATM volatility bought at that exact minute. The descriptive object is `VRP_break = own trading-time IV − subsequent trading-time RV`; a positive number favours the option seller. Results below are exploratory associations, not a causal or deployable finding. They must be read against `NGE_BREAKOUT_TEST.md`: breakouts occur almost daily, continuation to the close is approximately zero, and about 92% re-enter their opening range.

The placebo is reported beside the headline because it distinguishes a breakout-specific premium from the unconditional time-of-day premium. The family contains **32 predeclared tests** and the Bonferroni 5% threshold is **0.0015625**. Nominal p-values are not family-wise discoveries unless they fall below that threshold.

## 1. Headline estimand

Both IV and RV are annualised with 375 trading minutes per session and 252 sessions per year. Units are volatility points; positive VRP means realised volatility fell short of the premium bought.

| spec | N | IV at break | RV after break | mean VRP | median | sd | VRP > 0 | t p | Wilcoxon p | Bonferroni α |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OR15 | 1320 | 12.45 | 9.05 | 3.40 | 3.27 | 3.13 | 90.4% | <0.0001 | <0.0001 | 0.001563 |
| OR30 | 1318 | 12.43 | 8.89 | 3.54 | 3.44 | 3.30 | 90.7% | <0.0001 | <0.0001 | 0.001563 |

## 2. Matched time-of-day placebo

Each breakout session received exactly 200 pseudo-break draws, sampled with replacement from its specification's empirical actual-break clock distribution using seed 20260823. The placebo uses the same absolute-strike selection, own trading-time inversion, and remaining-session RV pipeline. The paired object compares each actual break with that session's mean valid pseudo-break VRP.

| spec | mean VRP at break | mean placebo VRP | paired difference | paired t p | paired Wilcoxon p | Bonferroni α |
|---|---:|---:|---:|---:|---:|---:|
| OR15 | 3.40 | 3.41 | -0.01 | 0.5132 | 0.0471 | 0.001563 |
| OR30 | 3.54 | 3.56 | -0.03 | 0.2783 | 0.0614 | 0.001563 |

The placebo comparison, not the headline sign alone, determines whether the breakout event appears special. A positive headline shared by the placebo is evidence about the ordinary intraday variance-risk premium, not confirmation that breaks create it.

**Reading:** the approximately +3.4 to +3.5 volatility-point headline premium is large and precisely positive, but the matched-clock placebo is essentially identical. The actual-minus-placebo mean is -0.006 points for OR15 and -0.026 for OR30; neither paired t-test approaches the Bonferroni threshold. The archive therefore documents a remaining-session variance-risk premium, not a breakout-specific change in that premium.

## 3. Direct instrument check

The directional option is the ATM CALL after an up-break and ATM PUT after a down-break. The straddle buys both at the same absolute ATM strike. Returns are traded 1-minute close at the break to traded 15:29 close, as a percent of premium.

| spec | instrument | N | mean return | median | win rate | nominal t p | nominal Wilcoxon p | Bonferroni α |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| OR15 | directional ATM option | 1316 | -1.91% | -17.69% | 39.2% | 0.4338 | <0.0001 | 0.001563 |
| OR15 | ATM straddle | 1316 | -1.80% | -6.53% | 34.5% | 0.1121 | <0.0001 | 0.001563 |
| OR30 | directional ATM option | 1313 | 0.95% | -12.36% | 39.8% | 0.6977 | <0.0001 | 0.001563 |
| OR30 | ATM straddle | 1313 | -3.08% | -7.00% | 32.9% | 0.0028 | <0.0001 | 0.001563 |

Paired raw-point comparison (option P&L points minus the directional spot leg's signed follow-through points):

| spec | comparison | N | mean difference (points) | nominal paired-t p | Bonferroni α |
|---|---|---:|---:|---:|---:|
| OR15 | directional option − spot | 1316 | -1.92 | 0.3167 | 0.001563 |
| OR15 | straddle − spot | 1316 | -5.12 | 0.1772 | 0.001563 |
| OR30 | directional option − spot | 1313 | -5.35 | 0.0018 | 0.001563 |
| OR30 | straddle − spot | 1313 | -11.01 | 0.0011 | 0.001563 |

Raw option-price points and NIFTY spot points share index-point units but use different capital and risk. These differences are therefore descriptive, not leverage- or risk-adjusted instrument rankings.

**Execution-bound warning:** all option results use traded close to traded close and exclude bid–ask spread, brokerage, STT, and other costs. They are an **upper bound** on what a real option buyer could achieve.

**Reading:** the option buyer's median and win rate are worse than the directional spot leg in both specifications. Mean directional-option return is -1.91% for OR15 and 0.95% for OR30, but the medians are negative and only about 39% win. The spot leg wins 49.9% and 52.2% of sessions. This is descriptive evidence that spot was the cleaner breakout instrument in this archive; it is not a risk-adjusted or executable ranking.

## 4. Registered splits

Opening-IV quartiles use this module's own 09:15 trading-time CALL/PUT inversion. The panel vendor field is comparison-only. Gamma sign is `gex_otm_trade_w10 < 0`. The `failed` split is the unchanged post-break label returned by `breakout_row`; it is an outcome-defined descriptive split, not an ex-ante strategy.

### OR15

| split | group | N | mean VRP | share > 0 | nominal p | Bonferroni α |
|---|---:|---:|---:|---:|---:|---:|
| breakout_direction | down | 672 | 3.15 | 88.4% | 0.0036 | 0.001563 |
|  | up | 648 | 3.66 | 92.4% |  |  |
| year | 2021 | 247 | 3.23 | 88.3% | <0.0001 | 0.001563 |
|  | 2022 | 247 | 5.00 | 94.3% |  |  |
|  | 2023 | 245 | 2.45 | 94.7% |  |  |
|  | 2024 | 247 | 3.04 | 84.2% |  |  |
|  | 2025 | 248 | 2.79 | 88.7% |  |  |
|  | 2026 | 86 | 4.78 | 95.3% |  |  |
| expiry_day | 0 | 1044 | 3.86 | 92.5% | <0.0001 | 0.001563 |
|  | 1 | 276 | 1.66 | 82.2% |  |  |
| opening_iv_quartile | Q1 | 329 | 1.70 | 85.7% | <0.0001 | 0.001563 |
|  | Q2 | 329 | 2.69 | 90.6% |  |  |
|  | Q3 | 329 | 3.47 | 92.4% |  |  |
|  | Q4 | 329 | 5.84 | 93.6% |  |  |
| dealer_net_gamma_sign | 0 | 1094 | 3.28 | 89.8% | 0.0065 | 0.001563 |
|  | 1 | 226 | 3.97 | 93.4% |  |  |
| failed_breakout | 0 | 107 | 3.34 | 89.7% | 0.8216 | 0.001563 |
|  | 1 | 1213 | 3.41 | 90.4% |  |  |

### OR30

| split | group | N | mean VRP | share > 0 | nominal p | Bonferroni α |
|---|---:|---:|---:|---:|---:|---:|
| breakout_direction | down | 668 | 3.42 | 89.5% | 0.1763 | 0.001563 |
|  | up | 650 | 3.66 | 91.8% |  |  |
| year | 2021 | 247 | 3.36 | 88.3% | <0.0001 | 0.001563 |
|  | 2022 | 247 | 5.08 | 94.3% |  |  |
|  | 2023 | 245 | 2.59 | 94.7% |  |  |
|  | 2024 | 245 | 3.17 | 85.7% |  |  |
|  | 2025 | 248 | 2.97 | 88.7% |  |  |
|  | 2026 | 86 | 4.99 | 95.3% |  |  |
| expiry_day | 0 | 1044 | 4.03 | 93.0% | <0.0001 | 0.001563 |
|  | 1 | 274 | 1.64 | 81.8% |  |  |
| opening_iv_quartile | Q1 | 329 | 1.83 | 86.9% | <0.0001 | 0.001563 |
|  | Q2 | 328 | 2.87 | 89.9% |  |  |
|  | Q3 | 328 | 3.62 | 92.7% |  |  |
|  | Q4 | 329 | 5.91 | 93.9% |  |  |
| dealer_net_gamma_sign | 0 | 1092 | 3.43 | 90.2% | 0.0251 | 0.001563 |
|  | 1 | 226 | 4.03 | 92.9% |  |  |
| failed_breakout | 0 | 110 | 3.07 | 86.4% | 0.2664 | 0.001563 |
|  | 1 | 1208 | 3.58 | 91.1% |  |  |

These heterogeneity p-values are nominal and face the same 0.0015625 threshold. Small subgroups and post-event `failed` labels do not identify a trading rule.

**Reading:** year, expiry-day status, and own opening-IV quartile survive Bonferroni in both OR specifications. VRP is lower on expiry days and rises monotonically from the lowest to highest opening-IV quartile. Breakout direction, dealer-gamma sign, and the post-event failed label do not survive correction. Four sessions without a valid own 09:15 inversion are excluded only from the opening-IV quartile split.

## 5. Coverage and losses

Panel universe: **1320 sessions, 2021-01-01 through 2026-05-12**.

| spec | panel | spot | breakout | ATM C+P quote | valid own IV | final VRP N | option P&L N | min valid placebo draws |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| OR15 | 1320 | 1320 | 1320 | 1320 | 1320 | 1320 | 1316 | 87 |
| OR30 | 1320 | 1320 | 1318 | 1318 | 1318 | 1318 | 1313 | 138 |

Exclusive post-breakout losses:

- **OR15:** none
- **OR30:** none

Sessions without a resolvable breakout: **OR15 none**; **OR30 2024-10-24, 2024-11-21**. They are not silently included in the OR30 final N.

Same-entry-strike 15:29 option exits absent from the archive: **OR15 4** (2021-02-01, 2024-03-21, 2025-04-30, 2026-02-01), **OR30 5** (2021-02-01, 2024-03-21, 2025-04-30, 2025-05-15, 2026-02-01). These sessions remain in the VRP estimand and are excluded only from EST-04 option P&L.

Each session received 200 placebo draw attempts. Invalid quote/inversion draws remain missing rather than being replaced after observing availability; the minimum valid count is 87 and the median is 200. This preserves the pre-drawn clock distribution and makes placebo missingness visible.

The archive scan read 2,772 files and found 0 missing; it scanned 20,860,781 source rows and retained 595,732 deduplicated required-minute rows. Deduplication key was `(date, clock, side, absolute strike)`, keeping highest volume.

## 6. Validation

### Trading-time reproduction guard

Own 09:15 IV was recomputed on every comparable panel date, rather than a favourable subsample: **N=1316**, correlation with panel vendor `atm_iv_open` = **0.7142**, own mean = **12.76**, panel-vendor mean = **18.74**, own-minus-panel mean difference = **-5.98 vol points**. The predeclared large-divergence flag (correlation <0.90 or |mean gap|>2 points) is **True**. The level gap is expected when vendor convention embeds non-trading time, but the 0.714 correlation shows that this is not merely a constant shift. Vendor and own IV are not interchangeable; all headline, placebo, and opening-IV-quartile calculations therefore use the own trading-time inversion.

### Lookahead and state audit

- Imported `nge_breakout_test.breakout_row()` unchanged; source SHA-256 `616371b49bf560e8f4b8ca4ac1bf58aeb95ba8621d77b285ff031cfc6654b2d7`.
- Recomputed opening-range endpoints and checked first passage using rows no later than the break: range violations **0**, earlier-crossing violations **0**.
- Break IV was joined on exact `(date, bo_clock)` only. No forward-fill, interpolation, daily IV, close IV, or later quote entered it.
- ATM was selected from archive **absolute strikes** at that minute after deduplication; target minutes farther than 25 points from selected ATM: **0**.
- `failed`, option exit P&L, and RV are post-event outcomes. They never define the break or entry quote.

### Multiple-testing ledger

| ID | registered test |
|---|---|
| OR15-T01 | VRP one-sample t-test |
| OR15-T02 | VRP Wilcoxon signed-rank |
| OR15-T03 | break-minus-placebo paired t-test |
| OR15-T04 | break-minus-placebo Wilcoxon signed-rank |
| OR15-T05 | VRP by breakout direction (Welch) |
| OR15-T06 | VRP by year (Kruskal-Wallis) |
| OR15-T07 | VRP by expiry-day status (Welch) |
| OR15-T08 | VRP by opening-IV quartile (Kruskal-Wallis) |
| OR15-T09 | VRP by dealer net-gamma sign (Welch) |
| OR15-T10 | VRP by failed label (Welch) |
| OR15-T11 | directional-option return one-sample t-test |
| OR15-T12 | directional-option return Wilcoxon signed-rank |
| OR15-T13 | straddle return one-sample t-test |
| OR15-T14 | straddle return Wilcoxon signed-rank |
| OR15-T15 | directional-option minus spot points paired t-test |
| OR15-T16 | straddle minus spot points paired t-test |
| OR30-T01 | VRP one-sample t-test |
| OR30-T02 | VRP Wilcoxon signed-rank |
| OR30-T03 | break-minus-placebo paired t-test |
| OR30-T04 | break-minus-placebo Wilcoxon signed-rank |
| OR30-T05 | VRP by breakout direction (Welch) |
| OR30-T06 | VRP by year (Kruskal-Wallis) |
| OR30-T07 | VRP by expiry-day status (Welch) |
| OR30-T08 | VRP by opening-IV quartile (Kruskal-Wallis) |
| OR30-T09 | VRP by dealer net-gamma sign (Welch) |
| OR30-T10 | VRP by failed label (Welch) |
| OR30-T11 | directional-option return one-sample t-test |
| OR30-T12 | directional-option return Wilcoxon signed-rank |
| OR30-T13 | straddle return one-sample t-test |
| OR30-T14 | straddle return Wilcoxon signed-rank |
| OR30-T15 | directional-option minus spot points paired t-test |
| OR30-T16 | straddle minus spot points paired t-test |

Registered count: **32** · Bonferroni threshold: **0.0015625**. The JSON attaches this threshold to every inferential p-value.

## 7. Identification and object ledger

| object | category | timing/source | role and boundary |
|---|---|---|---|
| opening-range breakout | deterministically derived | spot closes through the break, unchanged imported function | event; first passage only |
| absolute ATM strike | deterministically derived | archive strikes and spot at the exact minute | nearest strike; lower strike wins an exact tie |
| break IV | estimated/model-dependent | traded CALL+PUT closes at break; BS, r=0.065, trading time | headline expectation proxy; depends on BS inversion |
| post-break RV | deterministically derived | 1-minute spot returns after break through 15:29 | realised volatility outcome |
| VRP | deterministically derived from estimated IV | break IV minus subsequent RV | descriptive premium, not causal |
| option P&L | observed/derived | traded closes at break and 15:29, same absolute strike | model-free before costs; upper bound after omitted spreads |
| dealer gamma sign | proxy | panel `gex_otm_trade_w10` at open | position-sign proxy, not observed dealer inventory |
| executable net return | **Unidentified** | bid/ask and costs absent | traded closes cannot identify attainable execution |

## 8. Specification audit

| ID | status | implementation/evidence |
|---|---|---|
| DATA-01 | Implemented | `nge_panel.csv`; N/date span and flow reported |
| DATA-02 | Implemented | `analyze_still_water_spot.load_spot()` via `load_spot_by_date`, 09:15–15:29 |
| DATA-03 | Implemented | all manifest rows enumerated with `manifest_rows/cached_path`; required columns read |
| DATA-04 | Implemented | absolute contract-minute key; highest volume retained |
| STATE-01 | Implemented | unchanged imported `breakout_row`; OR15 and OR30 |
| STATE-02 | Implemented | nearest absolute archive strike at exact break minute |
| STATE-03 | Implemented | own CALL/PUT BS inversion, r=0.065; vendor IV secondary only |
| STATE-04 | Implemented | exact remaining minutes plus archive-session count, 375×252 |
| STATE-05 | Implemented | mean squared 1-minute post-break log returns; per-session count in CSV |
| STATE-06 | Implemented | same pre-break RV construction; descriptive column and summary |
| EST-01 | Implemented | moments, positive share, t and Wilcoxon |
| EST-02 | Implemented | 200 draws/session, seed 20260823, identical pipeline, paired tests |
| EST-03 | Implemented | all seven requested splits; opening quartiles use own trading-time IV |
| EST-04 | Implemented | directional option, straddle, and paired raw-point spot comparisons |
| VAL-01 | Implemented | all-date 09:15 own-IV reproduction guard |
| VAL-02 | Implemented | frozen 32-test ledger and p-value threshold |
| VAL-03 | Implemented | exact-minute/source-hash/first-passage audits |
| VAL-04 | Implemented | full sample flow and exclusive loss reasons |
| OUT-01 | Implemented | this report |
| OUT-02 | Implemented | both requested CSV panels, including ineligible rows/reasons |
| OUT-03 | Implemented | structured JSON results and audits |
| OUT-04 | Implemented | deterministic analysis script and new quote cache |

Required components: **22/22 implemented** · Partial: **0** · Missing: **0** · Unidentified required components: **0**. The executable after-spread return is explicitly Unidentified but is an exclusion, not a required estimand. Unapproved scope reductions: **0** · proxy substitutions: **0**.

## 9. What is and is not established

This archive can document whether break-minute trading-time IV exceeded subsequent same-session RV, whether that difference was unusual relative to matched clocks, and how traded-close option P&L behaved before costs. It cannot establish a causal breakout effect, a persistent out-of-sample premium, executable profitability after spread and charges, or a deployable long/short-vol rule. The many registered splits are screening evidence only. No Gate A/Gate B conclusion or live state changes.
