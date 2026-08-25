# Research priors from the original D51 day

These numbers are **initial research priors only**. They are not hard-coded production weights and should not be interpreted as evidence that the strategy is ready for live capital.

The source day suggested that passive quoting at the touch was adversely selected, while selective bids several ticks behind the market had better conditional hedged markouts. The put side was materially more stable than the call side in that one sample. A fresh leave-target-strike-out smile/surface residual was the strongest fair-value feature, with option depth imbalance useful as a shorter-horizon microprice signal and futures OFI / synthetic-forward displacement useful mainly as secondary toxicity/skew state.

Indicative pooled one-day bid results used to choose the initial action grid:

| Contract | Offset below best bid | Conservative fill rate | Fill-conditioned hedged markout | Quote-opportunity EV |
|---|---:|---:|---:|---:|
| CE | 0.00 | 7.19% | -0.0857 | -0.00616 |
| CE | 0.15 | 1.81% | +0.0078 | +0.00014 |
| CE | 0.20 | 1.10% | +0.0315 | +0.00035 |
| CE | 0.30 | 0.42% | +0.0461 | +0.00020 |
| PE | 0.00 | 7.63% | -0.0798 | -0.00609 |
| PE | 0.15 | 2.54% | +0.0087 | +0.00022 |
| PE | 0.20 | 1.68% | +0.0465 | +0.00078 |
| PE | 0.30 | 0.64% | +0.1013 | +0.00064 |
| PE | 0.40 | 0.27% | +0.1518 | +0.00041 |

The CE 0.20-point bid edge flipped negative in the final time quartile of the source tape, whereas PE 0.20/0.30-point bids stayed positive across all four quarters. That regime failure is why D51 ALO-SMM has separate CE/PE × BUY/SELL models, online calibration, and a side-level kill switch.

The one-day fixed PE example around `bestBid - 0.30` / `bestAsk + 0.40` produced too few completed cycles to be statistically meaningful. It should be treated as a search-region clue, not as a fixed strategy.

The shadow month exists to replace these priors with many independent daily observations.
