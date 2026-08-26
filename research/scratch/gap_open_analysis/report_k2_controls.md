# NIFTY k=2 sequence model with weekday and opening-IV controls

**Exploratory full-sample follow-up.** The frozen decision/target timing is unchanged: predictors use 09:15–09:17 and the target label uses strictly future minute stamps 09:18–09:45 (28 observations). Opening IV is the arithmetic mean of the ATM-call 09:15 and 09:16 prints. Buckets are low <14, middle 14–18 inclusive, and high >18.

## Model comparison

All **1,318** frozen-panel days have both IV prints; no observations are lost. The high-first base rate is **50.1%**. Continuous predictors retain the prior one-standard-deviation scaling; Monday and middle IV are reference categories. Five special weekend sessions are retained under their own dummy. Inference is Newey-West HAC(5), and accuracy is in-sample.

| Model | N | Pseudo-R² | Accuracy | Base | Uplift | Initial flag β / HAC p |
|---|---:|---:|---:|---:|---:|---:|
| Original predictors | 1318 | 0.37% | 53.0% | 50.1% | +2.9 pp | 0.384 / .017 |
| + weekday and IV bucket | 1318 | 0.64% | 53.6% | 50.1% | +3.6 pp | 0.397 / .014 |

The controls add **0.27 percentage points** of pseudo-R² and change accuracy by **+0.7 pp**. The initial-sequence coefficient changes from 0.384 to 0.397; its HAC p-value changes from .017 to .014.

The robust joint Wald tests are weekday p=.516, IV-bucket p=.670, and all seven added controls p=.674.

## Weekday breakdown

Persistence effect = target high-first rate after initial high-first minus the rate after initial low-first.

| Day | N | Base high-first | After initial high / low | Persistence effect | p |
|---|---:|---:|---:|---:|---:|
| Monday | 265 | 49.1% | 51.3% / 45.9% | +5.4 pp | .390 |
| Tuesday | 265 | 48.3% | 51.8% / 44.4% | +7.4 pp | .228 |
| Wednesday | 263 | 48.7% | 47.7% / 49.3% | -1.6 pp | .798 |
| Thursday | 261 | 52.5% | 59.3% / 46.4% | +13.0 pp | .036 |
| Friday | 259 | 52.5% | 52.8% / 52.3% | +0.5 pp | .938 |
| Special weekend | 5 | 20.0% | 33.3% / 0.0% | +33.3 pp | .361 |

## Opening-IV breakdown

| IV bucket | N | Base high-first | After initial high / low | Persistence effect | p |
|---|---:|---:|---:|---:|---:|
| low_<14 | 475 | 49.7% | 52.2% / 47.4% | +4.8 pp | .294 |
| middle_14_18 | 330 | 51.5% | 48.8% / 54.2% | -5.4 pp | .326 |
| high_>18 | 513 | 49.5% | 54.9% / 43.3% | +11.6 pp | .009 |

## Weekday × IV cell-size audit

The 15 joint cells range from **N=33** (Friday|high_>18) to **N=185** (Thursday|high_>18). **3/15** cells have N<50 and are flagged as thin. Full cell estimates are saved in the CSV; the separate tables above are the more defensible summaries.

The standout joint cell is **Thursday × high IV**: N=185 and +21.3 pp persistence (unadjusted p=.004). It is not a thin cell, but it is the strongest result selected after inspecting 15 joint cells and the earlier k sweep; a simple 15-cell Bonferroni benchmark would put p near .058.

A diagnostic model interacting the initial-sequence flag with regular weekday and IV bucket gives robust joint p=.731 for weekday heterogeneity and p=.062 for IV-bucket heterogeneity. Its pseudo-R² is 1.14% and accuracy is 54.2%; this is a diagnostic, not the requested primary additive-control specification.

## Verdict

**The controls do not turn k=2 into a materially more convincing model.** They add only 0.27 pp of pseudo-R² and 0.7 pp of in-sample accuracy, while the original initial-sequence coefficient slightly strengthens rather than being absorbed. The high-IV slice (+11.6 pp, N=513) and especially Thursday × high IV (+21.3 pp, N=185) are legitimate prospective regime hypotheses, but IV-interaction heterogeneity is only borderline jointly (p=.062) and the strongest cell was selected after extensive scanning. This is not yet a demonstrated trading edge.

## Caveats

- This is a selected follow-up to the best k from a six-k scan; unadjusted p-values remain exploratory.
- The ATM call changes contract/strike through the source construction; its IV is a volatility-state proxy, not a constant instrument series.
- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.
- P0 is the prior session's final available spot stamp, not an official NSE close.
- Opening-IV audit: range 5.33–75.57; zero/non-positive dates=0.
