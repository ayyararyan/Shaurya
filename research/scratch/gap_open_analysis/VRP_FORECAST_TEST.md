# Forecasting RV − IV to expiry on NIFTY weeklies

**Date:** 2026-08-23 · **Status:** exploratory offline analysis · **Frozen specification:** `VRP_FORECAST_SPEC.md`
**No broker, credentials, order path, live trading, or Gate A / Gate B change. No gate armed.**
Scripts: `vrp_forecast_common.py` (panel), `vrp_forecast.py` (estimation), `vrp_forecast_handcheck.py` (VAL-02).
Artifacts: `vrp_forecast_panel.pkl`, `vrp_forecast_results.json`, `vrp_forecast_handcheck.json`,
`vrp_forecast_archive_spot_audit.json`.

---

## Owner summary

The question was whether the gap between the volatility you pay at the open and the volatility the
index actually delivers before expiry can be **forecast**, and how accurately, with the most recent
year kept untouched as an out-of-sample test.

**Answer: partly — and the forecastable part is not the part an option can trade.**

Two things had to be separated, and separating them is the whole result.

1. **Realised volatility measured only during market hours** is highly forecastable. On the 246
   untouched sessions the simplest sensible model explains **63–67%** of the variation in
   `RV − IV`, survives every robustness cut, and beats its placebo at p = 0.000. This is a
   textbook HAR result correctly reproduced, not a discovery.
2. **Realised volatility including overnight gaps** — which is what an option holder is actually
   exposed to, because the position stays on through the night — is **barely forecastable**.
   The same models get **R² ≈ +0.15** on the daily sample and **−0.09 to +0.14** across five
   genuinely independent subsamples, with only 3 of 10 cells beating their placebo at 5%.

The difference between those two numbers is the overnight jump. It is **17.7%** of total variance
on average, implied volatility does not price it, and past volatility barely forecasts it
(out-of-sample R² 0.22). It is the noise that decides whether a multi-day option pays, and it is
close to unforecastable.

**The decision-relevant fact.** Across the untouched year the model essentially never says "buy":
it predicts a positive spread on **0.4%** of sessions. Even in the third of days it ranks cheapest,
realised `RV − IV` averaged **−0.39 volatility points** and was positive only **36.6%** of the time.
So the forecast does have real information — it separates days that were very expensive from days
that were only slightly expensive, a spread of about **1.9 volatility points** — but there is no
subset of the untouched year in which buying volatility had a positive expected edge.

**Interpretation change:** none to any gate. It sharpens the standing economics: the volatility
risk premium is not only a level, it is a level whose *deviations* are mostly unforecastable at the
horizon a weekly option lives on. **Action needed from Aryan:** none for this test. **Bottom line:**
the spread is forecastable enough to rank sellers' opportunities, not enough to create a buyer's.

---

## 1. What was built

One row per NIFTY session, 09:15 origin, nearest weekly (WEEK1) expiry.

- `IV` — own Black–Scholes inversion (r = 0.065) of the traded 09:15 close of the ATM CALL and the
  ATM PUT, averaged, **trading-time maturity** (375 min/session, 252 sessions/year).
- `RV` — annualised realised volatility of NIFTY spot from that minute through 15:29 on the expiry
  date: Σ squared 1-minute log returns across every session in the window, divided by the same
  trading-time maturity. Reported in **two conventions**: with overnight gap returns in the
  numerator (headline, what the holder is exposed to) and intraday-only (the convention every
  earlier number in this project used).
- `VRP = RV − IV`, Aryan's sign. Positive = the buyer underpaid.

**Panel:** 1,298 sessions, **2021-02-03 to 2026-05-12** (the first 22 sessions are consumed by the
`rv22` predictor). The archive ends 2026-05-12, so "the recent one year" is **2025-05-13 →
2026-05-12, n = 246**, never touched during fitting or specification.

| convention | mean IV | mean RV | mean VRP | median | sd | share VRP > 0 |
|---|---:|---:|---:|---:|---:|---:|
| RV includes overnight (headline) | 12.70 | 10.78 | **−1.92** | −1.93 | 3.17 | 19.6% |
| RV intraday only (incumbent) | 12.70 | 9.46 | **−3.24** | −3.00 | 3.03 | 9.6% |

**This is itself a correction worth noting.** Every prior premium figure in this project was
intraday-only. Once the overnight gaps the option is genuinely exposed to are put back in the
numerator, the average premium on this population falls from **3.24 to 1.92 volatility points** —
about **41% of the apparent premium was an artifact of leaving the nights out of realised
volatility while the option carried them.** Nothing published is retracted (the Gate A/Gate B
numbers were same-session objects with no overnight in them), but any *multi-day* claim built on
the intraday convention overstates the seller's edge by roughly 1.3 volatility points.

