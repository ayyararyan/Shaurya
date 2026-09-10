# RV Forecast V2 — pre-registered horse race

**Frozen before first result run:** 2026-09-10  
**Purpose:** replace the current nearest-weekly IV-only RV mapping only if a strictly ex-ante model wins out of sample.  
**Trading use:** NIFTY butterfly carried overnight. Overnight variance is therefore part of the headline target, not a robustness variant.

## 1. Forecast origin and target

Default forecast origin is the **10:00 one-minute bar close**. Every predictor must be observable by that origin. The research script can be rerun at another clock, but model comparison is always within the same origin.

The headline target is **forward integrated realized variance** from the forecast origin through the nearest weekly expiry close:

`RV_int_total = RV_int_intraday + RV_int_overnight`

- `RV_int_intraday`: squared one-minute NIFTY log returns from the origin through expiry, within sessions.
- `RV_int_overnight`: every close-to-next-open squared log return occurring after the origin and before expiry.
- The current morning gap is already known at 10:00 and is a predictor; it is **not** part of the future target.
- Integrated variance is the primitive target. Human-readable annualized RV is `sqrt(RV_int / eSSVI_T)`.
- The trading state remains `q = forecast_RV_int / eSSVI_theta`.

This target matches the economics of an overnight-held butterfly. No intraday-only model can win the headline race by ignoring nights.

## 2. Historical eSSVI reconstruction

Historical WEEK1 files contain ATM +/- 10 strikes rather than the full live chain. For each origin:

1. derive a robust forward from same-bar put-call parity;
2. select one OTM option per strike;
3. use the vendor IV when sane, otherwise invert the same-bar close with Black-76;
4. fit a constrained one-slice eSSVI (`theta`, `rho`, `psi`) using only that origin's prices;
5. derive surface skew/curvature features and fixed-width RR/BF states.

No fixed-width surface feature may extrapolate outside the strikes supporting that historical fit.

Because the old archive is too narrow to reproduce the production `include_atm_strikes=false` support rule, the historical fit explicitly uses the near-ATM OTM region. That policy is reported in every result artifact and must not be presented as byte-identical to the live surface. When a wider historical chain is available, this horse race should be rerun with the production surface policy.

## 3. Predictor information set

All features are ex ante.

### A. Current implied surface

- eSSVI `theta`, `rho`, `psi`, `phi=psi/theta`
- ATM annualized IV
- ATM total-variance skew derivative
- RR100 / RR200 / RR400 when inside fitted support
- BF100 / BF200 / BF400 when inside fitted support
- parity forward basis
- surface fit RMSE / quote count
- time to expiry and sessions/nights remaining

### B. Past realized-volatility state

Strictly completed sessions only:

- intraday variance HAR windows: 1 / 5 / 22 / 66 sessions
- overnight variance HAR windows: 1 / 5 / 22 / 66 gaps
- positive / negative realized semivariance
- bipower variation and jump-variation proxy
- realized quarticity
- largest absolute one-minute return

### C. Current-session information known by origin

- current opening gap and squared gap
- open-to-origin realized variance
- open-to-origin positive / negative semivariance
- open-to-origin jump proxy
- open-to-origin signed and absolute return
- largest open-to-origin one-minute move

### D. Optional timestamp-audited exogenous overnight features

The script accepts an optional CSV whose feature names must start with `exo_`. Candidate examples for a later data pass:

- GIFT Nifty overnight return / variance
- prior US session return and VIX move
- USDINR overnight move
- oil / major global index overnight moves
- known RBI / Fed / macro event flags

These features are not silently synthesized. Historical timestamp provenance is required before they enter the race.

## 4. Pre-registered model race

The first result run compares these fixed families:

1. **Mean-rate benchmark** — expanding historical mean variance rate, scaled to current horizon.
2. **IV identity** — eSSVI `theta`; assumes realized integrated variance equals implied integrated variance.
3. **Current frozen NSGVC** — the exact current Shaurya coefficients (`-0.8941884292`, `0.9083950192`, `0.0481227276`) applied to historical eSSVI theta and maturity.
4. **Refit IV-only log model** — expanding/purged log integrated RV on log eSSVI theta and log maturity.
5. **HAR total** — direct log total-RV model using current implied variance plus separate past intraday/overnight HAR states.
6. **HAR + eSSVI** — adds eSSVI shape features.
7. **HAR + eSSVI + rich ridge** — adds semivariances, jumps, current-session state, VIX when available, and optional timestamp-audited exogenous features; ridge penalty selected only inside purged training data.
8. **Day/night decomposition** — predicts future intraday variance rate and future overnight variance per night separately, then sums them.
9. **Day/night decomposition + ridge** — regularized version of (8).
10. **Small nonlinear HGB** — conservative histogram gradient boosting on the rich feature set, trained on log integrated variance. It is a contender, not the favored model; complexity must earn its place out of sample.

Every newly fitted log-variance model uses a **training-only Duan-style smearing factor** when mapping its log forecast back to variance units. This fixes the conditional-median/conditional-mean retransformation problem without touching future data.

No candidate is promoted because of in-sample fit.

## 5. No-lookahead / purge rule

For a forecast on date `d`, a historical row can enter training **only if its expiry is strictly before `d`**.

This is stronger than a simple chronological split. It guarantees that no training label contains returns from the forecast date or its future holding window.

The same purge rule applies to every inner validation fold used to choose ridge strength. No shuffled cross-validation is permitted.

## 6. Evaluation

Primary selection metric: **out-of-sample QLIKE on total integrated variance**.

Secondary diagnostics:

- OOS R² versus expanding mean-rate benchmark
- RMSE in annualized RV volatility points
- correlation of predicted and realized integrated variance
- year-by-year stability
- horizon-by-horizon stability (`n_sess`)
- intraday-component QLIKE/correlation for decomposed models
- **overnight-component QLIKE/correlation/MSE** for decomposed models
- implied `q = forecast_RV_int / theta`

A model is not considered superior if the headline gain comes from intraday RV while overnight performance deteriorates materially.

## 7. Promotion rule

The production NSGVC model remains unchanged during this experiment.

A V2 model can be proposed for production only after it:

1. beats the **current frozen NSGVC** on headline total-variance QLIKE;
2. beats or materially improves the mean-rate benchmark on OOS R²/RMSE;
3. is not dependent on one year or one expiry horizon;
4. does not obtain its gain by degrading overnight-variance forecasts;
5. survives a final frozen rerun after model/feature choices are locked.

The final production coefficients, feature normalization, and q threshold are a separate validation step. The horse-race script has no broker or order path and cannot arm a trading gate.
