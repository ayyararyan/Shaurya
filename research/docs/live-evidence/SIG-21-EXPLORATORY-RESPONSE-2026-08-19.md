# SIG-21 exploratory future mid-price response scan — `X-SIG21-DAT20-01` (2026-08-19)

**Exploratory scan ID:** `X-SIG21-DAT20-01` · **`confirmatory_eligible`: false** ·
**Protocol:** `H-SIG21` (unchanged, untouched) · **Threshold provenance:** `in_sample_exploratory`

**Object categories (working contract §7.1).** Counts, episode structure and selectivity curves are
**deterministically derived**. Every mean, correlation, standard error, confidence interval,
p-value and required-sample figure is **estimated**. The relocation families remain **proxies**.
The `VOL-04` regime stratum is **unidentified** here. Nothing is scenario-based except where the
text says so.

---

## 0. Why this was allowed to happen at all

Aryan directed this work by voice on 2026-08-19 at about 16:42 IST: *"you did not try any
correlation with the future mid price and that does not actually tell us anything… what we needed
to do was actually see the future mid price correlations and accordingly try and see what is some
model we can come out with because without that it's all noise."*

That instruction does not break the `H-SIG21` registration, for one specific reason, and this
reason is repeated in every artifact this scan writes:

> Both `DAT-20` tapes were captured at 13:09 and 13:20 IST on 2026-08-19. The registering commit
> `f2cf6501` was pushed at **15:00:42 IST**, about an hour and fifty minutes later. `H-SIG21` §1.5
> admits only tape collected *after* that commit into the first outcome sample, and §1.2 already
> excludes these tapes' post-event price paths from SIG-21 inference. They were therefore
> **already permanently ineligible** for Confirmed/Falsified status before this scan existed.
> Looking at them now costs nothing that was not already spent.

**What this is:** a declared exploratory scan on tape that can never be confirmatory.

**What this is not, and must never be presented as:** a SIG-21 result; evidence that deep-book
anomalies forecast price; a Confirmed/Falsified verdict; or grounds to modify the immutable
384-cell registration. `docs/sig-claims/H-SIG21.md` is byte-for-byte unchanged.

The refusals are in code, not only in prose. The entry point refuses a confirmatory or economic
framing before it opens a file, refuses any tape whose SHA-256 is not one of the two pinned
pre-registration captures, refuses any threshold claiming a provenance other than
`in_sample_exploratory`, and refuses to emit anything less than the complete 384-cell family.

---

## 1. Plain English first

### 1.1 The "2 episodes" number was mostly an artefact of how it was computed — but the honest replacement is still tiny

Aryan's objection was that two usable episodes out of 40,724 candidates cannot be the data
speaking. He is right, and the scan shows exactly where that number came from.

The 2 came from **pooling all 32 construction cells' candidates into one timeline with no
threshold applied at all**. Under that reading the far book is publishing continuously, every
burst's 11-second window touches its neighbour's, and each contiguous tape collapses to one
episode. The number was counting tapes.

Three things change it:

- **Applying the registered threshold.** Pooled, the risk set stays stuck at 2 episodes all the
  way from the 50th percentile to the **99.5th** — the lower registered threshold does not rescue
  it. It only breaks free between 99.6% and 99.7%, peaking at **39 episodes at the 99.9th
  percentile**, one third of the 118-episode capacity of 22 minutes of tape.
- **Estimating cell by cell, which is what the registered family actually does.** A single
  construction cell's anomalies are far sparser than the union of all 32. Summed across cells the
  primary risk set is **321 episodes at 99.5%** and **129 at 99.9%** — median 5 and 2 per cell.
  Not 2, but not much.
- **Not binding the episode window to the family maximum.** This is the largest single effect.
  At the registered 99.5% threshold a `Z = 0.5 s, h2 = 1 s` cell needs only 1.5 s of exclusivity
  and gets **260 episodes**; the same events under the 11-second family maximum give **2**. A
  factor of 130 between two cells of the same registered family, caused entirely by the convention
  that binds every cell to the largest endpoint in the family.

**Verdict on Aryan's question.** The 11-second rule is the binding constraint at every selectivity
we can reach on this tape, and it binds hardest at the low-selectivity end. The registered 99.5%
threshold does *not* produce a usable pooled risk set; 99.9% produces one that is usable in
arithmetic and still far too small for the registered power gates. And selectivity is not
monotonically helpful: summed over cells, the primary risk set **peaks at the 95th percentile
(608 episodes) and falls to 129 by the 99.9th**. Both registered thresholds sit on the falling
side of the curve.

### 1.2 What the mid-price relationship actually looks like

Attaching the registered response convention to every burst, the unconditional picture is that
this was a **falling, volatile 22 minutes**. The mid-price mean return is negative at every
horizon (−0.33 ticks at 1 s, −3.29 ticks at 10 s), a down-move is more likely than an up-move at
every horizon (49.6% versus 40.4% at 10 s), and the standard deviation is enormous relative to the
effect sizes the registration cares about: **14.6 ticks at a 1-second horizon and 34.9 ticks at
10 seconds**, against a registered detection target of 0.25 ticks.

That single fact — a session-wide drift sitting inside a very wide distribution — explains almost
everything the family arms show, and it is why the negative controls matter so much.

### 1.3 What survives the negative controls: almost nothing, with one exception

This is the most valuable thing in the scan, and it is a warning.

Across the complete 384-cell family, the raw event-response arms produce a nominal |t| above 1.96
in **157 of the 278 cells that have a t-statistic at all**. That looks like a result. It is not:

| Negative control | Cells with nominal \|t\| > 1.96 | Expected under the null |
|---|---:|---:|
| Real family (all-event arm) | 157 / 278 with a t | 5% |
| Within-bucket timestamp shuffle | **159 / 384 (41.4%)** | 5% |
| Side-label permutation | **149 / 384 (38.8%)** | 5% |
| Future events "predicting" past returns | **121 / 384 (31.5%)** | 5% |
| Near-boundary (rim) churn events | 40 / 384 (10.4%) | 5% |
| **Matched quiet episodes (pure placebo)** | **0 / 384 (0.0%)** | 5% |

