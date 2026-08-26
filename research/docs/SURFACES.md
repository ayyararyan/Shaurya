# Volatility surfaces

This document is the implementation companion to `docs/module-spec/SUR.md`. `TASKS.md`
remains the sole status ledger.

## Module interface

Every enabled parameterisation implements `VolatilitySurface` from
`src/shaurya/surfaces/base.py`:

- `fit(SurfaceFitRequest)` calibrates from observed market data;
- `evaluate(log_moneyness, maturity_years)` returns total variance, annualized implied
  volatility, and an explicit support status;
- `params` and `diagnostics` use the existing CON-03 `SurfaceParameter` and `FitDiagnostic`
  contracts;
- `arb_check()` independently checks butterfly and calendar no-arbitrage conditions;
- `to_frame(...)` emits the versioned CON-03 `SurfaceFrame`.

`SurfaceFitRequest` is an adapter, not a competing market-data schema. Its observations are
CON-01 `TapeRow` instances. Forward values and exact expiry timestamps are separate explicit
inputs because neither can be recovered from an option-book packet without silently choosing
a market convention.

## DAT integration boundary

The DAT handoff supplies the latest causally available row for each option instrument, or a
short sequence from which SUR selects the latest row. The current adapter expects:

- canonical CON-05 option identity
  `NSE:NSE_FNO:<UNDERLYING>:option:<YYYY-MM-DD>:<STRIKE>:<CE|PE>`;
- positive, non-crossed best bid and ask in the CON-01 depth fields;
- a receive timestamp no later than the fit valuation timestamp;
- one forward and one timezone-aware IST expiry timestamp per requested expiry.

Rows with invalid/crossed books, failed IV inversion, unrequested expiries, or in-the-money
contracts are excluded with named diagnostic counts. Every requested expiry must retain at
least five usable OTM quotes. Failure is explicit `InsufficientSurfaceData`; an expiry is never
silently dropped. Tomorrow's DAT integration only needs to construct this request from replayed
or live option `TapeRow` records and the forward/expiry context.

## eSSVI calibration

For log-forward-moneyness `k`, slice total variance is

```text
w(k) = 0.5 * [theta + rho*psi*k
              + sqrt((psi*k + rho*theta)^2 + theta^2*(1-rho^2))]
```

where `psi = theta * phi(theta)`. Option BBO mids are inverted with discounted Black-76.
Inverse variance-spread weights are normalized within each maturity, so one very liquid expiry
cannot erase the others from the joint objective.

All requested maturities are calibrated in one SLSQP problem. The constrained layer enforces:

- `theta > 0`, `-0.999 <= rho <= 0.999`, `psi > 0`;
- `psi * (1 + |rho|) <= 4`;
- `psi^2 * (1 + |rho|) <= 4*theta`;
- nondecreasing `theta` across expiry;
- nondecreasing total variance on synchronized log-moneyness grids for every adjacent expiry.

The constraints drive calibration. A separate diagnostic pass then evaluates the
Gatheral-Jacquier implied-density factor and adjacent-expiry total-variance spreads on denser
grids. A fitted surface that fails this independent pass is rejected.

## Diagnostics

CON-03 diagnostics include:

- weighted R-squared and weighted total-variance RMSE;
- quote counts and named exclusion counts;
- residual count, mean, and maximum absolute residual in deep-put, put-wing, ATM, call-wing,
  and deep-call buckets;
- parameter changes by common expiry versus the previous eSSVI frame;
- optimizer method, iterations, objective, constraint set, and minimum constraint margin;
- fitted support, interpolation policy, and the full independent arbitrage report.

No previous frame means stability is explicitly `not_available`; it is not reported as zero.

## Support and interpolation

Strike interpolation uses the eSSVI functional form only inside each expiry's observed
log-moneyness range. Between fitted maturities, total variance is linear in time and requires
overlapping strike support. Strike and maturity extrapolation are both disabled. Unsupported
requests return `EvaluationStatus.DATA_INSUFFICIENT` with a reason and no numeric value.

## Temporal smoothing, age, and quoting

`ESSVITemporalSmoother` applies a time-decayed EWMA to same-expiry parameters across consecutive
raw fits. It carries the latest maturity and forward, intersects strike support, rechecks both
parameter constraints and independent no-arbitrage diagnostics, and moves a failed blend toward
the latest raw fit until feasible. One frame is not smoothing: quoting remains blocked until at
least two frames contribute materially.

`SurfaceFrame.surface_age_seconds` is the decision time minus the oldest quote timestamp used in
the latest cross-sectional fit. The consuming strategy supplies `staleness_threshold_seconds`;
Shaurya only computes `is_stale = age > threshold`. Raw surfaces are allowed for research but
`SurfaceUse.QUOTING` rejects them. The D19 dashboard remains a read-only ANL consumer and adds no
low-latency or C++ fitting requirement.

## Explicit exclusions

SVI (`SUR-03`) and SABR (`SUR-04`) remain blocked under D8 until a concrete data-led need is
approved. This implementation does not add either model or a C++ fitting path.
