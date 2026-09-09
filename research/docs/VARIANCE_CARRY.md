# eSSVI variance-carry state

Shaurya now exposes the two NIFTY volatility-state variables used by the NSGVC research as
first-class, read-only analytics derived from the accepted eSSVI surface.

## 1. Front-expiry q ratio

For the nearest fitted expiry, eSSVI ATM integrated implied variance is simply the slice ATM total
variance, `theta`. The frozen weekly RV calibration is retained unchanged:

```text
log(predicted_integrated_RV)
    = -0.8941884292
      + 0.9083950192 * log(theta)
      + 0.0481227276 * log(T)

q = predicted_integrated_RV / theta
```

`q` is therefore a **variance ratio**, not a volatility ratio. The corresponding volatility ratio is
`sqrt(q)` and is also emitted for convenience.

The historical NSGVC reference threshold remains `q <= 0.70`. It is exposed as monitoring metadata;
this module does not place orders or impose a strategy gate.

The fitted coefficients came from the 2023-2025 nearest-weekly research calibration. Consequently,
Shaurya computes q only from the nearest eSSVI slice through `front_variance_carry_state`; the module
does not pretend that the same calibration has been validated for T2/T3 maturities.

## 2. 400-point risk reversal

Let `K_ATM` be the nearest 50-point NIFTY strike to the front eSSVI forward. Shaurya computes

```text
RR400 = IV(K_ATM - 400) - IV(K_ATM + 400)
```

from the same accepted eSSVI slice. No wing extrapolation is allowed: if either 400-point wing lies
outside the slice's observed log-moneyness support, RR400 is null with an explicit reason.

The frozen research reference level is `0.0270810062` (about 2.7081 volatility points).

**Important:** the five-year stress study found that RR400 was useful in the recent regime but
reversed sign as a hard veto in the 2021-2022 backcast. Shaurya therefore labels it
`regime_conditioned_state_not_master_veto`. It is retained as state information, not promoted to an
unconditional execution veto.

## 3. Historical-vs-live comparability

The original backtest reconstructed ATM IV and RR400 from historical option bars. The live Shaurya
values use the accepted eSSVI fit instead. The calibration coefficients and reference cutoffs are
unchanged, but the live values are **surface-consistent continuations**, not byte-for-byte
reconstructions of the historical inputs.

This distinction is deliberate: the eSSVI layer supplies synchronized, arbitrage-checked state while
preserving the frozen research calibration instead of silently re-optimizing it on live data.

## 4. API

```python
from shaurya.analytics.variance_carry import front_variance_carry_state

state = front_variance_carry_state(surface)
payload = state.to_dict()
```

The payload includes ATM IV, integrated IV, forecast integrated RV, annualized forecast RV, q, the
volatility ratio, the 400-point put/call wing IVs, RR400, the historical reference thresholds, and
explicit threshold flags.
