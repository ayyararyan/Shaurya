# D50 nonlinear OFI gate and Kalman-beta result — 2026-08-21

## Verdict

The existing C8 predictor surface does move between locally favorable and unfavorable episodes,
but the proposed nonlinear state variables did **not** identify those episodes out of sample on
today's data. The Kalman-beta model also added effectively no forecasting value. The best held-out
result was the simpler validation-selected 75% shrinkage of the rolling-ridge forecast: **+1.14%
OOS R2** versus the rolling-mean baseline. This is a modest, one-day exploratory result, not a
deployable or confirmatory edge.

## Frozen design and sample

- Instrument: August 2026 NIFTY future; displayed-mid response; C8 depth-scaled CCZ OFI at M=10.
- Axes: six beta windows (7.5–20m), five OFI sampling horizons (0.5–10s), and seven prediction
  horizons (5–30s).
- Chronological split: 09:35–12:00 train, 12:05–13:30 validation, 13:35–15:29:30 test, with
  five-minute purges.
- Support: 4,472 five-second cadence rows; 1,670 train, 996 validation, 1,351 test; 9,457 scored
  model-horizon test outcomes.
- Hyperparameters were chosen only on train/validation. Kalman response updates were delayed until
  each response matured; gate labels crossing a split boundary were excluded.

## Held-out test horse race

| Model | Interpretation | OOS R2 | RMSE (ticks) | MAE (ticks) | Direction |
|---|---|---:|---:|---:|---:|
| M0 | Rolling-mean baseline | 0.00% | 24.661 | 14.772 | 46.29% |
| M1 | Rolling-ridge C8 ensemble | +0.76% | 24.567 | 15.208 | 49.63% |
| M2 | Kalman betas | +0.01% | 24.660 | 14.772 | 46.37% |
| M3 | Nonlinear gate x M1 | +0.88% | 24.553 | 14.814 | 48.23% |
| M4 | Nonlinear gate x M2 | +0.00% | 24.661 | 14.772 | 46.30% |
| Falsifier | Constant 75% shrinkage of M1 | **+1.14%** | **24.521** | 15.017 | 49.13% |

The validation procedure chose zero weight for M2, meaning the Kalman forecast was best turned off.
The constant-shrinkage falsifier beat M3, so M3's small improvement cannot be credited to useful
nonlinear regime detection.

## Horizon shape

M1 was negative or flat at 5–12.5 seconds and positive at 15 seconds (+0.69%), 20 seconds
(+0.73%), and 30 seconds (+2.25%). M3 was positive at every horizon after shrinkage, from +0.30%
at 10 seconds to +1.76% at 30 seconds, but its aggregate result remained below the constant
shrinkage falsifier. The Kalman models stayed economically indistinguishable from M0 at every
horizon.

## State-gate diagnostic

The test surface was positive on only 23.88% of eligible rows and had median future surface R2 of
-3.04%. Its five-minute summaries crossed above and below zero, confirming that the surface level
varied through the afternoon. However, the gate's test AUC was **0.475** and its highest predicted
probability quintile had the *lowest* realized positive-state rate (16.67%). Thus today's eight
current-predictor geometry variables did not forecast when OFI would be active.

## Integrity and evidence boundary

The first gate artifact was rejected because an OFI-tensor temporary was mutated during squaring,
which made a bounded coherence measure exceed one. The corrected code preserves the source tensor,
adds construction and terminal support checks, and was rerun from the complete tape. M0/M1/M2 were
unaffected; only corrected M3/M4/gate values are reported. Earlier run artifacts are retained only
for audit and are invalid as evidence.

The source tape missed the strict opening gate by 4.44 seconds, and the D50 model class was designed
after D49 was observed. Therefore the entire exercise remains same-day exploratory calibration.
No dashboard, live collector, socket, credential, order path, or trading authority was changed.

Accepted full-artifact SHA-256:
`1b47c0343dad003a9e2b64f78470a7e76ac6ff7fbf0e75620f392bce2bc0f36b`.
