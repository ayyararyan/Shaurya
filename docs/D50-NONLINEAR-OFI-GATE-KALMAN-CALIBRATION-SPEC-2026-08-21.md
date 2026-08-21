# D50 nonlinear OFI gate and Kalman-beta calibration

**Frozen before outcome-producing D50 execution:** 2026-08-21.

## Status and evidence boundary

This is a one-day exploratory calibration on the already observed 2026-08-21 NIFTY August-future
tape. The model class was proposed after D49's late-session outcome was known. Consequently no D50
number may be called prospective or confirmatory, even though every forecast inside the analysis
is constructed causally and scored on chronological held-out rows.

## Objective

Test whether the existing C8 predictors contain nonlinear information about their own future
efficacy, whether causally updated Kalman coefficients improve on rolling ridge coefficients, and
whether both mechanisms are jointly useful.

## Frozen data and timing

- Source: completed 2026-08-21 DAT tape for `NIFTY-Aug2026-FUT`, displayed-mid response.
- Five-second anchor clock: last usable depth200 observation in each five-second IST bucket.
- C8 predictors: displayed-book baseline controls plus ten-level depth-scaled CCZ OFI, M=10.
- OFI sampling horizons `s={0.5,1,2,5,10}` seconds.
- Beta windows `L={7.5,10,12.5,15,17.5,20}` minutes.
- Prediction horizons `h={5,7.5,10,12.5,15,20,30}` seconds.
- Response starts after the unchanged 0.5-second causal gap.
- Train: 09:35:00–12:00:00 IST; validation: 12:05:00–13:30:00; test:
  13:35:00–15:29:30. The omitted five-minute intervals are purges for the gate's forward label.
- All fitting, state features and delayed Kalman updates use only information available by the
  forecast anchor. Test rows never select hyperparameters.

## Predictor-geometry state

At every anchor, derive only from the existing five-by-ten CCZ OFI tensor and C8 controls:

1. log OFI energy;
2. mean cross-depth directional coherence;
3. mean touch concentration (first three of ten levels);
4. cross-sampling-horizon sign agreement;
5. trailing-60-second aggregate-OFI persistence;
6. absolute aggregate-OFI acceleration versus ten seconds earlier;
7. spread; and
8. log displayed L1 depth.

Missing or non-finite geometry is refused, never zero-imputed.

## Models

- `M0`: causal rolling target-mean baseline, the median across the six declared L windows.
- `M1`: median across all 30 causal rolling-ridge C8 forecasts `(L,s)` for each h. Ridge penalties
  are selected on train only and fixed for validation/test.
- `M2`: median across five `(s,h)` linear-Gaussian Kalman filters. Each filter predicts the return
  residual relative to M0. Betas follow `beta_t=rho*beta_{t-1}+eta`; response observations update
  the state only after their own response end. `(rho,Q)` is selected on validation only from the
  frozen grid `rho={0.98,0.995,1}`, `Q scale={1e-7,1e-6,1e-5,1e-4,1e-3}`; R comes from train
  residual variance.
- `M3`: `M0+p_t*(M1-M0)`.
- `M4`: `M0+p_t*(M2-M0)`.

`p_t` is a regularised nonlinear logistic spline of the eight predictor-geometry variables. Its
binary target is whether the median 210-cell surface R2 over forecasts issued in the next five
minutes is positive. Spline knots are training quintiles; regularisation is selected on
validation. Gate labels whose five-minute future crosses a split boundary are excluded.

As a required falsifier, constant-shrinkage versions of M1 and M2 choose
`c in {0,0.25,0.5,0.75,1}` on validation and use `M0+c*(M-M0)` on test. The nonlinear gate is not
credited if its apparent gain is matched by constant shrinkage.

## Outputs and tests

The terminal artifact must include source hashes; exact split/support counts; train-selected ridge
penalties; validation-selected Kalman and gate hyperparameters; M0–M4 validation/test R2, MAE,
RMSE and direction accuracy; constant-shrinkage falsifiers; gate AUC/Brier/calibration by
probability quintile; positive-surface label rates; and explicit leakage/causal checks.

Acceptance requires complete declared axes, non-empty train/validation/test support, no test-based
selection, finite predictions, delayed Kalman updates, and artifact read-back. No dashboard,
socket, credential, order path or live process is changed.

## Post-estimation reporting amendment

After the first complete artifact was inspected, two omitted diagnostics were identified and added
without changing any estimator, split, feature, target, hyperparameter grid or selection: M0–M4
metrics separately by forecast horizon, and descriptive five-minute surface-height plus univariate
geometry-quintile panels. These additions are explicitly post-estimation diagnostics and may not be
used to claim a pre-registered nonlinear relation or to refit D50.

## Execution and correction record

The complete-tape execution finished on 2026-08-21. The first gate artifact was rejected after a
bounded-feature audit found `depth_coherence > 1`. Under the production Python 3.14/NumPy build,
the temporary expression used to square the OFI tensor could reuse its input buffer, corrupting
later geometry features. The implementation now squares an explicit copy and enforces `[0,1]`
invariants both when geometry is built and before the terminal artifact is returned. M0, M1 and
M2 did not depend on these features and were unchanged; all reported M3, M4 and gate results come
only from the corrected rerun. The rejected artifacts remain audit-only and are not evidence.

The accepted artifact is summarized in
`docs/results/D50-NONLINEAR-OFI-GATE-KALMAN-2026-08-21.json` and interpreted in
`docs/D50-NONLINEAR-OFI-GATE-KALMAN-REPORT-2026-08-21.md`. Its SHA-256 is
`1b47c0343dad003a9e2b64f78470a7e76ac6ff7fbf0e75620f392bce2bc0f36b`.
