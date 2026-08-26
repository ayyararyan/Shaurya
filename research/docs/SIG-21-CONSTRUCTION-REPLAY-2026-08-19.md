# SIG-21 construction replay — the basic depth200 support grid (2026-08-19)

**Protocol:** `H-SIG21` · **Sample role:** `construction_replay_only` · **Outcome join:** denied.

**Object category (working contract §7.1):** every count, share, magnitude and rate below is
**deterministically derived** from observed displayed book states. The relocation families are
**proxies**, as registered. The final section is explicitly **scenario-based**. Nothing here is
estimated, and nothing here is predictive.

**What this is not.** `H-SIG21` §1.2 permanently excludes the post-event price paths of the two
retained `DAT-20` tapes from SIG-21 inference. This replay therefore computes no price response,
return, midpoint, markout, label or outcome of any kind, and joins no candidate to any later
price state. There is no result about whether deep-book anomalies forecast anything, because no
such quantity was computed and none is authorised.

---

## 1. Plain English first

We replayed the already-registered SIG-21 construction detector across 21.8 minutes of recorded
200-level NIFTY-futures order book and counted what it actually produces. Six things matter.

**First, the grid is not empty — it is full.** All 32 construction cells are populated. Every one
of the 384 registered family cells therefore has some construction support behind it. Nothing in
the registered design is structurally unreachable.

**Second, "rare disturbance in the normally quiet far ladder" is not what the data looks like.**
The detector fires **40,724 times in 21.8 minutes** — about **1,872 candidates per minute**, in
**5,325 distinct timestamp bursts**, roughly **245 bursts per minute** with a median of 7
candidates per burst. The far book beyond ₹20 is not quiet at all at the raw construction level.
The word "rare" in the hypothesis has to be carried entirely by the past-only threshold layer
(§5 of the registration), which selects the extreme upper tail of magnitudes. Construction alone
does not make these events rare, and the registered 99.5%/99.9% thresholds are doing far more
work than the ₹20 far boundary is.

**Third — and this is the most consequential finding — the primary risk set collapses.** The
registered primary estimate uses **non-overlapping episodes** built from an 11-second window
(`Z + h2` max). Over both tapes there is **not one gap of 11 seconds or more between candidate
bursts** — the largest gap anywhere is **0.81 seconds**. Every burst's window therefore overlaps
its neighbour's, the whole tape connects into a single chain, and 40,724 candidates reduce to
**2 non-overlapping episodes — one per tape.** Scaled naively that is catastrophic for power:
continuous activity gives roughly one episode per continuous session, so `N_eff` would count
sessions, not events. The mechanical ceiling is `floor(session seconds / 11)` = **2,045 episodes
per full session** no matter how many candidates there are. Anything approaching useful `N_eff`
requires the anomaly-retention rate to be low enough that surviving bursts are genuinely
separated in time; a threshold that keeps even 5% of bursts still saturates the ceiling. This is
a real, load-bearing design constraint that surfaces before any outcome is ever inspected.

**Fourth, the two sides are not symmetric and the ask side inside ₹20–50 is where the grid is
thin.** Bid-side candidates outnumber ask-side 25,548 to 15,176 overall, but the imbalance is
concentrated: the six `ask | 20_50` cells hold **15 to 47 candidates each** against 664 to 1,556
for their bid counterparts — a factor of roughly 30. Ten of the 32 cells have fewer than 50
candidates in 21.8 minutes. Those are the cells that will be first to fail a support gate.

**Fifth, and this changes how the biggest cells should be read: much of the grid's mass sits on
the 200-level window's own moving rim.** For each candidate we measured how far its price is from
the outermost occupied price on its own side. **41.4% of all candidates lie within ₹1 of that rim,
and 64.2% within ₹5.** It is concentrated in exactly the largest cells: **76.9% of ask removals
and 72.5% of ask additions are within ₹1 of the rim** (97.1% and 94.6% within ₹5), against roughly
half on the bid. The four `addition`/`removal · gt_50` cells hold 21,808 candidates — 53.6% of the
grid — and on the ask side they are very largely the ladder's outer edge shifting, not a
disturbance inside a stable far book. The registered §3 boundary-churn rule is working as written;
it simply only suppresses a *near-complete* slide (≥95% price overlap, at most two prices entering
or leaving), and a busier rim shift passes through as ordinary additions and removals. By
contrast the quantity-change and order-count-change families are genuinely interior — only 5–6%
of them lie within ₹1 of the rim, with a median around ₹30 inside it on the bid. Nothing was
reclassified and the registration is untouched; this is reported so the grid is not read as if all
40,724 candidates were interior far-book events.

