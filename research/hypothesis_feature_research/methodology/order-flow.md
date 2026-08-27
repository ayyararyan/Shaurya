# Order-flow methodology

## 1. Hypotheses

`H-order-flow-001` validates CKS L1 and CCZ construction. `H-order-flow-002` tests incremental
future-mid prediction. `H-order-flow-003` tests horizon/state/nonlinear response structure.

## 2. Source tests and entry points

Core tests are `test_cks_l1_ofi.py`, `test_ccz_ofi.py`, `test_ofi_horserace.py`,
`test_mid_lag_ofi.py`, `test_d40_ofi_horizon_extension.py`, `test_nonlinear_ofi_state.py`,
`test_ofi_response_surface.py`, and `test_rolling_c8.py`. Producers live in matching `signals/`
and `analytics/` modules; exact paths are in traceability.

## 3. Input lineage

Consecutive depth20/depth200/Full states supply ranked prices, quantities, receive time, epoch, and
quality flags. Targets use future displayed-mid endpoints after declared gaps. Qualified volume
increments are optional controls and remain aggregate proxies.

## 4. Feature derivation

Verified from code: the CKS closed form is quoted in `cks_l1_ofi.py:129`; CCZ bid/ask branch formulas
are in `ccz_ofi.py:142-174`; common-denominator aggregation and training-only PC weights are in
`ccz_ofi.py:436-527`. Detailed stable feature contracts appear in `../features.csv`.

## 5. Temporal alignment and leakage

Windows are `(t-w,t]`, same epoch, complete history, and invalid transitions are refused. Targets
start after a causal gap. Chronological splits/embargoes isolate training from test; PC/ridge/model
selection uses training/validation only; rolling forecasts are issued before outcomes mature.

## 6. Procedure and metrics

Hand-check signs and aggregation; build fixed comparable target panels; run ridge model families and
past mirrors; report R2 plus companion metrics, per-tape signs, HAC/bootstrap inference, Holm/BY
adjustment, horizon curves, smoothness, nonlinear gate/Kalman diagnostics, and rolling scores.

## 7. Output interpretation

Located evidence is mixed: D41 says OFI and lagged returns add incremental information in its named
same-day design; D40 reports strength peaking near 20s then disappearing by 30s; D49 is smooth but
all 210 OOS cells are negative; D50 is weak/non-confirmatory. These do not establish stable alpha.

## 8. Edge cases and quality checks

Crossed/partial books, unsupported level counts, insufficient window history, reconnects,
denominator floors, absent trade support, missing target endpoints, pending labels, isolated surface
spikes, and prior corrupted nonlinear tensors remain explicit.

## 9. Limitations

CCZ is rank-keyed and aggregate, not order identity. Overlapping horizons reduce effective sample
size. Most located evidence is one day or short late-session windows and lacks costs/fills/capacity.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_cks_l1_ofi.py tests/test_ccz_ofi.py tests/test_mid_lag_ofi.py tests/test_ofi_response_surface.py tests/test_rolling_c8.py
```

Do not run full-session controllers or live-study CLIs without separate source/side-effect review.

## 11. Researcher decisions

Choose primary OFI family/window/depth, target/reference, cross-session replication requirement,
multiplicity family, economic threshold, and whether mixed exploratory results warrant a new
preregistered test.
