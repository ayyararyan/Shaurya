# Shaurya RV Model — Frozen Specification

**Model ID:** `RV-V2-DAY-GAMMA-ESSVI-2026-09-10`  
**Status:** **FROZEN**  
**Frozen:** 2026-09-10  
**Forecast origin:** completed 10:00 IST one-minute bar  
**Underlying:** NIFTY 50  
**Horizon:** 10:00 IST to nearest listed weekly expiry close  
**Primitive target:** forward integrated realized variance  
**Operational q threshold:** **`q < 0.825`**  
**Sensitivity band:** `0.80-0.85` (diagnostic only)

This document and `frozen_model_coefficients.json` define the frozen RV-V2 model. `RV_Q_THRESHOLD_RECALIBRATION_2026.md` defines the threshold study. Any conflicting older NSGVC constants remain historical/legacy objects and do not redefine RV-V2.

---

## 1. Frozen architecture

The forecaster decomposes the holding-period variance into economically distinct in-session and closed-market components:

\[
\boxed{\widehat V_{total,t}=\widehat V_{day,t}+\widehat V_{night,t}}.
\]

Let

- \(\theta_t\) = nearest-weekly eSSVI ATM total variance at 10:00;
- \(T_t\) = calendar year fraction from 10:00 to expiry close;
- \(\sigma_{IV,t}=\sqrt{\theta_t/T_t}\);
- \(\tau_{N,t}\) = total calendar year fraction in future close-to-next-open intervals before expiry.

The frozen equations are

\[
\boxed{\widehat V_{day,t}=1.0966512633204137\exp(\eta_{D,t})}
\]

and

\[
\boxed{\widehat V_{night,t}=\frac{\theta_t}{T_t}\tau_{N,t}
\exp\{\operatorname{clip}(\eta_{N,t},-5,5)\}}.
\]

Therefore

\[
\widehat\sigma_{RV,t}=\sqrt{\widehat V_{total,t}/T_t},
\qquad
\boxed{q_t=\widehat V_{total,t}/\theta_t}.
\]

The trading gate uses **q in variance units**, not the volatility ratio `sqrt(q)`:

\[
\boxed{\text{entry/continue when }q_t<0.825}.
\]

---

## 2. Why day and night are separate

For a coming close-to-open interval define the option-implied calendar-time variance budget

\[
B_{N,t}=\sigma_{IV,t}^2\Delta\tau_t
\]

and realized overnight variance

\[
V_{N,t}=\left[\log(O_{t+1}/C_t)\right]^2.
\]

The empirical ratio is \(R_{N,t}=V_{N,t}/B_{N,t}\).

Pre-holdout evidence showed:

- 94.35% of historical nights had `R_N < 1`;
- median `R_N = 0.08252`;
- mean `R_N = 0.30772`;
- among the pre-specified normal 95% nights, 99.35% had `R_N < 1` and median `R_N = 0.07224`.

On the fresh May-August 2026 extension:

- 85.96% of all nights had `R_N < 1`;
- median `R_N = 0.11983`;
- 100% of nights classified as normal by the pre-holdout rule had `R_N < 1`;
- median normal-night `R_N = 0.08386`.

Thus ordinary closed-market hours consume much less variance than a naive pro-rata IV clock, but rare gaps are large enough to dominate the unconditional mean and gamma P&L. A single fixed IV haircut is therefore inferior to an explicitly modeled night multiplier.

The separate two-state diagnostic produced normal/tail multipliers near 0.1883 and 4.8454. Those are **diagnostics**, not coefficients in the frozen model.

---

## 3. Information set and no-lookahead contract

Every input must be observable immediately after the 10:00 bar closes.

Allowed information:

1. current nearest-weekly eSSVI `theta`;
2. completed historical intraday variance;
3. completed historical overnight gaps;
4. current session open-to-10:00 realized state;
5. current opening gap, which is already known at 10:00;
6. actual exchange-calendar information: expiry, future session sequence and closed-market intervals.

