# H-SIG21-A1 — Amendment 1 to the H-SIG21 pre-registration

**Amendment ID:** `H-SIG21-A1` · **Protocol amended:** `H-SIG21`
**Date raised:** 2026-08-19 · **Approved by Aryan:** 2026-08-19, by voice, ~17:40 IST
**Decision ID in `TASKS.md`:** `D34`
**Status:** **PRE-DATA.** Committed and pushed **before any confirmatory tape exists.**

---

## 0. Why this file exists instead of an edit to `H-SIG21.md`

`docs/sig-claims/H-SIG21.md` is the immutable pre-registration. Its first pushed commit,
`f2cf65011d02882191b5cfda566c1024119964d7` (pushed 2026-08-19T15:00:42+05:30), **is** the
registration clock that `D29` and `SIG-19` rely on. Editing that file in place would leave the
registration and the clock disagreeing, and would destroy the audit trail that makes the
registration worth anything.

So the registration body is untouched — verifiable with
`git log -- docs/sig-claims/H-SIG21.md`, which must show exactly one commit, `f2cf650`. This file
is a dated, numbered amendment sitting beside it and is referenced from
[`README.md`](README.md) § "Amendments".

**The critical timing fact.** No tape eligible for the first `H-SIG21` outcome sample has been
collected. `H-SIG21` §1.5 admits only tape collected after the registering commit; §8 requires
five post-registration calibration sessions and then twenty evaluation sessions, and **zero of
those twenty-five sessions exist.** The only tapes ever opened are the two `DAT-20` captures from
13:09 and 13:20 IST, which predate the registering commit and are permanently ineligible by
§1.5/§1.2. This amendment is therefore made **before any confirmatory data exists at all**. It is
a pre-data amendment, not a post-hoc one, and it cannot have been chosen to make a result look
better because no result exists to look at.

---

## 1. Plain English — what changed and why

The registration said: when we count events, two events that are close together in time should
not be counted twice, because their prediction windows overlap and they are really telling us the
same thing once. To enforce that, it made every test in the study wait **eleven seconds** between
one event and the next one it would count.

Eleven seconds is the length of the *longest* test in the study — the one that looks one second
ahead of the event and then measures ten seconds of price. But most of the tests are much shorter.
A test that waits half a second and then measures one second of price is finished in **one and a
half seconds**. Making that test wait eleven seconds throws away almost everything it could have
used, for no reason.

We measured how much it throws away. On the recorded tape, at the study's own event threshold, the
short test kept **260 events under its own one-and-a-half-second rule and 2 events under the
eleven-second rule.** That is a factor of 130 — between two tests that belong to the same study
and are supposed to be comparable.

The change: **each test now waits its own length, not the longest test's length.** Nothing else
moves. The rule that overlapping events must not be double-counted is exactly as strict as before
— it is just applied to the window each test actually uses.

The old eleven-second version is kept and reported side by side, so anyone can check that the
change is the only thing that moved.

---

## 2. Requirement affected

**`H-SIG21` §6, first bullet pair — primary risk set definition.**

**Original text (unchanged in the registration body):**

> - All changes in one receive-timestamp burst form one cluster.
> - Bursts whose predictive windows overlap are grouped into an episode. The primary risk set
>   keeps non-overlapping episodes using the largest registered endpoint (`Z + h2 = 11 s`).
>   All-event estimates may be reported only with dependence-robust inference and cannot replace
>   the primary.

**Amended text, in force from this commit:**

> - All changes in one receive-timestamp burst form one cluster.
> - Bursts whose predictive windows overlap are grouped into an episode. The primary risk set
>   keeps non-overlapping episodes using **that cell's own registered endpoint `Z + h2`**, so a
>   `Z = 0.5 s, h2 = 1 s` cell uses a 1.5 s window and a `Z = 1.0 s, h2 = 10 s` cell uses an
>   11 s window. The family-maximum 11 s window is retained as an **explicitly declared
>   robustness arm** (`robustness_family_maximum_episodes`), reported for every cell alongside the
>   primary and never promoted to it. All-event estimates may be reported only with
>   dependence-robust inference and cannot replace the primary.

Everything else in §6 is unchanged, including — deliberately — the matched-quiet-control
definition. See §7 below.

---

## 3. Measured evidence that motivated it

All figures from `X-SIG21-DAT20-01`, the declared exploratory scan on the two pre-registration
`DAT-20` tapes, recorded in `docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md` §3.2. Those tapes can
never be confirmatory, so this evidence costs the registration nothing.

Coverage: 1,305.37 s of depth200, 5,482 publications, 40,724 candidates in 5,325 bursts. Median
inter-burst gap 0.20 s; the largest gap anywhere on the tape is 0.81 s. The far book publishes
essentially continuously.

At the lower registered threshold (99.5%):