Re-timing every event to a random other instant in the same 30-minute bucket destroys any
event-to-response link — and produces *more* nominal significance than the real family. Permuting
the side labels barely dents it. Asking the events to predict the return over the window that
already closed before they happened still fires in nearly a third of cells.

**The apparatus is measuring the session's drift, not the events.** Any raw-level statistic over
22 minutes of a one-directional market will look significant.

The one control that does *not* fire is the pure placebo: quiet instants differenced against
matched quiet instants, 0 of 384 cells, max |t| = 1.00. That is the tell. **Differencing kills
it** — which is precisely why `H-SIG21` §6 makes the event-minus-matched-control difference the
primary estimand rather than the raw response. The registration got this right; this tape is a
demonstration of why.

### 1.4 The registered control design is infeasible at the lower registered threshold

At the 99.5% threshold, 1,580 anomaly bursts are retained across 22 minutes. Every one of the
2,354 candidate control instants lies within 11 seconds of one of them. **Zero quiet controls
exist.** The registered primary estimand is therefore *undefined* for all 192 cells at that
threshold — not weakly estimated, undefined. At 99.9% the retained set falls to 217 bursts and
313 quiet instants survive (13.3%), so 159 events can be matched.

Even those matches are weaker than registered: no `VOL-04` regime label exists for this
instrument-session and fitting one on 22 minutes would be within-sample, so matching is on three
of the four registered strata.

### 1.5 The one pattern worth a new hypothesis

Set the 384-cell family aside — it is too thin to say anything. The correlation analysis, which
uses all 40,724 candidates and does not depend on the threshold layer, shows one coherent pattern.

For each predictor we report three columns at the non-overlapping 11-second block level: the
association with the **future** return, with the mirror-image **past** return, and with the
**contemporaneous** reaction leg. A genuinely forward-looking feature should show up in the first
and not the other two.

| Predictor (pooled, Z = 0.5 s, h2 = 10 s) | future *t* | past *t* | contemporaneous *t* | reading |
|---|---:|---:|---:|---|
| **`burst_side_imbalance`** | **−4.46** | −0.65 | −0.16 | forward only |
| `burst_signed_magnitude` | −2.54 | −0.39 | −1.68 | partly reaction |
| `signed_magnitude` | −2.55 | 1.14 | −0.51 | forward-leaning |
| `distance_from_touch_rupees` | 2.52 | −0.18 | −1.83 | mixed |
| `order_count_change` | −1.58 | −0.05 | −1.12 | reaction |
| `magnitude` (unsigned) | −0.41 | 1.85 | 1.48 | drift / reaction |
| `burst_total_magnitude` | −1.26 | 1.14 | −1.19 | drift / reaction |
| `burst_candidate_count` | −0.47 | 0.28 | −1.37 | nothing |

`burst_side_imbalance` — the bid-minus-ask share of far-book candidates inside one publication
burst — is the only predictor whose association is concentrated in the forward window and absent
from both placebos. It strengthens monotonically with horizon (*t* = −1.03, −3.23, −4.46 at 1, 5
and 10 seconds) and does so for both registered `Z` values. Its sign is **negative**: bursts
skewed toward the *bid* side precede *lower* prices.

Unsigned magnitude — the thing the registered detector actually thresholds on — carries nothing,
and what little it appears to carry shows up more strongly in the past-return placebo.

**How much weight this can bear: very little.** Across all 1,548 correlation rows the block-level
estimator fires at 26.6% for the future return, 20.0% for the past-return placebo and 22.9% for
the contemporaneous leg. A false-positive rate of one in five means a single |t| of 4.46 inside a
1,548-row grid is not, by itself, evidence of anything. What is worth something is the *shape* —
monotone in horizon, stable across `Z`, absent from both placebos, and confined to the one feature
family that carries a side. That is a hypothesis, and §9 says a hypothesis needs its own
registration and its own later tape. Section 8 below writes it as a proposal.

### 1.6 Nothing here is powered, and one gate may be unreachable by design

Not a single cell in any of the three arms meets the registered 0.25-tick mean MDE gate on a
credible sample size. Between 85 and 115 cells per arm *appear* to meet it, but the median sample
size among them is **1 observation**: their Bartlett long-run variance collapsed toward zero. On
credible samples the count is **0 out of 384 in every arm**.

More consequentially, with the response volatility observed here the 0.25-tick gate needs roughly
**26,000 effective episodes at a 1-second horizon and 149,000 at 10 seconds** — per cell, before
any multiplicity allowance. The entire registered 20-session evaluation sample has an arithmetic
ceiling of **40,900 non-overlapping 11-second episodes across all 384 cells and all strata
combined**. Split evenly that is 106 per cell, so the requirement is **239× to 1,402× the
available per-cell share**. Even pooling the whole evaluation sample into one cell would miss the
gate at 5 and 10 seconds.

The 5-percentage-point move-probability gate is a different story: it needs 457–742 effective
episodes per cell, which is within reach for a small number of well-populated cells.

**This is a finding about the registered design, not about this tape**, and it is the single most
important thing for Aryan to decide on. Section 9 puts it into change-control format.

**Action needed from Aryan:** one decision, on the §14 proposal in section 9 — whether to keep the
primary risk set as registered, or adopt one of the three alternatives. Nothing else here requires
a decision, and nothing here has been implemented against the registration.

---

## 2. Protocol status, source and integrity

| Field | Value |
|---|---|
| Exploratory scan ID | `X-SIG21-DAT20-01` |
| `confirmatory_eligible` | `false` |
| `sample_role` | `exploratory_scan_pre_registration_capture` |
| Registering commit | `f2cf65011d02882191b5cfda566c1024119964d7` |
| Registering commit pushed | 2026-08-19T15:00:42+05:30 |
| Threshold provenance | `in_sample_exploratory` (all cutoffs) |
| `H-SIG21.md` modified | no |

| Field | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `sha-20260819T073935.092996Z-6ca41203` | `sha-20260819T075057.972093Z-286d5105` |
| Tape SHA-256 | `751ee15a…955b71e0` | `c20590d6…08c82b82` |
| Instrument | `NSE:NSE_FNO:NIFTY:future:2026-08-25`, security `58072`, `NIFTY-Aug2026-FUT` | same |
| Captured (IST) | 13:09:35 | 13:20:57 |
| Manifest SHA-256 agrees | yes | yes |

