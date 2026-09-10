# Shaurya RV Model — Frozen Specification

**Model ID:** `RV-V2-DAY-GAMMA-ESSVI-2026-09-10`  
**Status:** **FROZEN**  
**Frozen on:** 2026-09-10  
**Forecast origin:** 10:00 IST one-minute bar close  
**Underlying:** NIFTY 50  
**Horizon:** 10:00 IST to nearest weekly NIFTY expiry close  
**Primary use:** overnight-carried NIFTY butterfly / variance-carry state  
**Primitive forecast:** forward integrated realized variance

> This freezes the RV prediction model, not the old butterfly entry cutoff `q < 0.70`. Because the RV mapping changes, the trading threshold must be calibrated separately.

---

## 1. Frozen model

The frozen forecaster is the **Day + Gamma-night** architecture selected in the strict fresh-holdout Stage-2 race.

It decomposes future integrated realized variance into two economically different objects:

```text
V_total_hat = V_day_hat + V_night_hat
```

or

\[
\widehat V_{total,t}=\widehat V_{day,t}+\widehat V_{night,t}.
\]

The day component forecasts continuous/in-session variance. The night component forecasts the variance consumed during future close-to-next-open intervals. The latter is essential because ordinary nights usually consume much less variance than a naive pro-rata IV allocation, while rare overnight jumps can dominate total weekly variance.

Let:

- \(\theta_t\): nearest-weekly eSSVI ATM total variance at 10:00;
- \(T_t\): calendar year fraction from 10:00 to expiry close;
- \(\sigma_{IV,t}=\sqrt{\theta_t/T_t}\): eSSVI ATM annualized IV;
- \(\tau_{N,t}\): total calendar year fraction spent in future close-to-next-open intervals before expiry.

The headline frozen equation is

\[
\boxed{\widehat V_{total,t}=\widehat V_{day,t}+\sigma_{IV,t}^2\tau_{N,t}\exp(\operatorname{clip}(\eta_{N,t},-5,5))}.
\]

The day component is

\[
\boxed{\widehat V_{day,t}=1.0966512633204137\exp(\eta_{D,t})}.
\]

The dashboard annualized RV forecast is

\[
\boxed{\widehat\sigma_{RV,t}=\sqrt{\widehat V_{total,t}/T_t}}
\]

and the model-implied variance ratio is

\[
\boxed{\widehat q_t=\widehat V_{total,t}/\theta_t}.
\]

---

## 2. Economic motivation and overnight result

For one coming closed-market interval, define the morning-IV calendar variance budget

\[
B_{N,t\to t+1}=\sigma_{IV,t}^2\Delta\tau_{t\to t+1},
\]

and realized overnight variance

\[
V_{N,t\to t+1}=\left[\log(O_{t+1}/C_t)\right]^2.
\]

The variance-consumption ratio is

\[
R_{N,t}=V_{N,t\to t+1}/B_{N,t\to t+1}.
\]

Pre-holdout evidence:

- 94.35% of all nights had `R_N < 1`;
- median `R_N = 0.08252`;
- mean `R_N = 0.30772`;
- within the pre-specified normal-95% state, 99.35% had `R_N < 1`;
- median normal-night `R_N = 0.07224`;
- mean normal-night `R_N = 0.15870`.

Fresh May-August 2026 holdout:

- 85.96% of all nights had `R_N < 1`;
- median `R_N = 0.11983`;
- 100% of nights classified as normal by the pre-holdout rule had `R_N < 1`;
- median normal-night `R_N = 0.08386`.

Thus normal overnight RV is not merely a little below morning IV. On compatible variance units, ordinary closed-market hours consume only a small fraction of a naive calendar-time IV budget. But a few extreme gaps pull the unconditional mean upward, so a fixed small haircut is unsafe.

A separately tested two-state diagnostic estimated:

```text
normal-state multiplier       = 0.1882683881
tail-state multiplier         = 4.8454333175
all-state historical mean     = 0.3077235901
```

Those values are diagnostics only. They are not coefficients in the frozen Gamma-night equation.

