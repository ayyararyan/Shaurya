# What ordinary deep-book activity says about the futures price — `X-DEEPBOOK-DAT20-02`

**Exploratory scan ID:** `X-DEEPBOOK-DAT20-02` · **`confirmatory_eligible`: false**
**Date:** 2026-08-19 · **Tape:** the two retained pre-registration `DAT-20` NIFTY-futures captures
**This is not `H-SIG21`** and may never be described as part of it. `H-SIG21`'s registration and
its 384-cell family are untouched by everything below.

---

# Part 1 — Plain English

## 1.1 The question

Aryan asked, in his words:

> "these were only based on abnormal events that happened in 11 seconds. I want to know a basic
> question — what does normal order book activity tell us about predictive power of the futures at
> 200 levels? That's a very simple question. Let us see what we get if we answer that simple
> question instead of first going too complicated into detecting abnormal activity."

So this scan drops anomalies completely. No thresholds. No rare events. No episodes. It looks at
the ordinary, everyday shape of the 200-level order book — how much is resting on each side, how
many orders that is spread across, how far out it sits, and how all of that is changing — and asks
what it says about where the price goes next.

## 1.2 The answer, in two sentences

**On this tape we cannot show that ordinary deep-book activity tells us where the futures price is
going.** And on the specific question that matters most for this project — does anything below
level 20 add anything, once the top of the book is already being used — **the answer is no, and it
is a fairly clean no.**

## 1.3 The central test, and what it found

The test was built as a ladder. Start with only the best bid and best ask. Then add the top 5
levels. Then the top 20. Then levels 21 to 50. Then levels 51 to 200. At each step we ask one
thing: **did adding this deeper slice make the forecast better, on data the model has never seen?**

That last part matters. The model is trained on the first 70% of each recording and tested on a
later part, with a two-minute gap thrown away in between so that nothing from the training period
can bleed into the test period.

Here is what happened at the two steps that are the whole point of this project:

| Step | How many times it was tested | How many times it helped, beyond doubt |
|---|---:|---:|
| Adding levels **21–50** to the top 20 | 5 (one per time horizon) | **0** |
| Adding levels **51–200** on top of that | 5 | **0** |

Zero out of ten. Not "small and uncertain" — nothing at all. Several of the steps actually made
the forecast slightly *worse*, which is what you expect when you add information that carries
nothing and only adds noise.

We ran the same ladder a second way, cutting the book by **price distance** (within ₹5, ₹5–20,
₹20–50, beyond ₹50) instead of by level number, because those are not the same thing. There, one
of ten deep steps did clear the bar: going beyond ₹50 at the 30-second horizon. But that particular
test had only **four independent chunks of data behind it**. Four. That is not a finding, it is a
coin landing on its edge, and section 1.5 explains why we are confident it should not be believed.

## 1.4 What *did* look like something — and why it should not be trusted either

The one step that repeatedly looked meaningful was the *near* book: going from best-quote-only to
the top 5 levels. That fired at the 1-second horizon and again at 60 seconds.

That is not a surprise and it is not this project's question. The top of the book is public, it is
what everyone already looks at, and it is not what the 200-level ladder was bought for.

## 1.5 The most important number in this whole document

**The price fell steadily through both recordings.** Over 22 minutes it dropped, and it dropped
more the longer you waited: on average about 0.3 ticks over 1 second, and about 17 ticks over
60 seconds. (One tick is ₹0.05.)

That single fact will make almost anything look like it works, because "guess the price will fall"
is a good guess on this tape and a useless one in general. Here is exactly how much damage it does.
At the 60-second horizon:

| How the model is scored | Score |
|---|---:|
| Against "the price will not move" — **the raw number** | **0.40** |
| Against "the price keeps falling like it did in training" — **the honest number** | **0.05** |

Same model. Same data. Eight times the apparent quality, purely from the fall. Every number quoted
in this document is the honest one unless it explicitly says raw.

## 1.6 The test that should worry us most

We ran the exact same machinery backwards. Instead of asking the book to predict the price over
the next 10 seconds, we asked it to "predict" the price over the 10 seconds that had **already
happened** before the book was even looked at. Nothing can genuinely do that. Anything that fires
is measuring the drift, not information.

