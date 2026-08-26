# NIFTY k=2 sequence model with expiry-day and opening-IV controls

**Exploratory full-sample follow-up.** The k=2 timing and predictors are unchanged. The target remains strictly 09:18–09:45. IV buckets remain <14, 14–18 inclusive, and >18.

## Expiry classification audit

The proposed file-end rule is invalid: 65 of 66 source files span 29 calendar days, their `to_date` values cover all seven weekdays, and only 46/66 equal the final observed trading date. The files are storage chunks, not individual contracts. The CSV fields `expiry_flag=WEEK` and `expiry_code=1` identify the nearest-week selector but do not retain the contract expiry date.

Expiry dates are therefore reconstructed from the official NSE rule and the observed regular trading-date calendar: Thursday through 28-Aug-2025, no expiry in the transition interval, then Tuesday beginning 09-Sep-2025; holidays map to the preceding observed Monday–Friday session. This yields **276 expiry days** and **1042 non-expiry days**, with **3 scheduled expiries absent from the source and excluded rather than shifted**.

All scheduled weekdays: {'Thursday': 243, 'Tuesday': 36}; classified scheduled weekdays: {'Thursday': 240, 'Tuesday': 36}. Actual classified weekdays after holiday shifts: {'Monday': 4, 'Thursday': 228, 'Tuesday': 32, 'Wednesday': 12}; 16 dates move before the scheduled weekday. The missing scheduled dates are [{'scheduled_expiry': '2021-01-21', 'reason': 'scheduled session absent from source but not an NSE holiday'}, {'scheduled_expiry': '2021-06-10', 'reason': 'scheduled session absent from source but not an NSE holiday'}, {'scheduled_expiry': '2021-07-29', 'reason': 'scheduled session absent from source but not an NSE holiday'}]. Monthly expiry replaces that week's weekly contract; the binary label intentionally treats both as an index-expiry day and does not claim to distinguish them.

Of the earlier Thursday × high-IV cell's 185 days, **181 (97.8%) are classified expiry days**. This confirms that the earlier weekday cell was overwhelmingly an expiry cell rather than a generic Thursday cell.

## Model comparison

| Model | N | Pseudo-R² | Accuracy | Base | Uplift | Initial flag β / HAC p |
|---|---:|---:|---:|---:|---:|---:|
| Original predictors | 1318 | 0.37% | 53.0% | 50.1% | +2.9 pp | 0.384 / .017 |
| + expiry and IV bucket | 1318 | 0.47% | 53.0% | 50.1% | +2.9 pp | 0.399 / .014 |

The expiry-day main coefficient is **0.169** (HAC p=.277, odds ratio 1.18). The IV dummy block has joint p=.556; all three controls have joint p=.600.
As an additive control, expiry explains less than the prior weekday specification (0.47% versus 0.64% pseudo-R²; 53.0% versus 53.6% accuracy). Its value appears in conditioning the persistence effect, not in shifting the unconditional target rate.

## Persistence conditional on expiry

| Status | N | Base high-first | After initial high / low | Effect | p |
|---|---:|---:|---:|---:|---:|
| Expiry | 276 | 51.8% | 60.8% / 43.8% | +16.9 pp | .005 |
| Non-expiry | 1042 | 49.6% | 50.5% / 48.7% | +1.7 pp | .574 |

The simple difference between the expiry and non-expiry persistence effects is **+15.2 pp** (p=.023).

## Expiry × IV cells

| Cell | N | Base high-first | Persistence effect | Unadjusted p |
|---|---:|---:|---:|---:|
| expiry × low_<14 | 24 | 54.2% | +8.3 pp | .682 |
| expiry × middle_14_18 | 49 | 57.1% | -4.7 pp | .740 |
| expiry × high_>18 | 203 | 50.2% | +23.2 pp | <.001 |
| non_expiry × low_<14 | 451 | 49.4% | +4.6 pp | .329 |
| non_expiry × middle_14_18 | 281 | 50.5% | -5.3 pp | .371 |
| non_expiry × high_>18 | 310 | 49.0% | +4.2 pp | .461 |

The requested expiry × high-IV cell has **N=203**, **+23.2 pp** persistence, and p=<.001. Bonferroni across six cells gives **p=.006**.
Within high-IV days, expiry persistence exceeds non-expiry persistence by **+19.0 pp** (p=.033).

A diagnostic model allowing persistence to vary with both expiry and IV reaches 0.97% pseudo-R² and 53.9% accuracy. The three interaction terms are jointly significant at p=.034, but initial-sequence × expiry alone is p=.146 and joint IV-regime interaction p=.101.

## Verdict

**Expiry is the correct economic label behind the earlier Thursday cell, and it tightens the in-sample subgroup case—but it does not yet establish the k=2 edge.** Almost all Thursday × high-IV observations were expiry days, and the expiry × high-IV cell is cleaner and stronger. Yet expiry has no significant additive main effect, aggregate model fit remains tiny, and its persistence interaction weakens after allowing IV-regime interactions. Prospective validation is still required.

## Caveats

- Exact historical contract IDs/expiry dates are absent from the rolling CSV output; classification combines official NSE rules with the observed trading calendar.
- This remains a selected full-sample follow-up, not an out-of-sample validation.
- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.
