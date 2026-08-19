# H-SIG21 — deep-book anomaly to later NIFTY-futures price response

**Status:** PRE-REGISTRATION ONLY. Written under `D31` before any SIG-21 response code was built
or any future-price outcome was inspected. The first pushed commit containing this file is the
registration clock required by `D29` and `SIG-19`.

**Question:** Does a rare disturbance in the normally quiet far depth200 ladder contain
incremental information about a later NIFTY-futures mid-price response after the contemporaneous
reaction and the information already present in the near book are separated out?

This is a predictive-association design with causally timed feature construction. It does not
identify a structural causal effect of anonymous displayed orders.

## 1. Hard sequencing and contamination boundary

1. The price-keyed construction detector and synthetic fixtures are built first. Its public
   schema contains no price response, return, label or future-alignment field.
2. The two retained `DAT-20` tapes may be used only for parser/event-construction verification and
   event counts. Their post-event price paths are permanently excluded from SIG-21 inference.
3. This file and the construction detector must be committed, pushed and the remote hash verified
   before response, matching, power or inference code is built.
4. A numeric power artifact is then computed without joining anomaly rows to their outcomes. If
   the sample is underpowered, outcome execution is deferred rather than returning a null.
5. Only tape collected after the registering commit may enter the first outcome sample.

Any accidental response inspection before gates 3 and 4 makes the affected tape exploratory and
permanently ineligible for Confirmed/Falsified status.

## 2. Registered objects (`D29`)

- **Instrument/pooling:** NIFTY front-month future, instrument identity only. Contract rolls are
  separate strata; no cross-contract pooling is permitted in the first test.
- **X:** one price-keyed far-book atomic event produced by a depth200 publication, or one clustered
  episode of such publications. `CON-06`: deterministic from observed displayed price, quantity
  and order-count states; relocation is explicitly a proxy.
- **h1:** the interval between the immediately prior valid depth200 publication and the current
  publication. Events sharing one exact receive timestamp are one burst.
- **f1:** depth200 publication/event time on local `receive_ts`; no interpolation and no assumed
  exchange timestamp.
- **Y:** depth20 best-bid/best-ask midpoint return in futures ticks.
- **h2:** `{1 s, 5 s, 10 s}`.
- **f2:** depth20 publication time, using the last observation at or before each registered
  endpoint; no forward interpolation.
- **Z:** `{0.5 s, 1.0 s}` from the end of X to the start of Y. These respect the measured depth200
  publication floor but remain descriptive until the full reaction path `R`, including Kotak
  acknowledgement, is measured. A cell is decision-relevant only if `Z >= R`.
- **Strata:** side; price-distance band; 30-minute time-of-day bucket; pre-event spread/top-20
  liquidity bin; `VOL-04` HMM regime; contract identity/session.

The contemporaneous path from the pre-event midpoint through `t + Z` is reported descriptively
and never enters a predictive verdict or economic gate.

## 3. Price-keyed construction and the far region

Each side is represented as `{price -> (displayed quantity, displayed order count)}`. Level index
is metadata only. This makes a one-price insertion/removal one change instead of a fabricated
cascade through every deeper index.

The primary far region is **strictly more than Rs 20 from the same-side best quote in the
pre-event state**. This boundary uses only `DAT-20`'s pre-outcome activity measurement: 86.6–99.0%
of ordinary events occurred inside Rs 20. Registered distance strata are `(20, 50]` and `(50,
infinity)` rupees. The value is never recomputed from future prices or the post-event best quote.

Transitions spanning a reconnect/connection epoch, sequence/connection gap, partial/crossed book,
or invalid depth are excluded and counted by reason. A near-complete window shift that merely
drops the old outer boundary and admits a new outer boundary is flagged as boundary churn and does
not create an anomaly. Identical repeated states create no event.

## 4. Atomic event families

The complete registered atomic set is:

1. `addition` — price absent then present; magnitude = new displayed quantity.
2. `removal` — price present then absent; magnitude = prior displayed quantity.
3. `quantity_increase` / `quantity_decrease` — same price remains occupied; magnitude = absolute
   quantity change.
4. `order_count_increase` / `order_count_decrease` — same price remains occupied; magnitude =
   absolute order-count change.
5. `relocation_toward_touch_proxy` / `relocation_away_from_touch_proxy` — a same-side removal and
   addition in one burst whose displayed quantities differ by no more than 25%, greedily paired by
   smallest relative difference; magnitude is the smaller of the removed and added quantities.
   This is a displayed-liquidity relocation proxy, never an individual-order identity claim.

