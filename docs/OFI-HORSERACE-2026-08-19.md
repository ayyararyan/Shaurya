# Which short-horizon order-book predictor wins on the retained NIFTY futures tapes?

**Scan:** `X-OFI-HORSERACE-DAT20-05`

**Execution commit:** `e39d67ce787824d78a7439caa89afa15c784f0b4`

**Evidence:** Level-3 reproducible machinery; exploratory empirical comparison only

**Confirmatory eligible:** `false`

## Owner summary

No predictor produces a reliable winner on these two already-inspected recordings. The combined
model has the highest raw held-out fit from 0.5 through 2 seconds, regularised multi-level OFI leads
at 5 seconds, and depth-adjusted multi-level OFI has the highest primary-model score at 10 seconds.
But the strongest 0.5–2-second improvements explain the **past mirror more strongly**, the 1-, 2-
and 5-second numerical leaders are weak or negative on one tape, and none of the five horizon
leaders clears all three dependence checks.

The useful technical lead is narrower: the predeclared **depth-normalised CKS robustness sub-arm**
is the most consistently positive family. At the 2-second/2-second cell it adds **6.204 percentage
points** of OOS R2 over displayed depth and spread, with +8.262 and +3.115 points on the two tapes.
That agrees with the CKS inverse-depth mechanism, but it was a labelled sub-arm, the tapes and price
paths were already inspected, and the same tiny sample cannot establish a general forecast relation.

The 30-second gate **failed**. Raw CKS at 0.5 seconds had positive incremental 10-second fit in both
tapes, but its separately fitted coefficient changed sign across tapes. No 30-second cell was fitted
or ranked.

**Action needed from Aryan: none.**

## Claim–evidence ledger

| ID | Claim | Type | Estimand/evidence | Main threat | Boundary | Status |
|---|---|---|---|---|---|---|
| C1 | No primary predictor is a robust overall winner | Predictive | Held-out incremental OOS R2, per-tape reproduction, three dependence checks and past mirror | 22 minutes, one falling session, 25 horizon/window cells per family | Applies only to these tapes | Supported descriptively |
| C2 | Depth-normalised CKS is the strongest robustness lead | Predictive | Best sub-arm at h1=2 s/h2=2 s: +6.204 pp, positive on both tapes | Registered robustness sub-arm; outcome-inspected sample; multiple comparisons | Candidate construction, not a signal | Supported as exploratory lead |
| C3 | The 30-second arm must remain closed | Specification/gate | Raw M3 at h1=0.5 s/h2=10 s fails cross-tape coefficient sign stability | Direction is sensitive to tape | No 30-second inference | Mechanically resolved |
| C4 | Signed trades are measurable here but do not dominate | Predictive/measurement | 191 qualified non-coalesced prints; best primary M2 increment +1.672 pp at h1=5 s/h2=5 s | Sparse/coalesced prints; last observed print only | Not total market-order flow | Supported descriptively |

## Design and identification

The unit is one valid depth200 publication anchor. Predictors use only states and capture-time trade
labels at or before that anchor. The target is the later depth20 BBO-midpoint return from `t+0.5 s`
to `t+0.5 s+h2`. The estimand is held-out OOS R2 relative to the training-mean target and its
increment over M0, the depth-only baseline. Variation is chronological within two tapes; it does not
identify a structural counterfactual. “Causal” in the construction means no look-ahead, not a causal
economic effect.

The frozen specification is [`OFI-HORSERACE-SPEC-2026-08-19.md`](OFI-HORSERACE-SPEC-2026-08-19.md).
The common model sample uses a 70/30 within-tape split and a 120-second embargo. All scaling and
Ridge selection use training observations only, with three expanding inner folds and
`alpha in {0, .01, .1, 1, 10, 100}`.

## Sample and support

| Quantity | Tape 0 | Tape 1 | Pooled |
|---|---:|---:|---:|
| Run | `...6ca41203` | `...286d5105` | — |
| Covered seconds | 652.734 | 652.636 | 1,305.370 |
| Common predictor anchors | 2,540 | 2,670 | **5,210** |
| Training anchors | 1,778 | 1,868 | **3,646** |
| Embargo anchors | 496 | 464 | **960** |
| Test anchors before horizon coverage | 266 | 338 | **604** |
| Qualified signed-trade packets | 101 | 90 | **191** |
| Excluded coalesced packets | 64 | 53 | **117** |
| Excluded degraded/unclassified | 1 | 1 | **2** |

Future coverage declines near the tape end. At h2=0.5 seconds, the test contains 266 and 338
anchors; at 10 seconds, it contains 226 and 298. Every identified model uses the identical
complete-case positions within a cell. M2 is identified: both tapes exceed the frozen 20-packet
minimum after excluding coalesced and degraded prints. A window with no qualified print is an
observed zero; absence of the trade schema would instead have blocked M2.

