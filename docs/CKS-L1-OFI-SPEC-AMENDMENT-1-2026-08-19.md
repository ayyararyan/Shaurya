# Amendment 1 to `X-CKS-L1-OFI-DAT20-04` — response-horizon floor, window-floor justification, and two disclosed identification findings

**Amends:** `docs/CKS-L1-OFI-SPEC-2026-08-19.md` (frozen 2026-08-19 20:03, commit `b829321`)
**Status:** open amendment, recorded rather than applied by rewriting the frozen spec.
**Confirmatory eligible:** `false` (unchanged).

This amendment does **not** silently rewrite the frozen specification. The original text stands;
everything below is additive and separately timestamped.

## A0 Provenance and outcome-blindness of this amendment

Every diagnostic in this amendment was computed **from the raw tape JSONL only** — best-quote
prices/quantities, receive timestamps, and `full`-packet `last_price`. **No cell of the 25-cell
outcome grid, and no R², coefficient or test statistic from `artifacts/cks-l1-ofi/`, was read
while deriving these numbers or the decision rules below.** The decision rules are therefore
outcome-blind.

**Honest status caveat.** At the time this amendment was written, `artifacts/cks-l1-ofi/` already
existed on disk (the 25-cell scan had been executed, including its deterministic `replay/` check).
This amendment is therefore **pre-report and outcome-blind, but not pre-artifact**. It must not be
described as pre-outcome without that qualification.

## A1 Measured clocks — correcting the working premise

The scan was designed against an assumed "~0.4–0.5 s feed clock". Measured on both tapes, there
are **two different clocks**, and neither is 0.4–0.5 s in the way assumed:

| Series | Role | Distinct instants | Median gap | p90 | Max |
|---|---|---|---|---|---|
| `depth200` | OFI construction clock | 4.16 / 4.23 per s | **200.4 ms** | 399.8 ms | 603.3 ms |
| `depth20` | response (mid) clock | 1.99 / 2.00 per s | **500.7 ms** | 501.9 ms | 1003.1 ms |

(Tape A / tape B. `depth200` records arrive exactly 2-per-instant, `depth20` ~4-per-instant;
duplicate-timestamp records were collapsed before computing gaps.)

The `depth20` response clock is a hard **500 ms metronome** (p10 499.7 ms, p90 501.9 ms). The
`depth200` construction clock is ~200 ms. The remembered "0.4–0.5 s" figure corresponds to neither
publication cadence; it matches tape B's median **best-quote-change** interval (399 ms) and the
response metronome.

## A2 `WIN-CKS-01` Why `h1 = 0.5 s` is the admissible floor — retained, on restated grounds

`h1 ∈ {0.5, 1, 2, 5, 10}` s is **retained unchanged**. The justification is not publication
cadence — at 200 ms cadence a 0.25 s window would contain ~2 snapshot transitions. The binding
constraint is that `e_n` is zero unless the **best quote actually changes**, and best-quote changes
are far rarer than publications: **1.42/s (tape A), 0.77/s (tape B)**.

Fraction of windows containing at least one best-quote change:

| `h1` | tape A | tape B | median transitions in window |
|---|---|---|---|
| 0.10 s | 34.1% | 18.2% | 1 |
| 0.25 s | 46.3% | 27.8% | 2 |
| **0.50 s** | **53.8%** | **35.1%** | 3 |
| 1.00 s | 65.2% | 47.6% | 5 |
| 2.00 s | 79.2% | 63.4% | 9 |

Below 0.5 s the regressor is zero in a majority of windows on **both** tapes, and `OFI_{h1}`
degenerates from a pressure sum into a near-binary "did anything happen at the touch" indicator.
0.5 s is the shortest window at which more than half of tape-A windows carry a genuine best-quote
event. It is the floor, not a comfortable choice: **even at `h1 = 0.5 s`, 46% (A) and 65% (B) of
windows still have `OFI ≡ 0`**, a structural point mass that must be reported alongside every
`h1 = 0.5 s` cell.

Independently, an OFI window shorter than the 500 ms response grid would add right-hand-side
resolution the left-hand side cannot resolve. No 0.1 s or 0.25 s arm is constructed, and no
independent 0.1/0.25 s observation is claimed anywhere in this scan — the table above is a
support diagnostic on window occupancy, not a result.

## A3 `OUT-CKS-01-A` Response-horizon family — `h2 = 0.5 s` admitted

Precondition set by the requester: add `h2 = 0.5 s` **only if causal/as-of coverage supports it**.
Measured, with the frozen causal gap `Z = 0.5 s`, over all `depth200` window-end times, resolving
the `depth20` mid as-of both endpoints:

| `h2` | same-snapshot at both endpoints | median distinct mid updates spanned | zero-return share (A / B) |
|---|---|---|---|
| **0.5 s** | **0.6% / 0.5%** | **1.0** | **59.8% / 78.0%** |
| 1 s | 0.0% / 0.0% | 2.0 | 49.8% / 67.7% |
| 2 s | 0.0% / 0.0% | 4.0 | 34.5% / 53.8% |
| 5 s | 0.0% / 0.0% | 10.0 | 15.3% / 29.0% |
| 10 s | 0.0% / 0.0% | 20.0 | 4.7% / 14.4% |
| 30 s | 0.0% / 0.0% | 60.0 | 2.0% / 2.8% |