---

## 3. Forecast information set

Every predictor must be observable immediately after the 10:00 one-minute bar is complete.

Included:

1. current nearest-weekly eSSVI level;
2. completed historical intraday variance;
3. completed historical overnight gaps;
4. current session open-to-10:00 realized state;
5. current opening gap, already known at 10:00;
6. known trading-calendar information: listed expiry, future-night count, day of week, next closed-market interval length.

Excluded:

- any return after 10:00 on the forecast date;
- next-session open / next overnight gap;
- any future IV observation;
- unresolved weekly or one-night labels;
- post-hoc tail labels based on future realized gaps;
- future-revised event data.

---

## 4. Target construction

### Total target

\[
V_{total}=V_{day}+V_{night}.
\]

### Day target

For the forecast date, variance begins at the 10:00 close and includes one-minute log returns strictly after 10:00. Later sessions through expiry contribute full in-session one-minute variance.

\[
V_{day}=\sum_{r\in\text{future in-session 1m returns}}r^2.
\]

### Overnight target

\[
V_{night}=\sum_j\left[\log(O_{j+1}/C_j)\right]^2.
\]

The current morning gap is already known at 10:00 and is therefore a predictor, not part of the future target.

### Maturity

\[
T_t=\frac{\text{seconds from 10:00 IST to expiry 15:30 IST}}{365.25\times24\times60\times60}.
\]

Live expiry must come from the actual listed contract/exchange calendar. Do not infer it solely from weekday arithmetic. Historical research accounted for the Thursday-to-Tuesday weekly-expiry change and holiday-adjusted sessions.

---

## 5. eSSVI anchor

The live IV anchor is

\[
\theta_t=w_t(k=0),\qquad \sigma_{IV,t}=\sqrt{\theta_t/T_t}.
\]

Historical reconstruction used a constrained one-slice eSSVI fit from WEEK1 ATM±10 data. Because the historical chain is narrower than the live chain, historical surface policy is not byte-identical to production.

A final compatibility check replaced the ATM proxy with actual reconstructed eSSVI `theta`/ATM IV on the fresh holdout. The selected model's performance remained essentially unchanged, supporting production eSSVI `theta` as the live anchor.

**Not part of this frozen version:** raw eSSVI `rho`, `psi`, RR, BF or curvature predictors. Short-dated historical fits showed weak identification in some shape directions, so adding them after seeing the holdout would be an unvalidated model change.

---

## 6. Feature definitions

All returns use natural logs. All variance variables are unannualized integrated variance in decimal-return-squared units.

### Historical realized features

- `intra1`: prior completed session intraday variance.
- `intra5`: mean intraday variance over prior 5 completed sessions.
- `intra22`: mean intraday variance over prior 22 completed sessions.
- `gapv1`: prior completed overnight gap squared.
- `gapv5`: mean squared gap over prior 5 completed nights.
- `gapv22`: mean squared gap over prior 22 completed nights.
- `gap_max5`: maximum absolute overnight log gap over prior 5 completed nights.
- `gap_max22`: maximum absolute overnight log gap over prior 22 completed nights.

### Current-session features

- `gap_abs = abs(log(current_open / previous_close))`.
- `cur_var`: one-minute realized variance from session open through 10:00.
- `cur_abs_ret = abs(log(close_10:00 / current_open))`.
- `cur_max_abs`: largest absolute one-minute log return from open through 10:00.

### IV-state features

- `log_iv_total = log(theta)`.
- `log_T = log(T)`.
- `log_iv = log(sqrt(theta/T))`.
- `iv_chg1 = log(IV_t / IV_{t-1})` using 10:00 eSSVI ATM IV.
- `iv_rel22 = current 10:00 eSSVI ATM IV / mean(previous 22 10:00 eSSVI ATM IVs)`; construction requires at least 10 earlier valid observations.

### Calendar features