## Primary horse race

The table reports the strongest **reproducing** primary cell at each horizon: positive incremental
OOS R2 on both tapes. Percentage points are relative to M0. At 1 and 5 seconds this differs from the
unconstrained numerical maximum because the latter loses on tape 1.

| h2 | Primary family | h1 | Full OOS R2 | Increment vs M0 | Tape 0 | Tape 1 | Past-mirror increment | NW / bootstrap / non-overlap t |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | M6 combined | 5 s | 1.830% | **+2.018 pp** | +3.095 | +0.328 | +3.616 pp | 1.45 / 1.47 / 1.44 |
| 1 s | M6 combined | 1 s | 1.517% | **+2.115 pp** | +2.122 | +2.106 | +2.874 pp | 1.57 / 1.49 / 1.75 |
| 2 s | M6 combined | 5 s | 5.082% | **+5.539 pp** | +9.141 | +0.133 | +8.356 pp | 1.68 / 1.72 / 1.70 |
| 5 s | M4 regularised multi-level OFI | 2 s | 2.694% | **+1.719 pp** | +2.739 | +0.462 | +1.303 pp | 1.11 / 1.10 / 0.99 |
| 10 s | M3 raw exact L1 CKS | 0.5 s | 1.443% | **+0.082 pp** | +0.101 | +0.060 | -0.504 pp | 2.00 / 2.52 / 1.90 |

No row clears 1.96 on all three overlap-aware checks. The 0.5-, 1- and 2-second leaders explain the
past mirror more strongly than the future. At 5 and 10 seconds the future comparison is stronger,
but the gains are small or statistically unresolved.

### What each requested family contributes

- **M0 depth only.** OOS R2 is -0.188%, -0.598%, -0.457%, +0.975% and +1.361% from 0.5 to 10
  seconds. Displayed L1 depth and spread are weak benchmarks, not useful stand-alone forecasts.
- **M1 static L1 queue imbalance.** It adds +0.708, +1.114 and +2.731 pp through the 2-second
  horizon, but turns negative at 5 and 10 seconds. At 10 seconds the tape increments are +5.276 and
  -7.349 pp: the pooled result hides a sharp failure to reproduce.
- **M2 signed trade imbalance.** Its best increments by horizon are +0.081, +0.118, +0.793,
  +1.672 and +0.001 pp. The h1=5 s/h2=5 s cell is positive in both tapes (+2.528 and +0.618 pp),
  but sparse classified prints and coalescing make this a limited observed-flow object.
- **M3 exact raw L1 CKS.** Best increments are +0.639, +1.227, +1.473, +0.564 and +0.082 pp. The
  10-second gate cell reproduces in fit but not coefficient direction, so it cannot open 30 seconds.
- **M4 regularised multi-level OFI.** It leads the reproducing primary race at 5 seconds. The old
  h1=10 s/h2=10 s top-10 lead from `X-OFI-DAT20-03` does not survive the full seven-band Ridge model:
  M4 adds **-6.966 pp** there, with `alpha=100`.
- **M5 depth-adjusted multi-level OFI.** It beats M4 in 18 of 25 cells (the cell-level delta is
  emitted), but its best primary 10-second increment is only +0.122 pp and is negative on tape 1.
- **M6 combined.** It numerically leads 0.5–2 seconds. At the reproducing h1=1 s/h2=1 s cell,
  leaving out queue imbalance costs 1.245 pp and leaving out adjusted multi-level OFI costs 0.762
  pp; signed trades cost only 0.002 pp. At h1=5 s/h2=2 s, queue imbalance contributes 3.277 pp,
  M4 0.997 pp, M5 0.729 pp and trades 0.697 pp, while removing raw CKS improves fit by 0.433 pp.

## Depth-normalised CKS robustness lead

CKS predicts an inverse relationship between price-impact slope and depth, so M3b divides raw CKS
flow by causal average L1 depth. It is separate from the primary raw-CKS label and primary ranking.

| h2 | Best h1 | OOS R2 | Increment vs M0 | Tape 0 | Tape 1 | Past mirror |
|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | 2 s | 1.610% | +1.798 pp | +2.157 | +1.233 | +3.468 pp |
| 1 s | 2 s | 3.418% | +4.016 pp | +5.489 | +1.879 | +5.418 pp |
| 2 s | 2 s | **5.747%** | **+6.204 pp** | +8.262 | +3.115 | +2.608 pp |
| 5 s | 1 s | 4.446% | +3.471 pp | +5.082 | +1.486 | -1.218 pp |
| 10 s | 0.5 s | 3.143% | +1.781 pp | +2.657 | +0.815 | -0.186 pp |