| What we ran | How often it fired |
|---|---:|
| The real forward test — cut by level | 2 out of 20 |
| The real forward test — cut by price distance | 2 out of 15 |
| **Asking the book to "predict" the past** | **8 out of 20** |
| Asking the book to explain what the price did *while* it was being observed | 9 out of 20 |
| Re-timing every observation to a random other moment in the same half hour | 3 out of 20 |
| Mirroring which side is the bid and which is the ask, on half the sample | 1 out of 20 |

**The apparatus predicts the past about four times as often as it predicts the future.** That is
the loudest sentence in this document and it comes first for that reason. It does not mean the
forward results are fake; it means our tools fire on drift at a rate far above what they should,
so a forward result at the same rate is exactly what a null looks like here.

The same picture shows up in the simple one-feature-at-a-time table. Across 2,675 feature-horizon
pairs, the fraction that look statistically strong is **29% for the future, 32% for the past, and
39% for what the price was doing at the moment of observation** — against the 5% you would expect
if nothing were there. The past beats the future. That is drift.

## 1.7 Was the linear model just too simple?

No. We also ran one deliberately flexible, non-linear model as a **yardstick** — purely to measure
how much structure exists in principle. It is not a strategy candidate, it never will be, and its
number is not a result. It scored roughly the same as the plain models, and worse at two of the
five horizons. So the near-nothing we are seeing is not the linear form being too restrictive.
There is genuinely little there to find on this tape.

## 1.8 How much tape would actually settle this

This is the useful part, because "we cannot tell" is only useful with a number attached.

We measured how much the answer wobbles from one chunk of data to the next, and worked out how
much test data would be needed to detect a genuinely small-but-real improvement — one percentage
point of forecasting quality.

| Horizon | Tape needed to settle whether the deep book adds a small amount |
|---|---|
| **1 second** | **under half a trading session** |
| 5 seconds | half a session to about 19 sessions, depending on the slice |
| 10 seconds | about half a session to 1.5 sessions |
| 30 seconds | about 3 sessions |
| 60 seconds | 48 to 107 sessions |

So the short horizons are cheap and close. **One full trading day of the same recording would
settle the 1-second and 10-second questions properly.** The 60-second question is expensive and
probably not worth buying.

## 1.9 What this cannot say, stated plainly

22 minutes. One contract. One mid-afternoon half-hour. One direction of travel — down, the whole
time. No open, no close, no lunch lull, no news, no second contract, and **no variation between
sessions at all**, because there is only one session.

Nothing here is a result. Nothing here is evidence about whether the market can be forecast, and
nothing economic is claimed or implied. If the deep book does carry something, this tape is far too
small and far too one-directional to show it; and if the deep book carries nothing, this tape
cannot prove that either. What it *can* do is tell us what to record next, and it does: **one full
two-sided session, and re-run this scan unchanged.**

## 1.10 Four things that were broken, found by running it

Each of these produced a check that **could not have failed no matter what the data said** — the
most dangerous kind of bug in this sort of work, because it looks like a clean result. All four
were found, fixed, and locked down with tests.

1. **The raw and drift-adjusted columns were the same number.** After removing the drift, the
   thing the raw column was being compared against became zero, so both columns collapsed onto
   each other and the drift stopped being visible. The raw column is now scored before the drift
   is removed. This is the fix that produced the 0.40-versus-0.05 comparison in section 1.5.
2. **The "what was the price doing at the time" check was always exactly zero.** Both ends of it
   resolved to the same book update. It now spans the update either side of the observation.
3. **The bid/ask mirror check was mathematically incapable of changing the answer.** Mirroring
   every observation is something a linear model simply re-learns, so the check reproduced the
   real result to the last decimal. It now mirrors a random half of the sample, which cannot be
   re-learned.
4. **The regularisation strength was pinned at the edge of its own search range** in every single
   fit. A choice made at the boundary of the options offered is not a choice. The range was
   extended until the search stopped hitting the wall.

---

# Part 2 — Technical record

## 2.1 Protocol status

