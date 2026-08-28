# Rolling pseudo-live gap validation

**Verdict: no candidate passed all retrospective stability gates.**

This is a retrospective monthly walk-forward stability test, not a new holdout.

| candidate | net 1bp/day | net 2bp/day | net 6bp/day | positive months | p-value |
|---|---:|---:|---:|---:|---:|
| gap_continuation | -1.317 | -2.316 | -6.313 | 42.9% | 0.7478 |
| large_gap_continuation_first_hour | +0.087 | -0.229 | -1.494 | 51.8% | 0.4319 |
| gap_x_volatility_formula | -0.465 | -1.488 | -5.581 | 37.5% | 0.7029 |

Holm passes: none.
Stability passes: none.

Year-level metrics and every monthly calibration are in the JSON; monthly P&L and turnover are in the CSV.