**Sixth, the registered ₹50 band split is not where the mass is.** Observed far distances run
from ₹20 to a maximum of **₹87.7** — the depth200 ladder simply does not extend further on this
instrument at this time — so the registered `(50, ∞)` band is in practice `(50, 88]`. Within
that, **64% of all candidates sit in ₹50–75** and only 13% in ₹20–25. The split at ₹50 puts 75%
of the mass on one side of it. It is a legitimate registered choice and it is not being changed,
but Aryan should know the band boundary sits below the bulk of the distribution rather than
through the middle of it.

**Seventh, the baseline layer is exactly as far away as the registration implies, and no closer.**
`H-SIG21` §5 needs at least 200 historical candidates per key from **completed prior sessions**.
There are no completed prior sessions before these tapes, so **every registered key is
`baseline_insufficient`, without exception**, and no candidate was scored, no percentile was
computed and no threshold was estimated. What we can report is an upper bound: on the four key
axes that are determinable here (type × side × band × 30-minute bucket), 64 partial keys are
populated and 26 of them already exceed 200 candidates within 21.8 minutes. The two remaining
axes — the past-only liquidity bin and the `VOL-04` regime — cannot be formed from this tape at
all, and adding them can only split those keys further, so 26 is a ceiling, not a count.

**What Aryan should take from this.** The construction machinery works and produces a complete,
well-populated grid; that part of SIG-21 is now evidenced rather than assumed. Three design
pressures are now visible before any outcome exists: the 11-second non-overlapping episode rule
is the binding constraint on statistical power, not the candidate count; over half the grid's
mass sits on the moving rim of the 200-level window rather than inside a stable far ladder; and
the thin `ask | 20_50` cells are the ones most likely to be Deferred for support. All three are
facts about construction, so all three can be acted on without touching the outcome gate.

**Action needed from Aryan:** none. Nothing here changes the registered design, and nothing here
requires a decision before the five calibration sessions run.

---

## 2. Source and integrity

Both tapes were verified to be the **NIFTY front-month future** from their own capture metrics
before any replay work was done, and each tape's SHA-256 was recomputed and checked against the
SHA-256 the collector recorded in its manifest at capture time.

| Field | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `sha-20260819T073935.092996Z-6ca41203` | `sha-20260819T075057.972093Z-286d5105` |
| `instrument_id` | `NSE:NSE_FNO:NIFTY:future:2026-08-25` | `NSE:NSE_FNO:NIFTY:future:2026-08-25` |
| Dhan security ID | `58072` | `58072` |
| Trading symbol | `NIFTY-Aug2026-FUT` | `NIFTY-Aug2026-FUT` |
| Tape SHA-256 | `751ee15ad5681bd356db06983c86c4aa6fabbcd26ccab356b7e80d77955b71e0` | `c20590d66631ac3b63748ccbdf172f2e5e2fe81b61b618f3e5df542108c82b82` |
| Manifest SHA-256 agrees | yes | yes |

The replay refuses to run on any instrument whose registered kind is not `future`, and refuses
any tape whose bytes no longer match its manifest.

**Reproduce:**

```bash
.venv/bin/python scripts/sig21_construction_replay.py \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T073935.092996Z-6ca41203/tape_sha-20260819T073935.092996Z-6ca41203.jsonl \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T075057.972093Z-286d5105/tape_sha-20260819T075057.972093Z-286d5105.jsonl \
  --output artifacts/sig21-construction-replay/sig21_construction_grid_2026-08-19.json \
  --grid-rows-output artifacts/sig21-construction-replay/sig21_construction_grid_rows_2026-08-19.jsonl
```

---

## 3. How the 384-cell family decomposes

