# Intraday volatility lab — frozen retrospective result

**Research only. No broker/order path and no executable option-P&L claim.**

Overall verdict: **incremental forecast signal found**. 
6 of 6 forecast tasks passed.

## Data audit

- Accepted 1,339 complete weekday sessions; rejected 51 incomplete or pathological sessions.
- Matched 476,245 index/rolling-ATM rows and evaluated 78,740 five-minute decision points.
- Evaluation panel: 2021-01-01T09:20:00 through 2026-05-14T14:25:00.

## Frozen results

| target | selected on 2024 | 2025 skill [95% CI] | 2026 skill [95% CI] | Tuesday-regime skill | gate |
|---|---|---:|---:|---:|---|
| abs_move_15m | hist_index_options | +17.609% [+14.920%, +20.194%] | +5.254% [+3.065%, +7.618%] | +14.130% | PASS |
| abs_move_30m | hist_index_options | +18.132% [+15.113%, +21.339%] | +5.699% [+3.297%, +8.686%] | +14.535% | PASS |
| abs_move_60m | hist_index_options | +19.319% [+15.902%, +22.658%] | +4.894% [+1.816%, +8.251%] | +14.132% | PASS |
| realized_vol_15m | hist_index_options | +44.018% [+40.704%, +47.074%] | +30.295% [+25.045%, +35.308%] | +42.470% | PASS |
| realized_vol_30m | hist_index_options | +47.108% [+43.680%, +50.260%] | +34.673% [+27.994%, +40.226%] | +46.376% | PASS |
| realized_vol_60m | hist_index_options | +48.225% [+44.340%, +51.823%] | +33.626% [+25.063%, +40.351%] | +45.672% | PASS |

MAE skill is measured against a training-only time-of-day mean. Positive is better. The confidence interval resamples whole trading sessions because horizons overlap.

## Do the rolling-ATM option fields add signal?

The table below compares otherwise identical histogram models. Positive means adding the five option price/activity fields reduced MAE.

| target | 2024 selection | 2025 holdout | 2026 current | Tuesday regime |
|---|---:|---:|---:|---:|
| abs_move_15m | +0.384% | +0.135% | -0.231% | -0.278% |
| abs_move_30m | +0.516% | +0.051% | -0.244% | -0.140% |
| abs_move_60m | +0.871% | +0.073% | -0.679% | -0.759% |
| realized_vol_15m | +1.870% | +0.470% | -4.920% | -4.390% |
| realized_vol_30m | +2.917% | +0.101% | -9.859% | -8.865% |
| realized_vol_60m | +3.992% | -0.177% | -17.547% | -15.511% |

**Decision:** the forecast signal is durable, but the rolling-ATM option increment is not. Freeze an index-only model for prospective validation; do not use aggregate ATM activity as a directional or volatility alpha until fixed-contract quote data exists.

## Interpretation rules

- A task passes only if both its 2025 and 2026 daily-block 95% intervals are above zero.
- `option_feature_increment` in the JSON contains matched linear and nonlinear tests of whether rolling-ATM price/activity fields improve otherwise identical models.
- Tuesday-regime results are reported separately; they are short and retrospective, so they cannot substitute for prospective validation.
- The option archive has no fixed contract, strike, expiry, bid/ask, OI, IV, Greeks, or trade direction. The result can justify a forecast layer, not a tradable options strategy.
