# Paper-derived recent alpha scan

The final index week and option week were not used for fitting or selection.

**Verdict: no costed alpha is ready for promotion.**

## Results

- Quarter-hour phase-0 validation correlation: +0.0636; final: +0.2479.
- Quarter-hour gross validation/final: +4.88 / +3.78 bps/day; final net at a 6bp round-trip hurdle: -140.22 bps/day.
- Selected on validation: `cash`; final net: +0.00 bps/day.
- Best active gated candidate: `low_vol_p0.1`; final net: -4.33 bps/day.
- Best ungated comparator final net: -11.86 bps/day.
- Half-hour option reversal correlation (validation/final): +0.2898 / -0.4102.
- Smile-curvature correlation (validation/final): +0.4554 / +0.6249; rank correlation: -0.2428 / -0.4021.

## Decision

- The quarter-hour timing structure is the only interesting index result, but its one-minute turnover makes the observed gross edge uneconomic at the stated cost hurdle.
- Low-volatility gating reduced losses versus the ungated comparator, but even the best active candidate lost in validation and the final week; cash won.
- The option reversal changes sign across splits, and curvature changes sign between linear and rank statistics. Neither is stable enough to promote.

## Interpretation boundary

Index P&L is a NIFTY return proxy, not a futures fill simulation. Option results are predictive diagnostics only: the archive rolls ATM-relative buckets and lacks fixed strikes, expiries, bid/ask, IV, and open interest. They must not be read as executable option P&L.

The option headline uses a fixed 10% jump filter. Raw and rank correlations remain in the JSON.

## Paper trail

- Quarter-hour phase effects: https://arxiv.org/abs/2607.09426
- Regime-aware return prediction: https://arxiv.org/abs/2606.09478
- Intraday option reversals: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5081696
- Intraday volatility-smile geometry: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5893362

Full shifted-clock placebos, participation/gating candidates, audit counts, and split statistics are in `paper_alpha_scan.json`.
