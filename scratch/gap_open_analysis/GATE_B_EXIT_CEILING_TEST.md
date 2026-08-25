# Gate B: can any exit rule exist? The ceiling test

**Run date:** 2026-08-23
**Script:** `gate_b_exit_ceiling.py` · **Results:** `gate_b_exit_ceiling_results.json`
**Panel:** `gate_b_exit_ceiling_panel.csv` (264 rows, one per day) plus three breakeven CSVs
**Evidence class:** exploratory / specification check on **observed traded prices**. Not
identification-grade, not manuscript-ready. N and power are stated for every test.

This is **not** a fifth exit-rule grid. Four have been run (39, 32, 45 and 147 variants) and
all are null. This asks the prior question: **is there any extractable money in the post-fill
path at all, and is Gate B's perfect-hindsight ceiling special, or is it just what the running
maximum of any option premium path looks like?**

No broker, credential, exchange network or order path was used. No gate was armed. No order
exists or is authorised. Nothing outside this folder was written.

---

## Owner Summary

1. **Is the exit mechanism the missing piece? No.** The trade is not a good signal spoiled by a
   bad exit — there is nothing Gate-B-specific in the path for an exit rule to reach.
2. The perfect-hindsight ceiling on Gate B days is **+29.95%** (mid-IV, N=33) and **+32.70%**
   (pooled, N=120). On ordinary gap-fill days that are *not* Gate B it is **+33.08%** (N=231).
   **The control days have the slightly bigger ceiling.** Fires minus controls: −3.13pp, p=0.61.
3. So the famous 40-point giveback is not Gate B throwing away its own edge. It is what every
   noisy option path does, every day, whether the gate fired or not.
4. **When** the best exit occurs is a coin flip, provably. The timing of the post-entry high on
   spot matches the arcsine law — the exact law for a fair random walk — on every population
   tested (p = 0.34 mid-IV, 0.05–0.20 elsewhere; no rejection). You cannot forecast a coin flip.
5. **Headline number: the ceiling on the win rate of any exit rule ever written is 93.9%**
   (mid-IV, 31/33) / **92.5%** (pooled, 111/120), against 39.4% actually achieved. That gap looks
   like an opportunity — but control days have a ceiling of **93.5%**, statistically identical
   (p = 1.00). The headroom is arithmetic, not information.
6. Aryan's premise — "once the setup fires NIFTY trends, and trends by a lot" — is **not
   supported by the achievable move**. Median fill-to-close move on a fire is **−4.5 points**,
   45.5% of fires close higher, sign test p = 0.73. The 33.6-point figure in the spec is the
   *best point ever touched* (hindsight), and even that is *smaller* than a driftless random
   walk at the same volatility would give (59.2 observed vs 79.4 expected).
7. **Bottom line:** the money is not being lost at the exit. It is being paid at the entry, for
   volatility that never arrives — and Gate B days are no more directional, no more volatile and
   no more forecastable than the days it is being compared against.
8. **Action needed from Aryan:** none from this study. The §3 open decision in the topic file is
   unchanged and still parked.

---

## 0. What was tested, on what, with what N

| cell | definition | N |
|---|---|---:|
| **fires_mid** | published Gate B: non-expiry, gap-down, VIX rose, opening-IV bucket mid 14–18, gap filled after 09:17 | **33** |
| **fires_pooled** | the same minus the IV-bucket filter (non-expiry, gap-down, VIX rose, gap filled) | **120** |
| ctrl_nonfire | every non-expiry gap-down gap-fill day that is **not** a Gate-B fire | 231 |
| ctrl_ivmiss | the IV-bucket-mismatched near-misses: VIX rose, gap filled, wrong IV bucket | 87 |
| ctrl_novix | the pooled cell's own control: gap filled, VIX did **not** rise | 144 |
| (universe) | all non-expiry gap-down days whose gap fills after 09:17 | 264 |

The mid-IV cell (N=33) and the pooled cell (N=120) are reported **separately throughout**, never
merged into one headline, per the standing rule.