Both tape hashes are pinned in `PERMITTED_TAPE_SHA256`; the scan refuses any other tape, so a
post-registration calibration capture cannot be fed to it even by accident. Coverage is 1,305.37 s
(21.76 min) of depth200 across 5,482 publications, 40,724 candidates in 5,325 bursts — identical
to the construction replay, as it must be, since the same registered detector is used unchanged.

Both tapes belong to **one calendar session**. Session-clustered inference therefore has exactly
one cluster and the two contiguous captures are used as the block-resampling units. **No
between-session variation is observable at all**, which is a hard limit on everything below.

**Reproduce:**

```bash
.venv/bin/python -m scripts.sig21_exploratory_response_scan \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T073935.092996Z-6ca41203/tape_sha-20260819T073935.092996Z-6ca41203.jsonl \
  --tape data/live-captures/dat20-nifty-three-tier/sha-20260819T075057.972093Z-286d5105/tape_sha-20260819T075057.972093Z-286d5105.jsonl \
  --output artifacts/sig21-exploratory-response/sig21_exploratory_response_2026-08-19.json \
  --family-rows-output artifacts/sig21-exploratory-response/sig21_exploratory_family_rows_2026-08-19.jsonl \
  --fine-selectivity
```

---

## 3. Task 1 — episode count against selectivity

Magnitude percentiles are computed **within sample**, within each construction cell, using the
registered scoring rule (`bisect_right(history, magnitude) / n`, crossed when that is at least the
cutoff). This is a deliberately reduced stand-in for §5's six-axis past-only baseline, which does
not exist for these tapes; it is labelled `in_sample_exploratory` everywhere and is not the
registered baseline.

### 3.1 Pooled and per-cell, at the registered 11-second window

Capacity ceiling = `floor(1,305.37 / 11)` = **118** episodes.

| Cutoff | Retained events | Retained bursts | Pooled episodes | % of ceiling | Median inter-burst gap | Per-cell episodes (sum) | Median per cell |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 50% | 28,539 | 5,168 | 2 | 1.7% | 0.201 s | 365 | 12.0 |
| 75% | 20,302 | 4,911 | 2 | 1.7% | 0.201 s | 369 | 9.5 |
| 90% | 13,578 | 3,942 | 2 | 1.7% | 0.201 s | 444 | 11.5 |
| **95%** | 6,916 | 3,172 | 2 | 1.7% | 0.203 s | **608** | **18.5** |
| 99% | 3,068 | 1,778 | 2 | 1.7% | 0.402 s | 379 | 8.0 |
| **99.5%** (registered) | 2,037 | 1,580 | **2** | 1.7% | 0.404 s | **321** | 5.0 |
| 99.6% | 1,340 | 1,121 | 4 | 3.4% | 0.675 s | 302 | 4.0 |
| 99.7% | 494 | 425 | 28 | 23.7% | 1.198 s | 228 | 4.0 |
| 99.8% | 390 | 336 | 29 | 24.6% | 1.600 s | 212 | 3.0 |
| **99.9%** (registered) | 238 | 217 | **39** | **33.1%** | 1.800 s | **129** | 2.0 |
| 99.92% | 178 | 158 | 32 | 27.1% | 1.602 s | 86 | 1.5 |
| 99.95% | 174 | 155 | 31 | 26.3% | 1.602 s | 82 | 1.0 |
| 99.98% | 140 | 124 | 31 | 26.3% | 2.400 s | 81 | 1.0 |
| 99.99% | 99 | 85 | 33 | 28.0% | 7.401 s | 79 | 1.0 |

Three readings.

**The pooled curve is flat at 2 until 99.6%.** Every cutoff from the median to the lower registered
threshold leaves the pooled risk set degenerate. This is not a threshold that fails by a little.

**Ties matter more than the nominal rate suggests.** Far-book displayed quantities are heavily
tied on round lots (65, 130, 650, 1,300…). The nominal 99.5% cutoff retains **5.0%** of candidates,
not 0.5%, and the nominal 99.9% retains 0.58%, not 0.1%. The registered rule promotes whole
magnitude values together. That is the registered rule working as written; it is reported so the
"upper 0.5% tail" language is not read literally.

**Selectivity has an interior optimum and both registered thresholds are past it.** Summed over
construction cells the primary risk set peaks at the 95th percentile and has fallen by half by the
99.9th. Beyond the peak, each additional unit of selectivity removes more risk-set support than the
separation it buys.

### 3.2 Decomposing the 11-second window into its registered `(Z, h2)` pairs

The 11 s window is `Z_max (1.0 s) + h2_max (10 s)`. §6 binds every cell to it. Cells do not need
it.

| Cutoff | Z | h2 | Window | Episodes | Ceiling | % of ceiling |
|---:|---:|---:|---:|---:|---:|---:|
| 99.5% | 0.5 | 1 | 1.5 s | **260** | 870 | 29.9% |
| 99.5% | 0.5 | 5 | 5.5 s | 7 | 236 | 3.0% |
| 99.5% | 0.5 | 10 | 10.5 s | 2 | 124 | 1.6% |
| 99.5% | 1.0 | 1 | 2.0 s | 144 | 652 | 22.1% |
| 99.5% | 1.0 | 5 | 6.0 s | 6 | 216 | 2.8% |
| 99.5% | 1.0 | 10 | **11.0 s** | **2** | 118 | 1.7% |
| 99.9% | 0.5 | 1 | 1.5 s | 118 | 870 | 13.6% |
| 99.9% | 0.5 | 5 | 5.5 s | 66 | 236 | 28.0% |
| 99.9% | 0.5 | 10 | 10.5 s | 41 | 124 | 33.1% |
| 99.9% | 1.0 | 1 | 2.0 s | 100 | 652 | 15.3% |
| 99.9% | 1.0 | 5 | 6.0 s | 65 | 216 | 30.1% |
| 99.9% | 1.0 | 10 | 11.0 s | 39 | 118 | 33.1% |