When a removal/addition pair is classified as relocation, it is not also tested as an independent
removal and addition. Quantity and order-count changes at the same retained price remain separate
atomic families and their dependence is handled in the declared family/inference.

## 5. Past-only unusualness baseline

An event is unusual relative to an expanding empirical distribution containing **completed prior
sessions only**. The current session is buffered and cannot update its own threshold. The exact
baseline key is atomic type x side x distance band x 30-minute time bucket x past-only liquidity
bin x `VOL-04` regime. A key needs at least 200 historical candidate events; otherwise it is
`baseline_insufficient` and cannot enter inference.

Registered upper-tail thresholds are `{99.5%, 99.9%}`. Both are in the testing family whether or
not one produces a more attractive result. There is no fallback pooling across missing strata.

## 6. Event clustering and controls

- All changes in one receive-timestamp burst form one cluster.
- Bursts whose predictive windows overlap are grouped into an episode. The primary risk set keeps
  non-overlapping episodes using the largest registered endpoint (`Z + h2 = 11 s`). All-event
  estimates may be reported only with dependence-robust inference and cannot replace the primary.
- Each episode is matched to quiet risk-set instants from the same instrument, session,
  30-minute bucket and HMM regime, with no anomaly in the surrounding 11 seconds. Matching uses
  pre-event midpoint, spread, top-20 depth/OFI, recent return and realised volatility only.
- Controls are selected without access to any future response. Match failures are explicit.

The primary estimand is the event-minus-matched-control difference in the future depth20 midpoint
return distribution. Raw event responses are reported alongside it.

## 7. Registered family, outputs and inference

The primary two-sided discovery family contains:

`8 atomic types x 2 sides x 2 distance bands x 2 thresholds x 2 Z gaps x 3 h2 horizons = 384 cells`.

No cell may be added after outcomes are inspected. The 384-cell count is recorded in every
`SIG-19` trial row. Romano-Wolf step-down adjustment is primary. HAC/Newey-West lag is at least the
largest overlap; stationary block bootstrap is clustered within session; non-overlapping episode
resampling is reported alongside it. Every estimate carries raw `N`, effective `N_eff`, confidence
interval, adjusted p-value and the numeric ex-ante MDE.

For every cell report: mean/median and quantiles in ticks, probability of a move of at least one
tick in each direction, sign, peak event-time response, and reversion through 10 seconds. Report
the complete family, not only significant cells.

Negative controls fixed now: future-event leads predicting past returns, within-session/time-bin
timestamp shuffles, side-label permutation, near-boundary churn, and matched quiet episodes.

## 8. Sample and power gate

- Five full sessions after registration are baseline/calibration-only. They may establish event
  counts, strata support and unconditional response variance for power, but never a SIG-21 result.
- The first evaluation sample requires at least **20 subsequent full sessions**.
- Every HMM regime used in a stability verdict must occur in at least five evaluation sessions and
  supply at least 100 effective event episodes. Otherwise that regime verdict is Inconclusive.
- Before any outcome join, write and push a numeric power artifact giving `N`, projected `N_eff`,
  `G = 384`, post-multiplicity critical values and MDE for every supported cell.
- Adequate power requires an MDE no larger than **0.25 futures tick for the mean response** and no
  larger than **5 percentage points for the probability of a >=1-tick move**. Cells failing either
  relevant gate are Deferred and are not outcome-tested.

## 9. Verdict and promotion boundary

The first evaluation is intentionally two-sided. It can establish that a registered deep-book
event family is incrementally informative, not confirm a newly observed directional sign.

- **Informative, descriptive:** survives the full family but `Z < R`.
- **Informative, admissible candidate:** survives the full family and `Z >= R`; still not a trading
  rule or evidence of profitability.
- **Falsified at the registered economic scale:** adequately powered confidence region excludes
  effects of the registered MDE in both directions.
- **Inconclusive:** underpowered, match/support failure, or regime/sign instability.

Any direction/horizon chosen from this first sample must be assigned a new `H-SIG21C-*` ID,
committed before new tape is collected, and confirmed one-sided on that later tape before it may
enter the joint option-quoting configuration. `SIG-17`'s maker economics remain a separate gate.

## 10. Required artifacts

- outcome-blind price-keyed candidate/anomaly rows with exclusion counts;
- construction, boundary-slide, reconnect and past-only leakage fixtures;
- pushed registration commit hash and code commit hash;
- numeric pre-outcome power artifact;
- immutable `SIG-19` trial rows for all executed cells;
- full dependence-aware response report and machine-readable family output;
- `CON-09` finding retaining observed/derived/estimated/proxy labels and all limitations.
