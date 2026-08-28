# Intraday option-surface alpha benchmark — 2026-08-26

Status: **no strategy promotion; conditional final target remains unopened**.

## What was added

- Causal Black-76 implied-volatility extraction from current two-sided quotes.
- Weighted quadratic total-variance factors for near and far expiries: ATM IV, variance skew,
  curvature, fit error, quote support, spread, depth imbalance, and put-call parity residual.
- Same-strike ATM straddle bid/ask fields for an executable long/short P&L check.
- Base-state, surface-only, and combined 30/60/300-second context representations.
- Ridge, histogram gradient boosting, and a five-seed masked autoencoder plus ridge probe.
- Block-bootstrap validation, Holm family-wise correction, conformal abstention, and adverse-side
  bid/ask P&L accounting.

The raw normalizer streamed 10,718,238 quote updates into the following causal five-second panels:

| role | date | usable states |
|---|---:|---:|
| discovery | 2026-08-19 | 2,588 |
| validation | 2026-08-21 | 1,484 |
| conditional final | 2026-08-26 | 2,501 |

August 19 was split chronologically 60/40 for model fitting and discovery measurement. August 21
was the cross-session validation set. Candidate multiplicity includes all 93 reported model,
representation, target, and horizon combinations. August 26 target construction was not called.

## Result

No candidate survived Holm correction.

The only nominal pre-correction result was base-state histogram boosting for 30-second realized
futures volatility: validation MAE skill **+3.20%**, block-bootstrap `p=0.0415`. It did not survive
the 93-candidate family correction and its August 19 discovery skill was **-6.51%**, so it is not a
credible lead.

Best results by relevant family:

| candidate | discovery skill | validation skill | p-value |
|---|---:|---:|---:|
| surface HGB, signed straddle, 300s | -6.98% | +1.04% | 0.2429 |
| all HGB, absolute straddle, 300s | +8.34% | -0.45% | 0.6172 |
| surface HGB, absolute straddle, 30s | +7.48% | -4.00% | 0.9670 |
| masked autoencoder, absolute straddle, 30s | +7.08% | -24.86% | 1.0000 |
| masked autoencoder, absolute straddle, 60s | +5.09% | -29.79% | 1.0000 |
| masked autoencoder, absolute straddle, 300s | +2.55% | -21.64% | 1.0000 |

The autoencoder learned an in-session representation but transferred especially poorly. Surface
shape by itself also failed to make straddle movement predictable across these two capture windows.

## Decisions

- Do not inspect August 26 surface/straddle targets from this experiment.
- Do not run OpenEvolve on these factors: without a validated evaluator it would optimize August 19
  noise, repeating the earlier formula-search failure.
- Do not run the conformal execution layer: it is intentionally downstream of predictive
  validation, and no predictor reached that gate.
- Retain the separately validated historical index-only 15/30/60-minute volatility model. The
  recent tapes begin around midday or later rather than at the market open, so a clean prospective
  multi-resolution bridge needs newly captured full sessions; substituting the first captured
  quote for the true session open would change the historical feature definition.
- Pre-register the next test as: fit through August 26 features only, collect complete sessions,
  evaluate the index volatility prior first, and test whether surface/L2 features improve it. Only
  a surviving incremental model may enter OpenEvolve and bid/ask strategy evaluation.

Remote reproducibility root:

`/Users/maheit/Documents/Shaurya-research/2026-08-26-surface-alpha`

Local machine-readable validation output:

`scratch/surface-alpha-validation.json`