At the lower registered threshold the shortest-horizon cell has **130 times** the risk set of the
longest-horizon cell, and the registration hands both of them the longest-horizon number. This is
the single clearest lever available and it is the subject of the change proposal in section 9.

It is a diagnostic, not an alternative estimate. Nothing in the family below uses anything other
than the registered 11-second window.

---

## 4. Task 2 — the future mid-price response

### 4.1 Convention, applied exactly as registered

`Y` is the depth20 BBO midpoint return in futures ticks; `f2` is the last depth20 observation at or
before each endpoint with no forward interpolation; `Z ∈ {0.5, 1.0} s`; `h2 ∈ {1, 5, 10} s`. One
tick is ₹0.05, the NSE futures tick. Every observed depth20 best quote on these tapes lies on a
₹0.10 grid, so every midpoint lies exactly on the ₹0.05 grid and one tick is the smallest
representable move.

The contemporaneous leg (pre-event midpoint → `t + Z`) and the predictive leg (`t + Z` →
`t + Z + h2`) are carried in separate fields throughout and are never merged.

Responses are attached **per contiguous tape**. The two captures are separated by about four
minutes of no data; a window spanning that gap would silently resolve its endpoint to a stale
pre-gap observation.

**Labelling failures, all counted:** 306 `endpoint_beyond_coverage` (endpoint past the tape's last
depth20 observation — see section 6), 475 `invalid_depth20_path` (an unusable depth20 state inside
the window), 130 `invalid_depth20_asof_state`.

### 4.2 Unconditional response, every burst, no threshold

| Z | h2 | n | Predictive mean | SD | P(≥ +1 tick) | P(≤ −1 tick) | Contemporaneous mean | Mean peak in window |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | 1 | 5,282 | −0.329 | 14.61 | 0.182 | 0.228 | −0.243 | −0.385 |
| 0.5 | 5 | 5,189 | −1.679 | 28.25 | 0.349 | 0.424 | −0.246 | −1.792 |
| 0.5 | 10 | 5,067 | −3.285 | 34.86 | 0.404 | 0.496 | −0.206 | −2.252 |
| 1.0 | 1 | 5,273 | −0.308 | 14.39 | 0.182 | 0.227 | −0.348 | — |
| 1.0 | 5 | 5,175 | −1.676 | 28.14 | 0.351 | 0.424 | −0.361 | — |
| 1.0 | 10 | 5,053 | −3.294 | 34.84 | 0.407 | 0.495 | −0.287 | — |

All in ticks. The distribution is wide, slightly down-skewed, and its mean drifts steadily negative
with horizon — the session fell. **Reversion through 10 s runs the wrong way**: the mean end-point
move at 10 s (−3.29) is *larger* in magnitude than the mean in-window peak (−2.25), so the average
path continues rather than reverting. That is a drift signature, not an impact-and-decay signature.

Per-candidate figures are also emitted. They weight each burst by how many candidates it contains
and add no independent information, because every candidate in a burst shares the burst's response.

### 4.3 The complete 384-cell family, three arms side by side

All 384 cells are emitted for all three arms whether or not anything is happening in them. Each
cell carries mean, median, quantiles (p05/p25/p50/p75/p95), min, max, P(≥ +1 tick), P(≤ −1 tick),
P(no move), sign, peak response, reversion through 10 s, raw `N`, distinct bursts, HAC lag, naive
and HAC standard errors, 95% confidence interval, two effective sample sizes, and the Romano-Wolf
adjusted p-value with its step-down rank.

| Arm | What it is | Registered status |
|---|---|---|
| `primary_non_overlapping_episodes` | one value per selected non-overlapping 11 s episode, mean of its member events | §6 **primary** |
| `secondary_all_event_overlap_robust` | every retained event, HAC/Newey-West at a lag covering the 11 s overlap | §6 **supplement only** |
| `event_minus_matched_control` | the registered **estimand**, estimated by `hac_newey_west_mean_difference` | §6 primary estimand |

The secondary arm is never promoted to primary. It is reported because §6 permits it and because
the primary arm is close to empty.

| Arm | Threshold | Median N | Max N | Cells with a *t* | \|t\| > 1.96 | Min adjusted *p* | Adjusted *p* < 0.05 |
|---|---:|---:|---:|---:|---:|---:|---:|
| primary episodes | 99.5% | 5 | 39 | 169 | 105 | 0.993 | 0 |
| primary episodes | 99.9% | 2 | 39 | 108 | 77 | **0.003** | **1** |
| secondary all-event | 99.5% | 7 | 676 | 169 | 88 | 0.983 | 0 |
| secondary all-event | 99.9% | 2 | 54 | 109 | 69 | 0.058 | 0 |
| event − control | 99.5% | 0 | 0 | 0 | 0 | 1.000 | 0 |
| event − control | 99.9% | 1 | 40 | 90 | 59 | 0.580 | 0 |

Effective sample sizes are reported twice and labelled: a **deterministically derived** episode
count, and an **estimated** variance-inflation `N_eff = n · naive variance / HAC variance` capped
at `n`. They are different objects and are not interchangeable.

**The one cell that clears the Romano-Wolf bar should be read as a warning, not a result.**
`removal|ask|gt_50|q999|z1000ms|h1s` has adjusted *p* = 0.003 — on **n = 2 episodes**, with a HAC
standard error of 0.0255 ticks and a t-statistic of −387. The standard error is an artefact of two
observations, not a measurement. It is reported because §7 requires the complete family, and it is
flagged here because reporting it without this sentence would be misleading.

The bootstrap family-wide critical values tell the same story: the 95th percentile of the
bootstrap max-|t| distribution is **92** for the all-event arm and **343** for the primary episode
arm. A studentised bootstrap on cells holding two to five observations is not a usable inferential
object, and those numbers are the evidence that it is not.

### 4.4 Correlation structure (Aryan's explicit request)

Eight predictors — `magnitude`, `signed_magnitude`, `distance_from_touch_rupees`,
`order_count_change`, and burst aggregates `burst_candidate_count`, `burst_total_magnitude`,
`burst_signed_magnitude`, `burst_side_imbalance` — against the future midpoint return, for all six
`(Z, h2)` pairs, pooled and for each of the 32 construction cells. 1,548 rows, complete, nothing
filtered or ranked away.