`H-SIG21` §7 registers `8 atomic types × 2 sides × 2 distance bands × 2 thresholds × 2 Z gaps ×
3 h2 horizons = 384` cells. Only the first three axes are decided by construction. The remaining
three **multiply the same construction support** rather than adding independent support: one
construction cell with `n` candidates supplies all 12 of its family cells with the same `n`.

| Axis | Levels | Measurable in this replay? | Why |
|---|---:|---|---|
| atomic type | 8 | Yes | determined by the price-keyed transition |
| side | 2 | Yes | determined by the ladder |
| distance band | 2 | Yes | determined by the pre-event same-side best quote |
| threshold | 2 | **No** | needs the §5 past-only baseline over completed prior sessions; none exist |
| `Z` gap | 2 | **No** | defines the start of an outcome window |
| `h2` horizon | 3 | **No** | defines the outcome horizon itself |

**Result:** 32 construction cells, all 32 populated, 0 empty. `32 × 12 = 384` family cells all
have non-zero construction support. This does **not** mean 384 cells are testable — it means none
of them is ruled out by construction. Testability depends on the threshold layer and the episode
risk set, neither of which is measurable outcome-blind.

---

## 4. The basic grid — 32 construction cells

Magnitude is a **displayed quantity** for the addition, removal, quantity and relocation families
and a **displayed order count** for the order-count families. It is never a return. Rate is over
1,305.4 seconds (21.76 minutes) of observed depth200 time.

| Cell (type · side · band) | n | Share | Bursts | /min | Mag median | p90 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `removal · ask · gt_50` | 5,914 | 14.52% | 2,276 | 271.8 | 130 | 1,040 | 2,535 | 3,120 |
| `addition · ask · gt_50` | 5,866 | 14.40% | 2,193 | 269.6 | 130 | 1,040 | 2,405 | 3,120 |
| `addition · bid · gt_50` | 5,109 | 12.55% | 2,153 | 234.8 | 195 | 1,755 | 8,320 | 8,450 |
| `removal · bid · gt_50` | 4,919 | 12.08% | 2,208 | 226.1 | 195 | 1,755 | 8,320 | 8,450 |
| `relocation_toward_touch_proxy · bid · gt_50` | 2,200 | 5.40% | 1,771 | 101.1 | 65 | 130 | 650 | 1,300 |
| `quantity_decrease · bid · 20_50` | 1,556 | 3.82% | 1,329 | 71.5 | 650 | 650 | 1,300 | 2,405 |
| `quantity_increase · bid · 20_50` | 1,550 | 3.81% | 1,333 | 71.2 | 650 | 650 | 1,300 | 2,535 |
| `order_count_increase · bid · 20_50` | 1,550 | 3.81% | 1,333 | 71.2 | 1 | 1 | 3 | 8 |
| `order_count_decrease · bid · 20_50` | 1,541 | 3.78% | 1,317 | 70.8 | 1 | 1 | 3 | 6 |
| `removal · bid · 20_50` | 1,238 | 3.04% | 1,092 | 56.9 | 325 | 650 | 1,300 | 2,535 |
| `addition · bid · 20_50` | 1,082 | 2.66% | 944 | 49.7 | 650 | 650 | 1,300 | 1,690 |
| `quantity_decrease · ask · gt_50` | 800 | 1.96% | 751 | 36.8 | 195 | 390 | 780 | 910 |
| `order_count_decrease · ask · gt_50` | 800 | 1.96% | 751 | 36.8 | 3 | 6 | 12 | 14 |
| `quantity_increase · ask · gt_50` | 729 | 1.79% | 727 | 33.5 | 195 | 520 | 910 | 1,235 |
| `order_count_increase · ask · gt_50` | 729 | 1.79% | 727 | 33.5 | 3 | 8 | 14 | 19 |
| `relocation_away_from_touch_proxy · bid · 20_50` | 716 | 1.76% | 596 | 32.9 | 130 | 650 | 650 | 1,495 |
| `quantity_decrease · bid · gt_50` | 693 | 1.70% | 662 | 31.9 | 65 | 65 | 130 | 455 |
| `order_count_decrease · bid · gt_50` | 693 | 1.70% | 662 | 31.9 | 1 | 1 | 1 | 7 |
| `quantity_increase · bid · gt_50` | 689 | 1.69% | 658 | 31.7 | 65 | 65 | 65 | 650 |
| `order_count_increase · bid · gt_50` | 689 | 1.69% | 658 | 31.7 | 1 | 1 | 1 | 4 |
| `relocation_toward_touch_proxy · bid · 20_50` | 664 | 1.63% | 574 | 30.5 | 650 | 650 | 1,300 | 1,300 |
| `relocation_away_from_touch_proxy · bid · gt_50` | 659 | 1.62% | 619 | 30.3 | 65 | 65 | 65 | 1,755 |
| `removal · ask · 20_50` | 47 | 0.12% | 46 | 2.2 | 65 | 650 | 1,001 | 1,300 |
| `relocation_away_from_touch_proxy · ask · gt_50` | 41 | 0.10% | 40 | 1.9 | 130 | 585 | 585 | 585 |
| `relocation_toward_touch_proxy · ask · gt_50` | 40 | 0.10% | 39 | 1.8 | 130 | 397 | 1,755 | 1,755 |
| `addition · ask · 20_50` | 39 | 0.10% | 32 | 1.8 | 65 | 650 | 1,755 | 1,755 |
| `quantity_decrease · ask · 20_50` | 35 | 0.09% | 33 | 1.6 | 65 | 650 | 1,755 | 1,755 |
| `order_count_decrease · ask · 20_50` | 34 | 0.08% | 32 | 1.6 | 1 | 1 | 1 | 1 |
| `quantity_increase · ask · 20_50` | 33 | 0.08% | 32 | 1.5 | 65 | 650 | 1,401 | 1,755 |
| `order_count_increase · ask · 20_50` | 31 | 0.08% | 30 | 1.4 | 1 | 1 | 2 | 2 |
| `relocation_away_from_touch_proxy · ask · 20_50` | 23 | 0.06% | 21 | 1.1 | 65 | 1,534 | 1,755 | 1,755 |
| `relocation_toward_touch_proxy · ask · 20_50` | 15 | 0.04% | 15 | 0.7 | 650 | 1,755 | 1,755 | 1,755 |

