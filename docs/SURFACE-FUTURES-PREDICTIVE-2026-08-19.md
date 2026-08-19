# What the displayed eSSVI surface says about the next five-second futures move

**Scan:** `X-SURFACE-FUT5-20260819-06`

**Date:** 2026-08-19

**Confirmatory eligible:** `false`

**Execution commit:** `1b3442ad9bdf367171e981693c317b79a7e8bed6`

## Plain-English answer

On this full-session recording, the displayed eSSVI surface did **not** predict the NIFTY future's
mid-price move from `t+0.5 s` to `t+5.5 s`.

The surface-only Ridge model had held-out R² of **−0.24%**. That is numerically less bad than the
five-level LOB model (−0.74%), five-level OFI model (−2.01%) and their combination (−2.90%), but all
four lost to the training-mean benchmark. Adding the 72 surface-economic features to LOB+OFI made
held-out R² **worse**, from −2.90% to −6.08%, an increment of **−3.17 percentage points**.

The feature screen tells the same story. No held-out Pearson or Spearman relationship between any
surface feature and the future move survived the declared BH-FDR correction. The largest held-out
Pearson magnitude was only 0.0467. The largest Spearman magnitude was 0.0803, with FDR q=0.566.
Current skew and curvature levels were smaller still.

This is an exploratory failure to find predictive power, not evidence that surface information can
never help. It is one already-inspected session, and the displayed surface was raw-unsmoothed on
94.9% of eligible frames because the existing SUR-07 smoother honestly refused repeated raw surface
timestamps.

## Same-sample model comparison

All models use the identical 2,579 observations, exact five-level future book and exact future
target. The first 1,805 rows train the models; 23 rows are embargoed for 120 seconds; the final 751
rows are held out. Every fitted future model selected the maximum frozen Ridge penalty, alpha=100.

| Model | Inputs | Held-out R² | RMSE (ticks) | First test half R² | Second test half R² |
|---|---|---:|---:|---:|---:|
| N | training mean | 0.00% | 25.800 | — | — |
| S | displayed surface economics | **−0.24%** | 25.831 | −0.88% | +0.99% |
| SQ | surface + quality | −11.33% | 27.222 | −6.52% | −20.68% |
| L | five-level LOB | −0.74% | 25.895 | −0.09% | −2.01% |
| O | five-level OFI | −2.01% | 26.057 | −1.07% | −3.83% |
| LO | LOB + OFI | −2.90% | 26.172 | −1.49% | −5.66% |
| LOS | LOB + OFI + surface | −6.08% | 26.572 | −4.92% | −8.33% |
| LOSQ | all blocks + quality | −19.10% | 28.156 | −11.98% | −32.94% |

The literal no-price-change RMSE is 25.804 ticks. The training-mean benchmark is only marginally
better because the training mean is −0.147 ticks.

### Primary paired comparison

For `LOS` versus `LO`, adding the surface changed held-out R² by −3.173 percentage points and
changed mean squared error by **−21.118 tick²** under the convention that positive favours the
enhanced model. The dependence-aware t statistics are:

- Newey-West/HAC lag 2: **−2.029**;
- stationary bootstrap, expected block 6 frames: **−2.033**;
- non-overlapping 10-second blocks: **−1.958**, across 377 blocks.

The honest interpretation is that the surface block did not help and instead increased error in
this test segment. This does not identify causal harm, an inverse signal or an economic effect.

Surface quality was especially harmful as a predictor: `SQ−S` was −11.09 percentage points and
`LOSQ−LOS` was −13.02 points. Their paired t statistics were approximately −5 to −7 across the
three estimators. Quality therefore stays a labelled diagnostic block and is not folded into the
surface-economic headline.

## Skew, curvature and parameter correlations

No held-out correlation passed FDR. Two rows illustrate the upper edge of the search:

| Held-out relationship | Correlation | HAC t | BH-FDR q |
|---|---:|---:|---:|
| Pearson: Sep-29 ATM-IV one-frame change | +0.0467 | +1.178 | 0.989 |
| Spearman: Sep-01 minus Aug-25 ATM-skew one-frame change | −0.0803 | −2.106 | 0.566 |

The current level variables—the quantities closest to “observe skew/curvature pattern x now”—are
also weak:

| Current displayed level | Held-out Pearson | Held-out Spearman |
|---|---:|---:|
| Aug-25 ATM skew | −0.0059 | +0.0193 |
| Aug-25 ATM curvature | −0.0104 | −0.0008 |
| Sep-01 ATM skew | −0.0244 | −0.0631 |
| Sep-01 ATM curvature | −0.0096 | −0.0246 |
| Sep-29 ATM skew | +0.0128 | +0.0168 |
| Sep-29 ATM curvature | +0.0136 | +0.0056 |

Some full-sample change/velocity correlations pass FDR, but none survives in the held-out family.
The strongest full-sample Spearman relationship is about −0.081 for the near-expiry theta/ATM-IV
change cluster. It is not treated as predictive evidence.

Individual Ridge coefficients are not importance claims. The 72-dimensional surface matrix has
rank 54; in the full sample, 354 of 2,556 feature pairs have absolute Pearson correlation at least
0.95. In particular, one-frame deltas and per-second velocities are nearly identical because fit
gaps are close to five seconds. Ridge coefficients and mean-absolute contributions are emitted for
audit, but their split credit is not economically interpretable.

## Past mirror and same-window diagnostics

The apparatus explains completed or overlapping price motion far better than future motion:

| Model | Future R² | Past mirror R² | Same-window R² |
|---|---:|---:|---:|
| S | −0.24% | +2.44% | +3.95% |
| O | −2.01% | +26.85% | +33.30% |
| LO | −2.90% | +25.81% | +33.57% |
| LOS | −6.08% | +24.26% | +28.21% |

This is the main contamination warning. Five-level OFI strongly tracks the price move that has
already happened or overlaps its own window, but not the next five-second move after the 500 ms
gap. Surface changes show the same pattern more weakly. Same-window results validate construction;
they are not forecasts.

## Freshness, smoothing and placebo checks

Restricting to fresher displayed surfaces does not rescue the result:

| Surface age arm | Train | Test | S R² | LO R² | LOS R² | LOS−LO |
|---|---:|---:|---:|---:|---:|---:|
| ≤480 s | 1,104 | 751 | −0.48% | −3.53% | −7.28% | −3.75 points |
| ≤240 s | 393 | 676 | −4.71% | −11.21% | −14.11% | −2.90 points |

The frozen 300-second no-wrap lag placebo is also negative: LO R² −2.43%, lagged-surface LOS R²
−7.56%, increment −5.13 points. Its three paired t statistics are −3.80, −3.93 and −3.68. Both the
current and stale surface blocks hurt this one-session fit; the placebo does not create a positive
surface lead.

Of 2,579 common observations, 131 (5.08%) were temporally smoothed and 2,448 (94.92%) were labelled
`raw_unsmoothed: raw surface timestamps must increase strictly`. Median surface age was 286.6 s;
p95 was 895.0 s; 27.34% were above the existing 480 s stale threshold. The fitted slice itself was
well-behaved when emitted: all frames passed the arbitrage check; median weighted R² was 0.9871;
median total-variance RMSE was 0.0000571; the normal frame used 225 quotes.

Live fit duration is unavailable because it was not persisted in the tape. Its fixed quality
column is missing with an explicit training-only missing indicator. Replay CPU duration never
enters a model.

## Data and target record

- Pinned tape: 5,496,592 rows; 9,149,464,566 bytes; SHA-256
  `f85b4bdb4c6cce15664849dbf7405d89d35b89a258a2834d94acb0004108a28f`.