Predictors, all strictly past-only: `iv` (observed at the origin), HAR components `rv1 / rv5 / rv22`
(trailing 1/5/22 **completed** sessions, ending 15:29 of the prior day, same numerator convention),
`carry = rv22 − iv`, `n_sess` (horizon), `is_expiry_day`, `gap`, `|gap|`, `dow`, and India VIX on
the reduced sample.

## 2. The benchmark question, decided before looking at results

`IV` is **observed** at the forecast origin. Forecasting `RV − IV` is therefore arithmetically the
same as forecasting `RV` and subtracting a known number, so a naive R² against zero would be a
fabricated result. Two benchmarks are carried throughout:

- **MOD-00** — the constant: the training-sample mean of the spread. A trader who knows only
  "weeklies are systematically rich" has this for free. **This is the benchmark that matters.**
- **MOD-00b** — assume `RV` lands on its training average and subtract the observed `IV`. Zero
  volatility-forecasting skill, pure mechanics.

On the headline convention MOD-00b scores **R² = −0.75** against MOD-00, i.e. it is far *worse*
than the constant. When implied volatility is high, realised volatility is high too, so the spread
does not move one-for-one with `IV`. **The mechanical channel contributes nothing here** — whatever
skill the models have is genuine realised-volatility forecasting.

## 3. Headline result — RV including overnight gaps, 246 untouched sessions

R² is against MOD-00. "sign acc" is the share of sessions on which the forecast got the *direction
of the deviation from the training mean* right. Newey–West lag = 10 (the maximum horizon).

| training window | model | OOS R² | RMSE | corr | sign acc | NW p | placebo p | bottom tercile | top tercile |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A: all prior (n=1052) | MOD-00 constant | +0.000 | 3.94 | — | — | — | — | −1.57 | −1.64 |
| A | MOD-01 `iv + rv5` | +0.127 | 3.68 | +0.334 | 67.5% | 0.0066 | 0.000 | −2.24 | −0.40 |
| A | MOD-02 HAR | **+0.146** | 3.64 | +0.365 | 68.3% | 0.0054 | 0.000 | −2.29 | −0.39 |
| A | MOD-03 HAR + structure | +0.145 | 3.64 | +0.361 | 66.3% | 0.0053 | 0.000 | −2.43 | −0.64 |
| A | MOD-04 ridge (all features) | +0.103 | 3.73 | +0.315 | 66.7% | 0.0016 | 0.006 | −2.18 | −0.71 |
| A | MOD-05 log-RV HAR, then subtract IV | **+0.165** | 3.60 | +0.411 | 68.3% | 0.0186 | 0.000 | −2.24 | −0.25 |
| B: two years (n=492) | MOD-02 HAR | +0.076 | 3.75 | +0.290 | 62.2% | 0.129 | 0.025 | −2.30 | −0.59 |
| B | MOD-05 | +0.070 | 3.76 | +0.354 | 63.4% | 0.434 | 0.000 | −2.24 | −0.42 |
| C: one year (n=247) | MOD-02 HAR | +0.083 | 3.77 | +0.266 | 66.7% | 0.053 | 0.051 | −2.32 | −0.62 |
| C | MOD-05 | +0.044 | 3.85 | +0.337 | 67.1% | 0.662 | 0.000 | −2.25 | −0.47 |

**Training length matters and the answer is against the brief.** Aryan asked for "a year or two".
Fitting on the full 4.3 years roughly **doubles** out-of-sample accuracy (R² 0.15–0.17) relative to
one or two years (0.04–0.08), and the short windows stop clearing their placebo. Volatility models
want long samples; there is no regime argument in this archive for throwing the early years away.

**Complexity does not help.** The best model is the simplest structural one — a HAR on log realised
volatility, exponentiated, minus the observed `IV`. Ridge with every feature is worse. Adding
horizon, expiry-day, gap and carry adds nothing (+0.145 vs +0.146). India VIX adds **+0.006 of R²**
on its reduced sample (905/246 split, MOD-03 0.1251 → MOD-06 0.1313) — nothing.

## 4. What the accuracy is actually worth

| | value |
|---|---:|
| RMSE of the forecast | 3.64 vol points |
| RMSE of the constant benchmark | 3.94 vol points |
| improvement | **0.30 vol points, 7.6%** |
| correlation forecast vs realised | +0.365 |
| sign-of-deviation accuracy | 68.3% |
| tercile spread (top − bottom) | **+1.91 vol points** |
| sessions where the forecast is **positive** | **0.4%** (1 of 246) |
| realised VRP > 0, all sessions | 26.8% |
| realised VRP > 0, top forecast tercile | 36.6% |

