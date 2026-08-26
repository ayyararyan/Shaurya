# VOL — Realised volatility and forecasting

## Objective

Provide the complete agreed realised-volatility estimator set, out-of-sample forecast evaluation, HMM regime classification, and realised-versus-implied comparison. Unlike speculative SUR parameterisations, this measurement toolkit is built in full now.

## Object and identification ledger

| Object | Category | Boundary |
|---|---|---|
| Underlying bars and accumulated tick tape | Observed | Bars come from DAT-03; tick history can only accumulate prospectively through DAT-02/DAT-05 (D16). |
| Realised-volatility estimators | Deterministically derived estimators | Measurements depend on sampling and estimator choice; they are not latent true volatility. |
| Volatility forecasts and HMM regimes | Estimated | Must be evaluated out of sample. |
| Implied surface | Estimated | Consumed from SUR/GRK. |
| RV–IV / variance-risk-premium finding | Deterministically derived comparison of estimated/derived inputs | Emits `CON-09` with inherited labels and limitations. |

Tick-level history before collection began is genuinely unavailable from the broker APIs; bars are not a proxy substitute for kernel/bipower testing (D16).

## Architecture and contracts

- Consumes DAT bars and retained `CON-01` tape rows.
- Consumes SUR/GRK surface outputs and emits `CON-09` opportunity/finding records.
- Python is the research implementation. No live-order-path duplicate is specified.
- Forecast evaluation is strictly out of sample; in-sample fit is diagnostic only.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-VOL-01 | Port the existing realised-volatility estimators with preserved tests. | VOL-01 | TBD `src/shaurya/vol/realized.py` | Port/regression/reference tests; RV series |
| REQ-VOL-02 | Implement close-to-close, Parkinson, Garman–Klass, Rogers–Satchell, Yang–Zhang, realised kernel, and bipower estimators; test tick estimators only against tape accumulated via DAT-02/DAT-05. | VOL-02, D16 | TBD estimator modules | Synthetic/property/live-tape tests; estimator panel |
| REQ-VOL-03 | Port volatility forecasting and evaluate forecasts out of sample with QLIKE and MSE. | VOL-03 | TBD `src/shaurya/vol/forecasting.py` | Walk-forward QLIKE/MSE report |
| REQ-VOL-04 | Implement HMM regime classification now as the benchmark regime method. | VOL-04 | TBD `src/shaurya/vol/regime.py` | Recovery/stability/OOS fixtures; regime series |
| REQ-VOL-05 | Compare realised volatility with fitted implied volatility and emit the result through `CON-09`. | VOL-05 | TBD `src/shaurya/vol/vrp.py` | Alignment/label/causality tests; finding record |

## Outputs and acceptance tests

- Versioned RV estimator panel with sampling metadata and data-support flags.
- Out-of-sample forecast scorecards using QLIKE and MSE.
- HMM regime series with fit/window metadata.
- RV–IV finding records retaining estimated/derived labels.
- Acceptance includes synthetic known-process tests, missing/irregular-timestamp handling, and proof that tick estimators never substitute bar data.

## Exclusions

- In-sample fit presented as forecast evidence.
- Retrospective tick reconstruction from DAT-03 bars.
- Strategy selection or parameter tuning to make a preselected trade appear profitable (D8).

## Deferred items

- Kernel/bipower live-tape validation waits on sufficient prospectively accumulated DAT-02/DAT-05 data (D16); the requirements themselves are not deferred.