| Field | Value |
|---|---|
| Exploratory scan ID | `X-DEEPBOOK-DAT20-02` |
| `confirmatory_eligible` | `false` |
| `sample_role` | `exploratory_scan_pre_registration_capture` |
| Part of `H-SIG21`? | **No.** Shares two tapes and the depth20 mid-price convention; nothing else |
| `H-SIG21.md` modified | no — still one commit, `f2cf650` |

**Why looking at these price paths was permitted.** Both tapes were captured at 13:09 and 13:20
IST. The `H-SIG21` registering commit `f2cf6501` was pushed at 15:00:42 IST, about an hour and
fifty minutes later. `H-SIG21` §1.5 admits only tape collected *after* that commit into its first
outcome sample, and §1.2 already excludes these tapes' post-event price paths from SIG-21
inference. They were permanently outside any confirmatory sample before this scan existed.

**Refusals are in code, not only in prose.** `assert_exploratory_claim` rejects any confirmatory or
economic framing before a file is opened; `assert_permitted_tape` rejects any tape whose SHA-256 is
not one of the two pinned pre-registration captures, so a post-registration calibration tape cannot
be fed to it by accident; `assert_complete_table` rejects a table that has been filtered or
truncated to its interesting rows.

| Field | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `sha-20260819T073935.092996Z-6ca41203` | `sha-20260819T075057.972093Z-286d5105` |
| Tape SHA-256 | `751ee15a…955b71e0` | `c20590d6…08c82b82` |
| Instrument | `NSE:NSE_FNO:NIFTY:future:2026-08-25` | same |
| depth200 publications | 2,718 | 2,764 |
| depth20 publications | 1,306 | 1,309 |
| Coverage | 652.7 s | 652.6 s |
| Usable observations | 2,713 | 2,758 |
| Dropped | 1 unusable book state, 4 no covered horizon | 1 unusable, 1 no depth20 anchor, 4 no covered horizon |

Every drop is counted by reason. Nothing is imputed and no missing value is treated as zero.

**Reproduce:**

```bash
.venv/bin/python -m scripts.deepbook_normal_activity_scan \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T073935.092996Z-6ca41203/tape_sha-20260819T073935.092996Z-6ca41203.jsonl \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T075057.972093Z-286d5105/tape_sha-20260819T075057.972093Z-286d5105.jsonl \
  --output artifacts/deepbook-normal-activity/deepbook_normal_activity_2026-08-19.json \
  --nested-rows-output artifacts/deepbook-normal-activity/deepbook_nested_rows_2026-08-19.jsonl \
  --association-rows-output artifacts/deepbook-normal-activity/deepbook_association_rows_2026-08-19.jsonl
```

## 2.2 Object categories (working contract §7.1)

- **Deterministically derived:** every region total, imbalance, average order size, book-shape
  measure and difference. These are arithmetic on the displayed book.
- **Estimated:** every fit, out-of-sample R², standard error, confidence interval, test statistic
  and required-sample figure.
- **Proxy:** average order size (displayed quantity ÷ displayed order count). It is the one genuine
  partial recovery of order granularity available, and it is labelled a proxy everywhere.
- **Unidentified:** per-order identity, per-order lifetime, true message-level order flow. The feed
  carries no order IDs and no message stream. No proxy is substituted for these.

## 2.3 Features — 584 per depth200 publication

**Regions, by level index:** `best` (level 1), `l1_5`, `l1_20`, `l21_50`, `l51_200`. The first
three are cumulative, matching the brief's "best quote only; top 5; top 20"; the last two are
disjoint slices. The cumulative overlap is collinear by construction and is handled by the ridge
penalty rather than hidden.

**Regions, by price distance from the same-side best quote:** within ₹5, ₹5–20, ₹20–50, beyond ₹50.
Reported as a full parallel parameterisation because level index and price distance are not the
same partition — on this tape the first ten levels sit inside ₹5, not the first twenty.

**Per region, per side:** total displayed quantity; total displayed order count; occupied level
count; average order size (the proxy).
**Per region:** quantity imbalance, order-count imbalance and average-order-size imbalance, each as
`(bid − ask) / (bid + ask)`.

