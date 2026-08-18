# SUR — Volatility surfaces

## Objective

Provide a common surface interface, an eSSVI implementation, arbitrage checks, diagnostics, interpolation policy, and explicit staleness measurements. Additional parameterisations are retained as stable requirements but blocked until data reveals a concrete need (D8).

## Object and identification ledger

| Object | Category | Boundary |
|---|---|---|
| Option-chain quotes and timestamps | Observed | Supplied by DAT; quality and timing remain attached. |
| Surface parameters, fitted variance, diagnostics | Estimated | A fitted representation, never an observed volatility. |
| Interpolated/extrapolated surface values | Estimated | Must identify the method and support region. |
| Butterfly/calendar checks and surface age | Deterministically derived | Computed from the fitted surface and timestamps. |
| Staleness flag | Deterministically derived | Measurement under a strategy-supplied threshold; Shaurya does not choose the strategy threshold. |

No surface fit identifies an unobserved true volatility process. Sparse or unsupported regions must remain explicit rather than silently filled without the declared interpolation/extrapolation policy.

## Architecture and contracts

- Consumes `CON-03` surface frames and `CON-07` time semantics.
- Produces versioned `CON-03` frames for GRK, VOL, SIG, ANL, and live controls.
- Python is authoritative for research surface fitting. Any future live-order-path implementation must be separately designated and parity-tested; none is specified here.
- A raw fit taking roughly three seconds is not tick-synchronous; live quoting consumes a temporally smoothed surface.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-SUR-01 | Define one interface exposing `fit`, `evaluate`, `params`, `diagnostics`, and `arb_check`. | SUR-01 | `src/shaurya/surfaces/base.py` | Interface conformance suite |
| REQ-SUR-02 | Port eSSVI behind the common interface with preserved tests. | SUR-02 | `src/shaurya/surfaces/essvi.py` | Port/regression/golden-fit tests; surface frame |
| REQ-SUR-03 | When a data-shown need exists, implement raw, natural, and jump-wings SVI with conversions. | SUR-03, D8 | Deferred `src/shaurya/surfaces/svi.py` | Conversion/property/fit tests |
| REQ-SUR-04 | When a data-shown need exists, implement SABR using the Hagan expansion and document its low-strike/long-maturity arbitrage limitation. | SUR-04, D8 | Deferred `src/shaurya/surfaces/sabr.py` | Reference-value and limitation tests |
| REQ-SUR-05 | Check butterfly non-negative implied density and calendar non-decreasing total variance. | SUR-05 | `src/shaurya/surfaces/arbitrage.py` | Known-valid/invalid property fixtures; arb report |
| REQ-SUR-06 | Report weighted R², residuals by moneyness bucket, and parameter stability across consecutive frames. | SUR-06 | `src/shaurya/surfaces/essvi.py` | Diagnostic fixture and surface report |
| REQ-SUR-07 | Expose surface age and staleness as measurements; let each strategy supply its threshold; require smoothed rather than tick-synchronous raw surfaces for quoting. | SUR-07, CON-07 | `src/shaurya/surfaces/state.py` | Age/threshold/causality tests; staleness fields |
| REQ-SUR-08 | Declare and test strike/maturity interpolation and extrapolation rather than inheriting fitter defaults. | SUR-08 | `src/shaurya/surfaces/interpolation.py` | Boundary/support tests; policy metadata |

## Outputs and acceptance tests

- Versioned surface frames with parameters, support, diagnostics, age, staleness, and arbitrage results.
- Interface conformance for every enabled parameterisation.
- Property tests reject known butterfly/calendar violations and exercise conversion boundaries.
- Acceptance requires explicit data-insufficient results in unsupported cells; silent NaNs or undocumented extrapolation fail.

## Exclusions

- Strategy-specific surface choice or staleness tolerance.
- American or single-stock option surfaces in current scope.
- SVI/SABR construction before a concrete data-led need (D8).
- Claiming fitted implied volatility is observed or causal.

## Deferred items

- REQ-SUR-03 and REQ-SUR-04 are explicitly blocked under D8, not dropped.
