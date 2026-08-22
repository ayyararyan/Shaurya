# NIFTY k=2 expiry-only and India-VIX-rise sequence test

**Exploratory full-history conditioning test.** The frozen k=2 decision/target timing is unchanged: predictors use 09:15–09:17 and the target is strictly 09:18–09:45. Every regression uses only the original predictors: gap, P1, P3, initial range ratio, and initial high-first.

## India VIX construction and data audit

The lowercase folder contains **60 files** and 511,827 unique minute timestamps from 2021-08-04 10:00:00+05:30 through 2026-05-27 19:49:00+05:30. The uppercase sibling contains one file; it is byte-identical to the matching lowercase file, with **0 conflicts**.

For each NIFTY trading date, VIX open is the `open` value of the first print between 09:15 and 15:30 IST; prior close is the `close` value of the immediately preceding NIFTY trading session. `vix_rose=1` when open/prior-close−1 is positive. To preserve no-lookahead, a date is eligible only if its first VIX print arrives by 09:17. This excludes anomalous early files whose first print is 09:27 or 10:00.

## Sample attrition

- Frozen full sample: **1318 days**.
- Expiry-only: **276 days**.
- Expiry days with an overnight VIX gap known by 09:17: **243 days**.
- Expiry days with VIX rose: **108 days**.
- Of those, **108** use an exact 09:15 VIX print.

Of the expiry dates, 27 lack a usable overnight VIX gap (mostly before the series begins in August 2021), and 6 more have their first VIX print after 09:17 and are excluded for no-lookahead. The final N=108 is above the requested 80-day warning line, but it is still a modest and selected subsample.

## Model progression

| Sample | N | Base high-first | Initial high / low target rate | Effect / p | Pseudo-R² | Accuracy vs base | Flag β / HAC p |
|---|---:|---:|---:|---:|---:|---:|---:|
| full_sample | 1318 | 50.1% | 52.5% / 47.6% | +4.9 pp / .078 | 0.37% | 53.0% vs 50.1% | 0.384 / .017 |
| expiry_only | 276 | 51.8% | 60.8% / 43.8% | +16.9 pp / .005 | 2.72% | 58.7% vs 51.8% | 0.839 / .009 |
| expiry_and_vix_rose | 108 | 57.4% | 74.5% / 42.1% | +32.4 pp / <.001 | 9.86% | 65.7% vs 57.4% | 0.674 / .363 |

The exact-09:15 sensitivity is effectively the same filter: N=108, persistence +32.4 pp (p <.001), pseudo-R² 9.86%, and accuracy 65.7% versus 57.4% base.

The combined sample's raw two-proportion split is strong, but the initial-high-first coefficient is **not independently significant** in the joint model (HAC p=.363). At k=2, the sequencing flag and P3 encode much of the same opening path (correlation -0.765), so conditioning on P3 makes the flag's incremental contribution imprecise.

## Verdict

**VIX-rise conditioning strengthens the raw expiry-day persistence pattern in sample, but it does not establish an independent sequencing edge.** The raw effect is larger and model fit rises sharply; accuracy uplift over the changing base rate improves only modestly, from 6.9 to 8.3 percentage points. Most importantly, the joint model cannot separate the sequencing flag from the correlated P3 path reliably (HAC p=.363). This is a promising N=108 in-sample subgroup, not validation. Freeze the rule and require prospective or untouched-period confirmation before trading it.

## Caveats

- Accuracy and fitting are in-sample; the VIX-rise condition was selected after prior expiry/high-IV findings.
- The VIX series begins in August 2021 and contains anomalous off-session timestamps; session filtering and the by-09:17 gate prevent those late prints from leaking into the decision.
- High/low labels use minute-stamped NIFTY spot levels, not intraminute OHLC extrema.