**Book shape, per region per side:** the quantity-weighted mean distance of displayed size from the
mid-price, and the ordinary-least-squares slope of level quantity on distance from the touch (how
steeply size builds as you go deeper).

> **Shape is computed per region, never once over the whole ladder.** A single whole-book shape
> number consumes levels 51–200 and would then sit inside the `best_quote_only` rung, leaking
> exactly the information the central test measures. `test_book_shape_is_computed_per_region_so_the_nested_ladder_cannot_leak`
> pins this.

**Flow.** Every level feature above is differenced at three look-backs: since the immediately
preceding publication, and over 1-second and 5-second look-backs resolved as-of — the last
publication at or before the look-back instant, never interpolated forward. Where no earlier
reference exists, the difference is zero *and* a companion `__available` flag is zero, so an
unavailable difference is never mistaken for a measured one.

## 2.4 Target

Depth20 best-bid/best-ask mid-price return in futures ticks (₹0.05) at **1, 5, 10, 30 and 60
seconds**. The last observation at or before each endpoint; no forward interpolation.

An endpoint past the end of depth20 coverage is **refused**, not resolved backwards. This is the
right-edge defect found on these exact tapes and recorded in
`docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md` §6.1: without the guard, an endpoint past the
final observation silently resolves back to it and fabricates a zero return over a negative
realised horizon.

Three legs are carried separately and never merged:

- **future** — anchor to `anchor + h`. The thing being predicted.
- **past mirror** — `anchor − h` to anchor. A negative control.
- **contemporaneous** — the depth20 interval that *straddles* the depth200 publication. It uses
  information from after the anchor, deliberately; its only job is to expose a feature that is
  reacting rather than leading. It is never a target the model is scored on and never a predictor.

### Unconditional response — the drift, made visible first

| Horizon | n | Mean (ticks) | SD (ticks) | P(≥ +1 tick) | P(≤ −1 tick) |
|---:|---:|---:|---:|---:|---:|
| 1 s | 5,471 | −0.270 | 14.77 | 0.152 | 0.188 |
| 5 s | 5,437 | −1.613 | 28.22 | 0.320 | 0.390 |
| 10 s | 5,395 | −3.265 | 34.54 | 0.374 | 0.480 |
| 30 s | 5,227 | −10.745 | 47.23 | 0.376 | 0.576 |
| 60 s | 4,976 | −17.114 | 54.72 | 0.361 | 0.607 |

The mean is negative at every horizon and grows steadily in magnitude. The distribution is wide
relative to it. This is a one-directional session inside high variance, and it is the single fact
that governs everything else.

## 2.5 Out-of-sample design

Each tape is split chronologically at 70% of its observations, an embargo band is discarded from
**both** sides, and the parts are pooled. Splitting the pool once would put an entire tape on one
side of the boundary and confound the split with the four-minute recording gap between captures.

| | |
|---|---:|
| Train | 3,829 |
| Embargoed and discarded | 1,002 |
| Test | 640 |
| Embargo | 120 s |

The embargo must exceed the longest horizon or a training observation's 60-second target window
would still be open when the test set begins. 120 s is double the minimum. The design was fixed
before any result was inspected and was not adjusted afterwards; the cost is a small test set, and
that cost is the honest price of the guarantee. `test_the_embargo_must_exceed_the_longest_target_horizon`
refuses a shorter one.

**Penalty selection never touches the test set.** The ridge penalty is chosen on a held-out tail of
the *training* set only. Using the test set would make the reported out-of-sample number an
in-sample number wearing a disguise.

## 2.6 The central test — nested region comparison

`best_quote_only → top_5 → top_20 → plus_21_50 → plus_51_200`, each rung the previous rung's
features plus one region's, so each increment is exactly what that region adds once the nearer book
is accounted for.

Two columns are reported for every rung: `out_of_sample_r2_vs_training_mean` (drift-adjusted, the
one to read) and `out_of_sample_r2_vs_zero` (raw, scored on the unadjusted scale against a no-change
forecast).