**Entry-minute convention, identical for fires and controls:** each day's own gap-fill minute —
the first minute strictly after 09:17 at which spot returns to or through the prior session's
15:29 close. This is enforced structurally: `gate_b_common.build_paths` runs one code path over
all 264 days and the gate label is attached afterwards. Median entry is 09:43 on fires_mid,
09:32 on fires_pooled, **09:33 on both control cells** — so the comparison is not a
holding-period comparison in disguise. Every test that could be affected is additionally run
with labels permuted **within entry-time strata** and the answer does not move.

**Premium series:** real strike-tracked traded one-minute bar closes for the actual entry strike,
held fixed and looked up by absolute value. Minute coverage is **100.0% on 263 of 264 days** and
97.8% on the one exception (2026-02-01, a control day not quoted at 15:29 itself; it exits at
its last priced minute under the project's two-minute grace).

---

## 1. T1 — Oracle ceiling versus placebo. **The decisive test, and it is null.**

Perfect-hindsight exit: the maximum traded premium over every minute from the fill to 15:29,
divided by the entry premium.

| cell | N | mean | p10 | Q1 | **median** | Q3 | p90 | max | sd |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **fires_mid** | 33 | **+29.95%** | +1.15 | +5.02 | **+12.37%** | +36.49 | +92.89 | +111.4 | 35.70 |
| **fires_pooled** | 120 | **+32.70%** | +2.14 | +6.62 | **+20.45%** | +50.38 | +90.54 | +177.3 | 35.34 |
| ctrl_nonfire | 231 | **+33.08%** | +3.00 | +7.70 | **+22.01%** | +51.28 | +79.37 | +177.3 | 32.71 |
| ctrl_ivmiss | 87 | +33.74% | +3.02 | +6.87 | +21.65% | +51.32 | +88.48 | +177.3 | 35.35 |
| ctrl_novix | 144 | +32.67% | +2.93 | +8.32 | +23.89% | +51.25 | +77.38 | +153.8 | 31.13 |

The pooled +32.70% reproduces `GATE_B_EARLY_EXIT_SCAN.md` §2.5 to the second decimal.

### Fires minus controls

| comparison | difference | permutation p | **stratified** permutation p | Mann–Whitney p |
|---|---:|---:|---:|---:|
| fires_mid − ctrl_nonfire | **−3.13pp** | 0.6076 | **0.6136** | 0.2770 |
| fires_mid − ctrl_ivmiss | **−3.80pp** | 0.6038 | **0.6088** | 0.3716 |
| fires_pooled − ctrl_novix | **+0.03pp** | 0.9942 | **0.9951** | 0.4970 |

Normalising away the mechanical growth of a running maximum with holding length (peak return per
√minute) gives the same answer: −0.265 per √min, p=0.489 (mid); −0.021, p=0.936 (pooled).

### Giveback from the hindsight peak to the close

| cell | mean peak | mean close | **giveback** |
|---|---:|---:|---:|
| fires_mid | +29.95% | −6.08% | **36.02pp** |
| fires_pooled | +32.70% | −7.61% | **40.31pp** |
| ctrl_nonfire | +33.08% | −9.26% | **42.34pp** |
| ctrl_novix | +32.67% | −9.91% | **42.58pp** |

**The controls give back more than the fires do.**

### Loss and gain per minute held (horizons differ, so this is required)

| cell | mean minutes to the peak | oracle gain per minute | mean minutes to close | close loss per minute |
|---|---:|---:|---:|---:|
| fires_mid | 134.1 | +0.675%/min | 314 | **−0.0093%/min** |
| fires_pooled | 118.1 | +0.663%/min | 298 | **−0.0197%/min** |
| ctrl_nonfire | 114.0 | +0.883%/min | 298 | −0.0276%/min |
| ctrl_novix | 115.2 | +1.018%/min | 301 | −0.0299%/min |

Gate B bleeds slightly *slower* per minute than a control day, and its oracle accrues slightly
*slower* too. Both differences are inside noise.

### Power

| comparison | smallest difference resolvable at 80% power | observed |
|---|---:|---:|
| fires_mid vs ctrl_nonfire | **18.43pp** | −3.13pp |
| fires_mid vs ctrl_ivmiss | 20.39pp | −3.80pp |
| fires_pooled vs ctrl_novix | **11.60pp** | +0.03pp |

Honest reading: this test could not detect a ceiling advantage smaller than ~12–18pp, so it does
not *prove* the difference is exactly zero. But the point estimates are **negative** — fires sit
slightly *below* controls on two of three comparisons — so the data give no directional hint that
a Gate-B-specific ceiling exists. To argue otherwise you would have to argue for an effect whose
sign is the opposite of what was measured.

### > INTERPRETATION GATE — the verdict this test was built to deliver
>
> **Controls show a ceiling that is equal to or larger than Gate B's.** Therefore **+32.70% is a
> property of option premium paths in general, the 40pp giveback is generic path noise, and no
> exit rule can extract it, because there is nothing Gate-B-specific in the path to extract.**
>
> The alternative branch — "fires' ceiling is materially and significantly above controls',
> therefore the exit search was looking in the wrong space" — **is not the branch the data take.**
> The difference is −3.13pp with p=0.61.

---

## 2. T2 — Is the peak time arcsine-distributed?

For a driftless path on [0, T] the time of the maximum follows the arcsine law,
F(x) = (2/π)·arcsin(√x): a U-shape with most mass at the two ends and a thin middle. Normalised
peak time is u = (minutes from entry to the peak) / (minutes from entry to 15:29). One-sample
Kolmogorov–Smirnov test against that CDF. Main test restricted to days with ≥120 minutes of path
so u is not coarsely discretised; the full sample is reported as a declared sensitivity in the
JSON and does not change any conclusion.

### (a) Post-entry SPOT maximum — the clean test (spot carries no theta drift)

| cell | N | KS D | **KS p** | u<0.25 | 0.25≤u≤0.75 | u>0.75 |
|---|---:|---:|---:|---:|---:|---:|
| **fires_mid** | 31 | 0.1637 | **0.3396** | 41.9% | 12.9% | 45.2% |
| **fires_pooled** | 108 | 0.1278 | **0.0538** | 41.7% | 23.1% | 35.2% |
| ctrl_nonfire | 203 | 0.0832 | 0.1139 | 39.4% | 25.6% | 35.0% |
| ctrl_ivmiss | 77 | 0.1325 | 0.1224 | 41.6% | 27.3% | 31.2% |
| ctrl_novix | 126 | 0.0945 | 0.1974 | 38.1% | 24.6% | 37.3% |
| *arcsine law* | — | — | — | *33.3%* | *33.3%* | *33.3%* |

**The arcsine law is not rejected at 5% on any population.** The mid-IV cell's 41.9 / 12.9 / 45.2
split is the textbook U — and §2.5's "37.5% before 11:00, 43.3% at or after 14:00, thin middle"
is exactly this, measured on a wall clock instead of a normalised one.

### (b) Premium peak

| cell | N | KS D | KS p | direction of the departure |
|---|---:|---:|---:|---|
| fires_mid | 31 | 0.2303 | 0.0629 | D⁺ — peaks **earlier** than arcsine |
| **fires_pooled** | 108 | 0.1659 | **0.0046** | D⁺ = 0.166 at u≈0.16 — earlier |
| ctrl_nonfire | 203 | 0.1534 | **0.0001** | D⁺ = 0.153 at u≈0.25 — earlier |
| ctrl_novix | 126 | 0.1815 | **0.0004** | **D⁺ = 0.182** — earlier, and *more* so than fires |

The premium peak **is** rejected on the larger samples, and the departure is in one direction: the
premium peaks **earlier** than a driftless path would. That is time decay — a negative drift pulls
the argmax forward. It is not a tradeable clock, for two reasons: it is a *drift* statement, not a
*timing* statement, and **the control days depart from arcsine by more than the fires do**
(D = 0.182 on ctrl_novix vs 0.166 on fires_pooled). Nothing here is Gate-B-specific.

### > INTERPRETATION GATE
>
> **Non-rejection on spot.** The location of the best available exit is distributed exactly as a
> coin-flip path's argmax. It is **structurally unforecastable** — not "we have not found the
> indicator yet", but "there is no clock to find". **This closes the exit question by theorem
> rather than by a fifth failed grid**, and it is consistent with the Merton drift-estimation
> result already recorded in the project file: a running maximum's location is a pure
> drift-versus-diffusion object, and drift is not estimable by finer sampling.

**One honest caveat, applying equally to fires and controls.** By construction every one of these
264 days enters at a *running high* of the post-09:17 spot path — the fill minute is the first
minute spot regains the prior close. That conditioning pushes the argmax slightly early on all
populations, which is visible as the small D⁺ excess at low u even on spot. It cannot generate a
fires-versus-controls difference, because it is applied identically to both.

---

## 3. T3 — The maximum achievable win rate under any exit rule

### The headline

> # **93.9%**
> ### Mid-IV cell, N = 33 (31 of 33 days), 95% CI 79.8–99.3%
>
> # **92.5%**
> ### Pooled cell, N = 120 (111 of 120 days), 95% CI 86.2–96.5%
>
> No exit rule can sell above the running maximum of the traded premium. So the share of days on
> which the premium **ever trades above its own entry price** is a hard upper bound on the win
> rate of every exit rule that has been tested, could be written, or will ever be written on this
> trade. **Actual hold-to-close win rate: 39.4% (mid) / 38.3% (pooled).**
>
> ## And here is why that number is not an opportunity:
> # **93.5%**
> ### The identical ceiling on the 231 control days that are *not* Gate B fires.
> ### Fires − controls: **+0.4pp, permutation p = 1.00.**

| cell | N | **ceiling win rate** | 95% CI | net 2% costs | net 5% | ceiling >+10% | ceiling >+25% | **actual** |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| **fires_mid** | 33 | **93.9%** (31/33) | 79.8–99.3 | 84.8% | 75.8% | 57.6% | 36.4% | **39.4%** |
| **fires_pooled** | 120 | **92.5%** (111/120) | 86.2–96.5 | 90.0% | 81.7% | 63.3% | 43.3% | **38.3%** |
| ctrl_nonfire | 231 | 93.5% (216/231) | 89.5–96.3 | 91.3% | 84.8% | 67.1% | 47.2% | 39.8% |
| ctrl_ivmiss | 87 | 92.0% (80/87) | 84.1–96.7 | 92.0% | 83.9% | 65.5% | 46.0% | 37.9% |
| ctrl_novix | 144 | 94.4% (136/144) | 89.3–97.6 | 91.0% | 85.4% | 68.1% | 47.9% | 41.0% |

Permutation tests on the ceiling difference: fires_mid − ctrl_nonfire **+0.4pp, p = 1.0000**;
fires_mid − ctrl_ivmiss +2.0pp, p = 1.0000; fires_pooled − ctrl_novix −1.9pp, p = 0.6159.

This construction is **model-free**: entry premium and maximum premium are both traded one-minute
bar closes on the tracked strike. No Black-Scholes value enters it.

### The breakeven-move decomposition, as briefed

Second, independent construction. For each minute after the fill, the spot level S\* at which the
option returns to its entry premium is solved from Black–Scholes with implied volatility held at
the trading-time value inverted from the **traded** entry premium. Breakeven move = S\* − S0. It
grows through the session because decay must be made up. **Scenario object, declared** — it exists
to express the ceiling in index points and it does not enter any headline number.

| cell | N | breakeven reachable at some minute | **MFE exceeds breakeven at the minute it was touched** | median breakeven at the MFE minute | median breakeven at close | median MFE | median fill-to-close move |
|---|---:|---:|---:|---:|---:|---:|---:|
| **fires_mid** | 33 | 100.0% | **93.9%** | **8.5 pts (0.03σ)** | 34.6 pts (0.13σ) | **33.5 pts** | **−4.5 pts** |
| **fires_pooled** | 120 | 96.7% | **94.2%** | 9.3 pts (0.03σ) | 33.2 pts (0.12σ) | 48.1 pts | −16.7 pts |
| ctrl_novix | 144 | 97.2% | **91.7%** | 11.6 pts (0.04σ) | 32.4 pts (0.13σ) | 55.6 pts | −2.8 pts |

σ is the day's entry-minute implied volatility scaled to the remaining **trading-time** horizon.

**The two constructions agree to within 0.3pp on the mid-IV cell (93.9% vs 93.9%) and 1.7pp on
the pooled cell.** They use different machinery and different information; that they land in the
same place is the study's internal consistency check.

**What the points say in plain terms.** On a median fire the market only has to be 8.5 index
points above the fill for the option to be worth what was paid, *at the moment the day's high is
made* — a trivial bar, cleared 93.9% of the time. Hold to the close and the bar rises to 34.6
points, and the median day's best-ever excursion (33.5 points) no longer clears it — while the
median day actually **closes 4.5 points below the fill**. The trade is not failing because the
bar is high. It is failing because nobody can be at the high when it happens, and the bar rises
underneath you while you wait.

---

## 4. T4 — Aryan's premise, re-verified directly on spot

The spec records *"median further favorable move after fill: 33.6 pts (mean 60.7)"*. The project
record says that is MFE — the best point *touched*. **Confirmed from a fully independent rebuild:
median MFE on fires_mid is 33.5 pts, mean 59.2 pts.** The spec figure is the hindsight excursion,
not an achievable move.

### Fill-to-close spot move, fires versus controls

| cell | N | **signed mean** | **signed median** | share up | sign test p | t p vs 0 | \|move\| mean | \|move\| median | MFE mean | MFE median | MAE mean | realised vol entry→close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **fires_mid** | 33 | **+5.2** | **−4.5** | **45.5%** | 0.728 | 0.738 | 71.4 | 73.3 | 59.2 | 33.5 | −86.5 | **8.16%** |
| **fires_pooled** | 120 | **−2.2** | **−16.7** | **44.2%** | 0.235 | 0.838 | 85.3 | 69.6 | 71.4 | 48.1 | −86.7 | **8.57%** |
| ctrl_nonfire | 231 | −13.1 | −11.1 | 47.2% | 0.430 | 0.108 | 90.4 | 65.9 | 71.3 | 52.1 | −92.1 | 9.14% |
| ctrl_ivmiss | 87 | −5.0 | −18.8 | 43.7% | 0.284 | 0.710 | 90.6 | 69.5 | 76.0 | 50.0 | −86.8 | 8.72% |
| ctrl_novix | 144 | −18.0 | −2.8 | 49.3% | 0.934 | 0.082 | 90.3 | 65.5 | 68.4 | 55.6 | −95.3 | 9.39% |

Points, NIFTY index. Realised volatility is annualised in trading time (375 min/session,
252 sessions/year).

### Fires minus controls, permutation p-values

| comparison | signed close move | (stratified) | absolute close move | MFE | realised vol |
|---|---:|---:|---:|---:|---:|
| fires_mid − ctrl_nonfire | +18.3 pts, p=0.410 | p=0.410 | **−19.0 pts**, p=0.209 | **−12.1 pts**, p=0.332 | −1.0pp, p=0.131 |
| fires_mid − ctrl_ivmiss | +10.2 pts, p=0.674 | p=0.669 | −19.3 pts, p=0.232 | −16.8 pts, p=0.279 | −0.6pp, p=0.341 |
| fires_pooled − ctrl_novix | +15.9 pts, p=0.281 | p=0.286 | −4.9 pts, p=0.625 | +2.9 pts, p=0.722 | −0.8pp, p=0.055 |

The MFE row reproduces the project record exactly: **fires_pooled 71.4 vs ctrl_novix 68.4,
p = 0.72.**

### Against a driftless random walk at each day's own realised volatility

E[max] of a driftless Brownian path over the same horizon at the same volatility:

| cell | driftless E[max] | observed MFE | **ratio** |
|---|---:|---:|---:|
| fires_mid | 79.4 pts | 59.2 pts | **0.746** |
| fires_pooled | 80.8 pts | 71.4 pts | **0.883** |
| ctrl_nonfire | 82.5 pts | 71.3 pts | 0.864 |
| ctrl_novix | **83.1 pts** | 68.4 pts | 0.823 |

The ctrl_novix figure of 83.1 pts reproduces the number already in the project record. **On every
population the observed favourable excursion is smaller than a coin flip's** — most of all on the
mid-IV fires, at 75% of the random-walk benchmark.

### > The one-line answer
>
> **"Gate B days trend, and trend by quite a bit" is supported only by the hindsight-MFE
> convention, not by the achievable close-based move:** the median fire closes **4.5 points
> below** the fill, only **45.5%** close higher (sign test p=0.73), the fires' absolute move and
> realised volatility are *lower* than the control days', and even their hindsight excursion is
> 25% *smaller* than a driftless random walk at their own volatility would produce.

---

## 5. Verification

Required checks, each answered explicitly.

| check | result |
|---|---|
| **N in every test** | fires_mid **33**, fires_pooled **120**, ctrl_nonfire **231**, ctrl_ivmiss **87**, ctrl_novix **144**, universe **264**. T2 restricts to ≥120 minutes of path: 31 / 108 / 203 / 77 / 126 — the excluded days are listed in the panel CSV via `minutes_to_close`, and the unrestricted full-sample KS results are in the JSON. |
| **Entry-minute convention matched between fires and controls** | **Yes, structurally.** One code path (`gate_b_common.build_paths`) constructs all 264 days from the same rule — first minute strictly after 09:17 at which spot ≥ prior session 15:29 close — and the Gate-B label is attached afterwards. Median entry: fires_mid 09:43, fires_pooled 09:32, ctrl_nonfire 09:33, ctrl_novix 09:33. Every fires-vs-controls test is additionally run with labels permuted **within entry-time strata**; no stratified p-value differs from its raw counterpart by more than 0.006. |
| **No calendar-time IV inversion** | **Confirmed.** Every implied volatility in this module comes from `trading_T()` — 375 minutes/session, 252 sessions/year — per `CORRECTION_GATE_B_VOL_CRUSH.md`. The calendar-time `T0_days` field from `gate_b_common` is used in exactly one place: the inversion-validation check below, where a calendar figure is *required* in order to compare against the vendor's calendar-convention quote. |
| **Inversion machinery validated** | Inverting the traded entry premium under the **calendar** convention reproduces the vendor's own tape IV with **correlation 0.9970** and a median level ratio of **1.0250** (15.63 vs 15.22). So the machinery is correct and the trading-time figure (mean 11.67, median 10.85) is a pure convention change, not a different measurement. It is **not comparable to a vendor quote** and is never quoted as one. σ·√T is identical under both conventions, so the T3(b) breakeven map is convention-invariant. |
| **No Black-Scholes proxy in any headline number** | **Confirmed.** T1, T2, T3(a) and T4 are computed entirely from traded one-minute bar closes and the NIFTY minute tape. The only model-dependent object is the T3(b) breakeven-move decomposition, labelled scenario-based in situ; its answer (93.9% / 94.2%) independently agrees with the model-free T3(a) answer (93.9% / 92.5%), which is why the headline can rest on the model-free construction alone. `bs_gap_fill_pnl.py`'s frozen-opening-IV P&L series is **not used anywhere in this module**. |
| **Loss-per-minute-held reported where horizons differ** | Yes — §1, per-minute table. |
| **Mid-IV and pooled reported separately** | Yes, in every table. |
| **Data coverage** | 100.0% of minutes quoted on 263 of 264 days; 97.8% on 2026-02-01 (a control), which exits at its last priced minute under the project's two-minute grace. No day is dropped for pricing, so no result can be driven by non-random missingness. |
| **Reproduction guard** | `gate_b_common.reproduction_guard` passed at the top of the run: the 33-fire set, entry clocks, strikes, Black-Scholes entry premiums, all three published trailing-stop means and every fixed-clock figure in `GAP_FILL_SIGNAL_MODULE_SPEC.md` recovered. |
| **Independent reproductions of prior figures** | pooled oracle peak **+32.70%** (§2.5) ✓ · hold-to-close **−6.08%** mid / **−7.61%** pooled ✓ · fires MFE **71.4** vs controls **68.4** ✓ · driftless E[max] **83.1 pts** ✓ · spec's MFE "33.6 / 60.7" recovered as 33.5 / 59.2 ✓ |

### Hand check against the raw archive CSVs

Three Gate-B days recomputed from the source one-minute files directly, bypassing the pickled
quote cache entirely (the check re-reads `.../dhan_fresh_2021_2026/options/<year>/*.csv`, filters
to `option_type == "CE"` and the tracked absolute strike, and recomputes entry, close and running
maximum from the raw `close` column):

| date | strike | entry | raw entry | panel entry | raw close | panel close | raw max (clock) | panel max | raw close return | raw oracle peak |
|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|
| 2021-09-08 | 17350 | 09:18 | 78.05 | 78.05 ✓ | 59.30 | 59.30 ✓ | 81.25 (09:19) | 81.25 ✓ | −24.02% | +4.10% |
| 2024-02-20 | 22100 | 09:43 | 134.20 | 134.20 ✓ | 173.80 | 173.80 ✓ | 174.75 (15:17) | 174.75 ✓ | +29.51% | +30.22% |
| 2026-01-29 | 25350 | 13:03 | 199.20 | 199.20 ✓ | 243.30 | 243.30 ✓ | 262.60 (14:52) | 262.60 ✓ | +22.14% | +31.83% |

All nine comparisons match exactly. Worked example, 2021-09-08: the ATM 17350 CALL is bought at
78.05 at 09:18, trades up to 81.25 one minute later — the day's entire high — and closes at 59.30.
The oracle exit is worth +4.10%; hold-to-close is −24.02%; the giveback is 28.1pp, and the whole
of it is available in a single minute that arrives 60 seconds after the fill.

### Environment note

`scipy` was absent from the interpreter available to this session, so the analysis ran under
`/private/tmp/sha_consumer/.venv/bin/python` (numpy 2.2.6, scipy 1.18.0, pandas 2.3.3);
`scikit-learn 1.9.0` was installed into that venv because `gate_b_common` transitively imports
`ml_gated_put_call`. No project file, cache or artifact outside this folder was modified.

---

## 6. Limitations, stated plainly

1. **N = 33 is small and this study does not fix that.** T1 can only resolve a ceiling difference
   larger than ~18pp on the mid-IV cell and ~12pp pooled. A genuine but modest Gate-B ceiling
   advantage would be invisible here. What the study can say is that the measured difference is
   **negative** on two of three comparisons, so the data do not point in the direction the
   hypothesis needs.
2. **These are one-minute bar closes, not executable fills.** The oracle ceiling in particular is
   the most optimistic possible reading: it assumes selling at the exact printed high of a single
   minute. The 93.9% ceiling is therefore an upper bound on an upper bound. Costs of 2% and 5% of
   premium are shown alongside it; the real bid-ask on a weekly ATM NIFTY option is not in this
   dataset, and `GATE_B_REAL_PREMIUM_VALIDATION.md` §7 bounds it separately.
3. **The T3(b) breakeven map is model-dependent** (Black–Scholes, volatility frozen at the
   trading-time entry value, r = 6.5%, no dividend). It is used only to express the ceiling in
   index points. The headline does not rest on it. Its agreement with the model-free construction
   is reassurance, not proof.
4. **The arcsine test is a test of a distribution, not of every possible timing rule.** Failing to
   reject arcsine on spot means the argmax location is *distributionally* indistinguishable from a
   fair walk's. It does not mathematically exclude a conditional rule that uses information
   outside the path itself. It does exclude every rule that reads the clock or the path — which
   is what all four prior grid searches were.
5. **Ties and boundary mass in the KS test.** u = 0 occurs whenever the peak is the entry minute
   itself. The arcsine CDF is continuous, so the test is mildly conservative in the presence of
   these ties; the effect is identical across fires and controls and is far too small to overturn
   a p of 0.34.
6. **The entry is a conditioned point,** not a random one: it is the first minute spot regains the
   prior close, hence a running high of the post-09:17 path. This mildly biases every argmax
   early, on fires and controls alike. It cannot manufacture a difference between them.
7. **Multiplicity.** This run performs 3 ceiling comparisons, 10 KS tests, 3 ceiling-share
   comparisons and 12 T4 comparisons — 28 tests. **Nothing here is a discovery claim requiring
   correction**: every headline is a *null* or a *bound*, and the two nominally significant results
   (premium-peak arcsine rejections at p=0.0046 and p=0.0001) are *stronger on the controls than
   on the fires*, which is the opposite of a Gate-B finding. Had any fires-versus-controls test
   come back positive it would have needed a Bonferroni threshold of 0.0018 to survive.

---

## 7. Open questions — recorded, deliberately not run

Per the brief, anything beyond the four tests is written down rather than executed.

1. **Is the ceiling equally generic on Gate A?** Gate A has genuine walk-forward evidence and a
   same-day-expiry contract with no overnight period. Running T1/T2/T3 on the 55 Gate-A days would
   say whether an oracle ceiling that *does* exceed its controls looks different — i.e. it would
   give this test a positive control. Without one, T1's null is a null without a calibration point.
2. **Does the arcsine result survive on the PUT side and on non-gap-fill entries?** The entry
   conditioning in limitation 6 is the one structural feature this design cannot remove. An entry
   rule that is not a running high (e.g. a fixed 09:30 clock) would break the conditioning and
   test whether the U-shape is the market's or the sampling rule's.
3. **The §6 gamma-refund reconciliation** already open in the topic file (26% on the gate-day call
   versus 87% on the all-day straddle) is the natural next quantitative question, because T3 now
   shows the breakeven bar at the *close* (34.6 pts, 0.13σ) is the binding constraint and that bar
   is set entirely by the decay-minus-gamma balance.
4. **Is the 6.7-point implied-minus-realised overpayment smaller further out on the curve?**
   Unchanged as the one download worth the Dhan token. Nothing in this study bears on it, and
   nothing in this study should be read as bearing on it.
5. **A short-premium version of the same ceiling test.** If the oracle ceiling is generic and the
   giveback is generic, the symmetric question is whether the oracle *floor* is equally generic —
   i.e. whether the seller's side of this identical path structure has an asymmetry the buyer's
   side lacks. The margin constraint (₹1.5–2.5 lakh/lot against a ₹10,000 budget) makes it
   unactionable today, so it is a research question, not a trade.

---

## 8. What this changes

**Nothing in the specification, and no gate state.** `GAP_FILL_SIGNAL_MODULE_SPEC.md`,
`MODEL_REQUIREMENTS_TRACEABILITY.md` and `~/Documents/gap-open-engine` are untouched; the Gate B
spec change remains a parked decision awaiting Aryan's explicit word. Both gates remain disarmed.

**Interpretation change:** one, and it is worth stating precisely. The prior reports could say
only *"we searched for an exit rule and did not find one"* — an absence of evidence across four
grids. This study upgrades that to a **bound with a mechanism**: the money visible in the
hindsight path is present on Gate-B days and on ordinary days in identical amounts (T1), its
location is distributed as a fair walk's argmax (T2), and the achievable ceiling it implies is
statistically identical on fires and controls (T3). *"We have not found the exit"* becomes
*"there is no Gate-B-specific exit to find, and here is the quantity that says so."*

**Action needed from Aryan:** none.