Read the last three rows together. The model has real ranking information — a 1.9-point spread
between its cheapest and dearest thirds is economically large next to a 1.9-point average premium —
but it **never predicts that volatility is cheap**, and the third of days it likes best still
realised a negative spread on average and paid off on barely a third of them.

## 5. Robustness — where the headline weakens

**Overlap.** Consecutive sessions share up to 10 sessions of the same realised path, so 246 daily
rows contain only about 51 independent horizons. Two corrections were run.

*Non-overlapping subsamples.* A session at position *p* inside one expiry cycle cannot share a
realised path with the session at position *p* in the next cycle. All five phases:

| phase | n | MOD-02 R² | placebo p | MOD-05 R² | placebo p |
|---|---:|---:|---:|---:|---:|
| 0 (first session of the cycle) | 51 | **−0.122** | 0.369 | −0.092 | 0.288 |
| 1 | 51 | +0.111 | 0.056 | +0.141 | 0.018 |
| 2 | 51 | +0.070 | 0.202 | +0.058 | 0.115 |
| 3 | 51 | +0.111 | 0.000 | +0.093 | 0.000 |
| 4 | 38 | +0.130 | 0.051 | +0.070 | 0.076 |

Median across the ten phase cells ≈ **+0.08**, one phase negative, **3 of 10 cells** beat their
placebo at raw 5% (phase 1 MOD-05, phase 3 both models). The headline +0.15 is not an artifact — four of five phases are positive — but on independent
observations it is a small, unstable effect, not a robust one.

*Newey–West.* The improvement in squared error over the constant has NW t = 2.78, p = 0.0054 at
lag 10 for MOD-02. MOD-05, the better point forecast, is weaker under HAC (p = 0.019) because its
errors are more autocorrelated.

**Horizon.** Skill is concentrated at short maturities and gone by mid-week:

| sessions to expiry | n | mean VRP | OOS R² |
|---:|---:|---:|---:|
| 1 (expiry day) | 52 | −1.64 | **+0.384** |
| 2 | 51 | −1.51 | +0.177 |
| 3 | 52 | −1.65 | +0.071 |
| 4 | 50 | −1.42 | +0.007 |
| 5 | 37 | −1.35 | **−0.030** |

On expiry day there is no overnight gap left in the window at all — which is precisely why R²
jumps to 0.38 there and decays to zero as more nights enter.

**Regime drift.** The training mean spread is −2.04; the test-year mean is **−1.41**. The premium
narrowed by 0.6 points in the untouched year, so the benchmark itself was mis-centred against the
test period. This helps no model in particular but it is a live caution: the constant is not stable.

## 6. The contrast that explains everything — intraday-only

Same code, same split, same predictors; only the overnight term is removed from the target.

| training window | model | OOS R² vs MOD-00 | RMSE | corr | sign acc | placebo p |
|---|---|---:|---:|---:|---:|---:|
| A | MOD-02 HAR | +0.638 | 2.05 | +0.803 | 85.8% | 0.000 |
| A | MOD-05 log-RV HAR | **+0.665** | 1.97 | +0.820 | 84.6% | 0.000 |
| B two years | MOD-05 | +0.621 | 2.08 | +0.802 | 74.0% | 0.000 |
| C one year | MOD-05 | +0.624 | 2.07 | +0.790 | 77.6% | 0.000 |

And it holds on every non-overlapping phase: **+0.65, +0.69, +0.63, +0.56, +0.30**, placebo p = 0.000
in all five. Nothing fragile about it.

The gap between 0.67 and 0.15 is the overnight jump:

| | value |
|---|---:|
| overnight share of total realised variance, mean | **17.7%** |
| median | 12.7% |
| 90th percentile | 44.8% |
| out-of-sample R² forecasting the overnight vol contribution itself | **0.22** |
| correlation of that forecast with the outcome | +0.48 |

Overnight variance is not *entirely* unforecastable, but it is the large, poorly-predicted piece,
and implied volatility does not price it separately. **The forecastable part of realised volatility
is the intraday diffusion; the part that decides whether a multi-day option pays is the overnight
jump.** You cannot buy the first without also buying the second.

This is the same structural moral as the project's Merton (1980) result on trend days — that a
short-window drift estimate is nearly worthless — arriving from the other direction: here the
*diffusion* is estimable, exactly as Merton says, and it is still not enough, because the option's
payoff loads on a jump component the estimate does not cover.

## 7. In-sample coefficients (interpretation only, MOD-03, training window A)

