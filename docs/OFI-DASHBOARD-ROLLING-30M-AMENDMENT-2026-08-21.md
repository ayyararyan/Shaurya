# OFI dashboard rolling 30-minute forecast amendment

**ID:** `D46 / ANL-06-ROLLING-C8-30M`

**Directed and approved by Aryan Ayyar:** 2026-08-21. The default table must not reuse a morning
70/30 fit to describe the current regime. For every new forecast, estimate the C8 coefficients
from the immediately preceding 30 minutes, issue the forecast, and accumulate forecast accuracy
and OOS R-squared only after the future outcome is observed.

**Supersedes:** D45's D39/D40 value source and progress strip. D39 and D40 remain preserved
historical studies and complete read-only API artifacts; they are not the live table estimator.

## 1. Statistical object

For forecast anchor `t`, lookback `h1 in {0.5,1,2,5,10}` seconds and future horizon
`h2 in {0.5,1,2,5,10,20}` seconds:

1. construct the unchanged displayed-book C8 features at `t`, using displayed mid, `M=10`, and
   the existing depth-scaled rank-keyed CCZ OFI equations;
2. select training anchors `s` in `[t-1800s,t]` from the same connection epoch;
3. admit a training row only if its entire target is known by `t`, i.e.
   `s + 0.5s + h2 <= t`;
4. use the existing C8 ridge estimator, training-only standardisation and training-only inner
   penalty selection;
5. forecast the displayed-mid change from `t+0.5s` through `t+0.5s+h2`; and
6. retain that forecast as pending until both response endpoints are observable.

Forecast cadence is five seconds. A worker restart may restore already-issued pending forecasts
and score accumulators, but must never manufacture/backfill forecasts for anchors that passed
before the corrected worker was running.

## 2. Cumulative metrics

Each cell accumulates only genuine post-launch forecasts. Its baseline is the training-target mean
from the same rolling fit that generated that forecast:

`R2 = 1 - sum((y_t - yhat_t)^2) / sum((y_t - ybar_train,t)^2)`.

Also retain scored count, forecasts issued, pending count, MAE, RMSE, and directional accuracy on
non-zero realised moves. A cell with no mature forecast displays `—`, not zero.

**Scoring amendment:** D47
(`OFI-DASHBOARD-FIVE-MINUTE-WIN-SCORE-AMENDMENT-2026-08-21.md`) adds the owner-defined
`+1/0/-1` threshold score and makes its trailing-five-minute mean the visible cell companion to
cumulative R2. It does not change forecasts, betas, training rows, targets, or cumulative R2.

## 3. Delivery and evidence boundary

The default dashboard is one 5-column by 6-row cumulative-R2 table. The compact API exposes the
rolling state and `GET /api/rolling-c8` exposes its complete state. The browser polls every five
seconds. The worker tails the existing DAT tape, opens no Dhan socket, has no credential or order
path, and cannot place orders.

The predictor is **snapshot-implied net displayed OFI** constructed from consecutive Dhan book
states. Gross order-arrival and cancellation intensities remain unidentified without event/MBO
data. Results remain exploratory and non-confirmatory.

## 4. Acceptance

- `ROLL-DATA-01`: read only complete JSONL lines from the active DAT dataset.
- `ROLL-CAUSAL-01`: every training row lies in the preceding 30 minutes and its label matures by
  the forecast anchor.
- `ROLL-EST-01`: all 30 C8/M10 cells use the unchanged ridge path.
- `ROLL-OOS-01`: issue first, score only after outcome maturity; no startup backfill.
- `ROLL-METRIC-01`: cumulative R2 uses each forecast's own rolling-training-mean baseline.
- `ROLL-OUT-01`: table and API show cumulative R2, support and freshness from this object only.
- `ROLL-OPS-01`: durable file-tail worker, atomic state, append-only forecast/outcome receipts,
  no socket, credentials or order path.
