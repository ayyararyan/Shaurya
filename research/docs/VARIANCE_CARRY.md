# eSSVI variance-carry state

Shaurya exposes the nearest-weekly NIFTY variance-carry state used by the NSGVC research as
read-only analytics derived from the accepted eSSVI surface.

## 1. Realized-volatility forecast

The RV model is the frozen validation-selected **IV-only** specification from the NSGVC study. Its
target is **forward integrated realized variance**, not annualized volatility directly.

For the nearest fitted expiry, eSSVI gives ATM total variance `theta`, so

```text
IV_int = theta = ATM_IV^2 * T
```

The frozen calibration is

```text
log(predicted_RV_int)
    = -0.8941884292
      + 0.9083950192 * log(IV_int)
      + 0.0481227276 * log(T)
```

where `T` is time remaining to expiry in years. The human-readable annualized RV forecast is then

```text
forecast_RV = sqrt(predicted_RV_int / T)
```

and the corresponding annualized realized-variance forecast is `predicted_RV_int / T`.

The coefficients came from the 2023-2025 nearest-weekly research calibration, so Shaurya does not
apply this mapping to T2/T3 as though those horizons had already been validated.

The ANL-03 dashboard now shows the front-expiry **FORECAST RV** in annualized volatility points,
alongside ATM IV, q, expiry and forecast horizon. The same fields are present in `/api/state` and
historical dashboard payloads under `rv_forecast`.

## 2. Front-expiry q ratio

The q state is simply the ratio of predicted integrated realized variance to current integrated
implied variance:

```text
q = predicted_RV_int / IV_int
```

`q` is therefore a **variance ratio**, not a volatility ratio. The equivalent volatility ratio is
`sqrt(q)`, which gives the useful identity

```text
forecast_RV = ATM_IV * sqrt(q)
```

The historical NSGVC reference threshold remains `q <= 0.70`. It is monitoring metadata; this
module does not place orders or impose a strategy gate.

## 3. 400-point risk reversal

Let `K_ATM` be the nearest 50-point NIFTY strike to the front eSSVI forward. Shaurya computes

```text
RR400 = IV(K_ATM - 400) - IV(K_ATM + 400)
```

from the same accepted eSSVI slice. No wing extrapolation is allowed: if either 400-point wing lies
outside the slice's observed log-moneyness support, RR400 is null with an explicit reason.

The frozen research reference level is `0.0270810062` (about 2.7081 volatility points).

The five-year stress study found that RR400 was useful in the recent regime but reversed sign as a
hard veto in the 2021-2022 backcast. Shaurya therefore labels it
`regime_conditioned_state_not_master_veto` and retains it as state information rather than an
unconditional execution veto.

## 4. Historical-vs-live comparability

The original backtest reconstructed ATM IV and RR400 from historical option bars. Live Shaurya uses
the accepted eSSVI fit. The calibration coefficients and reference cutoffs are unchanged, but the
live values are surface-consistent continuations rather than byte-for-byte reconstructions of the
historical inputs.

## 5. API

```python
from shaurya.analytics.variance_carry import (
    front_variance_carry_state,
    realized_volatility_forecast,
)

forecast = realized_volatility_forecast(atm_iv=0.12, maturity_years=7 / 365)
state = front_variance_carry_state(surface)
```

`RealizedVolatilityForecast` contains ATM IV, integrated IV, predicted integrated RV, annualized
forecast variance, annualized forecast RV, q and the volatility ratio. `VarianceCarryState` adds the
400-point wing IVs and RR400 state.