Forbidden information includes any return after 10:00, next-session open, future IV, unresolved weekly labels, future-revised event data, and post-hoc classifications based on the realized future path.

For any fitted/recalibrated model at origin date `d`, a training label is eligible only when its **entire outcome is already resolved before `d`**. For weekly labels this means historical expiry `< d`. Inner validation uses the same purge rule. No shuffled cross-validation is permitted.

Forecasts whose actual listed expiry lies beyond the observed endpoint are censored rather than mapped backward to the last available session.

---

## 4. Target construction

Total future variance is

\[
V_{total}=V_{day}+V_{night}.
\]

`V_day` is the sum of squared one-minute NIFTY log returns strictly after the 10:00 origin through the expiry session, excluding close-to-open jumps.

`V_night` is

\[
V_{night}=\sum_j[\log(O_{j+1}/C_j)]^2
\]

for every future closed-market interval occurring before expiry.

The current morning gap is a predictor, not part of the future target.

Maturity is

\[
T=\frac{\text{seconds from 10:00 IST to listed expiry close}}
{365.25\times24\times60\times60}.
\]

The actual exchange-listed weekly expiry must be used. Historical construction respects the Thursday-to-Tuesday weekly-expiry change, holidays, and legitimate special sessions.

---

## 5. eSSVI anchor

The IV anchor is

\[
\theta=w(k=0),\qquad \sigma_{IV}=\sqrt{\theta/T}.
\]

Historical reconstruction fits one constrained eSSVI slice using only the origin-time option snapshot. The historical ATM±10 rolling archive is narrower than the live chain, so the historical support policy is not claimed to be byte-identical to the production surface.

A final compatibility test replaced the ATM proxy with reconstructed eSSVI `theta` on the fresh holdout and left Day + Gamma-night performance essentially unchanged. Production therefore uses eSSVI `theta` directly.

Raw eSSVI `rho`, `psi`, RR/BF and curvature are **not predictors in this frozen version**. Shape directions were weakly identified in short-dated historical slices, and adding them after seeing the holdout would be an unvalidated architecture change.

---

## 6. Frozen feature definitions

All returns are natural log returns; variance variables are unannualized decimal-return-squared quantities.

Historical realized features:

- `intra1`: prior completed-session intraday variance;
- `intra5`: mean intraday variance over prior 5 completed sessions;
- `intra22`: mean intraday variance over prior 22 completed sessions;
- `gapv1`: prior completed overnight gap squared;
- `gapv5`: mean squared gap over prior 5 completed nights;
- `gapv22`: mean squared gap over prior 22 completed nights;
- `gap_max5`, `gap_max22`: maximum absolute overnight log gap over prior 5/22 nights.

Current-session features:

- `gap_abs = abs(log(current_open / previous_close))`;
- `cur_var`: one-minute realized variance from session open through 10:00;
- `cur_abs_ret = abs(log(close_10:00/current_open))`;
- `cur_max_abs`: largest absolute one-minute log return through 10:00.

IV-state features:

- `log_iv_total = log(theta)`;
- `log_T = log(T)`;
- `log_iv = log(sqrt(theta/T))`;
- `iv_chg1 = log(IV_t/IV_{t-1})` using 10:00 eSSVI ATM IV;
- `iv_rel22 = IV_t / mean(previous 22 valid 10:00 ATM IV observations)`, requiring at least 10 earlier observations.

Calendar features:

- `dow`: Monday=0 ... Friday=4; special sessions retain their actual weekday;
- `n_nights`: count of future close-to-open intervals before expiry;
- `next_night_years`: calendar year fraction from current close to next session open;
- `weekend_night = 1` when `next_night_years > 1.5/365.25`, else 0;
- `night_years`: sum of all future closed-market year fractions before expiry.

