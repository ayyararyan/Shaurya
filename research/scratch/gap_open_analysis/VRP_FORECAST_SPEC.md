# Forecasting RV − IV to expiry — Frozen Specification

**Date:** 2026-08-23
**Requested by:** Aryan (voice, 13:27 IST): *"We have implied volatility as well as realized
volatility over the observed period to expiration. I want to find a simple method where we can
forecast RV minus IV, and how accurate is it. Do that exercise over maybe a year or two of data,
and do not touch the recent one year so we can use that as out-of-sample."*
**Status:** Exploratory. No Gate A / Gate B specification change. No gate armed. No broker,
credential, or order path. Offline analysis only.

---

## 1. Research question

At the open of session *d*, the ATM weekly implied volatility `IV_d` is **observed**. The
volatility the index subsequently delivers between that moment and the option's expiry,
`RV_d`, is not. Is the spread

    VRP_d  =  RV_d  −  IV_d           (Aryan's sign: positive = the buyer was underpaying)

**forecastable out of sample** from information available at 09:15 on day *d*, and by how much?

## 2. Why it matters

The project's standing economic conclusion is that money leaves a long-premium NIFTY position at
entry, not at exit: implied is paid at ~15 (calendar convention) / ~11.7 (trading-time convention)
and realised arrives at ~8.5 / ~8.2. That is a *level* result — a constant. It says long premium
is a bad average trade; it says nothing about whether the *deviation* from that average is
predictable. If it is, the direction question the project has repeatedly failed to answer becomes
irrelevant: one would simply buy vol when the spread is forecast wide and sell (or stand aside)
when it is forecast narrow.

**Identity that governs the whole exercise (ID-01).** `IV_d` is observed at the forecast origin.
Therefore forecasting `RV_d − IV_d` is *arithmetically identical* to forecasting `RV_d` and
subtracting a known number. Any apparent skill must come from realised-volatility predictability,
which is well documented (volatility clustering, HAR). The honest benchmark is therefore **not**
zero and **not** a naive RV model — it is the **in-sample mean of the spread itself**, because a
trader who knows only "options are systematically ~3–7 vol points rich" already has that constant
for free. Reporting R² against zero would be a fabricated result.

## 3. Estimand

    IV_d  = ATM implied volatility at 09:15 on day d, own Black–Scholes inversion,
            CALL and PUT averaged, trading-time maturity
    RV_d  = annualised realised volatility of NIFTY spot from 09:15 on day d
            through 15:29 on the expiry date of the nearest weekly (WEEK1)
    VRP_d = RV_d − IV_d,  in annualised volatility points

Both legs annualised in the **trading-time convention**: 375 minutes per session, 252 sessions per
year (`CORRECTION_GATE_B_VOL_CRUSH.md`; calendar-time maturity is forbidden in this project's
headlines).

## 4. Requirements

### Data

| ID | Requirement |
|---|---|
| DATA-01 | Universe = every session in the hydrated archive with a resolvable next weekly expiry and a complete spot path. Report N and date span. |
| DATA-02 | Option quotes from `nge_common.load_snapshot()` (09:15 and 15:29 bars, absolute strike, highest-volume dedup). Do **not** rebuild a separate chain. |
| DATA-03 | Spot minute closes via `analyze_still_water_spot.load_spot()`, restricted to 09:15–15:29. |
| DATA-04 | Expiry calendar = `k2_expiry_calendar.csv` (`actual_expiry`), the project's incumbent, via `nge_common._expiry_dates()`. |
| DATA-05 | India VIX levels from `k2_expiry_vix_rose_panel.csv` (`vix_open`, `vix_prior_session_close`, `vix_known_by_decision`). Coverage starts 2021-08-04 — VIX-using models are fitted on the reduced sample and reported **separately**, never merged into the headline sample count. |

### State construction

| ID | Requirement |
|---|---|
| STATE-01 | ATM strike at 09:15 = archive strike closest to 09:15 spot, resolved on the **absolute** strike, never on the rolling `rel_strike` label. |
| STATE-02 | `T_d` (trading-time years) = `sessions_to_expiry / 252`, sessions counted inclusively over archive sessions from *d* to the expiry date (`nge_common.trading_sessions_between`). |
| STATE-03 | `IV_d` = own BS inversion (r = 0.065) of the traded 09:15 `close` of the ATM CALL and the ATM PUT, averaged over the two sides that invert successfully. The vendor `iv` column is carried as a **comparison column only**, never as the headline. |
| STATE-04 | Per-session realised variance `RVar_s` = Σ of squared 1-minute log spot returns within session *s* (09:15→15:29). A 5-minute-sampled variant is carried as a sampling sensitivity. |
| STATE-05 | Overnight variance = squared log return from 15:29 close of session *s* to 09:15 spot of session *s+1*. |
| STATE-06 | **Headline** target: `RV_d = sqrt( ( Σ_{s=d..E} RVar_s + Σ overnight ) / T_d )`. The option holder is exposed to overnight gaps, so they belong in the numerator; the trading-time denominator says nights carry no *time*. Both conventions are reported. |
| STATE-07 | **Secondary** target: intraday-only numerator (no overnight term), which is the convention every prior project number used. Report both; state which is which. |

### Predictors — all strictly past-only (LEAK-01)

| ID | Requirement |
|---|---|
| PRED-01 | `iv` — `IV_d` itself, observed at the origin. |
| PRED-02 | `rv1`, `rv5`, `rv22` — annualised realised volatility over the previous 1 / 5 / 22 **completed** sessions, ending 15:29 of session *d−1*, same numerator convention as the target. HAR components. |
| PRED-03 | `carry` = `rv22 − iv` — the currently observable spread. |
| PRED-04 | `n_sess` (horizon in sessions), `is_expiry_day`, `dow`. |
| PRED-05 | `gap` — overnight gap of session *d* (known at 09:15). |
| PRED-06 | `vix_open`, `vix_overnight_gap` — reduced-sample block only. |
| LEAK-01 | No predictor may use any bar at or after 09:16 on day *d*, and no trailing window may include day *d*. An explicit audit must assert this and appear in the report. |

### Models

| ID | Requirement |
|---|---|
| MOD-00 | **Benchmark.** Constant = training-sample mean of `VRP`. Every reported skill number is against this. |
| MOD-01 | OLS: `VRP ~ iv + rv5`. |
| MOD-02 | HAR OLS: `VRP ~ iv + rv1 + rv5 + rv22`. |
| MOD-03 | HAR + structure: MOD-02 `+ n_sess + is_expiry_day + |gap| + carry`. |
| MOD-04 | Ridge on all standardised features, penalty chosen by a **forward-chaining** (never shuffled) CV inside the training window only. |
| MOD-05 | Decomposition model: forecast `log RV` by HAR, exponentiate, subtract the observed `IV_d`. Same information, different functional form; exists to make ID-01 visible. |
| MOD-06 | VIX-augmented MOD-03 on the reduced sample. |

### Out-of-sample design

| ID | Requirement |
|---|---|
| OOS-01 | Test window = the final 12 months of the archive, **never touched during fitting or specification choice**. |
| OOS-02 | Training variants: (A) all sessions before the test window; (B) the two years before it; (C) the one year before it. Aryan asked for "a year or two"; all three are reported so the sample-length effect is visible rather than chosen. |
| OOS-03 | Primary metric = out-of-sample R² against MOD-00 (Campbell–Thompson form: `1 − SSE_model / SSE_benchmark`, benchmark mean estimated on **training** data only). Also RMSE, MAE, correlation, and sign-of-deviation accuracy. |
| OOS-04 | Tercile sort: mean realised `VRP` in the test window by forecast tercile, plus the top-minus-bottom spread. |
| OOS-05 | **Overlap-aware inference.** Consecutive observations share up to 10 sessions of the same realised path. Report Newey–West (lag = max horizon) standard errors, and re-run the whole evaluation on a **non-overlapping** subsample (one session per expiry cycle). |
| OOS-06 | **Placebo.** Block-bootstrap / permutation of the forecast series within the test window (≥1,000 draws, seed 20260823) to give the null distribution of OOS R². Report the empirical p-value. |
| OOS-07 | **Economic read-out.** Share of test sessions with `VRP > 0` overall and within the top forecast tercile; the mean spread in the top tercile against the unconditional mean. A forecast that never predicts a positive spread is a forecast that never says "buy". |

### Validation

| ID | Requirement |
|---|---|
| VAL-01 | Reproduction guard: the sample-wide mean `IV` and mean `RV` must be consistent with the project's published trading-time figures (11.67 vs 8.16 on the Gate B population). Any deviation must be explained by the stated population/horizon difference, not waved away. |
| VAL-02 | Hand-check 3 sessions end to end against the raw archive CSVs. |
| VAL-03 | Assert zero calendar-time maturity in any headline path. |
| VAL-04 | Assert the leakage audit (LEAK-01) passes. |

## 5. Explicit exclusions

- No option P&L, no trade simulation, no execution costs — this measures forecast accuracy of a
  volatility spread, not the returns of a strategy. The strategy question is downstream and is
  **not** authorised by this spec.
- No expiries beyond WEEK1 (the archive has none).
- No intraday re-forecasting; one forecast per session at 09:15.
- No machine-learning model beyond penalised linear regression. Aryan asked for a *simple method*;
  the project has already established that the ML branch scored AUC 0.500 on the direction problem.

## 6. Completion criteria

Report states, for each training variant and each target convention: OOS R² vs MOD-00, its
placebo p-value, the tercile table, the non-overlapping replication, and a plain-English verdict
on whether the spread is forecastable to a useful degree.
