# What price-keyed OFI explains about the next futures return — `X-OFI-DAT20-03`

**Date:** 2026-08-19 · **Confirmatory eligible:** `false`  
**Execution commit:** `b6c574d` · **Complete grid:** 175/175 cells

## Plain English

### The answer

There is one clear **candidate** in these recordings:

> Add up price-keyed OFI over the last **10 seconds**, using the top **10 levels**, and use it to
> explain the futures return over the next **10 seconds** after a 0.5-second gap.

Positive OFI means bid quantity strengthened or ask quantity disappeared. Its fitted sign is
positive: more buy pressure is followed by a higher return.

On the held-out tail of the two recordings:

| Quantity | Result |
|---|---:|
| OFI-only out-of-sample R² | **7.92%** |
| Spread + microprice baseline R² | **−0.12%** |
| Baseline + OFI R² | **7.78%** |
| Improvement from adding OFI | **7.91 percentage points** |
| Return change for +1 standard deviation of OFI | **+4.07 ticks** |
| Return change for +100 contracts of OFI | **+0.083 ticks** |

The sign and improvement are present in both recordings separately. The full-model R² is 2.78%
in the first recording and 3.77% in the second; OFI improves their state baselines by 8.80 and
4.57 percentage points respectively.

### What inside the ten levels carries it

The secondary nested ladder says the best quote is not the source. At the 10-second/10-second
candidate:

| Added OFI band | Change in out-of-sample R² |
|---|---:|
| Level 1 | −0.53 points |
| Levels 2–5 | **+6.60 points** |
| Levels 6–10 | **+1.39 points** |
| Levels 11–20 | −14.18 points |
| Levels 21–50 | −0.69 points |
| Levels 51–100 | −0.25 points |
| Levels 101–200 | +1.17 points |

So the actual lead is **flow just behind the touch, especially levels 2–5 and then 6–10**. It is
not level 1, and it is not the far 200-level tail.

### Why this is not yet a finding

The candidate is numerically visible but statistically unresolved on 22 minutes of one falling
session.

1. The three overlap-aware checks on its forecast-error improvement are only **1.51, 1.65 and
   1.20**. The required bar was 1.96 on all three. It does not clear it.
2. The same OFI explains the **already-finished past** more strongly than the future: 13.29 versus
   7.91 percentage points of incremental R². Across the complete grid, the past increment beats
   the future in **103 of 175** cells. The tape still carries strong drift/reaction contamination.
3. Exactly one of 175 cells clears all three unadjusted checks. It is 2-second OFI over 200 levels
   predicting 2 seconds, with only +0.21 percentage points of incremental R². Its coefficient
   flips sign between the two recordings and its improvement is negative in one. One isolated hit
   in a 175-cell search is what chance looks like, not evidence.
4. The first recording alone makes level-1 OFI appear spectacular at 30 seconds (R² up to 57.7%);
   the second recording does not reproduce it. That is a clean demonstration of why this session
   cannot choose a 30-second model.

### Construction check

The strongest same-window relationship is the 10-second/top-10 construction, with descriptive
R² = 13.21%. That is the expected direction and supports the arithmetic, but same-window OFI and
price change are partly mechanical, so this number is never called forecasting power.

Price-keying and the outer-window guard matter, but the guard is not driving the result: removed
outer-edge quantity is only about **0.023–0.026%** of total absolute quantity change across the five
OFI windows.

### Bottom line

Aryan's correction changed the answer. The mixed 584-feature scan did not isolate this object.
Once OFI is isolated, the data points to a specific candidate:

> **10-second price-keyed OFI in levels 2–10 → next 10-second futures return.**

But the honest status is **exploratory lead, not confirmed signal**. The decisive next test is to
freeze this one candidate before the next tape and run it unchanged on a full, two-sided market
session. The 175-cell discovery grid must not be searched again on that confirmation tape.

## Technical record

### Frozen axes

- OFI windows: 0.5, 1, 2, 5, 10 seconds.
- Cumulative depths: 1, 5, 10, 20, 50, 100, 200.
- Future-return horizons: 1, 2, 5, 10, 30 seconds.
- Causal gap: 0.5 seconds.
- Models: OFI only; spread + microprice tilt; state baseline + OFI.
- Split: first 70% of each tape for training, 120-second embargo, later tail for test.
- Sample: 5,204 aligned observations; 3,641 train; 961 embargoed; 602 test.
- Inference: Newey–West, within-tape stationary block bootstrap, and non-overlapping time blocks.

### Object construction

For each consecutive valid depth200 state, bid quantity changes enter positively and ask quantity
changes negatively at the same absolute price. Each changed price is assigned the shallowest rank
it occupies in either endpoint. A one-level outer-window slide is excluded and counted so a vendor
window boundary cannot masquerade as flow. The cumulative top-D OFI is then summed over the frozen
look-back window. All windows require complete past coverage inside one connection epoch.

Target returns use the depth20 BBO midpoint, coverage-guarded and resolved as-of. The response begins
0.5 seconds after the OFI window ends. The complete future and past grids are emitted; no top-cell
filtering occurs in the artifacts.

### Reproduce

```bash
.venv/bin/python -m scripts.deepbook_ofi_scan \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T073935.092996Z-6ca41203/tape_sha-20260819T073935.092996Z-6ca41203.jsonl \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T075057.972093Z-286d5105/tape_sha-20260819T075057.972093Z-286d5105.jsonl \
  --output artifacts/deepbook-ofi/ofi_predictive_scan_2026-08-19.json \
  --grid-output artifacts/deepbook-ofi/ofi_grid_2026-08-19.jsonl \
  --nested-output artifacts/deepbook-ofi/ofi_nested_depth_2026-08-19.jsonl \
  --replicates 400
```

Artifacts are gitignored by repository policy. The complete deterministic regeneration command,
execution commit and pinned tape hashes make them reproducible.
