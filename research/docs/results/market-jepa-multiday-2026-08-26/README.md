# Multi-day Market-JEPA — 2026-08-26

Status: **one exploratory representation lead; no model or trading promotion**.

## Data and protocol

Three completed, schema-compatible NIFTY futures/options tapes were streamed once into a common
causal five-second representation:

| role | session | raw rows | clean states | contiguous sequences used |
|---|---:|---:|---:|---:|
| discovery | 2026-08-19 | 5,496,592 | 2,588 | 2,553 |
| validation | 2026-08-21 | 3,286,554 | 1,484 | 1,449 |
| diagnostic | 2026-08-26 | 1,935,092 | 1,791 before cutoff | 1,748 |

The raw normalizer used receive-time ordering, a ten-second maximum quote age, a 1.5% ATM-relative
strike window, and a 30-second buffer after every connection-epoch transition. Feature
normalization was fitted on August 19 only. August 21 controlled early stopping and linear-probe
regularization. No August 26 target after the pre-existing 09:08:45 UTC training cutoff was used.

The fixed model had 375,200 parameters, a two-minute context, and 5-, 30-, and 60-second latent
targets. Five fixed-architecture seeds were run on Apple MPS. Each early-stopped fit took 6.2–8.7
seconds after preprocessing.

## Five-seed diagnostic results

MAE skill is relative to a discovery+validation median forecast. Positive is better.

| 30-second target | Median JEPA skill | Range | Positive seeds |
|---|---:|---:|---:|
| Absolute NIFTY futures return | -41.14% | -66.38% to -0.60% | 0/5 |
| Realized futures volatility | -79.05% | -124.25% to -10.30% | 0/5 |
| Absolute ATM straddle change | **+7.16%** | -11.90% to +9.05% | 3/5 |
| Near-ATM spread change | -4.13% | -28.77% to +4.08% | 1/5 |

The representation did not collapse: diagnostic effective rank ranged from 38.6 to 42.4 out of
96. Nevertheless, futures-movement and volatility prediction failed across every seed. The
straddle-magnitude result is the only lead, but its sign changes with initialization and one partial
diagnostic session cannot establish reliability.

A simple last-state ridge model achieved +14.04% diagnostic skill for signed near-ATM spread
change, while the corresponding JEPA median was negative. That supports keeping a simple baseline
in every future comparison; it is a liquidity forecast diagnostic, not executable alpha.

## Decision

- Do not use the JEPA for trading.
- Preserve absolute ATM-straddle movement as a preregistered representation target for the next
  independent session.
- Preserve the last-state ridge spread-change model as the mandatory simple benchmark.
- Do not change architecture or select a favorable random seed using the August 26 diagnostic.

Remote reproducibility root:

`/Users/maheit/Documents/Shaurya-research/2026-08-26-market-jepa`