**Sign convention (§15.3).** `signed_magnitude = magnitude × (+1 bid / −1 ask) × (+1 liquidity
arriving / −1 liquidity leaving)`. A large bid-side addition is a large positive number; a large
ask-side addition is a large negative one. This is descriptive book-pressure bookkeeping and
asserts nothing about which way price *should* move.

Two fits are reported for every row:

- **event level** — all candidates, with a **naive** standard error, marked `inference_valid:
  false`. It is shown only so the inflation is visible: naive |t| reaches 20.9 where the honest
  estimator gives 4.5.
- **non-overlapping 11-second block level** — predictors and responses averaged within
  non-overlapping blocks, with a HAC standard error. Overlap is removed by construction. **This is
  the one to read.**

The full three-column comparison (future / past-mirror placebo / contemporaneous leg) is in
section 1.5. The pooled `burst_side_imbalance` row at `Z = 0.5, h2 = 10` is
`r = −0.296, t = −4.46` forward, `t = −0.65` on the past mirror, `t = −0.16` contemporaneously.

### 4.5 Matched quiet controls and their failures

Controls are depth20 instants with the complete registered past-only covariate vector (midpoint,
spread, top-20 depth, top-20 depth-imbalance flow, 10-second past return, 60-second realised
volatility) and a complete set of response cells, selected without any access to a future
response, matched on instrument × session × 30-minute bucket × regime and then nearest by scaled
covariate distance. Quietness is judged against the union of retained anomalies at the same
threshold, within ±11 s, as §6 requires.

| Threshold | Retained anomaly bursts | Control candidates | **Quiet controls** | Matched events | Failure reasons |
|---:|---:|---:|---:|---:|---|
| 99.5% | 1,580 | 2,354 | **0** | **0** | `no_same_stratum_candidates` ×1,392, `event_covariate_history_insufficient` ×188 |
| 99.9% | 217 | 2,354 | 313 | 159 | `no_same_stratum_candidates` ×44, `event_covariate_history_insufficient` ×14 |

At 99.5% the registered primary estimand does not exist on this tape. Not "is imprecise" — does
not exist. Every instant in 22 minutes is within 11 seconds of a retained anomaly.

`top20_ofi` is implemented as the change in displayed depth imbalance across the preceding depth20
transition, `Δ(bid depth) − Δ(ask depth)`. It is a **proxy** for order-flow imbalance: the feed
carries no message stream, so a message-level OFI is **unidentified**.

The `VOL-04` regime axis is a constant placeholder (`vol04_regime_unavailable`), so matching is on
three registered strata rather than four. Every control here is weaker than the design requires.

### 4.6 Negative controls

Five, exactly as fixed in §7, each summarised over the complete 384-cell family. Results are in
section 1.3. Operationalisations:

1. **Future events predicting past returns** — the response is replaced by the return over the
   exact mirror window `[t − Z − h2, t − Z]`, refusing any window whose left edge precedes the
   tape's first depth20 observation.
2. **Within-session/time-bin timestamp shuffle** — each retained event keeps its cell but is
   re-timed to another depth200 instant from the same tape and the same 30-minute bucket.
3. **Side-label permutation** — side labels permuted across retained events.
4. **Near-boundary churn** — restricted to retained events within ₹1 of the outermost occupied
   price on their own side, the population the construction replay showed is largely the 200-level
   window's rim moving rather than interior far-book activity.
5. **Matched quiet episodes** — each quiet instant matched to its nearest *other* quiet instant by
   the §6 covariate rule and differenced.

Control 5 was wrong in a first draft of this scan and is worth recording. It paired the quiet set
against a **permutation** of itself. Differencing a set against a bijection of itself sums to zero
identically, so the placebo could never fire whatever the data did — a null manufactured by
arithmetic. It now uses nearest-neighbour matching, which is not a bijection, and
`test_quiet_episode_placebo_is_not_forced_to_zero_by_construction` locks that in.

---

## 5. Both risk sets, side by side

Reported together, never substituted:

| | Primary (registered) | Secondary (§6 supplement) |
|---|---|---|
| Unit | non-overlapping 11 s episode | retained event |
| `N_eff` reported | episode count (deterministic) + variance-inflation (estimated) | same two |
| Median N per cell, 99.5% | 5 | 7 |
| Median N per cell, 99.9% | 2 | 2 |
| Inference | block bootstrap + Romano-Wolf | HAC/Newey-West + block bootstrap + Romano-Wolf |
| Status | primary | supplement; **not** promoted |

Neither is adequate. The secondary arm's larger raw N buys nothing: its variance-inflation `N_eff`
discounts the duplicate responses that multiple candidates in one burst contribute.

---

## 6. Two defects found in the registered primitives on first contact with real tape

These modules were built and unit-tested against synthetic fixtures. This scan is their first
contact with recorded market data, and it found two things.

### 6.1 `build_depth20_response_labels` had no right-edge coverage guard — **fixed, with a regression test**

The as-of rule selects the last depth20 observation at or before each endpoint. At the right edge
of a finite tape that rule is unsafe: an endpoint past the final observation silently resolves back
to that final observation, no failure is recorded, and the label is emitted as if measured.

On these tapes, **306 cells** had an endpoint beyond depth20 coverage. Of those, **45 collapsed
both endpoints onto the same observation and reported exactly 0.0 ticks over a realised horizon
that was negative** — the window closed 0.48–0.98 s *before* it was supposed to open — and **88**
reported exactly 0.0 ticks. Those are fabricated measurements, and in a confirmatory run they
would land in the sample as genuine zero responses at the end of every session.

Fix: `coverage_end_ts_ns` is now an **optional** parameter. Supplied, any cell whose endpoint falls
past it is refused with `endpoint_beyond_coverage`. Omitted, behaviour is byte-identical to before,
so no existing caller changes and no registered semantics move silently. This scan supplies it.

Tests: `test_unguarded_labels_silently_truncate_the_horizon_at_the_tape_edge` documents the defect
so it cannot be reintroduced, `test_coverage_guard_refuses_endpoints_past_the_last_observation`
proves the guard, and `test_coverage_guard_defaults_to_the_previous_behaviour` proves the default
is unchanged.

