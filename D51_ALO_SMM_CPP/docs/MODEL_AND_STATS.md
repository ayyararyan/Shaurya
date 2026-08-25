# Learning model and retained statistics

## Online models

Models are separate for every `CE/PE × B/S × offset`. This is deliberate: the original D51 day showed materially different CE and PE stability and asymmetric buy/sell toxicity.

### Fill model

Online standardized logistic SGD. The target is the conservative cross-through fill indicator over the configured horizon.

### Fill-conditioned markout model

Online standardized linear/ridge SGD, updated only when the counterfactual order is labelled filled.

For BUY:

`markout = option_mid_h - quote - delta_entry*(future_h-future_entry) - buy_cost`

For SELL:

`markout = quote - option_mid_h + delta_entry*(future_h-future_entry) - sell_cost`

Thus the target tries to isolate option-specific liquidity value rather than naked NIFTY direction.

### Calibration and kill switch

Every mature candidate supplies realized action EV, including actions not selected. An EW calibration corrects persistent model bias. Once a side has enough observations, strongly negative rolling counterfactual EV disables it.

## Persistent state

`state/model_state.dat` contains model weights, feature standardization moments, observation/fill counts, and EW calibration state. It contains no account credentials.

## Daily compact outputs

Under `stats/YYYY-MM-DD/`:

- `shadow_decisions.csv` — one row per policy decision; selected quotes only.
- `feature_samples.csv` — configurable random sample of **the full model state**, exact token/strike/symbol, fitted surface parameters, candidate action, model prediction and counterfactual outcome. Default sample rate 10%.
- `shadow_fills.csv` — simulated policy fills with exact token/strike/symbol and aggregate inventory state.
- `health.csv` — feed count, dropped ring messages, exchange/feed lag, receive-to-strategy queue delay, surface-fit compute time, decision-cycle compute time, and surface success rate.
- `action_stats.csv` — offset-level counts/fill rates/markout/EV means and SDs.
- `day_summary.json` — side-level rolling EV/observation totals and action summaries.
- `run_config.json`, `instruments.csv`, `VERSION`, `run_hashes.sha256`, `run_environment.txt` — non-secret provenance needed to reproduce each day without retaining the raw tape.
- `model_state_eod.dat` — end-of-day model/calibration snapshot for reconstructing the learning path across the month.

The action aggregate is retained at 100%; the higher-dimensional state/action rows are sampled to control storage. This is intentionally much smaller than a raw tape but preserves enough information to retrain/audit the policy rather than relying only on serialized weights. It supports questions such as:

1. Is fill probability stable by quote distance?
2. Is fill-conditioned markout stable?
3. Which distances have persistent positive total EV?
4. Does the learned policy shut off failing CE/PE or buy/sell regimes?
5. How much simulated inventory and holding time accumulates?
6. Are surface quality/feed staleness causing most OFF decisions?

## Month-end acceptance tests

Do not evaluate the month by aggregate P&L alone. At minimum check:

- day-by-day and week-by-week EV by action;
- CE vs PE and BUY vs SELL stability;
- minimum sample counts and confidence intervals;
- fill-rate calibration by predicted probability decile;
- markout calibration and residual drift;
- stability across time-of-day/expiry-distance regimes;
- inventory residence time and forced-end-of-day treatment;
- sensitivity to statutory cost assumptions;
- sensitivity to 0.05–0.15 point extra slippage/adverse fill assumptions;
- performance when each calendar day is held out in turn.

Only after these pass should the policy be frozen for a one-lot live pilot.