Missing/non-finite frozen features must cause the V2 forecast to be unavailable. They may not be imputed from future observations or silently replaced by the old IV-only model.

---

## 7. Day model

Standardize each day feature using the frozen training mean and standard deviation:

\[
z_j=(x_j-\mu_j)/s_j.
\]

Then

\[
\eta_D=-9.648343925288218+\sum_j\beta_{D,j}z_j
\]

and

\[
\widehat V_{day}=1.0966512633204137\exp(\eta_D).
\]

The smearing factor `1.0966512633204137` is applied exactly once. The selected day penalty is `0.0` (OLS after standardization).

Frozen day feature order:

```text
log_iv_total, log_T, intra1, intra5, intra22, cur_var, cur_abs_ret,
gap_abs, gapv5, gapv22, iv_rel22, dow, n_nights
```

Exact means, standard deviations and standardized coefficients are stored in `frozen_model_coefficients.json` and implemented in `research/src/shaurya/analytics/rv_model.py`. Their order is part of the model specification.

---

## 8. Gamma-night model

“Gamma-night” is an internal name for the positive exponential-link/QLIKE model; it is not the option Greek gamma.

The aggregate night IV budget is

\[
B_{night}=\frac{\theta}{T}\tau_N.
\]

Standardized night features enter

\[
\eta_N=-1.205448400603679+\sum_j\gamma_jz_j.
\]

The frozen mapping is

\[
\widehat V_{night}=B_{night}\exp(\operatorname{clip}(\eta_N,-5,5)).
\]

Frozen night feature order:

```text
log_iv, iv_chg1, iv_rel22, gap_abs, gapv1, gapv5, gapv22,
gap_max5, gap_max22, intra1, intra5, intra22, cur_var, cur_abs_ret,
cur_max_abs, next_night_years, dow, weekend_night
```

The selected ridge penalty is `alpha=1.0`, with the intercept unpenalized. Training uses a QLIKE-style positive variance objective on one-night close-to-open squared returns with the corresponding IV night budget as an offset.

For multi-night weekly horizons the 10:00 multiplier is applied to the aggregate future closed-time IV budget. Later-night market states are not observable at the initial origin and therefore may not be inserted retrospectively.

---

## 9. Frozen RV validation result

On the strictly censored May-August 2026 fresh weekly evaluation, the Day + Gamma-night model with eSSVI anchoring delivered approximately:

- total integrated-variance QLIKE: **0.1659**;
- annualized RV RMSE: **about 3.70 volatility points**;
- eSSVI-theta identity QLIKE: **about 0.1789**;
- current legacy NSGVC QLIKE: **about 0.1831**.

The result is consistent with the earlier ATM-anchor run and supports the eSSVI-theta production anchor. The gain comes from treating the overnight variance clock separately rather than merely fitting a more flexible total-RV regression.

---

## 10. Worked calculation — 2026-05-29

At the completed 10:00 origin:

```text
theta              = 0.0002092675583887
T                  = 0.0115788272872461
ATM IV             = sqrt(theta/T) = 0.1344369545
V_day_hat          = 0.0001241848824323
V_night_hat        = 0.00005447078355436
V_total_hat        = 0.0001786556659867
annualized RV_hat  = sqrt(V_total_hat/T) ~= 0.12422
q                  = V_total_hat/theta = 0.8537188820
```

Since `0.85372 > 0.825`, the frozen q gate is **not satisfied** on this example.

---

## 11. q-threshold recalibration

The old `q < 0.70` cutoff belongs to the old IV-only RV mapping and cannot be transferred unchanged because RV-V2 shifts the q distribution upward materially.

Threshold calibration used:

- nearest-weekly NIFTY ATM short iron butterfly;
- ±500-point wings;
- completed 10:00 entry observation;
- at most one new entry per expiry, taking the earliest date satisfying the candidate q gate;
- exact historical four-leg 10:00 structure credit;
- exact bounded terminal payoff against expiry NIFTY;
- nominal 2 structure-point cost, plus 0/4/6/8-point stress;
- frozen RV coefficients throughout.

