# OpenEvolve alpha discovery run

## Verdict

**Rejected in validation; final week not accessed.**

OpenEvolve 0.2.27 ran 20 generations using GPT-5.6 Luna/Sol through an authenticated, ephemeral,
read-only Codex CLI adapter. Generated formulas were AST-restricted and received only causal,
standardized arrays from September 1, 2025 through June 30, 2026.

The seed's weaker-subperiod discovery result was -1.682 bps/day after a 1 bp round trip. The
evolved winner improved this to +0.502 bps/day, with +0.549 and +0.502 bps/day in the two
discovery subperiods. It remained -3.315 bps/day at the 6 bp stress hurdle.

The frozen formula was a volatility-gated gap fade plus a small session-reversal term. Its
July 1-August 14 validation results were:

| round-trip cost | mean bps/day | annualized Sharpe | one-sided p |
|---:|---:|---:|---:|
| 0 bps | +0.847 | +1.31 | 0.3194 |
| 1 bp | +0.271 | +0.44 | 0.4379 |
| 2 bps | -0.305 | -0.50 | 0.5713 |
| 6 bps | -2.608 | -3.92 | 0.9172 |

Promotion required positive net performance and one-sided p < 0.05 at 1 bp. The candidate failed,
so August 17-21 target returns were not evaluated by this promotion run. Repeatedly trying new
evolution winners on the same validation period is prohibited.

The frozen program is
[`discovery_best_20.py`](../../../experiments/openevolve_alpha/discovery_best_20.py).