**Coverage supports it**: at `h2 = 0.5 s` the two endpoints resolve to *different* `depth20`
snapshots in 99.4–99.5% of cases, spanning exactly one update. The precondition is met, so
`h2 = 0.5 s` is admitted.

**Disclosed before any outcome is read:** the `h2 = 0.5 s` target carries a **59.8% (A) / 78.0% (B)
point mass at exactly zero**. This is not a coverage artifact — the endpoints are distinct
snapshots that genuinely carry the same mid. Consequences that must be stated with the cell, not
discovered afterwards: in-sample and out-of-sample R² are mechanically depressed by the point mass;
Newey–West and block-bootstrap inference is unreliable against a spike-and-slab target; and the
A-versus-B gap (60% vs 78%) will present as tape instability when it is really an activity
difference between the two recordings.

**Resulting grid.** Core family `h1 ∈ {0.5, 1, 2, 5, 10}` × `h2 ∈ {0.5, 1, 2, 5, 10}` = **25 core
cells**; `h2 = 30 s` is retained as a **declared longer robustness arm**, 5 further cells;
**30 cells emitted in total**, all of them, including nulls, negatives and failures.

**Implementation note — not yet applied.** `cks_l1_ofi.py` imports `RETURN_HORIZONS_SECONDS` from
`deep_book_ofi`, which is shared with the frozen, already-reported `X-OFI-DAT20-03`. The horizon
tuple must **not** be edited there. This amendment requires a CKS-local constant, e.g.
`CKS_RETURN_HORIZONS_SECONDS = (0.5, 1, 2, 5, 10, 30)`, substituted at the four use sites in
`cks_l1_ofi.py`, with `expected = len(OFI_WINDOWS_SECONDS) * len(CKS_RETURN_HORIZONS_SECONDS)`
updated to 30 and the scan re-run. Until that is done the artifact remains a 25-cell grid and the
report must say so.

## A4 `ID-CKS-02` Displayed level one is not the true touch — a first-order identification finding

This is the most consequential measurement in this amendment and it bears directly on whether the
object the scan builds is the CKS object at all.

**Spread, measured on the `depth20` response clock:**

| | median | p10 | p90 | share > 2 ticks |
|---|---|---|---|---|
| Tape A | **100 ticks (₹5.00)** | 34 | 188 | 99.8% |
| Tape B | **134 ticks (₹6.70)** | 74 | 204 | 100.0% |

For scale, the entire mid range of each recording is 497 ticks (A) and 194 ticks (B) — on tape B
the **median quoted spread is about two-thirds of the whole price range of the recording.**

**Where trades actually print**, relative to the prevailing displayed quote (`full` packets matched
to the last `depth20` snapshot at or before them):

| | strictly inside the quote | exactly at bid or ask | outside |
|---|---|---|---|
| Tape A (n=794) | **48.1%** | 31.5% | 20.4% |
| Tape B (n=802) | **41.9%** | 17.1% | 41.0% |

**Roughly half of all executions print strictly inside the displayed best bid/ask.** The displayed
level 1 on this feed is therefore **not the true touch** for a large fraction of trading, and
`q^B`, `q^A` are not the true touch queues.

Consequences, binding on how the result may be described:

- The constructed `e_n` is the order-flow imbalance of the **outermost displayed band**, not the
  CKS best-quote object. It should be named as such in the report.
- CKS (2014) obtained R² ≈ 65% *contemporaneously* on US equities where L1 **is** the touch and
  spreads are ~1 tick. That benchmark is **not comparable** to this feed, and a weak result here is
  as likely to be a level-1 identification failure as an absence of information.
- This independently rationalises `X-OFI-DAT20-03`'s finding that the predictive lead sat in levels
  2–10 and **explicitly not in level 1**: the informative liquidity sits behind a wide, stale
  displayed L1.
- `mean_l1_depth_window` and `l1_depth_end` inherit the same defect: they measure the outer band's
  displayed size, not touch depth, so `cks_pressure` is a ratio of two mis-located quantities.

Nothing here is a reason to suppress the scan. It is a reason to report it as a level-1
*identification* study on a feed whose level 1 is not the touch, and to refuse any claim that a
null result demonstrates the CKS object lacks content.

## A5 Minor: tape timestamp field

`exchange_ts` carries IST wall-clock with a `+00:00` suffix (first record: `exchange_ts`
`2026-08-19T13:09:29+00:00` against `receive_ts` `2026-08-19T07:39:35Z`). Every clock in this scan
uses `receive_ts`, so no result is affected. Recorded so it is not rediscovered as a bug.

## Unchanged

Exploratory status, `confirmatory_eligible = false`, the two permitted tapes, the identification
limits in `ID-CKS-01`, the `e_n` definition and its eight-component decomposition, `h1`, `Z = 0.5 s`,
the five models plus `R1`, the split and embargo, the placebo and dependence programme, and every
explicit exclusion.

