# H-SIG21-A2 — Amendment 2 to the H-SIG21 pre-registration

**Amendment ID:** `H-SIG21-A2` · **Protocol amended:** `H-SIG21`
**Date raised:** 2026-08-19
**Status:** **PRE-DATA.** Zero of the twenty-five required post-registration sessions exists.

---

## 0. Why this is an amendment

`docs/sig-claims/H-SIG21.md` remains immutable. Its phrase “full session” is governed by the
dated official NSE F&O calendar, but supporting code and planning documents had encoded the old
09:15–15:30 session as a date-independent 22,500-second constant. NSE extended the equity-
derivatives close to 15:40 effective 2026-08-03. A current full session is therefore
09:15–15:40 IST, or **23,100 seconds**.

This correction is made before any eligible calibration or evaluation tape exists. It changes no
event definition, response, estimator, threshold, direction, or outcome. It only corrects the
dated session boundary and quantities mechanically derived from it.

## 1. Binding correction

For sessions before 2026-08-03, the regular NSE equity-derivatives clock is 09:15–15:30 IST. For
sessions on or after 2026-08-03, it is 09:15–15:40 IST. Code must obtain the close and session
length from the dated calendar helper rather than a date-independent constant.

For the registered 11-second family-maximum episode window, the mechanical opportunity ceilings
on or after 2026-08-03 are:

- one session: `floor(23,100 / 11)` = **2,100**;
- five calibration sessions: **10,500**;
- twenty evaluation sessions: **42,000**.

These are ceilings for planning, not effective sample sizes and not evidence about an effect.

## 2. Time-of-day strata

The registered thirty-minute time-of-day bins remain anchored at 09:15. Under the later close,
they naturally include a final short **15:30–15:40** bin. It must be emitted rather than folded
into another bin, and its smaller support must be reported. No bin boundary before 15:30 changes.

The descriptive three-bucket summaries used outside the immutable registration are
09:15–11:00, 11:00–14:00, and 14:00–15:40. They are named time-of-day buckets, not equal thirds.

## 3. Historical evidence

The two `DAT-20` runs were approximately eleven-minute midday captures. The old close statement
did not affect their rows, construction counts, hashes, or conclusions. Their dated documents
retain the executed record and carry additive errata. Any corrected session-scale derivative must
be versioned; the original artifact is not overwritten.

## 4. Implementation and audit

- `src/shaurya/contracts/timing.py` owns the dated NSE equity-derivatives clock.
- Capture acceptance verifies actual timestamps, not requested duration.
- SIG-21 construction, exploratory-response, and normal-activity planning consume 23,100 seconds
  for current sessions.
- Surface expiry close is dated: 15:30 before the effective date, 15:40 on or after it.
- Boundary and capacity regression tests pin both sides of the effective date and the
  2,100/10,500/42,000 ceilings.

The immutable `H-SIG21.md` body is unchanged.