- `dow`: Monday=0, Tuesday=1, ..., Friday=4; special sessions retain actual weekday.
- `n_nights`: number of future close-to-open intervals before expiry.
- `next_night_years`: calendar year fraction from current close to next session open.
- `weekend_night = 1` when `next_night_years > 1.5/365.25`, otherwise 0.
- `night_years`: total year fraction across all future close-to-open intervals before expiry.

---

## 7. Frozen day model

For each feature `x_j`, use

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

The factor `1.0966512633204137` is a training-only Duan smearing correction.

Pre-holdout penalty selection chose `DAY_RIDGE_ALPHA = 0.0`, so the frozen day fit is OLS after standardization.

Canonical frozen day constants:

```csv
feature,mean,sd,beta_z
log_iv_total,-9.17769826615,0.949884660757,0.668585876205
log_T,-5.37926296734,1.16542411296,0.155343929548
intra1,3.91887797329e-05,7.81330632114e-05,0.0488749416757
intra5,3.93435217273e-05,4.43266945002e-05,-0.0417405297773
intra22,3.96184276443e-05,2.50488958403e-05,0.020940448427
cur_var,1.26299838766e-05,3.02580534574e-05,0.0263976392752
cur_abs_ret,0.00256683141374,0.00237247897388,0.0142815800606
gap_abs,0.00321501706234,0.00423463134833,-0.000649029229989
gapv5,2.82684755127e-05,7.05376202747e-05,-0.0348568943024
gapv22,2.81540893816e-05,4.01684814695e-05,0.0115095497434
iv_rel22,1.00936598943,0.373301726123,0.0849497919244
dow,2.01368159204,1.42509906372,0.0103703609669
n_nights,1.8868159204,1.37619249454,0.0534364581467
```

Feature order is part of the frozen model.

---

## 8. Frozen overnight Gamma-night model

`Gamma-night` is an internal label for a positive exponential-link / QLIKE variance model; it is unrelated to the option Greek gamma.

First calculate aggregate closed-time IV budget

\[
B_{night,t}=\sigma_{IV,t}^2\tau_{N,t}=\frac{\theta_t}{T_t}\tau_{N,t}.
\]

Then standardize each night feature and calculate

\[
\eta_N=-1.205448400603679+\sum_j\gamma_j z_j.
\]

Apply the frozen clip and exponential link:

\[
m_N=\exp(\operatorname{clip}(\eta_N,-5,5)),
\]

\[
\boxed{\widehat V_{night}=B_{night,t}m_N}.
\]

Canonical frozen night constants:

```csv
feature,mean,sd,beta_z
log_iv,-1.89921764941,0.369119205228,-0.0301910387963
iv_chg1,0.000149262377511,0.389257349037,-0.0680857352934
iv_rel22,1.00936598943,0.373301726123,-0.0217020337282
gap_abs,0.00321501706234,0.00423463134833,-0.018213596442
gapv1,2.8227797073e-05,0.000144846098013,-0.0168872136027
gapv5,2.82684755127e-05,7.05376202747e-05,-0.00486681136702
gapv22,2.81540893816e-05,4.01684814695e-05,0.0416595845845
gap_max5,0.0071738474556,0.00709783279457,0.00186792805737
gap_max22,0.01337672758,0.0111406654585,0.0115392811269
intra1,3.91887797329e-05,7.81330632114e-05,0.0764042776661
intra5,3.93435217273e-05,4.43266945002e-05,0.0185879958099
intra22,3.96184276443e-05,2.50488958403e-05,-0.00217657878741
cur_var,1.26299838766e-05,3.02580534574e-05,0.01502416869
cur_abs_ret,0.00256683141374,0.00237247897388,0.0325419087546
cur_max_abs,0.00165272982696,0.00142561359496,0.0394723299324
next_night_years,0.00333356791977,0.00239763020281,-0.00130306518337
dow,2.01368159204,1.42509906372,-0.0204249631289
weekend_night,0.245024875622,0.43010194832,0.0106963675224
```

### Night training objective

The model is estimated on one-night-ahead squared close-to-open gaps, using the corresponding one-night IV budget as an offset:

\[
\widehat V_{N,i}=B_{N,i}\exp(\eta_{N,i}).
\]

The frozen objective is

\[
\min_\gamma\frac1N\sum_i\left[\frac{V_{N,i}}{\widehat V_{N,i}}-\log\left(\frac{V_{N,i}}{\widehat V_{N,i}}\right)-1\right]+\alpha_N\sum_{j>0}\gamma_j^2,
\]

with

\[
\boxed{\alpha_N=1.0}.
\]

The intercept is not penalized.

### Multi-night rule

The night model is learned on one-night outcomes, but for a multi-night weekly horizon the current 10:00 state multiplier is applied to the aggregate future closed-time IV budget:

\[
\widehat V_{night,weekly}=\left(\frac{\theta_t}{T_t}\tau_{N,t}\right)\exp(\operatorname{clip}(\eta_{N,t},-5,5)).
\]

`next_night_years` and `weekend_night` describe the first upcoming night because later-night states are unobservable at 10:00. This approximation is part of the validated frozen model and must not be silently replaced by future information.

---

## 9. No-lookahead and purge rules

These rules are part of the model.

### Day/weekly training

For forecast origin `d`, a weekly row may enter training only if

\[
\boxed{expiry_i<d}.
\]

### One-night training

A one-night row may enter only if its next open has already occurred:

\[
\boxed{next\_date_i<d}.
\]

### Holdout boundary

At the 2026-05-29 holdout boundary, any training row whose next open or weekly expiry entered the holdout was excluded.

### End-of-sample censoring

If a forecast's true weekly expiry lies beyond the observed index sample, censor the row. Never map an unavailable future expiry backward to the last observed session.

### Hyperparameter selection

Only chronological, purged validation is permitted. Shuffled cross-validation is forbidden.

---

## 10. Frozen validation evidence

### Sample

```text
training start                         = 2023-01-23
training end                           = 2026-05-27
usable pre-holdout eSSVI origins       = 814
fresh extension                        = 2026-05-29 ... 2026-08-21
fully observed weekly holdout origins  = 57
holdout end after expiry censoring     = 2026-08-18
```

### Strict holdout that selected the architecture

| Model | QLIKE | Corr(var) | RV RMSE pts | RV MAE pts |
|---|---:|---:|---:|---:|
| **Day + Gamma-night** | **0.165780** | 0.8290 | **3.8366** | 2.8699 |
| Day + tail-mixture-night | 0.165824 | 0.8252 | 3.8467 | 2.8894 |
| Direct HAR/ATM | 0.168372 | 0.8209 | 3.9739 | 3.0098 |
| ATM-IV identity | 0.176848 | 0.8444 | 4.2277 | 3.2615 |
| Current NSGVC | 0.182769 | 0.8390 | 3.8714 | **2.8047** |
| Day + raw IV-night budget | 0.243932 | 0.8358 | 5.1005 | 4.2489 |

### eSSVI-anchor compatibility verification

After architecture selection, the fresh holdout was recalculated with reconstructed eSSVI `theta` / eSSVI ATM IV replacing the historical ATM proxy. This was a compatibility check, not a new selection round.

| Model | QLIKE | Corr(var) | RV RMSE pts | RV MAE pts | Mean pred RV | Mean actual RV |
|---|---:|---:|---:|---:|---:|---:|
| Day + tail-mixture-night | 0.165679 | 0.8210 | 3.7035 | 2.9624 | 13.34% | 12.92% |
| **Day + Gamma-night** | **0.165875** | **0.8224** | **3.6950** | 2.9491 | **13.31%** | 12.92% |
| Direct HAR/eSSVI | 0.168989 | 0.8139 | 3.8230 | 3.0754 | 13.70% | 12.92% |
| eSSVI theta identity | 0.178909 | 0.8382 | 4.0839 | 3.2079 | 14.51% | 12.92% |
| Current NSGVC | 0.183124 | 0.8334 | 3.6958 | **2.8730** | 12.44% | 12.92% |
| Day + raw IV-night budget | 0.242222 | 0.8301 | 5.0356 | 4.3663 | 15.84% | 12.92% |

