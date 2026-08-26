# D49 C8 response-surface result — 2026-08-21

## Verdict

The prospective late-session response surface is **smooth** under the predeclared diagnostic:
all five OFI-sampling-horizon slices pass. It is not a favorable predictive surface. Every one of
the 210 cumulative genuine OOS R2 cells is negative, so the rolling C8 forecasts underperform
their corresponding rolling-training-mean baselines throughout this window.

## Sample and integrity

- Forecast anchors: 15:08:53.629468 through 15:28:39.612459 IST.
- 221 forecasts issued and 221 outcomes scored in every cell; 46,410 cell-forecasts total.
- Zero pending outcomes at completion; no missing or excluded cells.
- Six beta windows x seven prediction horizons x five OFI sampling horizons.
- Prospective-only: no backfill and no outcomes known when their forecasts were issued.
- Dashboard, socket allocation and order authority were unchanged.

## Smoothness evidence

For OFI sampling horizons 0.5, 1, 2, 5 and 10 seconds respectively, neighbor-interpolation RMSE
was 10.3%, 10.6%, 10.7%, 9.1% and 6.1% of the observed within-slice R2 range, below the frozen 35%
limit. Maximum neighbor residual shares were 43.3%, 37.1%, 29.2%, 38.7% and 22.1%, below 75%.
Median absolute second-difference shares were 9.6%, 13.5%, 14.4%, 8.9% and 6.8%, below 50%.

The within-slice R2 ranges were:

- 0.5s OFI sampling: -0.2454 to -0.0039;
- 1s: -0.2540 to -0.0184;
- 2s: -0.2471 to -0.0286;
- 5s: -0.3463 to -0.0219; and
- 10s: -0.4709 to -0.0177.

Thus the grid shows gradual local variation rather than isolated parameter spikes, but no cell
beats the baseline in this sample.

## Evidence boundary

This is a single roughly 20-minute late-session regime with heavily overlapping five-second
forecast waves. It maps local response shape; it is not independent statistical evidence, a
parameter recommendation, or proof that the surface is stable across days/regimes.

Terminal artifact SHA-256: `7121d98cbe64180baeb12d72a032d9fbde3b55f5527e3592e5e1cfc2cc736938`.