| Horizon | test n | best only | top 5 | top 20 | +21–50 | +51–200 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 s | 640 | +0.007 | +0.112 | +0.114 | +0.111 | +0.106 |
| 5 s | 606 | −0.002 | +0.091 | −0.027 | +0.104 | +0.126 |
| 10 s | 564 | +0.020 | +0.087 | +0.158 | +0.148 | +0.164 |
| 30 s | 396 | +0.014 | +0.120 | +0.094 | +0.081 | +0.081 |
| 60 s | 145 | −0.012 | +0.035 | +0.036 | +0.011 | +0.050 |

Drift-adjusted. The raw column for the same cells runs +0.008 / +0.112 / +0.114 / +0.112 / +0.107
at 1 s and +0.364 / +0.394 / +0.395 / +0.378 / +0.403 at 60 s — an eightfold inflation at 60 s,
entirely from the session's fall.

**Step-level significance rule.** A step is called distinguishable from zero only when **all three**
dependence-aware estimators agree in sign and all three exceed 1.96 in absolute value: the
Newey-West statistic on the paired squared-error differential, a within-tape stationary block
bootstrap, and a non-overlapping block estimate. This is deliberately conservative; every
individual number is reported so a looser rule can be applied and its cost seen. The naive standard
error is emitted alongside with `naive_inference_valid: false`.

### The deep steps, level ladder — the answer to the central question

| Horizon | Adds | ΔR² | Newey-West *t* | Bootstrap *t* | Non-overlap *t* | Blocks | Distinguishable? |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 s | 21–50 | −0.0025 | −0.18 | −0.19 | −0.09 | 152 | No |
| 1 s | 51–200 | −0.0053 | −0.67 | −0.69 | −0.68 | 152 | No |
| 5 s | 21–50 | +0.1315 | +1.31 | +1.42 | +1.25 | 30 | No |
| 5 s | 51–200 | +0.0217 | +1.42 | +1.48 | +1.29 | 30 | No |
| 10 s | 21–50 | −0.0093 | −0.45 | −0.51 | −0.48 | 14 | No |
| 10 s | 51–200 | +0.0158 | +1.31 | +1.41 | +1.25 | 14 | No |
| 30 s | 21–50 | −0.0125 | −0.36 | −0.68 | −0.46 | 4 | No |
| 30 s | 51–200 | +0.0003 | +0.01 | +0.02 | −0.38 | 4 | No |
| 60 s | 21–50 | −0.0257 | −0.43 | −1.93 | −0.22 | 2 | No |
| 60 s | 51–200 | +0.0389 | +1.03 | +5.02 | +0.51 | 2 | No |

**Nothing beyond level 20 clears the bar at any horizon.** Half the steps are negative.

The 60-second `+51–200` row is the clearest illustration of why the three-estimator rule exists:
the block bootstrap reports 5.02 on **two** non-overlapping blocks, while the non-overlapping block
estimate — which cannot manufacture precision it does not have — reports 0.51. Trusting any single
estimator there would have produced a headline.

### The deep steps, price-distance ladder

| Horizon | Adds | ΔR² | NW *t* | BB *t* | NOB *t* | Blocks | Distinguishable? |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 s | ₹20–50 | +0.0354 | +3.54 | +3.77 | +3.14 | 152 | **Yes** |
| 1 s | beyond ₹50 | +0.0139 | +0.79 | +0.79 | +0.85 | 152 | No |
| 5 s | ₹20–50 | +0.0908 | +0.58 | +0.61 | +0.74 | 30 | No |
| 5 s | beyond ₹50 | +0.0382 | +1.52 | +1.70 | +1.21 | 30 | No |
| 10 s | ₹20–50 | −0.3316 | −1.03 | −1.25 | −1.16 | 14 | No |
| 10 s | beyond ₹50 | −0.1222 | −1.56 | −1.84 | −1.53 | 14 | No |
| 30 s | ₹20–50 | +0.0905 | +0.79 | +0.91 | +0.22 | 4 | No |
| 30 s | beyond ₹50 | +0.0990 | +3.41 | +4.45 | +2.76 | 4 | **Yes** |
| 60 s | ₹20–50 | −0.0680 | −0.29 | −1.08 | −0.14 | 2 | No |
| 60 s | beyond ₹50 | +0.0229 | +0.65 | +1.24 | +0.69 | 2 | No |