The machine-readable grid in `artifacts/` carries `count`, `mean`, `median`, `p90`, `p99` and
`max` for every cell, including the mean omitted here for width, and emits all 32 rows whether
populated or not.

**Reading the grid.** Additions and removals dominate (59.5% of all candidates), and they are
near-mirror-images of each other in every cell — consistent with displayed liquidity being
posted and pulled at the same prices rather than with one-sided pressure. Quantity-change and
order-count-change counts are also near-identical within each cell, which is expected: a change
in displayed quantity at a retained price usually comes with a change in the order count at that
price. The registration already anticipates this and keeps them as separate atomic families with
their dependence handled in the declared inference family; the replay confirms the dependence is
strong and should not be ignored.

### Thin cells

Ten cells hold fewer than 50 candidates in 21.8 minutes, and eight of them are the `ask · 20_50`
family plus the two `ask` relocation-`gt_50` cells. If far-book activity is stable, these will
still accumulate a few thousand candidates over a full session — but they are the cells where a
support or power gate is most likely to bite, and they are the ones to watch in calibration.

---

## 5. Time of day

Both tapes sit inside a single mid-morning stretch: 13:09:35 to 13:31:50 IST. Only two 30-minute
buckets are touched, and the second is clipped to under two minutes, so raw counts must be read
against exposure.

| IST bucket | Observed s | Candidates | /s | bid | ask |
|---|---:|---:|---:|---:|---:|
| 13:00 | 1,187.7 | 37,481 | 31.6 | 23,731 | 13,750 |
| 13:30 | 117.6 | 3,243 | 27.6 | 1,817 | 1,426 |

The two buckets have similar per-second rates, so nothing intraday can be inferred from this —
by design, since a single mid-morning window carries no information about the open, the close,
or the lunch lull. The full type × bucket table is in the artifact.

---

## 6. Distance beyond the ₹20 far boundary

| | |
|---|---|
| Registered far boundary | ₹20 from the same-side best quote (pre-event) |
| Registered split | ₹50 |
| Observed distance range | ₹20 to **₹87.7** |
| Median / mean distance | ₹58.5 / ₹55.5 |