| | `iv` | `rv1` | `rv5` | `rv22` | `n_sess` | `is_expiry` | `|gap|` | `carry` | in-sample R² |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RV incl. overnight | −0.187 | +0.077 | −0.053 | −0.097 | +0.212 | −0.059 | +0.818 | +0.090 | 0.154 |
| RV intraday only | −0.315 | +0.130 | −0.062 | −0.174 | +0.034 | +0.861 | +0.754 | +0.141 | 0.459 |

Signs are economically sensible: a higher `IV` widens the negative spread (options get richer
faster than realised volatility follows), a larger opening gap narrows it (turbulent opens deliver
volatility), longer trailing volatility windows push it more negative (mean reversion after quiet
periods raises implied faster than realised).

## 8. Verification

| check | result |
|---|---|
| **VAL-02** hand-check, 3 sessions (2021-09-08, 2024-02-20, 2026-01-29) recomputed end to end from the raw archive CSVs by an independent code path | **worst absolute discrepancy 0.0000000000 volatility points** |
| **VAL-03** calendar-time maturity in any headline path | none — every maturity is `n_sessions / 252` |
| **VAL-04** leakage audit | `rv1/rv5/rv22` are cumulative sums ending strictly before the origin session; `gap` uses the prior close and the 09:15 spot; `iv` uses the 09:15 bar only; nothing at or after 09:16 on the origin day enters any predictor |
| **OOS-06** placebo | 2,000 circular shifts of the forecast series per cell, seed 20260823, preserving the forecast's own autocorrelation; empirical p reported in every table above |
| **OOS-01** test-window hygiene | the test window was never read during specification, feature choice, or model selection; ridge penalty chosen by forward-chaining CV *inside* the training window |
| **VAL-01** reproduction guard | mean own-inverted trading-time `IV` = 12.70 on all 1,298 sessions, against the project's published 11.67 on the 120-day Gate B population. Different population, different origin (09:15 vs the fill minute), same ballpark, same convention. Not an exact reproduction and is not claimed as one. |

### Data-integrity finding (triggered by the first draft of VAL-02, §9 of the working contract)

The first hand-check blew up by 3,136 volatility points on 2021-09-08. Cause: **some option CSVs in
the archive carry a different index's spot in the `spot` column.** A full scan of all 2,772 files
against the project's reference spot tape:

- **74 files** contain at least one row whose `spot` is more than 5% away from the reference;
  **1,164 rows** in total (~0.006% of ~19M rows).
- The contamination is **BANKNIFTY**: e.g. `2021-07-30…ATM+10` shows spot 35,836 with strike 36,800
  on days when NIFTY was 16,549. It sits almost entirely on the **far wings (ATM+8 … ATM+10)** in
  **2021–2022**, where the vendor's strike resolution evidently matched a Bank Nifty contract.
- **The 09:15 / 15:29 snapshot the project actually uses is clean**: 2 contaminated rows out of
  109,909, **both at 15:29, both on one 2021 date, zero at 09:15.** The NGE dealer-gamma work,
  which reads the full chain at 09:15, is therefore **not affected**.
- `analyze_still_water_spot.load_spot()` reads only the 66 ATM/CALL files and has **zero** sessions
  with a >2% one-minute move — the spot tape behind every realised-volatility number here is clean.

**Standing caution for the archive:** never read `spot` from an arbitrary strike file. Use
`load_spot()` or cross-check against it. Affected files are listed in
`vrp_forecast_archive_spot_audit.json`; contaminated snapshot rows in
`vrp_forecast_snapshot_contaminated_rows.csv`.

## 9. Limits

- **No P&L.** This measures forecast accuracy of a volatility spread. It does not simulate an
  option trade, and there are no bid–ask, STT, or brokerage costs anywhere in it. A 1.9-point
  tercile spread on a 12.7-vol ATM weekly is real but was not converted into money, and the
  project's own execution work says costs eat a large fraction of anything this size.
- **WEEK1 only.** The archive has no further-dated expiry, so the natural follow-up — is the
  premium, or its forecastability, different further out on the curve — is still blocked on the
  WEEK2/WEEK3 download already ranked #3 in the topic file.
- **One origin per day.** Forecasts are made at 09:15 only; no intraday re-forecasting.
- **Effectively ~51 independent horizons in the test year.** The confidence intervals implied by
  246 daily rows are optimistic; §5's phase table is the honest picture.
- Multiplicity: 42 headline evaluation cells plus 20 phase cells were computed. The intraday result
  clears any correction trivially; **the headline +0.15 would not survive a Bonferroni correction
  over the phase family**, which is exactly why it is reported as small-and-unstable rather than as
  a finding.