**This is not a specification change and has not been treated as one** — §2 registers "last depth20
observation at or before each endpoint", which presumes the endpoint is covered. But the
confirmatory pipeline must pass `coverage_end_ts_ns`, and that is flagged as a required step in
`TASKS.md` rather than assumed.

### 6.2 `select_primary_non_overlapping_episodes` is the identity on `cluster_event_episodes` output

`cluster_event_episodes` merges bursts whose windows overlap into connected components, so its
output is already non-overlapping. The selection step therefore never excludes anything, and
`overlap_excluded_episodes` reads 0 by construction, not by measurement.

This is not a bug — both functions are individually correct and the composition is safe. It is
reported because a diagnostic that can only ever read zero is easy to misread as evidence that no
overlap exclusion was needed. No change was made.

---

## 7. Task 3 — honest power and interpretation

### 7.1 What 22 minutes can and cannot support

**Can support:** the shape of the construction-to-episode relationship; the arithmetic of the
episode window; the observation that the registered control design is infeasible at 99.5% on a
continuously publishing book; an estimate of the unconditional response volatility good enough for
planning; and a demonstration that the negative controls fire at 20–41%.

**Cannot support:** any statement about whether deep-book anomalies forecast price. One contract,
one calendar session, one mid-morning window (13:09–13:31 IST), essentially one 30-minute bucket,
one volatility regime, one price direction, and **zero between-session variation**. There is no
open, no close, no lunch lull, no regime change, no second contract, and no way to distinguish a
property of the market from a property of that Wednesday afternoon.

### 7.2 Distance to the registered gates

`H-SIG21` §8: MDE ≤ **0.25 tick** for the mean response and ≤ **5 percentage points** for the
probability of a ≥1-tick move.

**Realised precision, per arm, across the 384 cells:**

| Arm | Median CI half-width | Ratio to 0.25 gate | Cells appearing to meet the gate | …on ≥ 30 observations |
|---|---:|---:|---:|---:|
| primary episodes | 2.75 ticks | 11× | 115 | **0** |
| secondary all-event | 3.87 ticks | 15× | 111 | **0** |
| event − control | 0.61 ticks | 2× | 85 | **0** |

The median sample size among the cells that *appear* to meet the gate is **1**. Their intervals are
narrow because a Bartlett long-run variance collapses toward zero on a handful of points, not
because anything was measured precisely. On credible samples, **no cell in any arm meets the mean
gate**.

**Required effective sample size**, from the observed response volatility, for the event-minus-
control contrast the registration specifies (`√2 · crit · σ / MDE`)²:

| Z | h2 | σ (ticks) | Need for 0.25-tick mean gate | Need for 5 pp probability gate | Registered 20-session ceiling | Shortfall vs ceiling | Shortfall vs per-cell share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | 1 | 14.61 | 26,229 | 457 | 40,900 | 0.6× | **246×** |
| 0.5 | 5 | 28.25 | 98,108 | 698 | 40,900 | 2.4× | **921×** |
| 0.5 | 10 | 34.86 | 149,347 | 740 | 40,900 | 3.7× | **1,402×** |
| 1.0 | 1 | 14.39 | 25,462 | 458 | 40,900 | 0.6× | **239×** |
| 1.0 | 5 | 28.14 | 97,314 | 700 | 40,900 | 2.4× | **914×** |
| 1.0 | 10 | 34.84 | 149,235 | 742 | 40,900 | 3.6× | **1,401×** |

The ceiling column is `floor(22,500 / 11) × 20 = 40,900` episodes for the **entire** evaluation
sample across **all** 384 cells and all strata — comparing one cell's requirement against it is
generous to the design, not harsh. The last column divides it evenly across the family.

At the bootstrap family-wide critical value of 92 rather than a per-cell 1.96, the requirement
rises to 56 million to 329 million episodes. That number is not credible as a target; it is
credible as evidence that a studentised bootstrap over 384 cells holding two observations each has
broken down.

σ here is a within-sample estimate from 22 mid-morning minutes of one contract. A calmer window
would lower it; the open or a news event would raise it. It is a planning figure, not a constant.

### 7.3 Plainly

**Nothing in this scan is powered.** Not one cell, in any arm, at either threshold, under any
critical value. The correct summary of the 384-cell family is *Inconclusive* in the §9 sense — and
even that word is too strong, because the tape was never eligible for a verdict.

---

## 8. Task 4 — a candidate model, as a proposal requiring its own pre-registration

**Status: PROPOSAL. Not a fitted claim. Not a result.** Under `H-SIG21` §9 anything selected from
a first sample needs a new `H-SIG21C-*` ID, committed before new tape is collected, and confirmed
on that later tape. This section is the input to writing that registration; it is not the
registration and nothing here may be quoted as evidence.

### 8.1 What the scan actually points at

Not the registered object. The registered family thresholds **unsigned magnitude** of **single
atomic events**, and unsigned magnitude is the one predictor family that carries nothing here —
what little it shows appears more strongly in the past-return placebo. The thing with a forward-
only asymmetry is a different object: the **side composition of a whole publication burst**.

### 8.2 Proposed specification

**Target.** `Y = ` depth20 BBO midpoint return in futures ticks over `[t + Z, t + Z + h]`, the
registered convention unchanged, with the coverage guard of section 6.1 mandatory.

**Horizon.** `h = 5 s` and `h = 10 s` primary; `h = 1 s` reported. `Z ∈ {0.5, 1.0} s`. The
association strengthens monotonically with horizon in this scan, which is the opposite of what a
microstructure-noise artefact usually does and is the main reason the pattern is worth a look.

**Unit of observation.** The **publication burst** (one depth200 receive timestamp), not the atomic
candidate. Candidates within a burst share a response, so the burst is the smallest unit carrying
independent information.

**Features, in order of what the scan supports:**

1. `burst_side_imbalance = (n_bid − n_ask) / (n_bid + n_ask)` over far-book candidates in the
   burst. The primary feature and the only one clean on both placebos.
2. `burst_signed_magnitude`, quantity-weighted. Weaker, and contaminated by a contemporaneous
   reaction (contemporaneous |t| exceeds forward |t|), so it enters only as a control.