| Registered band | n | Share |
|---|---:|---:|
| `(20, 50]` | 10,154 | 24.93% |
| `(50, ∞)` | 30,570 | 75.07% |

| Finer bin | n | Share |
|---|---:|---:|
| (20, 25] | 5,433 | 13.34% |
| (25, 30] | 2,566 | 6.30% |
| (30, 40] | 605 | 1.49% |
| (40, 50] | 1,550 | 3.81% |
| **(50, 75]** | **26,095** | **64.08%** |
| (75, 100] | 4,475 | 10.99% |
| (100, 150] and beyond | 0 | 0.00% |

Two things follow. The upper band is bounded in practice by the ladder's own span — depth200
reached at most ₹87.7 from the touch on this instrument during these tapes, so `(50, ∞)` is
really `(50, 88]` and the registered band is not open-ended in the way its label suggests. And
the distribution is bimodal rather than decaying: a cluster just past the ₹20 boundary, a trough
across ₹30–50, then the bulk at ₹50–75. The registered split at ₹50 lands in the trough, which
is a defensible place for a boundary, but it means the two bands are very unequal in size.

---

## 7. Burst and episode structure — the binding constraint

| Quantity | Value |
|---|---:|
| Distinct timestamp bursts | 5,325 |
| Bursts per minute | 244.8 |
| Candidates per burst — median / p90 / p99 / max | 7 / 14 / 25 / 42 |
| Inter-burst gap — median / p90 / p99 / **max** | 0.201 s / 0.400 s / 0.599 s / **0.807 s** |
| Inter-burst gaps ≥ 11 s | **0** |
| Registered episode window (`Z + h2` max) | 11 s |
| Episodes | 2 |
| **Non-overlapping episodes (primary risk set)** | **2** |
| Capacity ceiling `floor(observed s / 11)` | 118 |

The whole of each tape is one episode. That is not a defect in the clustering code — it is the
registered rule meeting a book that changes several times a second. The consequence is precise:

- The non-overlapping episode count of an unthresholded construction set measures **how many
  contiguous stretches of tape exist**, not how much support the study has.
- The primary risk set can never exceed `floor(T / 11)` — **2,045 per 22,500-second session**.
- For the risk set to approach that ceiling, the surviving anomaly bursts must be spaced by at
  least 11 seconds. At the observed 245 bursts per minute, a threshold retaining 5% still leaves
  ~11 surviving bursts per minute, which saturates the ceiling and produces heavy overlap
  exclusion rather than more episodes.

`H-SIG21` §6 already permits all-event estimates alongside the primary with dependence-robust
inference; this replay makes clear that the all-event arm is not a nicety here but the arm that
will carry most of the information, and that the primary arm's `N_eff` will be governed by the
11-second geometry rather than by candidate abundance.

---

## 8. Where the mass sits relative to the 200-level window's rim

For every candidate we measured the rupee distance between its price and the **outermost occupied
price on its own side** — a removal against the ladder it left, an addition or relocation
destination against the ladder it joined, a change at a retained price against whichever rim is
nearer. This uses only same-side displayed prices, so it is fully outcome-blind. No candidate was
reclassified and the registered detector is unchanged.

| Overall | Share |
|---|---:|
| Within ₹1 of the rim | **41.4%** |
| Within ₹5 of the rim | **64.2%** |

