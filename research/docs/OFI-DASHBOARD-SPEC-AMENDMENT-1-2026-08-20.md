# ANL-06 dynamic OFI dashboard — Amendment 1

**Amends:** `docs/OFI-DASHBOARD-SPEC-2026-08-20.md` (`X-OFI-DASHBOARD-2026-08-20`)
**Requirement affected:** `DASH-OUT-01`, and consequentially `DASH-OUT-03`
**Raised:** 2026-08-20 ~11:30 IST, from the first live `follow` read
**Approved:** by Aryan, 2026-08-20 ~11:33 IST
**Status of the parent spec body:** unchanged. The frozen spec is amended by this dated,
numbered file rather than edited in place, following the `H-SIG21-A1` and
`OFI-FULL-SESSION-REPLICATION-SPEC-AMENDMENT-1` precedent.

## Current requirement

`DASH-OUT-01` ranked the hero band by **accumulated placebo-benchmarked increment**, defined
in §7 of the parent spec as future incremental OOS R2 minus past-mirror incremental OOS R2.

## Why it appears necessary

The first live read exposed the defect immediately and unambiguously. On the growing
`ofi-late-partial-20260820` tape the hero showed:

- leader `M2 | h1 10 s | h2 10 s`
- placebo-benchmarked increment **+128.31 pp**
- future incremental OOS R2 over M0 **+5.64 pp**
- past-mirror incremental OOS R2 **−122.67 pp**

The cell led the board because its **past mirror collapsed**, not because it predicted. The
same pathology was visible in the pre-attach replay read, where the top cell by benchmarked
increment had a future incremental R2 of **−0.002**.

The difference `future − past` is unbounded below in its second term, so a cell whose placebo
degenerates is rewarded in exact proportion to how badly its placebo degenerates. As a
**guard** — "does this cell beat its own backwards-facing twin?" — the quantity is sound and
was the right instinct. As a **ranking statistic** it inverts the intended meaning: it
promotes broken placebos to the headline.

This is a defect in the specification as written on 2026-08-20, not in the implementation.
The implementation built `DASH-OUT-01` correctly.

## Proposed change, as approved

`DASH-OUT-01` now reads: the hero band displays the leader ranked by **accumulated future
incremental OOS R2 over `M0`, restricted to cells that pass the placebo guard** — that is,
cells for which the future increment strictly exceeds the past-mirror increment. Where no cell
passes the guard, **there is no leader** and the hero renders `WARMING`/no-leader rather than
promoting a guard-failing cell.

The placebo-benchmarked increment is **retained in full**: still computed, still published at
`/api/state` and `/api/cells`, still displayed on the hero band as a labelled guard statistic,
and still displayed on every cell face. It ceases to be the sort key. Aryan's standing decision
that **both** raw and placebo-benchmarked quantities remain always visible is unchanged and is
strengthened — the cell face now additionally carries the future increment over `M0`, which was
previously reachable only through a tooltip.

`DASH-OUT-03` follows for coherence: the slate magnitude ramp and the sign glyph are driven by
the same ranking statistic, so colour intensity and rank cannot disagree on screen. **Brick
remains reserved, unchanged, for the past-mirror-exceeds-or-equals-future condition.**

## Effect on economic and statistical interpretation

The headline changes meaning from "cell with the largest gap between its future and past
scores" to "**best genuine predictor that is not beaten by its own mirror**". This is strictly
closer to the question `D35`/`D37` pose. No estimand changes, no cell is removed from the
175-cell family, no threshold moves, and no measured quantity is deleted. Negative,
`WARMING`, `INSUFFICIENT` and guard-failing cells all remain visible exactly as before.

## Effect on outputs and comparability

Per-cell JSONL records are unchanged in schema and content; only `leader` selection and three
presentation fields differ. Records written before this amendment remain readable and
comparable, because the ranking is derived from fields that were already published. No re-run
of any prior artifact is required.

## Alternatives considered

1. **Rank by benchmarked increment but floor the past term at zero.** Rejected: it silently
   discards information about a degenerate placebo, which is exactly the condition worth seeing.
2. **Rank by benchmarked increment among guard-passing cells only.** Rejected: guard-passing
   still leaves the difference sensitive to a merely-poor past mirror, so a mildly negative
   placebo would continue to outrank a genuinely better predictor.
3. **Drop the hero entirely and show only the grid.** Rejected: Aryan asked for a hero band,
   and a correctly ranked one is informative.
4. **Rank by BH-FDR q-value.** Rejected for now: on this data zero cells survive BH-FDR, so
   the hero would be permanently empty and the guard would never be exercised. Worth revisiting
   on a clean full session.

## Recommendation

Adopt as approved. The guard was always the useful object; it was mis-promoted to a sort key.

## Verification required by this amendment

- A regression test reproducing the exact live pathology: a cell with future increment +0.039
  and past mirror −0.777 must **not** outrank a cell with future increment +0.100 and past
  mirror +0.020.
- A test that a cell failing the placebo guard never leads, even with the largest future
  increment in the family.
- A test that the hero reports no leader when every cell fails the guard.
- Field-parity: the ranking basis is stated on the page, and both increments appear on the cell
  face rather than in a tooltip.