3. `distance_from_touch_rupees`, burst-mean. Weak but placebo-clean; plausibly a proxy for how far
   the book is willing to post.
4. Registered near-book controls: spread, top-20 depth, the depth-imbalance flow proxy, past
   return, realised volatility — all past-only, entered as controls so the far-book term is
   incremental to the near book, which is the actual `H-SIG21` question.

**Functional form.** Deliberately linear:

```
Y_{t,Z,h} = α + β · burst_side_imbalance_t + γ' · near_book_controls_t + δ' · far_book_controls_t + ε
```

No interactions, no non-linearity, no feature selection. With one clean feature and no power,
anything richer is curve-fitting.

**Estimator.** OLS on non-overlapping `Z + h` blocks — which removes the overlap by construction
rather than correcting for it — with HAC/Newey-West standard errors clustered by session, and a
stationary block bootstrap for the interval. Report the naive standard error alongside so the
inflation stays visible.

**Sign to be registered in advance.** Negative: bid-skewed far-book bursts precede lower prices.
This must be fixed in the registration before the confirmation tape is collected, precisely because
it is the sign this exploratory scan happened to see.

### 8.3 Identification threats, named

- **Reactive posting.** Far-book liquidity may appear on the side the price is moving *toward*.
  The past-return and contemporaneous placebos argue against pure reactivity here (both are flat),
  but the contemporaneous leg only covers `[pre-event, t + Z]`; a reaction inside the final
  half-second before the event would evade both. **A shorter reaction leg is needed to close this.**
- **One direction of travel.** The whole sample fell. A feature keyed on side composition can look
  predictive in a one-directional session and vanish in a two-sided one. This is the largest threat
  and only new tape can settle it.
- **Window geometry.** The construction replay showed 41.4% of candidates sit within ₹1 of the
  200-level window's rim, and the rim is heavily side-asymmetric (76.9% of ask removals). Side
  imbalance may partly measure which side's rim is moving. **The confirmation must report the
  feature split by rim proximity**, which is a reporting split, not a new family cell.
- **Multiplicity.** This feature was found by looking at 1,548 correlation rows where placebos fire
  at 20%. Its selection is not evidence.
- **`VOL-04` absent.** Regime is unidentified here, so no regime stability statement is possible.

### 8.4 Falsification tests that would kill it

Registered in advance, each with a stated kill condition:

1. **Sign flips or loses significance on a two-sided session.** Kill.
2. **The past-return mirror placebo reaches half the forward |t|.** Kill — it is drift.
3. **A reaction leg shortened to 100 ms explains as much as the forward window.** Kill — it is
   reactive posting.
4. **The effect is confined to rim-proximate bursts.** Kill — it is window geometry.
5. **The coefficient is not incremental to the near-book controls.** Kill — SIG-21 asks for
   incremental information, and a far-book feature that only restates top-20 imbalance answers a
   different question.
6. **Adequacy.** The move-probability gate (5 pp, ~700 effective blocks per cell) is the reachable
   one. The 0.25-tick mean gate is not reachable at 5–10 s under the volatility observed here, and
   the `H-SIG21C-*` registration should say so in advance rather than discovering it afterwards.

### 8.5 If the null is right

It may be. Then the informative measurement is not a bigger sample of the same design, and this is
worth saying plainly:

- **Measure the reaction path `R` first.** §2 already says a cell is decision-relevant only if
  `Z ≥ R`, and `R` — including Kotak acknowledgement — is still unmeasured. If `R` exceeds 1.0 s,
  every registered `Z` is descriptive and no cell in the 384 can be decision-relevant whatever the
  response turns out to be. **This is cheap, it is a prerequisite, and it is not blocked by
  anything.**
- **Measure the far book on a two-sided, higher-volatility session** before spending 25 sessions on
  the registered design. One session of the open would test the drift-confound directly.
- **Reduce the family.** 384 cells against a 40,900-episode ceiling is 106 per cell. A pre-declared
  family of 24 cells has 16× the power per cell for the same tape. That is a registration decision,
  not an analysis decision.

A null on this design is a real finding about the design, and the design can be improved before the
20 sessions are spent rather than after.

---

## 9. Task 5 — specification-change proposal for Aryan

**This is a proposal. Nothing has been implemented. `H-SIG21.md` is untouched.**