| `Z` | `h2` | Cell's own window | Episodes under own window | Episodes under 11 s family maximum | Factor |
|---:|---:|---:|---:|---:|---:|
| 0.5 | 1 | 1.5 s | **260** | 2 | **130×** |
| 0.5 | 5 | 5.5 s | 7 | 2 | 3.5× |
| 0.5 | 10 | 10.5 s | 2 | 2 | 1× |
| 1.0 | 1 | 2.0 s | **144** | 2 | **72×** |
| 1.0 | 5 | 6.0 s | 6 | 2 | 3× |
| 1.0 | 10 | 11.0 s | 2 | 2 | 1× (identical by construction) |

At the upper registered threshold (99.9%) the same direction holds, less extremely: 118 versus 39
at `Z = 0.5, h2 = 1`.

Two further measured facts that bear on the decision, both from the same scan:

- Pooled across all 32 construction cells the primary risk set is **2 episodes** — one per
  contiguous tape — at every selectivity from the 50th percentile through the registered 99.5th.
  The number was counting tapes, not events.
- Summed over construction cells the primary risk set **peaks at the 95th percentile (608
  episodes) and has fallen to 129 by the 99.9th**, so both registered thresholds sit on the
  falling side of that curve. This amendment does not touch the thresholds; the fact is recorded
  because it bounds how much the amendment can be expected to buy.

---

## 4. Effect on interpretation and comparability

**On the estimand: none.** What is being estimated — the response distribution of a registered
cell, and the event-minus-matched-control difference that is the primary estimand — is unchanged.
This amendment changes only which observations enter the primary risk set of each cell.

**On the independence argument: none.** §6's purpose was that two observations in one cell must
not share a predictive window. That is *more* exactly enforced now, not less: previously a
1-second-horizon cell's episodes were separated by 11 s, which is stricter than its own window
needs but is not a different kind of guarantee. Each cell's episodes remain genuinely
non-overlapping for the window that cell is actually estimated on.

**On the estimator: none.** HAC/Newey-West lag, the session-clustered stationary block bootstrap
and Romano-Wolf step-down are all unchanged. The HAC lag floor stays at the registered
`REGISTERED_OVERLAP_LAG = 11` observations for both episode arms, so the primary arm is not given
a looser variance estimator than the arm it is being compared against.

**On comparability: cells' `N` and `N_eff` are no longer comparable across horizons.** A
1-second-horizon cell will now carry many more observations than a 10-second-horizon cell of the
same construction. This is a real cost and is stated plainly. The defence is that those cells were
never substantively comparable — they measure different horizons on the same tape, and a
10-second horizon genuinely has fewer independent opportunities in a fixed span than a 1-second
horizon does. The old convention made the `N` column look comparable while making it uniformly
wrong.

**On outputs:** every family artifact now carries four arms rather than three, and every cell row
carries `episode_window_seconds` and `family_maximum_episode_window_seconds`. The 384-cell family,
the thresholds, the atomic types, the sides, the distance bands, the `Z` values, the `h2` values,
the strata, the negative controls and the power gates are **all untouched**. No cell is added,
removed or redefined.

**On already-published figures:** none is invalidated. Everything published so far under the
family-maximum convention is reproduced exactly by the `robustness_family_maximum_episodes` arm,
and `test_the_family_maximum_arm_reproduces_the_pre_amendment_primary_arm` pins that.

---

## 5. Alternatives considered and rejected

These are the four options put to Aryan in `docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md` §9.

| | Option | Decision | Reason |
|---|---|---|---|
| (i) | Keep the family-maximum window as registered | **Rejected** | It leaves the primary arm at 2 episodes for half the family at the lower registered threshold — the situation §6 explicitly says must not arise, where the permitted supplement carries all the information and the primary carries none. |
| (ii) | Promote the overlap-robust all-event estimator to primary, demote the episode set to a robustness check | **Rejected** | It changes which estimator is authoritative and makes `N_eff` an estimated rather than a counted object. Worse, the tape shows the studentised bootstrap producing family-wide critical values of 92 and 343 on cells holding two to five observations. Making a variance-estimator-dependent arm primary while the variance estimator is visibly degenerate is the wrong direction. |
| (iii) | **Bind the episode window to each cell's own `Z + h2`** | **ADOPTED** | Smallest change that removes the demonstrated distortion. The collapse is caused by the family-maximum convention, not by the non-overlapping principle; this fixes exactly that and nothing else. It does not weaken the estimand or the estimator, and does not change the unit of observation. |
| (iv) | Replace episodes with fixed non-overlapping `Z + h2` time blocks | **Rejected** | Cleanest statistically, but it changes the unit of observation from event episode to time block, makes every previously reported episode figure non-comparable, and is the furthest of the four from the registered text. |

**Aryan's approval, verbatim (voice, 2026-08-19 ~17:40 IST):**

> "I agree with you for saying that each test should use its own length, that is number one,
> definitely let's go about that."

---

## 6. An honest note on `select_primary_non_overlapping_episodes`

The exploratory scan reported (§6.2 of that document) that
`select_primary_non_overlapping_episodes` is the **identity function** on
`cluster_event_episodes` output: the clustering step starts a new episode only when a burst begins
strictly after the running episode's end, so consecutive clustered episodes never share an
endpoint and the selection step can never exclude anything. Its `overlap_excluded` counter reads
zero **by construction, not by measurement.**

