# NIFTY k=2 clean expiry + VIX-rise model

The sample and target are frozen: 108 expiry days with a positive overnight India VIX change known by 09:17; target is high-before-low during 09:18–09:45. P3 is removed. Predictors are gap, P1, initial range ratio, initial high-first, and the continuous overnight VIX percentage change. Continuous predictors are standardized, so their coefficients represent a one-standard-deviation increase.

## Fit

- N: **108**; base high-first rate/accuracy: **57.4%**.
- McFadden pseudo-R²: **8.66%**.
- In-sample accuracy: **66.7%**, versus **57.4%** base (+9.3 pp).
- Raw initial-high-first split remains **+32.4 pp**, p <.001.

## Coefficients

- `intercept`: negative, beta=-0.297, HAC p=.308, odds ratio=0.74.
- `gap`: positive, beta=0.177, HAC p=.348, odds ratio=1.19.
- `P1`: positive, beta=0.070, HAC p=.688, odds ratio=1.07.
- `initial_range_ratio`: positive, beta=0.044, HAC p=.763, odds ratio=1.04.
- `vix_overnight_gap`: negative, beta=-0.028, HAC p=.858, odds ratio=0.97.
- `initial_high_first`: positive, beta=1.357, HAC p=.003, odds ratio=3.88.

## Comparison and verdict

The expiry-only model was 58.7% accurate versus 51.8% base. The prior combined model with P3 was 65.7% versus 57.4% base, with pseudo-R² 9.86%. The cleaner model is 66.7% versus 57.4% base, with pseudo-R² 8.66%. Thus accuracy rises by 1.0 pp while pseudo-R² falls by 1.20 pp; the cleaner model is easier to interpret, not uniformly better-fitting.

Removing P3 makes the initial-high-first coefficient significant (beta=1.357, HAC p=.003). Continuous VIX magnitude is not significant (beta=-0.028, HAC p=.858). Because the sample already conditions on VIX being positive, this tests dose-response among VIX-rise days—not the overall up-versus-down leverage effect. This remains a small, in-sample, post-selected N=108 result and requires untouched or prospective validation before use.