This is the most coherent exploratory pattern, especially at 2 seconds. It still comes from a
declared robustness family on contaminated data, and the 0.5- and 1-second past placebos are
stronger. It is a frozen lead for later data, not a finding from these tapes.

## Gate and negative controls

At h2=10 seconds, every non-combined primary family was assessed against four frozen conditions.
M1 and M4 lack positive pooled fit and per-tape reproduction; M2 lacks per-tape reproduction and
coefficient stability; M5 lacks per-tape reproduction and is weaker than its past mirror. M3 alone
has positive pooled and per-tape increments and beats its past mirror, but its standardized CKS
coefficient changes sign across the separately fitted tapes. Therefore `gate_passed=false` and
`conditional_30_second_cells=[]`.

The strongest same-window diagnostic reaches 15.484% OOS R2 at h1=10 seconds for M5. This supports
construction sensitivity but is partly mechanical and is never ranked as forecasting power.

## Relation to adjacent scans

`X-OFI-DAT20-03` found a fragile h1=10 s top-10 scalar OFI lead for h2=10 s (+7.91 pp), driven by
levels 2–10 and dominated by its past mirror. This horse race changes the object to seven marginal
bands with training-selected Ridge and a common depth-only baseline. The old cell collapses rather
than reproduces. `X-CKS-L1-OFI-DAT20-04` separately reported that depth scaling improved 22/25 CKS
cells and peaked around h1=2 s/h2=2 s. The present M3b result agrees numerically with that adjacent
scan while showing why raw M3 itself is much weaker.

## Literature benchmark

- [Cont, Kukanov and Stoikov](https://arxiv.org/abs/1011.6402) study contemporaneous short-interval
  price impact from BBO OFI and document inverse-depth scaling. M3b agrees with their depth-scaling
  mechanism, but our future-return target is different and cannot be validated by their impact
  result.
- [Gould and Bonart](https://arxiv.org/abs/1512.03492) predict the direction of the next midpoint
  change using static queue imbalance. M1 agrees only at 0.5–2 seconds and fails at 5–10 seconds;
  our target is fixed calendar-horizon return, not next-tick direction.
- [Xu, Gould and Howison](https://arxiv.org/abs/1907.06230) show that multi-level OFI improves
  contemporaneous midpoint fit on Nasdaq stocks as deeper levels are added. Our M4 leads only at 5
  seconds and fails at the old 10-second cell; that is a disagreement for future prediction, not a
  refutation of their contemporaneous result.
- [Kolm, Turiel and Westray](https://doi.org/10.1111/mafi.12413) find order-flow representations
  outperform raw book states for multi-horizon Nasdaq return forecasts. Our M6 and normalised-CKS
  patterns are directionally consistent, but two Indian-futures tapes and linear Ridge models are
  not comparable evidence.
- [Bechler and Ludkovski](https://arxiv.org/abs/1708.02715) find limit additions/cancellations and
  deeper shape predictive at meso horizons. M4's 5-second lead is consistent with that mechanism;
  the snapshot feed cannot separately identify gross additions and cancellations, so this scan
  cannot test their event decomposition.
- [Easley, López de Prado and O'Hara](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1695596)
  introduce VPIN as a volume-time toxicity metric. VPIN is not a directional signed-trade predictor
  and was deliberately excluded from M2 and the horse race.

## Limitations and bottom line

These are two approximately 11-minute tapes of one NIFTY futures contract in one falling session.
The price paths and related OFI outcomes had already been inspected. Overlapping targets leave only
small non-overlapping-block counts, multiplicity is large, and there is no independent day,
two-sided regime, cost model or maker-fill outcome. Trade signing observes only classified last
prints and excludes 117 coalesced packets rather than assigning one sign to unseen volume.

**Bottom line:** no requested primary model is robust enough to call a winner. The only coherent
lead worth freezing is depth-normalised L1 CKS around a 2-second lookback and 2-second response, but
it remains exploratory and non-confirmatory. Thirty seconds stays closed.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python -m scripts.ofi_horserace \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T073935.092996Z-6ca41203/tape_sha-20260819T073935.092996Z-6ca41203.jsonl \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T075057.972093Z-286d5105/tape_sha-20260819T075057.972093Z-286d5105.jsonl \
  --output artifacts/ofi-horserace/ofi_horserace_2026-08-19.json \
  --cells-output artifacts/ofi-horserace/ofi_horserace_cells_2026-08-19.jsonl \
  --past-output artifacts/ofi-horserace/ofi_horserace_past_2026-08-19.jsonl \
  --ranking-output artifacts/ofi-horserace/ofi_horserace_ranking_2026-08-19.csv \
  --replicates 400 --seed 20260819
```

Large outputs remain gitignored. Their hashes and compact results are committed in
`docs/results/OFI-HORSERACE-SUMMARY-2026-08-19.json`.