With the eSSVI anchor, Day + Gamma-night improves QLIKE about **7.3%** versus eSSVI-theta identity and **9.4%** versus current NSGVC.

The tail-mixture model becomes fractionally lower by 0.000196 QLIKE after the eSSVI substitution. It is not selected because changing the winner after inspecting the holdout would be post-hoc model selection. The frozen winner remains Day + Gamma-night.

---

## 11. Worked calculation — 2026-05-29

Real holdout inputs:

```text
eSSVI theta              = 0.0002092675583887
eSSVI ATM IV             = 0.1344369545 = 13.4437%
T to expiry               = 0.01157882729 years
future closed-time years  = 0.009525439197
future nights             = 2
```

Naive closed-time IV budget:

\[
B_N=(0.1344369545)^2(0.009525439197)=0.0001721560702.
\]

Frozen day forecast:

\[
\widehat V_D=0.0001241848824.
\]

Frozen Gamma-night state multiplier:

\[
m_N=0.3164035023.
\]

Night forecast:

\[
\widehat V_N=0.0001721560702\times0.3164035023=0.00005447078355.
\]

Total integrated variance forecast:

\[
\widehat V=0.0001786556660.
\]

Annualized RV forecast:

\[
\widehat\sigma_{RV}=\sqrt{0.0001786556660/0.01157882729}=0.12421559=\boxed{12.42\%}.
\]

Realized over the same horizon:

```text
realized day variance   = 0.0001372579261
realized night variance = 0.00004511622694
realized total variance = 0.0001823741530
realized annualized RV  ~= 12.55%
```

The example shows the core mechanism: naive IV allocated `0.00017216` to future closed time, while the state model allocated only `0.00005447`.

---

## 12. Operational pseudocode

```python
# Run after the 10:00 IST bar is complete.

theta = front_weekly_essvi.theta
T = year_fraction(timestamp_1000, expiry_close)
iv = sqrt(theta / T)

x_day = build_frozen_day_features()
z_day = (x_day - DAY_MEAN) / DAY_SD
eta_day = DAY_BETA[0] + dot(DAY_BETA[1:], z_day)
V_day = 1.0966512633204137 * exp(eta_day)

night_years = total_future_closed_time_years()
B_night = iv**2 * night_years

x_night = build_frozen_night_features()
z_night = (x_night - NIGHT_MEAN) / NIGHT_SD
eta_night = NIGHT_BETA[0] + dot(NIGHT_BETA[1:], z_night)
eta_night = clip(eta_night, -5.0, +5.0)
V_night = B_night * exp(eta_night)

V_total = V_day + V_night
RV_ann = sqrt(V_total / T)
q_hat = V_total / theta
```

Recommended live/dashboard fields:

```text
rv_forecast_ann
rv_forecast_integrated_variance
rv_forecast_day_variance
rv_forecast_overnight_variance
rv_forecast_overnight_share
rv_forecast_q
essvi_theta
essvi_atm_iv
n_nights
night_years
model_id = RV-V2-DAY-GAMMA-ESSVI-2026-09-10
```

If a required frozen feature is unavailable, emit a model-unavailable/degraded-data flag. Do not silently alter the estimator or impute using future information.

---

## 13. Frozen / not-frozen boundary

The following are frozen:

- 10:00 origin;
- target definitions;
- day/night decomposition;
- feature definitions and order;
- eSSVI `theta` anchor;
- all means/SDs and coefficients above;
- day smearing factor;
- day penalty `0.0`;
- night QLIKE objective;
- night penalty `1.0`;
- night exponential link and `[-5,+5]` clip;
- aggregate closed-time budget rule;
- purge and censoring rules;
- annualization and `q` definitions;
- no automatic coefficient refit.

Not frozen into this version, and therefore requiring a new version plus fresh validation:

- eSSVI `rho`, `psi`, RR, BF or curvature regressors;
- GIFT Nifty, US, VIX, USDINR, oil/global-market predictors;
- RBI/Fed/macro event flags;
- explicit jump-probability / tail-mixture model;
- boosted trees or other nonlinear models;
- online coefficient refits;
- alternate forecast origins or horizons;
- alternate variance-clock definitions;
- winsorization or deletion of tail nights;
- a new butterfly `q` cutoff.

Tail nights are economically part of an overnight-held butterfly and must not be deleted to improve fit statistics.

---

## 14. Re-estimation/versioning policy

Current coefficients are frozen and should not automatically refit every day.

Any future recalibration must:

1. preserve this specification and the original holdout evidence;
2. admit only fully resolved labels at every origin;
3. pre-register new features/model families before final testing;
4. use a new untouched or forward OOS block;
5. report total, day and overnight performance separately;
6. keep QLIKE as primary integrated-variance loss;
7. compare against eSSVI-theta identity and the then-current production model;
8. recalibrate the trading `q` threshold separately.

Suggested versioning:

```text
RV-V2-DAY-GAMMA-ESSVI-2026-09-10  # this frozen model
RV-V2.1-...                        # coefficient-only recalibration under same method
RV-V3-...                          # architecture / feature-set change
```

---

## 15. Interpretation for the butterfly

This is a variance/gamma-theta carry-state estimator, not a directional forecast.

The evidence supports three distinct statements:

1. normal overnight realized variance is usually much smaller than naive pro-rata morning-IV variance;
2. rare overnight gaps are large enough to dominate average variance and option P&L;
3. continuous/day and overnight variance should be modeled separately.

Low `q_hat` means forecast integrated RV is low relative to option-implied integrated variance `theta`. However, the old `q < 0.70` policy belongs to the old RV mapping and must not be assumed optimal for this frozen model.

---

## 16. Implementation audit checklist

- [ ] 10:00 bar is complete.
- [ ] actual listed weekly expiry is used.
- [ ] eSSVI fit is valid and `theta > 0`.
- [ ] `T > 0`.
- [ ] all lags use earlier completed observations only.
- [ ] current gap uses previous close/current open.
- [ ] current-session features stop at 10:00.
- [ ] future `night_years` uses calendar/session times only.
- [ ] every frozen feature is finite.
- [ ] feature order matches this document exactly.
- [ ] frozen means/SDs are unchanged.
- [ ] day smearing factor is applied exactly once.
- [ ] night `eta` is clipped before exponentiation.
- [ ] tail observations are retained.
- [ ] no unresolved label enters estimation.
- [ ] `RV_ann = sqrt(V_total/T)`.
- [ ] `q_hat = V_total/theta`.
- [ ] day and overnight components are exposed separately.
- [ ] model ID is emitted with every forecast.

---

## 17. Frozen constants summary

```text
MODEL_ID            = RV-V2-DAY-GAMMA-ESSVI-2026-09-10
ORIGIN              = 10:00 IST
DAY_INTERCEPT_Z     = -9.648343925288218
DAY_SMEAR           = 1.0966512633204137
DAY_RIDGE_ALPHA     = 0.0
NIGHT_INTERCEPT_Z   = -1.205448400603679
NIGHT_RIDGE_ALPHA   = 1.0
NIGHT_ETA_CLIP      = [-5.0, +5.0]
PRIMARY_LOSS        = QLIKE on integrated variance
IV_ANCHOR           = nearest-weekly eSSVI theta
ANNUALIZATION       = sqrt(V_hat / T)
Q_DEFINITION        = V_hat / theta
AUTO_REFIT          = disabled
```

---

## 18. Research lineage

Read with:

- `RV_FORECAST_V2_SPEC.md` — pre-registered Stage-1 design;
- `RV_HORSE_RACE_STAGE1_2026.md` — Stage-1 results and tail diagnosis;
- `rv_forecast_v2.py` — initial V2 research implementation;
- Stage-2 strict/censored outputs — overnight variance-clock and fresh-holdout tests.

If research code and this document disagree, **this frozen specification defines the intended model until a formally versioned replacement is approved**.