| Atomic type | Side | n | ≤ ₹1 | ≤ ₹5 | Median | p90 |
|---|---|---:|---:|---:|---:|---:|
| `addition` | bid | 6,191 | 48.7% | 75.4% | ₹1.2 | ₹32.2 |
| `addition` | ask | 5,905 | **72.5%** | **94.6%** | ₹0.4 | ₹3.3 |
| `removal` | bid | 6,157 | 51.6% | 75.7% | ₹1.0 | ₹31.9 |
| `removal` | ask | 5,961 | **76.9%** | **97.1%** | ₹0.3 | ₹2.1 |
| `quantity_increase` | bid | 2,239 | 5.3% | 20.8% | ₹30.6 | ₹36.9 |
| `quantity_increase` | ask | 762 | 5.8% | 43.3% | ₹5.6 | ₹11.7 |
| `quantity_decrease` | bid | 2,249 | 6.0% | 20.2% | ₹30.3 | ₹36.4 |
| `quantity_decrease` | ask | 835 | 5.0% | 40.8% | ₹6.0 | ₹11.8 |
| `order_count_increase` | bid | 2,239 | 5.3% | 20.8% | ₹30.6 | ₹36.9 |
| `order_count_increase` | ask | 760 | 5.8% | 43.4% | ₹5.6 | ₹11.6 |
| `order_count_decrease` | bid | 2,234 | 6.1% | 20.4% | ₹30.3 | ₹36.4 |
| `order_count_decrease` | ask | 834 | 5.0% | 40.9% | ₹6.0 | ₹11.7 |
| `relocation_toward_touch_proxy` | bid | 2,864 | 7.0% | 36.2% | ₹7.4 | ₹36.5 |
| `relocation_toward_touch_proxy` | ask | 55 | 7.3% | 23.6% | ₹12.4 | ₹55.3 |
| `relocation_away_from_touch_proxy` | bid | 1,375 | 64.5% | 83.5% | ₹0.3 | ₹30.2 |
| `relocation_away_from_touch_proxy` | ask | 64 | 48.4% | 84.4% | ₹1.3 | ₹7.4 |

(Counts here are per atomic type and side, so they aggregate the two distance bands and are
larger than any single grid cell.)

**Reading it.** The addition and removal families — 53.6% of the whole grid across their four
`gt_50` cells — are substantially the 200-level window's rim moving in and out as the book
shifts, overwhelmingly so on the ask. The `relocation_away_from_touch_proxy` family shares this
character on the bid (64.5% within ₹1), which is what one would expect if the "relocation" it is
pairing is often a rim price leaving and a new rim price arriving. By contrast the quantity and
order-count families are genuinely interior: only about one in twenty lies within ₹1 of the rim,
and the bid-side median sits ₹30 inside it.

**What this does and does not mean.** It does not invalidate anything: `H-SIG21` §3 registered the
boundary-churn rule and it is applied exactly as written, and a price entering or leaving at the
edge of a truncated 200-level view is still a real displayed-book change. What it means is that
the four largest cells are measuring a different physical thing from the quantity/order-count
cells — window geometry as much as far-book behaviour — and that any later reading of those cells
should say so. It also suggests a concrete, cheap robustness check for the calibration phase, in
the same spirit as the negative controls already fixed in §7 of the registration: report the
`gt_50` addition/removal cells split by rim proximity. That is a reporting split, not a new
family cell, so it does not touch the registered 384.

**Action needed from Aryan:** none now. This is flagged for the calibration read-out, not for a
decision today.

---

## 9. Exclusions and transition validity

| Quantity | Value |
|---|---:|
| depth200 publications (distinct receive timestamps) | 5,482 |
| Consecutive transitions attempted | 5,480 |
| **Valid transitions** | **5,470 (99.82%)** |
| Rejected transitions | 10 |

| Reason | Count | Effect |
|---|---:|---|
| `invalid_quality:crossed_book` | 8 | whole transition rejected |
| `invalid_quality:partial_book` | 2 | whole transition rejected |
| `whole_ladder_boundary_churn` | 24 | prices excluded, transition retained |

No transition was rejected for a connection-epoch boundary, a non-monotone receive time, an
incomplete two-sided book, or a missing pre-event best quote: both runs held a single connection
epoch throughout with no reconnects. The 24 boundary-churn exclusions are the registered guard
against a window slide fabricating an addition and a removal at the ladder's outer edge, and
they correctly leave the rest of the transition intact.

---

## 10. Coverage

| | Run 1 | Run 2 | Combined |
|---|---:|---:|---:|
| depth200 publications | 2,718 | 2,764 | 5,482 |
| Observed depth200 seconds | 652.73 | 652.64 | 1,305.37 |
| Publications per second | 4.16 | 4.24 | 4.20 |
| Publication gap — median / p90 / max (ms) | 200.4 / 399.8 / 603.3 | 200.4 / 399.7 / 603.3 | — |
| Gaps > 300 ms (DAT-20 registered threshold) | 544 | 498 | 1,042 |
| depth20 rows (counted for coverage only) | 5,534 | 5,466 | 11,000 |

