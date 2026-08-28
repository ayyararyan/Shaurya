# Aug 28 research handoff

## Honest status

Aug 28 is still an active market-data capture, so it cannot be called a completed or
prospective test session yet. The first honest outer test from this branch is Aug 31, with
all model and selection choices frozen after Aug 28 closes and before Aug 31 opens.

The results below are retrospective diagnostics using Aug 21 for discovery, Aug 26 for
validation, and the completed Aug 27 session as a conditional final check. They are not a
live-trading or profitability claim.

## Surface magnitude results

The 93-candidate frozen validation screen promoted 27 candidates after Holm correction.
The top supervised candidates were evaluated without refitting after selection:

| Candidate | Aug 26 validation skill | Aug 27 final skill | Final samples | Final p-value |
| --- | ---: | ---: | ---: | ---: |
| Surface HGB, 300 s realized futures volatility | 32.31% | 27.19% | 4,459 | 0.00050 |
| Base HGB, 300 s absolute ATM straddle change | 29.24% | 25.93% | 3,681 | 0.00050 |

Skill is MAE improvement against the discovery-session constant baseline. These models
forecast movement magnitude, not signed returns. They may be useful as regime or entry
filters, but they do not establish trade PnL after spread, fees, slippage, or hedging.

## Market-JEPA diagnostic

One fixed seed (42) trained on Aug 21, selected its stopping epoch on Aug 26, and was tested
on Aug 27. The JEPA embedding's MAE skill against a constant baseline was:

| Aug 27 target | JEPA skill | Last-state skill | Flattened-context skill |
| --- | ---: | ---: | ---: |
| Absolute ATM straddle change, 30 s | 3.66% | -9.71% | -37.91% |
| Absolute futures return, 30 s | -0.13% | -40.74% | -88.98% |
| Near-ATM spread change, 30 s | 8.85% | 21.90% | -13.47% |
| Realized volatility, 30 s | 5.82% | -3.12% | -25.43% |

JEPA is therefore useful enough to retain as a representation candidate, but it did not
uniformly beat simple features and is not itself an alpha or trading strategy.

## Reproducible artifacts on the Office Mac

- Selection: `/Users/maheit/Documents/Shaurya-research/2026-08-28-prospective/surface-alpha-21-26-27.json`
- Volatility final check: `/Users/maheit/Documents/Shaurya-research/2026-08-28-prospective/surface-top-final-2026-08-27.json`
- Straddle-magnitude final check: `/Users/maheit/Documents/Shaurya-research/2026-08-28-prospective/straddle-top-final-2026-08-27.json`
- JEPA run: `/Users/maheit/Documents/Shaurya-research/2026-08-28-prospective/jepa-21-26-27-seed42/results.json`

## Next prospective run

After Aug 28 is completed and catalogued, freeze the candidate set and run:

```bash
cd /Users/maheit/Documents/Shaurya-2026-08-28-research/research
.venv/bin/shaurya-research daily \
  --date 2026-08-28 \
  --next-session 2026-08-31 \
  --catalog /Volumes/Aryan/NSE/catalog/datasets \
  --bundle high_frequency
```

Do not label Aug 28 prospective: its data existed before this freeze. The Aug 31 report
must include costs and should keep cash as the default unless a signed, executable candidate
survives the branch's validation gates.
