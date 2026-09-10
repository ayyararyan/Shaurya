# RV Forecast V2 — Horse Race Stage 1

Run date: 2026-09-10
Forecast origin: 10:00 IST
Target: forward integrated NIFTY realized variance through nearest weekly expiry, including all future close-to-open overnight gaps.

## Data and audit

- Historical eSSVI reconstruction: 814 successful surfaces from 815 2023–2026 sessions (99.88%).
- Headline untouched static test: 89 sessions, 2026-01-01 through 2026-05-14.
- Static train set: 724 origins ending in 2025; labels admitted only when expiry was before 2026-01-01.
- Walk-forward update rule: for each 2026 origin d, a training row is admitted only when its expiry < d.
- Feb 3, 2026 tail audit: raw NIFTY bars show Feb 2 close near 25,088 and Feb 3 open 26,308.05, approximately +4.9%. This is a real market gap, not a session-boundary bug.

## Static untouched-2026 leaderboard

| Rank | Model | QLIKE | Corr(var) | RV RMSE pts | RV MAE pts | Mean pred RV | Mean actual RV |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | eSSVI IV identity (theta) | 0.5050 | 0.339 | 11.95 | 6.80 | 20.25% | 20.33% |
| 2 | HAR + eSSVI | 0.6109 | 0.309 | 11.88 | 6.00 | 18.03% | 20.33% |
| 3 | Rich eSSVI/HAR ridge | 0.6267 | 0.355 | 11.84 | 5.71 | 17.26% | 20.33% |
| 4 | Day/night decomposition | 0.6296 | 0.391 | 11.80 | 5.68 | 17.28% | 20.33% |
| 5 | HAR total | 0.6434 | 0.340 | 11.94 | 5.99 | 17.76% | 20.33% |
| 6 | Refit IV-only | 0.6527 | 0.359 | 11.97 | 5.93 | 17.43% | 20.33% |
| 7 | Current frozen NSGVC | 0.7621 | 0.350 | 12.20 | 5.99 | 16.75% | 20.33% |
| 8 | HGB nonlinear | 0.8204 | 0.444 | 12.53 | 6.35 | 16.19% | 20.33% |
| 9 | Day/night ridge | 1.0500 | 0.399 | 14.28 | 6.98 | 15.90% | 20.33% |
| 10 | Mean variance-rate | 1.3120 | 0.245 | 14.42 | 8.97 | 15.16% | 20.33% |

Primary finding: raw eSSVI theta is the best aggregate conditional-mean/tail-risk anchor in the 2026 test. Rich models often improve MAE/correlation but underpredict the rare extreme variance observations, which QLIKE correctly penalizes heavily.

## Strict purged expanding walk-forward in 2026

Using coefficients re-estimated only after a prior weekly label is completely realized:

| Rank | Model | QLIKE | Corr(var) | Mean pred RV |
|---:|---|---:|---:|---:|
| 1 | eSSVI IV identity | 0.5050 | 0.339 | 20.25% |
| 2 | HAR + eSSVI | 0.6210 | 0.266 | 18.84% |
| 3 | Day/night | 0.6367 | 0.310 | 18.46% |
| 4 | HAR total | 0.6413 | 0.291 | 18.75% |
| 5 | Refit IV-only | 0.6443 | 0.311 | 18.29% |
| 6 | Rich ridge | 0.6818 | 0.317 | 17.55% |
| 7 | Current NSGVC | 0.7621 | 0.350 | 16.75% |

After the Feb 3 expiry shock is fully observed, the refit IV-only model achieves QLIKE 0.2164 versus 0.2358 for raw theta over subsequent 2026 origins. The richer family therefore has useful ordinary-regime signal; it simply does not protect enough against previously unseen overnight tail jumps.

## Overnight component diagnosis

For the simple day/night decomposition in the untouched 2026 test:

- Intraday QLIKE: 0.1836; corr: 0.540.
- Overnight QLIKE: 4.2542; corr: 0.298.
- Mean actual future overnight integrated variance on rows containing nights: 0.000301.
- Mean predicted: 0.000070.

Overnight risk is therefore the dominant modeling failure, not intraday RV.

In 2026:

- Future overnight variance is 56.6% of total integrated variance when weighted across the sample.
- On rows containing at least one future night, the mean overnight share is 32.6%.
- Mean realized q = RV_int/theta is 1.413, while median q is only 0.772.
- q 90th percentile = 2.479; q 95th = 5.912; maximum = 13.867.

This distribution is extremely right-skewed: the typical carry trade can still have RV below IV, while a small number of overnight shocks dominate the arithmetic mean and expected gamma loss.

## Regime stability

QLIKE of the two simplest robust anchors by year:

| Year | eSSVI theta | Current NSGVC |
|---:|---:|---:|
| 2023 | 0.0646 | 0.0673 |
| 2024 | 0.1536 | 0.1729 |
| 2025 | 0.1644 | 0.1389 |
| 2026 | 0.5050 | 0.7621 |

Current NSGVC won narrowly in 2025 but its downward carry adjustment became dangerous in the 2026 overnight-tail regime.

## Adaptive Stage 2 experiments

After observing the Stage 1 result, additional QLIKE-link/offset models and fixed theta blends were tested. These are explicitly adaptive research diagnostics and are not pristine 2026 validation.

- Best adaptive QLIKE-link blend: approximately 0.5207, still worse than raw theta at 0.5050.
- A pre-2026-selected regime-switch gate did not beat theta in 2026.

Therefore there is no evidence yet to replace the production model with one of these Stage 2 variants.

## Current conclusion

Do not promote a new production RV model yet.

The next model architecture should retain two pieces rather than forcing one regression to do both jobs:

1. a central/ordinary-regime RV forecast, where HAR + eSSVI and the day model have genuine predictive information; and
2. an overnight jump/tail expectation, with eSSVI theta as a hard probabilistic anchor and separate event/global-state predictors where timestamp-clean historical data exist.

The production NSGVC coefficients and q<0.70 policy remain unchanged until a challenger beats the incumbent under a final frozen out-of-sample test.