```markdown
## Proposed Specification Change

**Requirement affected:** H-SIG21 §6, primary risk set definition
  ("Bursts whose predictive windows overlap are grouped into an episode. The primary risk set
   keeps non-overlapping episodes using the largest registered endpoint (Z + h2 = 11 s).
   All-event estimates may be reported only with dependence-robust inference and cannot replace
   the primary.")

**Current requirement:** every cell of the 384-cell family draws its primary risk set from
non-overlapping episodes built on the family-maximum 11-second window.

**Proposed change:** one of the four options below, at Aryan's choice.

**Why it appears necessary:** the depth200 far book publishes continuously — median inter-burst
gap 0.20 s, largest gap anywhere 0.81 s. Measured on the retained DAT-20 tapes:
  - pooled across all 32 construction cells, the primary risk set is 2 episodes (one per
    contiguous tape) at every selectivity from the 50th percentile through the registered
    99.5th, and reaches 39 only at 99.9%;
  - estimated cell by cell, it is 321 episodes summed across cells at 99.5% (median 5 per cell)
    and 129 at 99.9% (median 2);
  - summed over cells it peaks at the 95th percentile (608) and falls thereafter, so both
    registered thresholds sit on the falling side of the curve;
  - the family-maximum convention costs the most: at 99.5%, a Z=0.5/h2=1 cell has 260 episodes
    under its own 1.5 s window and 2 under the 11 s family maximum — a factor of 130;
  - at the 99.5% threshold zero quiet control instants exist anywhere in 22 minutes, so the
    registered primary *estimand* is undefined for all 192 cells at that threshold.

**Effect on economic/statistical interpretation:**
  - Option (i) keeps the estimand exactly as registered and accepts that the primary arm may be
    near-empty for the short-horizon cells, with the §6 supplement carrying the information —
    which is the situation §6 explicitly says must not arise.
  - Option (ii) changes which estimator is authoritative but not what is estimated. Dependence is
    handled by HAC/Newey-White and a session-clustered block bootstrap instead of by construction.
    Weaker by design: it trusts a variance estimator where the current rule trusts geometry.
  - Option (iii) leaves the estimand and the estimator alone and only stops the longest-horizon
    cell from dictating the exclusivity window of the shortest. Cells become non-comparable in
    risk-set size — which they already are in substance, since they measure different horizons.
  - Option (iv) changes the unit of observation from event episode to time block. Cleanest
    statistically, furthest from the registered text.

**Effect on outputs and comparability:** (i) none. (ii) primary/secondary labels swap in every
family artifact and SIG-19 trial row; N_eff becomes an estimated rather than a counted object.
(iii) `N` and `N_eff` change per cell and cross-cell N comparisons stop being meaningful; the
384-cell family and every other registered axis are untouched. (iv) `N_eff` becomes a block count;
all prior episode-based figures become non-comparable.

**Alternatives considered:**
  (i)   Keep as registered.
  (ii)  Make the overlap-robust all-event estimator primary, with the non-overlapping episode set
        demoted to a robustness check.
  (iii) Bind the episode window to each cell's own Z + h2 rather than the family maximum.
  (iv)  Replace episodes with fixed non-overlapping Z + h2 time blocks, one observation per block
        per cell, and estimate on block means.

**Recommendation: option (iii), with one addition.**

Reasons:
  - It is the smallest change that removes the demonstrated distortion. The collapse is caused by
    the family-maximum convention, not by the non-overlapping principle, and (iii) fixes exactly
    that and nothing else.
  - It preserves what §6 was protecting. Each cell's episodes remain genuinely non-overlapping
    *for that cell's own predictive window*, so the independence argument is unchanged; only the
    window it is applied to changes.
  - It does not weaken the estimand or the estimator, which (ii) does, and does not change the
    unit of observation, which (iv) does.
  - It is measurable now: at 99.5% it takes the shortest-horizon cells from 2 episodes to 260.
  - Option (ii) should be rejected on its merits: this tape shows a studentised bootstrap over
    cells holding two to five observations producing family critical values of 92 and 343. Making
    a variance-estimator-dependent arm primary when the variance estimator is visibly degenerate
    is the wrong direction.

  **The addition, and it matters more than the choice above.** Whichever option is taken, the
  registered matched-quiet-control definition needs revisiting on its own terms. Zero quiet
  instants exist at the 99.5% threshold, so the registered primary estimand is undefined for half
  the family regardless of how episodes are formed. Either the quiet window shrinks below 11 s,
  or quietness is defined per cell rather than against the union of all retained anomalies, or the
  99.5% arm is acknowledged in advance as control-free. This is a separate decision and it should
  be taken before the calibration sessions are spent, not after.

**Approval required from Aryan:** Yes. Nothing has been implemented.
```

---

## 10. Artifacts

| Artifact | Contents |
|---|---|
| `artifacts/sig21-exploratory-response/sig21_exploratory_response_2026-08-19.json` | complete scan: protocol metadata with both tape SHA-256s and the §1.5 justification, selectivity curve (pooled, per-cell totals, all 32 cells), `(Z, h2)` window decomposition, unconditional responses, the complete 384-cell family in three arms, three correlation tables (future / past placebo / contemporaneous), five negative controls each over all 384 cells, and the power statement |
| `artifacts/sig21-exploratory-response/sig21_exploratory_family_rows_2026-08-19.jsonl` | 1,152 flattened rows — 384 cells × 3 arms, complete, empty cells included |
| `scripts/sig21_exploratory_response_scan.py` | reproducible entry point; refuses confirmatory framings before opening a tape and refuses any tape outside the two pinned SHA-256s |
| `src/shaurya/signals/deep_book_exploratory_response.py` | scan module, protocol guards, statistics, negative controls |
| `tests/test_sig21_exploratory_response.py` | 76 tests |

`artifacts/` is gitignored by repository policy, as it is for `DAT-20` and the construction replay,
so these two files exist locally and are regenerated deterministically by the command in section 2.
Every number in this report comes from them.

---

## 11. Verification

- **Correctness:** 76 new tests; full suite **343 passed**; `ruff check .` clean; strict `mypy`
  clean on the project configuration.
- **Completeness:** all five tasks in the brief are produced — the selectivity/window diagnostic,
  the complete 384-cell response family with correlations, controls and negative controls in both
  risk sets, the power statement, the model proposal and the change-control proposal. Nothing was
  scoped out.
- **Evidence level:** **Dry-run verified (Level 3)** for the machinery — the entry point produced
  both artifacts from the retained tapes and the semantic invariants hold (384 cells in every
  family and every negative control, 1,152 flattened rows, tape SHA-256s agreeing with the capture
  manifests, the registered paired estimator agreeing with the arm mean in all 174 populated cells).
  **The empirical content is exploratory and underpowered, and is not evidence at any level about
  whether deep-book anomalies forecast price.**
- **Protocol audit:** `docs/sig-claims/H-SIG21.md` unchanged; no post-registration tape opened;
  every threshold labelled `in_sample_exploratory`; every artifact carries
  `confirmatory_eligible: false` and the §1.5 justification; the complete family emitted everywhere;
  no cell selected, ranked-and-truncated, or highlighted in place of the family.
- **Reuse audit:** `detect_candidates`, `build_depth20_response_labels`, `cluster_event_episodes`,
  `select_primary_non_overlapping_episodes`, `match_quiet_control`,
  `hac_newey_west_mean_difference`, `stationary_session_block_bootstrap` and
  `romano_wolf_stepdown` are all used as registered. Two defects found on first real-tape contact
  are recorded in section 6, one fixed behind an optional parameter with a regression test, one
  documented as a non-defect that reads misleadingly.

---

## Erratum — current full-session ceiling (added 2026-08-19)

The report's 40,900 evaluation ceiling used the old 22,500-second session constant. NSE equity
derivatives close at 15:40 from 2026-08-03, so a current session is 23,100 seconds and the correct
twenty-session ceiling is `floor(23,100 / 11) × 20` = **42,000**. This correction slightly changes
the planning denominator only. The scan's retained tapes, cell results, power verdict, negative-
control failures, and substantive conclusion are unchanged.
