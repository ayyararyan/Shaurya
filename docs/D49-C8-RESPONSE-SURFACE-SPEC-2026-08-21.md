# D49 prospective C8 response-surface scan

**Frozen before outcome-producing launch:** 2026-08-21.

This separate exploratory scan asks whether predictive performance changes smoothly over rolling
beta-estimation window `L` and prediction horizon `h`; it does not select a winning cell and does
not modify the dashboard.

- `L in {7.5,10,12.5,15,17.5,20}` minutes.
- `h in {5,7.5,10,12.5,15,20,30}` seconds.
- Each of the existing OFI sampling horizons `{0.5,1,2,5,10}` seconds is assessed separately.
- Model is unchanged: C8, displayed mid, M=10, 0.5-second response gap, exact causal rolling fit,
  five-second forecast cadence, training-only standardisation and ridge selection.
- Only forecasts issued after D49 launch are scored. There is no backfill.
- Primary surface value is cumulative genuine OOS R2 against each forecast's rolling-training-mean
  baseline. Overlapping forecasts mean this is an exploratory late-session diagnostic, not
  independent statistical evidence.

For each OFI sampling horizon, local smoothness is assessed from neighbor-interpolation RMSE,
maximum neighbor residual, and median absolute second difference. Normalising by the observed R2
range (floored at 0.01), the predeclared pass limits are 0.35, 0.75 and 0.50 respectively. The
overall label is `smooth` if at least four of five fully observed sampling-horizon surfaces pass,
`mixed` if one to three pass, and `not_smooth` if none pass. Smooth does not mean monotone.

Outputs are isolated state, append-only forecast/outcome receipts, and `final.json`. No UI route,
dashboard panel, dashboard process, socket, credential, or order path is added.