The publication cadence is tightly clustered at ~200 ms with a hard ceiling near 600 ms, which
matches the DAT-20 finding that depth200 skips publications when the far book is unchanged
rather than losing them. **Depth20 rows are counted, and nothing else** — no depth20 price,
quantity, ladder or midpoint is read anywhere in this replay, which is what makes the coverage
figure safe to report under §1.2.

---

## 11. The baseline layer — what is actually needed before thresholds exist

`H-SIG21` §5 requires an expanding empirical baseline from **completed prior sessions only**, keyed
on `atomic type × side × distance band × 30-minute bucket × past-only liquidity bin × VOL-04
regime`, with at least **200** historical candidates per key.

**Status: every key is `baseline_insufficient`. Zero candidates were scored. No percentile was
computed. No threshold was estimated.** There are no completed prior sessions before these tapes,
and deriving any threshold from within this sample is exactly what §5 forbids.

Two of the six key axes cannot be formed here at all:

- **past-only liquidity bin** — its bin edges are defined on completed prior sessions, and none
  exist;
- **`VOL-04` regime** — no HMM regime label is fitted for this instrument-session, and fitting one
  on an 11-minute window would again be within-sample.

On the four axes that *are* determinable, **64 partial keys are populated**, of which **26 already
hold at least 200 candidates** in 21.8 minutes. Because adding the two missing axes can only
partition these keys further, **26 is a strict upper bound** on how many full six-axis keys could
be estimable from an equivalent amount of tape — the true number is lower and cannot be
determined until a liquidity binning and a regime labelling exist.

The 38 partial keys below 200 range from **4 to 129** candidates, and the smallest are — again —
the `ask · 20_50` cells. Two consequences for planning:

1. **Volume is not the constraint for the busy keys.** At the observed rate, a single full session
   would put the 26 already-sufficient partial keys orders of magnitude past 200. The registered
   five calibration sessions are ample for those.
2. **The constraint is the two missing axes.** Once the liquidity bin and the `VOL-04` regime split
   each key further — say three liquidity bins and three regimes, which is a modest assumption —
   a key holding 200 candidates in one 30-minute bucket becomes nine keys holding a fraction each,
   and regimes are not evenly distributed across a session. The thin `ask · 20_50` cells will not
   survive that partition on five sessions. Expect `baseline_insufficient` to remain the status of
   a substantial minority of the 384 cells even after calibration, and expect that to be
   concentrated on the ask side inside ₹20–50.

Neither point can be sharpened outcome-blind, because the liquidity bin definition is itself a
calibration output.

---

## 12. Scenario extrapolation — explicitly **not** a measurement

**Object category: scenario-based.** These figures assume the candidate and burst arrival rates
observed in this window hold for a whole session. That is an assumption, not an estimate.

**Why the basis is biased.** The window is ~21.8 minutes of a single mid-morning stretch on one
contract. It excludes the open and the close, touches one 30-minute bucket properly and a second
only partially, contains one volatility regime, and cannot represent intraday seasonality in
far-book activity. Treat everything below as an order-of-magnitude planning figure.

| Scenario | Sessions | Candidates | Bursts | Non-overlapping episodes (ceiling) |
|---|---:|---:|---:|---:|
| One full session (22,500 s) | 1 | ~701,900 | ~91,800 | ≤ 2,045 |
| Registered calibration sample | 5 | ~3.51 M | ~458,900 | ≤ 10,225 |
| Registered evaluation sample | 20 | ~14.04 M | ~1.84 M | ≤ 40,900 |

Linearly scaling the *observed* episode count (2) is degenerate and is reported in the artifact
only with that label attached: continuous activity collapses each contiguous stretch to one
episode, so the observed count measures how many tapes there are.

The useful planning object is the retention bound. If a fraction `r` of bursts survives the
registered past-only threshold layer, the number of non-overlapping episodes is at most
`min(retained bursts, floor(session seconds / 11))`:

| Retained fraction of bursts | Retained bursts / session | Episode upper bound / session | Over 20 sessions |
|---:|---:|---:|---:|
| 100% | 91,784 | 2,045 | 40,900 |
| 10% | 9,178 | 2,045 | 40,900 |
| 5% | 4,589 | 2,045 | 40,900 |
| 1% | 918 | 918 | 18,357 |
| **0.5%** (99.5% threshold scale) | 459 | 459 | 9,178 |
| **0.1%** (99.9% threshold scale) | 92 | 92 | 1,836 |

