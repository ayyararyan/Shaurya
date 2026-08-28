# Market-JEPA prototype — 2026-08-26

Status: **compute feasibility passed; representation benchmark failed**.

This experiment is not a trading backtest or profitability claim. It excluded every
`sample_role=test` row before constructing market states, so the official strategy holdout remains
untouched.

## Setup

- Remote device: Apple M2 Max through PyTorch MPS.
- Model: 374,048 parameters; 96-dimensional embedding; three-layer causal context transformer;
  EMA target encoder; 5-, 30-, and 60-second latent targets.
- Input: 43 causal futures, option-book, and ATM cross-sectional state features.
- Context: 12 five-second observations (one minute).
- Strictly contiguous sequences after quality filtering: 107 discovery, 48 validation, and 43
  internal-test sequences, all drawn only from the original training region.
- Replications: five fixed-architecture seeds (1, 7, 23, 42, 101).
- Early-stopped training time: 2.1–2.8 seconds after Metal warm-up.

## Median frozen-probe result across five seeds

MAE skill is measured against a discovery+validation median forecast. Positive is better.

| 30-second target | Median JEPA skill | Seeds above zero |
|---|---:|---:|
| Absolute NIFTY futures return | -7.64% | 0/5 |
| Realized futures volatility | -6.49% | 1/5 |
| Absolute ATM straddle change | -33.20% | 0/5 |
| Near-ATM spread change | -5.01% | 1/5 |

The embeddings did not collapse: effective rank was approximately 27.6–28.4 out of 96 across
seeds. Nevertheless, frozen linear probes failed to beat a constant forecast consistently on every
target. The limitation is the tiny number of independent, contiguous sequences from one fragmented
afternoon—not compute capacity.

## Decision

Do not promote this model or use it for trading. Preserve the architecture as a reproducible
baseline, collect complete sessions, and repeat the same seed-aggregated benchmark across days.
The Mac is easily capable of running a materially larger model once independent data exists.

Remote reproducibility root:

`/Users/maheit/Documents/Shaurya-research/2026-08-26-market-jepa`