Two fire. The ₹20–50 band at 1 s has 152 blocks behind it and is the more credible of the two; the
beyond-₹50 result at 30 s has four. Both sit inside a search where the placebos fire at 15–45%, and
neither is reproduced in the level-index parameterisation of the same book. They are recorded, they
are not believed, and they are exactly the kind of row that a filtered table would have promoted
into a finding.

## 2.7 Negative controls

| Control | What it does | Fired |
|---|---|---:|
| Real forward test, level ladder | — | 2 / 20 |
| Real forward test, distance ladder | — | 2 / 15 |
| **Past-return mirror** | Target replaced by the return over the mirror-image window that closed *before* the observation | **8 / 20** |
| Contemporaneous leg | Target replaced by the move across the interval straddling the observation | 9 / 20 |
| Time shuffle | Each observation's responses re-attached to another instant in the same 30-minute bucket | 3 / 20 |
| Side-label mirror | Bid and ask labels swapped on a deterministic half of the sample | 1 / 20 |

The past-return mirror firing at 40% against a real rate of 10–13% is the finding. The apparatus
predicts what already happened better than what is about to happen. Under a correct null both
should sit near the conservative rule's rate, which is well below 5%.

The contemporaneous leg firing at 45% says the same thing from the other side: a large part of what
the features track is the move happening at the moment of observation, which is not available to
forecast with.

The time shuffle at 15% and the side mirror at 5% are the two that behave.

### Univariate association tables

Every feature against every horizon, on non-overlapping time blocks with an ordinary-least-squares
slope. 2,915 rows per leg, 8,745 in total, complete — nothing ranked or filtered away.

| Leg | Rows with a statistic | \|t\| > 1.96 | Share | Null |
|---|---:|---:|---:|---:|
| Future | 2,675 | 784 | 29.3% | 5% |
| **Past mirror** | 2,664 | 859 | **32.2%** | 5% |
| Contemporaneous | 2,675 | 1,045 | 39.1% | 5% |

The past beats the future here too. On a grid of this size with placebos firing at 30%, no single
large statistic in the future column is evidence of anything, which is precisely why the complete
table is emitted rather than its top rows.

## 2.8 Yardstick

A gradient-boosted depth-one stump ensemble (200 rounds, learning rate 0.05, split thresholds fixed
on a training-set quantile grid before boosting starts). **Yardstick only, never a strategy
candidate** — `D11(c)` and the `SIG-18` logic: a black-box model measures how much structure exists
in principle; anything promoted to a tradeable rule must be sparse and interpretable.

| Horizon | Yardstick OOS R² | Full linear OOS R² |
|---:|---:|---:|
| 1 s | +0.103 | +0.106 |
| 5 s | +0.077 | +0.126 |
| 10 s | +0.173 | +0.164 |
| 30 s | −0.129 | +0.081 |
| 60 s | +0.196 | +0.050 |

It ties the linear fits at short horizons and is worse at two of five. There is no large pool of
non-linear structure the linear models are missing. Its 60-second number rests on 145 test points
and should not be read as anything.

## 2.9 What sample would settle it

From the observed block-to-block variability of the squared-error differential, the number of
non-overlapping blocks needed for a one-percentage-point out-of-sample improvement to clear a
two-sided 1.96 bar, converted to trading sessions of recorded tape at this scan's test share
(11.7%).

| Horizon | Adds 21–50 | Adds 51–200 |
|---:|---:|---:|
| 1 s | 0.4 sessions | 0.1 sessions |
| 5 s | 19.4 sessions | 0.7 sessions |
| 10 s | 1.4 sessions | 0.5 sessions |
| 30 s | 2.6 sessions | 3.4 sessions |
| 60 s | 107 sessions | 48 sessions |

**One full trading session settles the 1-second and 10-second questions.** The 5-second `21–50`
cell and both 60-second cells are expensive and are dominated by how few independent blocks a long
horizon leaves in 22 minutes. These are planning figures estimated from one mid-afternoon window of
one contract; a calmer or more volatile session would move them.