- Target future: `NSE:NSE_FNO:NIFTY:future:2026-08-25`.
- Book: Dhan Quote/Full embedded five levels, explicitly not depth20/depth200.
- Surface: unchanged `SurfaceEngine`, expiries Aug-25/Sep-01/Sep-29, five-second cadence and the
  existing forward selector, eSSVI constraints, no-arbitrage gates and SUR-07 smoother/refusal.
- Successful fits: 2,581 of 2,582 attempts; one first frame has no prior surface; one final future
  target is beyond the tape edge; 2,579 common rows remain.
- Eligible anchor interval: 12:04:22.794–15:39:54.898 IST.
- Target distribution: median 0 ticks; interquartile range −10 to +10; 5th/95th percentiles about
  −46.1/+47.0; 17.37% are zero; the maximum is +466 ticks.
- Target as-of ages: median 0.438 s at the start and 0.435 s at the end; maxima 3.210/2.206 s, both
  safely inside the frozen 6 s guard.

The immutable row/byte/hash pins all match. The replay-measured first/last row timestamps are
06:34:12.754–10:10:02.723 UTC. The frozen specification's prose interval ended at 10:14:16.499 UTC;
that prose bound was inaccurate, but the uniquely pinned path, row count, byte count and SHA-256
were correct and the input was not changed or substituted.

## Comparison with the earlier OFI work

The scientifically valid comparison is the same-tape table above: at the exact five-second
lookback/five-second response on the exact five-level Full book, neither multivariable LOB nor OFI
beats the benchmark, and adding the surface makes the combined model worse.

The earlier `X-OFI-DAT20-03` scan reported an exploratory +7.91-point increment for ten-second,
top-ten price-keyed OFI predicting a ten-second return. The causal-alignment horse race reported a
+6.20-point exploratory lead for depth-normalised CKS at two seconds. Those numbers come from two
different 11-minute DAT-20 tapes, depth20/depth200 channels, anchor clocks and horizons. They are
context only—not apples-to-apples evidence that one object “wins” or that this full-session result
contradicts them.

## Bottom line

For this session and exact 500 ms gap / five-second horizon:

> **No displayed eSSVI skew, curvature, parameter or surface-change pattern showed credible
> held-out predictive power for the front-future mid move. The surface-only model was approximately
> flat but negative, every five-level LOB/OFI alternative was also negative, and adding the surface
> to LOB+OFI worsened held-out error.**

The result is useful because it rules out promotion from this experiment. A later test would need a
newly frozen candidate and independent full sessions; this tape cannot become confirmatory evidence.

## Validation and artifacts

- Primary artifact manifest SHA-256:
  `ef09f09da95538d5ad4f6331fc6e3fa0057307f050c27c141c2a2d31587fa36d`.
- A second independent full replay wrote to a separate output directory. All eight payload byte
  counts and SHA-256 values were identical. Its path-bearing manifest SHA-256 is
  `8bfc368a6ba8934307af1e4854f63eda637846d99560d51b5c53d620a4a09429`.
- Focused tests: 15 passed, with one `RuntimeWarning: invalid value encountered in divide` at the
  Ridge SVD path in `deep_book_normal_activity.py:871`.
- Full Python suite: 499 passed, with seven occurrences of that same warning.
- Repository Ruff: passed. Strict mypy: passed on 53 source files. Compileall, JSON validation and
  diff checks: passed.
- `docs/sig-claims/H-SIG21.md` is byte-for-byte unchanged.

## Reproduce

```bash
PYTHONPATH=src python -m scripts.surface_futures_predictive \
  --tape /Users/maheit/Documents/Shaurya/data/live-captures/anl03-live/sha-20260819T063412.584779Z-0a555c5b/tape_sha-20260819T063412.584779Z-0a555c5b.jsonl \
  --output-dir artifacts/surface-futures-predictive \
  --replicates 400 \
  --seed 20260819
```

Full outputs are gitignored and hash-pinned by the committed compact summary. Frozen requirement
coverage is in `docs/SURFACE-FUTURES-PREDICTIVE-SPEC-COVERAGE-2026-08-19.md`.