The development-only 2023-24 optimizer selected `q=0.75`, but that rule lost money in 2025 and early 2026 and was rejected.

A robust 0.80/0.825/0.85 comparison gave calendar-year mean return-on-risk:

| q | 2023 | 2024 | 2025 | worst year |
|---:|---:|---:|---:|---:|
| 0.800 | 0.1503 | 0.1127 | 0.1226 | 0.1127 |
| **0.825** | **0.1617** | **0.1170** | **0.1899** | **0.1170** |
| 0.850 | 0.0298 | 0.0956 | 0.1643 | 0.0298 |

The operational threshold is therefore frozen at

\[
\boxed{q<0.825}.
\]

The interval `0.80-0.85` is reported only as sensitivity; it is not a daily tuning range.

At q=0.825 and 2 cost points:

| Sample | Trades | Total P&L pts | Win rate | Mean return-on-risk |
|---|---:|---:|---:|---:|
| 2023 | 10 | +544.40 | 90.0% | +0.1617 |
| 2024 | 51 | +975.30 | 58.8% | +0.1170 |
| 2025 | 36 | +1,525.70 | 61.1% | +0.1899 |
| 2023-25 pooled | 96 | +3,319.00 | 63.5% | +0.1606 |
| 2026 Jan-May | 16 | +406.25 | 62.5% | +0.1592 |
| 2026 May-Aug | 9 | +79.60 | 77.8% | +0.0162 |
| 2026 combined | 25 | +485.85 | 68.0% | +0.1077 |

The approximate bootstrap 95% interval for pooled 2023-25 mean return-on-risk is `[0.0462, 0.2781]`. The 2026 samples are small and have wide uncertainty.

At q=0.825 aggregate point P&L remains positive in every reported split through an 8-point structure-cost stress. This is a stress test, not an assertion that real fills have fixed costs.

### Statistical status of 0.825

`0.825` is an **adaptive robustness calibration**. The 2023-24 mechanical optimum was rejected after later-period instability; the final robust choice uses year-by-year evidence through 2026. There is consequently no remaining historical period that should be described as an untouched threshold-selection holdout. New data after this freeze are the correct prospective validation sample.

Do not retune 0.825 in response to a short sequence of live winners or losers.

---

## 12. RR400 decision

The historical reference

```text
NSGVC_RR400_THRESHOLD = 0.0270810062
```

is retained for monitoring, but RR400 is **not a master veto** in RV-V2.

At q=0.825 the legacy RR veto reduced the 2023-25 sample from 96 to 38 trades and improved that calibration subset, but it produced negative aggregate performance in the Jan-May 2026 diagnostic subset. A newly retuned RR cutoff would itself be post-hoc.

Therefore RR400 remains a descriptive/regime-conditioned state. The frozen RV-V2 signal is q-only unless a later pre-registered experiment approves another gate.

---

## 13. Butterfly management rule

The q-threshold study selects **entry/continuation state**; it does not change the management rule.

For an open 500-point ATM iron fly:

1. evaluate once per trading day at 10:00 before expiry;
2. continuation requires `q < 0.825`;
3. recenter only when `abs(forward - held_centre) > 250` points;
4. if recentering, close the old four legs and reopen around the nearest 50-point centre.

The historical rolling ATM-relative archive cleanly identifies entry structures and terminal payoffs but cannot guarantee exact fixed-contract interim marks after large drift. Recenter P&L was therefore **not used to choose q**; doing so would risk splicing changing contracts. The >250-point rule remains a separately specified management rule.

---

## 14. Production implementation contract

The deterministic implementation lives at:

`research/src/shaurya/analytics/rv_model.py`

It contains:

- frozen feature order;
- frozen means/standard deviations;
- frozen day/night coefficients;
- day smearing factor;
- night eta clip;
- `RV_V2_Q_THRESHOLD = 0.825`;
- sensitivity constants 0.80/0.85;
- strict feature validation;
- `FrozenRVFeatures` input contract;
- `FrozenRVForecast` output contract;
- `forecast_frozen_rv(...)`.

The module intentionally does not fetch data or reconstruct missing lags. The caller must supply a causal 10:00 feature state. Missing or non-finite inputs fail closed instead of silently reverting to the legacy NSGVC forecast.

Legacy `variance_carry.py` constants/functions remain for reproducibility of the old model until all consumers are migrated explicitly. Their presence must not be interpreted as making `q=0.70` the RV-V2 gate.

---

## 15. Explicitly outside the frozen version

A new model version and new validation are required before adding or changing:

- eSSVI `rho`, `psi`, RR/BF or curvature regressors;
- GIFT Nifty, US market/VIX, USDINR, oil/global features;
- scheduled-event flags;
- explicit jump-probability classifier or two-state tail mixture;
- boosted/nonlinear estimators;
- online coefficient refits;
- forecast origin or target horizon;
- day/night variance-clock convention;
- eta clipping or smearing;
- q threshold;
- RR400 master veto;
- deletion/winsorization of economically real tail nights.

---

## 16. Versioning and audit checklist

Current version:

```text
RV-V2-DAY-GAMMA-ESSVI-2026-09-10
```

Suggested future versions:

```text
RV-V2.1-...   coefficient-only recalibration, identical architecture
RV-V3-...     feature/architecture/target change
```

Before emitting a forecast verify:

- 10:00 bar is complete;
- actual listed weekly expiry is used;
- eSSVI slice is accepted and `theta > 0`;
- `T > 0`;
- every lag uses completed earlier observations only;
- current-session features stop at 10:00;
- night intervals come from the actual trading calendar;
- all frozen features are finite;
- feature ordering and constants match the coefficient snapshot;
- day smearing is applied exactly once;
- night eta is clipped before exponentiation;
- annualized RV is `sqrt(V_total/T)`;
- q is `V_total/theta`;
- the gate compares q, not `sqrt(q)`, with 0.825;
- day/night components and model ID are exposed;
- no automatic refit occurs.

---

## 17. Frozen constants summary

```text
MODEL_ID             = RV-V2-DAY-GAMMA-ESSVI-2026-09-10
ORIGIN               = 10:00 IST
IV_ANCHOR            = nearest-weekly eSSVI theta
DAY_INTERCEPT_Z      = -9.648343925288218
DAY_SMEAR            = 1.0966512633204137
DAY_RIDGE_ALPHA      = 0.0
NIGHT_INTERCEPT_Z    = -1.205448400603679
NIGHT_RIDGE_ALPHA    = 1.0
NIGHT_ETA_CLIP       = [-5.0, +5.0]
PRIMARY_RV_LOSS      = QLIKE on integrated variance
Q_DEFINITION         = V_total_hat / theta
Q_THRESHOLD          = 0.825
Q_SENSITIVITY        = [0.80, 0.85]
RR400_MASTER_VETO    = false
AUTO_REFIT           = false
```

Research lineage:

- `RV_FORECAST_V2_SPEC.md` — pre-registered initial horse race;
- `RV_HORSE_RACE_STAGE1_2026.md` — Stage-1 tail diagnosis;
- `frozen_model_coefficients.json` — machine-readable exact coefficients;
- `RV_Q_THRESHOLD_RECALIBRATION_2026.md` — threshold methodology/results;
- `final_q_threshold_selection.json` — machine-readable threshold decision;
- `q0825_final_eval.csv` — summary strategy evidence;
- `research/src/shaurya/analytics/rv_model.py` — deterministic implementation.

If a research notebook or older NSGVC document disagrees with these frozen artifacts, the frozen artifacts above govern RV-V2 until a formally versioned replacement is approved.