## 2.10 Defects found while running this scan

Four. The first three each produced a check that **could not have failed whatever the data said** —
the same shape as the manufactured null found in the SIG-21 exploratory scan, where a placebo was
differenced against a bijection of itself.

| # | Defect | Fix | Regression test |
|---|---|---|---|
| 1 | Raw and drift-adjusted R² were the same number, because after adjustment the training mean is zero and both benchmarks coincide | Raw is scored on the unadjusted scale against zero | `test_the_raw_and_drift_adjusted_columns_are_not_the_same_number` |
| 2 | The contemporaneous leg was identically 0.0 for every observation — both ends resolved to the same publication under the as-of rule | It now spans the depth20 interval straddling the depth200 publication | `test_the_contemporaneous_leg_is_not_forced_to_zero_by_construction` |
| 3 | The side-label control mirrored every observation, which is an exact symmetry a refit linear model relearns; it reproduced the real result to the last decimal | It mirrors a deterministic half of the sample, which is not a symmetry | `test_side_label_control_is_not_a_symmetry_the_model_can_relearn` |
| 4 | The ridge penalty selected the largest value in its grid in every rung at every horizon — a censored search, not a choice | The grid was extended from 1e3 to 1e7 until selection stopped hitting the boundary | selection now lands interior; `test_the_ridge_path_agrees_with_fitting_each_penalty_separately` |

Defect 1 is the one that changed a headline: without it the drift trap would have been invisible in
the very table built to expose it.

## 2.11 Artifacts

| Artifact | Contents |
|---|---|
| `artifacts/deepbook-normal-activity/deepbook_normal_activity_2026-08-19.json` | complete scan: protocol metadata with both tape SHA-256s, per-tape drop reasons, the split, unconditional responses, both nested ladders at five horizons, four negative controls, three complete association tables, the yardstick and the required-sample figures |
| `artifacts/deepbook-normal-activity/deepbook_nested_rows_2026-08-19.jsonl` | one flattened row per ladder rung and per step, real and control families, complete |
| `artifacts/deepbook-normal-activity/deepbook_association_rows_2026-08-19.jsonl` | 8,745 rows — every feature × every horizon × future/past/contemporaneous, complete |
| `scripts/deepbook_normal_activity_scan.py` | reproducible entry point; refuses confirmatory framings before opening a tape and refuses any tape outside the two pinned SHA-256s |
| `src/shaurya/signals/deep_book_normal_activity.py` | scan module |
| `tests/test_deepbook_normal_activity.py` | 58 tests |

`artifacts/` is gitignored by repository policy, as it is for `DAT-20` and the SIG-21 scans, so
these files exist locally and are regenerated deterministically by the command in section 2.1.
Every number in this document comes from them.

## 2.12 Verification

- **Correctness:** 58 new tests; full suite **412 passed**; `ruff check .` clean; strict `mypy`
  clean on the project configuration.
- **Completeness:** every item in the brief is produced — both region parameterisations, quantity
  and order-count imbalances, average order size, book shape, flow at three look-backs, five
  horizons, raw and drift-adjusted, Newey-West and block bootstrap and non-overlapping block
  inference, all four negative controls, the nested comparison with an embargoed split, the
  yardstick, and the required-sample statement. Nothing was scoped out.
- **Evidence level:** **Dry-run verified (Level 3)** for the machinery. **The empirical content is
  exploratory and underpowered and is not evidence at any level about whether the futures price can
  be forecast.**
- **Protocol audit:** `docs/sig-claims/H-SIG21.md` unchanged; no post-registration tape opened;
  every artifact carries `confirmatory_eligible: false` and `is_part_of_h_sig21: false`; every
  table emitted complete.

---

## Erratum — session-equivalent conversions (added 2026-08-19)

NSE equity derivatives close at 15:40 from 2026-08-03, so the current session length is 23,100
seconds rather than 22,500. Every session-equivalent figure above that was converted with the old
constant should be multiplied by `22,500 / 23,100` = **0.974026**. Required seconds, model fits,
test results, tape hashes, and the exploratory verdict do not change. This additive note preserves
the original executed report while stating the corrected conversion.