## A6 Application record

This amendment was applied rather than left open:

- `cks_l1_ofi.py` now defines `CKS_RETURN_HORIZONS_SECONDS = (0.5, 1, 2, 5, 10, 30)` locally.
  `deep_book_ofi.RETURN_HORIZONS_SECONDS` is **unchanged**, so the frozen `X-OFI-DAT20-03` design is
  untouched. The three horizon-keyed annotations widened from `int` to `float` in
  `deep_book_ofi.py` and `deep_book_normal_activity.py` are **annotation-only** — both modules carry
  `from __future__ import annotations`, so nothing is evaluated at runtime and no existing artifact
  can change.
- The scan was re-run at 30 cells and replayed byte-for-byte. `cks_l1_ofi_components_2026-08-19.jsonl`
  is **bit-identical** to the pre-amendment run, confirming the transition decomposition is
  independent of the response grid.
- 448 repository tests pass at the time of this record; `ruff check` and strict `mypy` over 50
  source files are clean. (The suite is 450 after the later sub-second horizon coverage tests.)

**Side effect that must be disclosed.** Admitting a shorter horizon lets a few observations near the
end of each recording qualify that previously had no covered future horizon. The sample moved from
**5,204 to 5,210** observations (3,641 → 3,646 train, 602 → 604 test). Every cell therefore shifted
slightly, including the original 25. `docs/CKS-L1-OFI-2026-08-19.md` has been recomputed in full on
the 5,210-observation run; no figure in it is carried over from the 25-cell run.

**Outcome of the new arm, for the record.** None of the five `h2 = 0.5 s` cells clears the three
dependence checks, and the past-return mirror beats the future increment in **all five**. The arm is
a clean negative. Two headline counts also moved against the earlier run: cells clearing all three
checks fell from 2 to **1 of 30** for raw OFI and from 1 to **0 of 30** for depth-scaled pressure.

## A7 Correction record — figures carried over from the 25-cell run

The first amended edition of `docs/CKS-L1-OFI-2026-08-19.md` shipped with a correct 30-cell table
but with several **prose figures still carried over from the pre-amendment 25-cell run**, in direct
contradiction of the "no figure carried over" statement above. Every numerical claim in the report
was then re-derived from `artifacts/cks-l1-ofi/cks_l1_ofi_grid_2026-08-19.jsonl` and
`cks_l1_ofi_scan_2026-08-19.json` and corrected. The corrections, all in the amended (5,210
observation) direction:

| Claim | Shipped | Correct |
|---|---|---|
| Dependence statistics at the one surviving cell (2 s → 2 s) | 2.27 / 2.36 / 2.53 | **2.27 / 2.41 / 1.97** |
| Its per-tape increments | +0.036 / −0.005 "points" | **+3.60 / −0.48 points** (the shipped pair were fractions mislabelled as points) |
| A claimed "second surviving cell" (0.5 s → 10 s) | present | **removed** — its non-overlapping statistic is 1.90, so it never cleared; exactly one raw cell clears, as the summary table already said |
| Statistics at the strongest raw cell (1 s → 2 s) | 1.95 / 1.85 / 2.14 | **1.956 / 1.833 / 1.822** — misses on all three, the first by 0.004 |
| Same-window diagnostic, all five rows | 0.91/1.16, 0.45/3.02, −0.12/3.18, 6.92/14.99, 11.85/27.70 | **0.87/1.11, 0.62/3.08, 0.09/3.41, 6.28/14.37, 11.68/27.53** |
| `X-OFI-DAT20-03` comparison at 10 s → 10 s | +7.16 pp, −0.54 pp, 8.40% | **+7.12 pp, −0.55 pp, 8.38%** |
| Level-one coefficient at that cell | −3.03 pooled; −2.08 / −6.29 | **−3.09 pooled; −2.20 / −6.28** |
| Object split across the grid | top-10 wins 13, level one 12 | **top-10 wins 13, level one 17** (the shipped pair summed to 25, not 30) |
| `R1` best cells | 2.08% / 1.96% / 1.79% | **2.30% / 2.20% / 2.00%** |
| Bottom line, best pressure cell | "fails two of three checks" | **fails all three** (1.74 / 1.76 / 1.59) |

**No conclusion changes.** Every correction moves a number, not a verdict: the scan still finds one
raw cell clearing all three checks out of 30, zero pressure cells, a sign flip across the two
recordings at that cell, depth scaling helping in 27 of 30, and the `X-OFI-DAT20-03` lead surviving
the depth control while level one contributes negatively. Two corrections make the result slightly
*worse* than shipped (one survivor rather than two; the surviving cell's non-overlapping statistic
is 1.97 rather than 2.53, i.e. it barely clears).

Two stale pre-rebase commit hashes were also repaired: the frozen-spec reference above (`1e3ba42` →
`b829321`) and the artifact-digest pin in the report (`2cf3383` → `0279988`). Both originals were
orphaned by a rebase onto `origin/main` and were unresolvable in the published history.
