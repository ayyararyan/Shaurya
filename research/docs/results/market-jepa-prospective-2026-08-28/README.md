# Market-JEPA prospective validation — frozen 2026-08-28

## Status

**Frozen and waiting for one genuinely unseen completed session. No prospective targets have been
read and no prospective result exists yet.**

The authoritative bundle fingerprint is:

`89709f7b142ccf4e860a38d70d2b6c15376c4493377e5059716defbd8b2bcb5f`

The exact analysis-code commit recorded before the freeze is:

`eb4b548cae4124000ab26dac2fe31892e1ea4af3`

The older narrow bundle (`c3350aa8...836f28`) was never consumed and is superseded. It must not be
used for the final test.

## Frozen protocol

The experiment tests exactly three hypotheses on the first eligible session after August 28:

1. Whether Base+JEPA improves 30-second signed ATM-IV prediction beyond Base+PCA.
2. Whether 5/30/60-second JEPA transition shock predicts subsequent 30-second surface movement.
3. Whether JEPA improves or conditions 30-second ATM-IV mean-reversion forecasts.

The primary paired JEPA-vs-PCA comparison uses 60, 120, and 300-second bootstrap blocks. Shock
quintile boundaries come only from August 19 and 21. All five seeds are retained. The frozen
configuration records the architecture, features, alphas, lags, targets, blocks, metrics, selected
probe settings, source hashes, artifact hashes, and exact analysis commit.

The scientific conclusion is mechanical:

- **A — Promote JEPA to experimental Shaurya state feature:** JEPA beats PCA in at least four of
  five seeds and all three paired confidence intervals are positive in at least four seeds.
- **B — Keep JEPA as exploratory research only:** JEPA's point estimate beats PCA in at least three
  seeds, but A fails.
- **C — Drop JEPA from the active research stack:** JEPA beats PCA in fewer than three seeds.

This protocol cannot authorize trading, execution, deployment, or a P&L claim.

## Session discipline

The apply-only command rejects:

- August 19, 21, 26, or 27 and every date on or before August 28;
- the current India trading date or a future date;
- a changed column schema;
- fewer than 1,159 contiguous usable endpoints;
- modified source or frozen artifacts;
- a second run after successful bundle consumption.

A rejected session produces an explicit data-quality report without consuming the bundle. The
August 27 rejection path was exercised successfully during the audit.

## Office Mac paths

Frozen bundle:

`/Users/maheit/Documents/Shaurya-research/2026-08-28-market-jepa-prospective-freeze`

After the first eligible session is complete, run:

```bash
cd /Users/maheit/Documents/Shaurya-2026-08-28-research/research
/opt/homebrew/bin/uv run python experiments/apply_market_jepa_outer_test.py \
  --bundle /Users/maheit/Documents/Shaurya-research/2026-08-28-market-jepa-prospective-freeze \
  --session /absolute/path/to/completed/surface-states-YYYY-MM-DD.npz \
  --output /Users/maheit/Documents/Shaurya-research/market-jepa-prospective-YYYY-MM-DD
```

On success, the output directory will contain:

- `README.md`
- `results.json`
- `jepa_vs_pca.csv`
- `transition_shock.csv`
- `iv_mean_reversion.csv`
- `seed_stability.csv`
- `frozen_config.json`

Those result files do not exist yet because creating them requires the future outer-test session.