This amendment re-examined that under the new per-cell window and reached a decision.

**What was checked:** whether shrinking the window makes the selection step do real work. It does
not. A smaller window shrinks each episode's end timestamp but preserves the strict inequality
that clustering guarantees, so the composition is still the identity at every window size.
`test_selection_is_the_identity_on_clustered_output` now pins this at three different windows.

**Decision: the function stays as it is, and no behaviour was changed.** The reason it is kept
rather than deleted is that it is *not* the identity on episode sets that did not come from a
single `cluster_event_episodes` call — a union of per-cell episode sets, a set rebuilt from a
stored artifact, or any future caller assembling episodes another way. On those it genuinely
excludes overlap, and `test_selection_excludes_overlap_from_an_externally_assembled_episode_set`
proves it. Under this amendment that case is closer than it was, because per-cell windows make
"episodes from different cells" a natural thing to hold at once.

**What did change: the docstring.** It now states, in the function itself, that the zero
exclusion count on clustered input is a construction property and must never be cited as evidence
that overlap exclusion was checked and found unnecessary. That misreading was the actual risk, and
it is a documentation defect, not a behavioural one.

---

## 7. What this amendment deliberately does NOT change — the open item

**The matched-quiet-control definition is untouched.** `H-SIG21` §6's third bullet still reads
"with no anomaly in the surrounding 11 seconds", and the code still uses an 11-second quiet
window.

This is a deliberate omission, not an oversight. The exploratory scan showed the registered
control design is infeasible at the lower registered threshold on that tape — **zero** quiet
control instants exist anywhere in 22 minutes, so the primary estimand is undefined, not merely
imprecise, for all 192 cells at 99.5%. That is a real problem and it is bigger than the one this
amendment fixes.

Aryan deferred it, deliberately and explicitly, on 2026-08-19 (voice):

> "what counts as a quiet moment is something we need to reserve for tomorrow — only tomorrow's
> limit order book activity will tell us what is a quiet moment."

**No replacement definition is proposed here, and none may be adopted without a further
amendment.** It is carried as an open item in `TASKS.md` under `D34`. It must be settled before
the five calibration sessions are spent, because a control definition chosen after seeing
calibration outcomes would not be pre-data.

---

## 8. Implementation

| What | Where |
|---|---|
| Per-cell window derivation | `episode_window_ns(gap_seconds=..., horizon_seconds=...)` in `src/shaurya/signals/deep_book_response.py` |
| Family-maximum window, explicitly named | `FAMILY_MAXIMUM_EPISODE_WINDOW_NS` / `..._SECONDS`, same module |
| Primary risk set formed per cell | `build_cell_series` in `src/shaurya/signals/deep_book_exploratory_response.py` |
| Declared robustness arm | `robustness_family_maximum_episodes`, emitted for all 384 cells in `build_response_family` |
| Artifact provenance | `episode_window_convention: "per_cell_z_plus_h2"`, `episode_window_amendment: "H-SIG21-A1"`, plus per-cell `episode_window_seconds` |

Tests, in `tests/test_deep_book_response.py` and `tests/test_sig21_exploratory_response.py`:

- `test_episode_window_is_derived_from_the_cells_own_gap_and_horizon`
- `test_the_longest_registered_cell_reproduces_the_family_maximum_window`
- `test_episode_window_refuses_an_impossible_cell`
- `test_a_short_horizon_cell_retains_far_more_episodes_than_the_family_maximum`
- `test_the_family_maximum_arm_still_reproduces_the_old_numbers`
- `test_selection_is_the_identity_on_clustered_output`
- `test_selection_excludes_overlap_from_an_externally_assembled_episode_set`
- `test_cell_series_uses_this_cells_own_window_not_the_family_maximum`
- `test_the_family_maximum_arm_reproduces_the_pre_amendment_primary_arm`
- `test_family_emits_all_384_cells_with_all_four_arms`

---

## 9. Approval record

```markdown
## Proposed Specification Change
**Requirement affected:** H-SIG21 §6, primary risk set definition
**Current requirement:** every cell draws its primary risk set from non-overlapping episodes
  built on the family-maximum 11 s window.
**Proposed change:** bind the episode window to each cell's own Z + h2; retain the
  family-maximum window as a declared robustness arm.
**Why it appears necessary:** measured factor of 130 in retained episodes between two cells of
  the same registered family, caused entirely by the family-maximum convention.
**Effect on economic/statistical interpretation:** none on the estimand, the estimator or the
  independence argument; cross-horizon N comparisons stop being meaningful.
**Effect on outputs and comparability:** a fourth arm in every family artifact; the previous
  primary arm is reproduced exactly by it.
**Alternatives considered:** (i) keep as registered, (ii) promote the all-event estimator,
  (iii) per-cell window, (iv) fixed time blocks.
**Recommendation:** (iii).
**Approval required from Aryan:** Yes.
**APPROVED:** Aryan, by voice, 2026-08-19 ~17:40 IST.
**Committed before any confirmatory tape existed:** Yes — zero of the twenty-five required
  post-registration sessions have been collected.
```