No magnitude was ranked and no threshold was estimated to produce this table; each row is
arithmetic on the observed burst rate under a stated retention assumption.

Read against the registered power gate — MDE ≤ 0.25 futures tick on the mean response and ≤ 5
percentage points on the probability of a ≥1-tick move, across `G = 384` cells with Romano-Wolf
adjustment — the 99.9% row is the one to worry about. Roughly 1,800 non-overlapping episodes
across the whole 20-session evaluation sample, spread over 384 cells and then split by strata,
is thin. That is a statement about arithmetic and the registered design, not about any effect;
the actual MDE cannot be computed until the calibration sessions supply the unconditional
response variance, which is precisely what §8 requires before any outcome join.

---

## 13. What remains unmeasurable outcome-blind

Stated explicitly so it is not mistaken for an omission:

- **Any response, return, midpoint move, markout or sign.** Excluded by §1.2 for these tapes,
  permanently, and by §1.4 for everything until the power artifact is pushed.
- **The threshold axis of the family.** Needs completed prior sessions.
- **The `Z` and `h2` axes.** They are definitions of an outcome window.
- **`N_eff`, critical values and MDE.** They need the unconditional response variance, which is a
  calibration output under §8.
- **Matched quiet controls.** Matching itself is outcome-blind, but a match is only meaningful
  against a response, and building the control set now would consume the tape for no gain.
- **Whether the far book is "unusually" disturbed at any moment.** Unusualness is defined
  relative to the past-only baseline, which does not yet exist.

---

## 14. Artifacts

| Artifact | Contents |
|---|---|
| `artifacts/sig21-construction-replay/sig21_construction_grid_2026-08-19.json` | complete replay: protocol metadata with tape SHA-256s, family decomposition, all 32 construction cells, time-of-day, distance, burst/episode, window-edge proximity, exclusions, coverage, baseline layer, scenarios |
| `artifacts/sig21-construction-replay/sig21_construction_grid_rows_2026-08-19.jsonl` | one flattened row per construction cell, all 32 including empties |
| `scripts/sig21_construction_replay.py` | reproducible entry point; refuses outcome requests before opening any tape |
| `src/shaurya/signals/deep_book_construction_grid.py` | aggregation, refusal guard and grid construction |

The `artifacts/` tree is gitignored by repository policy, as it is for the `DAT-20` results, so the
two files above exist locally and are regenerated deterministically by the command in §2 rather
than committed. Every number in this report is reproduced from them.
| `tests/test_sig21_construction_replay.py` | 49 tests |

## 15. Verification

- **Correctness:** 49 new tests, full suite 255 passed, `ruff check .` clean, strict `mypy` clean.
- **Completeness:** every item requested in the replay brief is produced. Nothing was scoped out.
- **Evidence level:** Dry-run verified (Level 3) — the entry point produced the required artifacts
  from representative retained tape and the semantic invariants were checked (all 32 cells emitted
  including empties, shares summing to one, family expansion reconciling to 384, transition counts
  reconciling to publications, SHA-256 agreeing with the capture manifest).
- **Leakage audit:** passed. No response-producing function is imported or called; a regression
  test replaces `build_depth20_response_labels` with a raising stub and runs the full replay; a
  further test walks every key in the emitted artifact and asserts no outcome-bearing field name
  appears anywhere.

---

## Erratum — dated NSE F&O close (added 2026-08-19)

This replay used two approximately eleven-minute midday tapes, so the formerly stated 15:30 close
did not affect any retained row, construction count, hash, or conclusion. NSE equity derivatives
close at 15:40 from 2026-08-03. A current full-session projection therefore uses 23,100 seconds.

Holding the report's explicitly linear mid-morning rate projection fixed, the corrected one-session
scenario is approximately **720,657 candidates** and **94,232 timestamp bursts**. The registered
11-second family-maximum opportunity ceilings are **2,100 per session**, **10,500 over five
calibration sessions**, and **42,000 over twenty evaluation sessions**. These are scenario and
mechanical-ceiling corrections only; the original executed evidence above is preserved.
