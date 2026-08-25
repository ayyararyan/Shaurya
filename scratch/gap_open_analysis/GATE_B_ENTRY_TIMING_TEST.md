# Gate B entry-timing test: separating "the day is confirmed" from "buy the option now"

**Date:** 2026-08-23 · **Population:** 33 mid-IV Gate B fires and the 120-day VIX-rose parent,
fires 2021-09-08 to 2026-01-29, pool to 2026-04-20 · **Premiums:** real strike-tracked traded one-minute bar closes, ATM
strike re-picked at each entry minute · **Exit:** hold to 15:29 throughout · **Status:**
exploratory scan with placebo and stability discipline. Not a manuscript-grade result, not a
specification change, no gate armed, no order placed.

Scripts `gate_b_entry_timing.py`, `gate_b_entry_timing_common.py`; results
`gate_b_entry_timing_results.json`; per-day panel `gate_b_entry_timing_panel.csv`; full console
log `gate_b_entry_timing_console.txt`.

---

## Owner Summary

1. **Yes, partly — and it is TIMING, not selection.** Buying the same Gate B day's CALL 30 minutes
   to 4 hours after the gap fill instead of at the fill turns −6.08% into roughly **+2% to +13%**,
   on the *same 33 days*, paired p as low as **0.0006** (Bonferroni-adjusted 0.009).
2. The reason is that **the fill minute is the worst price of the day.** After a Gate B fill, spot
   falls **−15 to −25 points** over the next 20–120 minutes (p=0.0006 at +20 min) and only recovers
   into the close. You have been buying a call at the top of a V.
3. **This is not an executable-price artifact.** Entering one minute later — the earliest a live
   monitor could act — changes almost nothing (+0.64pp, p=0.57). The gain builds gradually over
   30 minutes, so it is drift, not a single spiky bar.
4. **But it does not create a positive expectancy.** The best late-entry cell is +13.1% with
   **p=0.16**. Later entry *removes the loss*; it does not prove a gain. Nothing here reverses the
   VAL-05 "do not arm" verdict.
5. **The conditional "buy once the trend confirms" idea (your actual proposal) found nothing.**
   Against the correct benchmark — unconditional entry at the *same clock* — **0 of 144 cells** are
   significant at even a raw 5%, and the best cell that actually trades is +4.29pp, p=0.39.
6. **Where conditioning appears to help, it is pure selection, and the placebo kills it.** The
   decomposition is +17.1pp selection versus +1.8pp timing; and on control days the *same grid*
   produces 19 cells significant at raw 5% and a best cell of +13.03pp, p=0.027 — better than
   anything the real Gate B label achieves.
7. **The one genuinely Gate-B-specific finding is E1, not E2.** Controls gain little from waiting
   (+0.8 to +6pp, none significant); fires gain +8 to +21pp. The difference-in-differences is
   positive in **15 of 15** entry cells, 4 significant at raw 5%, **none after Bonferroni**.
8. **Action needed from Aryan:** none. This is exploratory. If you want it pursued, the one test
   worth running is whether the post-fill pullback survives on out-of-sample Gate B days.

---

## 1. What was and was not changed from the standing method

| Convention | This test | Why it matters |
|---|---|---|
| Premiums | Real traded one-minute bar closes of the tracked absolute strike | `bs_gap_fill_pnl.py` froze IV at the open and runs ~8pp too generous. Verified: **0 code lines** in either script touch a Black-Scholes price series. |
| ATM strike | **Re-picked at the entry minute**, `round(spot(t)/50)*50` | A 12:00 entry buys the 12:00 ATM. On **17 of 28** fires with a 12:00 entry this is a different contract from the fill-minute ATM. |
| Exit | Hold to 15:29, every cell, no exception | Four exit grids are already null. No fifth was run. |
| Maturity for any implied vol | **Trading time**, 375 min/session × 252 sessions/yr | `CORRECTION_GATE_B_VOL_CRUSH.md`. One `365`-day line exists in the code and it is inside the explicitly labelled calendar *diagnostic* (§3.1). |
| Cells reported | mid-IV N=33 and pooled N=120 **separately, never merged** | — |
| Holding period | Loss-per-minute-held reported beside every total return | Holding periods differ by construction here; without it the latest entry always looks safest. |

**Population.** 264 non-expiry gap-down days whose gap filled after 09:17; **120** of those also had
an overnight VIX rise (the pooled cell); **33** of those also sit in the mid 14–18% opening-IV
bucket (published Gate B). The **87** VIX-rose non-mid-IV days are the control population used for
the E4 placebo — exactly the population named in the brief.

**Baseline reproduction.** This pipeline is independent of `gate_b_common.build_paths` for the panel
but recovers the published numbers exactly: fill-minute entry, hold to close, **−6.08% mean /
−13.46% median / 39.4% win / p=0.4660** on N=33 and **−7.61% / −13.22% / 38.3% / p=0.0672** on
N=120, with a **maximum per-day difference of 0.00e+00pp** across all 120 days. The
`gate_b_common.reproduction_guard` also passes.

---

## 2. E1 — Unconditional entry-time scan

Buy the ATM CALL at the stated clock, hold to 15:29. A day whose gap fills *after* a fixed clock is
excluded from that cell; the drop count is stated for every cell, and a common-sample version
restricted to days priceable in **every** cell follows.

### 2.1 Mid-IV Gate B, N=33

| Entry | dropped | N | mean | median | win | p vs 0 | held | per minute |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **fill (baseline)** | 0 | 33 | **−6.08%** | −13.46% | 39.4% | 0.4660 | 314m | −0.0093%/min |
| fill+15 | 0 | 33 | +1.97% | −5.78% | 39.4% | 0.8376 | 299m | +0.0127%/min |
| fill+30 | 0 | 33 | +4.92% | −2.56% | 48.5% | 0.5569 | 284m | +0.0318%/min |
| fill+45 | 0 | 33 | +3.75% | −2.97% | 42.4% | 0.6750 | 269m | +0.0167%/min |
| fill+60 | 0 | 33 | +1.53% | −3.51% | 42.4% | 0.8497 | 254m | +0.0062%/min |
| fill+90 | 2 | 31 | +6.77% | −6.32% | 38.7% | 0.4195 | 239m | +0.0164%/min |
| 10:00 | 12 | 21 | +7.30% | +3.91% | 52.4% | 0.5618 | 329m | +0.0222%/min |
| 10:30 | 8 | 25 | +9.57% | +1.99% | 52.0% | 0.3841 | 299m | +0.0320%/min |
| 11:00 | 5 | 28 | +5.27% | −10.65% | 46.4% | 0.6021 | 269m | +0.0196%/min |
| 11:30 | 5 | 28 | +4.80% | −7.02% | 42.9% | 0.6164 | 239m | +0.0201%/min |
| 12:00 | 5 | 28 | +10.14% | −6.13% | 46.4% | 0.3273 | 209m | +0.0485%/min |
| 12:30 | 5 | 28 | +11.82% | +2.61% | 50.0% | 0.1857 | 179m | +0.0660%/min |
| 13:00 | 3 | 30 | +11.12% | −3.29% | 43.3% | 0.1960 | 149m | +0.0747%/min |
| **13:30** | 2 | 31 | **+13.13%** | −0.07% | 48.4% | 0.1630 | 119m | +0.1103%/min |
| 14:00 | 2 | 31 | +7.80% | +5.77% | 54.8% | 0.2759 | 89m | +0.0876%/min |
| 14:30 | 0 | 33 | +6.42% | +4.99% | 57.6% | 0.2318 | 59m | +0.1089%/min |

**Every one of the 15 later cells has a higher mean than the fill baseline, and every one flips the
sign.** No cell is significant against zero (best p=0.16). Zero unpriceable trades on the fires.

**Common sample (N=21, days priceable in all 16 cells):** fill −7.06% → 10:00 +7.30% → 12:30
+15.22% → **13:30 +17.20%** → 14:30 +5.63%. The shape is not a composition effect.

### 2.2 Pooled, N=120

| Entry | dropped | unpriceable | N | mean | p vs 0 | per minute |
|---|---:|---:|---:|---:|---:|---:|
| fill (baseline) | 0 | 0 | 120 | **−7.61%** | 0.0672 | −0.0197%/min |
| fill+30 | 5 | 3 | 112 | −3.26% | 0.4413 | −0.0232%/min |
| fill+90 | 12 | 3 | 105 | −1.03% | 0.8026 | +0.0140%/min |
| 12:00 | 24 | 0 | 96 | −1.57% | 0.7261 | −0.0075%/min |
| **12:30** | 24 | 0 | 96 | **−0.97%** | 0.8161 | −0.0054%/min |
| 14:30 | 7 | 0 | 113 | −2.78% | 0.2463 | −0.0471%/min |

The pooled cell improves with later entry but **never turns positive**. Common sample N=70: fill
−12.12% (p=0.043) → 11:00 −1.53% → 14:00 −1.52%.

### 2.3 The composition-free version: paired late-minus-fill, same days

This is the load-bearing table. Each cell is compared with the fill baseline on exactly the days
priceable in both, so a cell cannot win by having lost its late-filling days.

| Entry | n | fill | late | difference | better on | p | Bonferroni (15) | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fill+15 | 33 | −6.08% | +1.97% | **+8.04pp** | 69.7% | 0.0129 | 0.194 | 0.0058 |
| **fill+30** | 33 | −6.08% | +4.92% | **+11.00pp** | 66.7% | **0.0006** | **0.0090** | 0.0014 |
| fill+45 | 33 | −6.08% | +3.75% | +9.83pp | 72.7% | 0.0172 | 0.258 | 0.0152 |
| fill+60 | 33 | −6.08% | +1.53% | +7.61pp | 78.8% | 0.0603 | 0.904 | 0.0307 |
| fill+90 | 31 | −7.12% | +6.77% | +13.89pp | 77.4% | 0.0109 | 0.163 | 0.0044 |
| 10:00 | 21 | −7.06% | +7.30% | +14.35pp | 85.7% | 0.0043 | 0.065 | 0.0029 |
| 10:30 | 25 | −6.63% | +9.57% | +16.20pp | 76.0% | 0.0058 | 0.087 | **0.0007** |
| 12:30 | 28 | −8.88% | +11.82% | +20.70pp | 82.1% | 0.0141 | 0.212 | 0.0071 |
| 13:30 | 31 | −7.12% | +13.13% | **+20.25pp** | 74.2% | 0.0302 | 0.453 | 0.0110 |
| 14:30 | 33 | −6.08% | +6.42% | +12.50pp | 60.6% | 0.1345 | 1.000 | 0.0767 |

All 15 cells positive. **fill+30 survives Bonferroni over the 15-cell family (0.0090).** On the
pooled 120, the same test gives +2.86pp to +8.93pp, raw p 0.004–0.18, none surviving Bonferroni.

### 2.4 Execution realism and the one-bar-artifact check (diagnostic, not in the pre-declared grid)

The gap fill is detected *on* a one-minute bar close, so **fill+1 is the earliest minute a live
monitor could buy**. If the whole effect were a single spiky bar at the crossing it would appear at
fill+1.

| Entry | fires: return difference vs fill | p | fires: spot change | p |
|---|---:|---:|---:|---:|
| fill+1 | +0.64pp | 0.5674 | −2.67 pt | 0.1069 |
| fill+2 | +2.81pp | 0.0220 | −5.83 pt | 0.0071 |
| fill+3 | +1.98pp | 0.1620 | −5.64 pt | 0.0569 |
| fill+5 | +3.96pp | 0.0606 | −7.10 pt | 0.0386 |
| fill+10 | +5.94pp | 0.0266 | −13.53 pt | 0.0154 |

**Two conclusions.** (i) The published −6.08% is executable — moving entry to the first actionable
minute changes it by less than a point. No prior number needs correcting on this ground.
(ii) The advantage **accumulates over 30 minutes**, so it is not a stale or spiky entry bar and it is
not a one-minute measurement artifact of the "first crossing of a noisy series" kind, which would
revert immediately. On controls the same table is flat (+0.03pp to +1.61pp, all p>0.11).

### 2.5 Where the later entry's advantage comes from

| Offset | fires: mean spot change | p | fires: ATM premium change | controls: mean spot change | p |
|---|---:|---:|---:|---:|---:|
| fill+15 | **−15.14 pt** | 0.0152 | −2.72% | −2.89 pt | 0.3949 |
| fill+30 | **−20.97 pt** | 0.0030 | −0.79% | −5.16 pt | 0.3363 |
| fill+45 | −16.63 pt | 0.0362 | −3.75% | −8.21 pt | 0.1811 |
| fill+60 | −11.17 pt | 0.2158 | −5.70% | −10.36 pt | 0.1255 |
| fill+90 | −21.19 pt | 0.0620 | −2.65% | −12.90 pt | 0.1726 |

Waiting buys a **lower strike at a lower spot**. The ATM premium itself barely moves (the strike
re-pick offsets most of the spot decline), so the gain is not "the option got cheaper" — it is
"you did not sit through the adverse leg."

### 2.6 Is the E1 gain a Gate-B property? (placebo, difference-in-differences vs controls)

Both arms are defined by the identical first-crossing rule on the identical spot series, so any
mechanical first-passage artifact cancels in the difference.

| Entry | fires | controls | DiD | Welch p | permutation p (5,000) |
|---|---:|---:|---:|---:|---:|
| fill+15 | +8.04pp | +0.77pp | +7.27pp | 0.0382 | **0.0166** |
| fill+30 | +11.00pp | +2.13pp | +8.87pp | 0.0168 | **0.0248** |
| fill+45 | +9.83pp | +4.47pp | +5.35pp | 0.2494 | 0.2422 |
| fill+90 | +13.89pp | +6.03pp | +7.87pp | 0.2174 | 0.2366 |
| 10:00 | +14.35pp | +3.41pp | +10.94pp | 0.0404 | **0.0318** |
| 12:30 | +20.70pp | +4.08pp | +16.62pp | 0.0788 | 0.0746 |
| 13:00 | +19.22pp | +2.07pp | +17.15pp | 0.0667 | 0.0548 |
| 13:30 | +20.25pp | +1.46pp | +18.79pp | 0.0661 | **0.0364** |
| 14:30 | +12.50pp | +2.73pp | +9.77pp | 0.3065 | 0.2902 |

**Positive in all 15 cells; 4 significant at a raw 5%; none survives Bonferroni (0.0033).** The 15
cells are heavily overlapping, so the 15/15 sign pattern is not 15 independent confirmations —
it is one fact appearing fifteen times, the same caution that applies to the four trendiness
indicators. Read it as: the effect is plausibly Gate-B-specific but not established as such.

### 2.7 Stability

The late-minus-fill gain is positive in **both halves of the sample in all 15 cells** on the fires
and in 14 of 15 on the pooled population. By year on the fires it is positive in 4–6 years of 5–6,
with **2022 consistently negative** (−6pp to −27pp) and 2026 negative at the longer offsets. This is
markedly better behaved than the mid-IV filter (which was one bucket) or the dealer-gamma
coefficient (which was one year, 2023).

---

## 3. E1b — Volatility overpayment by entry clock

Implied volatility inverted from the traded entry premium under a **trading-time** maturity;
realised volatility of spot from entry to close annualised on the same clock.

| Entry | N | implied | realised | gap | p | held |
|---|---:|---:|---:|---:|---:|---:|
| fill (baseline) | 33 | 11.67% | 8.16% | **+3.51pp** | <0.0001 | 314m |
| fill+30 | 33 | 11.58% | 7.84% | +3.74pp | <0.0001 | 284m |
| 12:30 | 28 | 11.79% | 7.49% | +4.30pp | <0.0001 | 179m |
| 14:30 | 33 | 12.38% | 8.49% | +3.89pp | <0.0001 | 59m |

**The overpayment per unit of volatility does not shrink with a later entry** — if anything it is
mildly larger at midday. Late entry helps by shortening the *hold*, not by improving the price of
volatility. The pooled table is the same shape (+3.81pp at the fill, +4.61pp at 12:30).

### 3.1 A convention note on the previously quoted 6.7-point overpayment

The project file records "implied 15.26% at entry vs realised 8.52%, gap −6.74 points". The
calendar-convention diagnostic in this run recovers **15.63%** at the fill minute — i.e. that 15.26
was a *calendar-time* implied volatility, the convention `CORRECTION_GATE_B_VOL_CRUSH.md` retracted.
Inverted consistently in trading time the same premiums imply **11.67%**, and the overpayment is
**+3.51pp, not 6.74pp**. The sign, the persistence and the significance (p<0.0001) all stand; the
magnitude was roughly doubled by the convention. **Nothing about the P&L changes** — every return in
this project is traded-price to traded-price and model-free. This is the follow-up that correction
required, not a new retraction.

---

## 4. E2 — Conditional "buy when the trend is captured"

At clock *t*, buy only if the trend has confirmed by *t*; otherwise skip the day, P&L exactly zero,
**still counted in the denominator**. Grid pre-declared: 16 entry clocks × 9 confirmations = **144
cells per population**, run identically on fires, pooled and controls.

Confirmations: spot has moved ≥ {0, 10, 20, 30, 50} points in the gate direction since the fill;
spot above session VWAP (volume-weighted using total traded CALL-chain volume — the NIFTY index
itself has no volume, so this is the only genuine volume weighting available); spot at its trailing
15- and 30-minute high; trailing 30-minute straight-line R² above the cross-sectional median at that
clock (threshold computed on the whole 120-day pool so fires and controls face the same bar —
in-sample by construction and declared as such).

### 4.1 Against the correct benchmark, it finds nothing

**Benchmark discipline:** each conditional cell is compared with the E1 **unconditional cell at the
same clock**, on the identical denominator.

| Population | cells | positive conditional mean | **beat same-clock unconditional** | significant vs it at raw 5% | smallest p | Bonferroni |
|---|---:|---:|---:|---:|---:|---:|
| mid-IV N=33 | 144 | 106 | 23 | **0** | 0.0773 | 1.000 |
| pooled N=120 | 144 | 45 | 112 | **0** | 0.0588 | 1.000 |
| **controls N=87** | 144 | 28 | 140 | **19** | **0.0015** | 0.215 |

Seven of the fires' 144 cells never trade at all. The single best "conditioning" result on the
fires — Δ = +6.08pp — is the degenerate cell `fill / move≥10`, which selects **zero** days: it is
literally "never trade", a restatement of the existing VAL-05 verdict, not a timing discovery. The
best cell that actually trades is `fill+30 / above VWAP`: **+4.29pp, p=0.3873**.

### 4.2 The decomposition: it is selection, and the selection is not real

Exact additive split of (conditional at *t*) − (unconditional at the fill), residual 0.00e+00 in
every cell:

| Population | cell | N | selected | skip | conditional | uncond@t | Δ same clock | **timing** | **selection** |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mid-IV | 12:30 / higher-high-30 | 28 | 4 | 85.7% | +9.97% | +11.82% | −1.85pp (p=0.73) | +1.77pp | **+17.09pp** |
| mid-IV | 10:30 / above VWAP | 25 | 12 | 52.0% | +9.26% | +9.57% | −0.30pp (p=0.97) | +0.19pp | **+15.71pp** |
| mid-IV | fill+30 / above VWAP | 33 | 19 | 42.4% | +9.21% | +4.92% | +4.29pp (p=0.39) | +1.63pp | **+13.65pp** |
| pooled | 12:30 / R²>median | 96 | 49 | 49.0% | +2.65% | −0.97% | +3.62pp (p=0.14) | +3.35pp | **+9.19pp** |
| controls | 10:00 / move≥50 | 51 | 5 | 90.2% | +2.12% | −10.91% | **+13.03pp (p=0.027)** | −2.78pp | **+19.22pp** |
| controls | 12:30 / R²>median | 68 | 34 | 50.0% | +1.39% | −6.24% | **+7.63pp (p=0.004)** | −0.17pp | **+11.88pp** |

**Selection carries the entire result in every cell, on fires and controls alike.** Timing
contributes −4pp to +3pp. Skip rates run 42%–92%; on the fires' best cell the 24 skipped days would
have returned −19.93% at fill entry while the 4 selected days returned +57.44%.

That looks like a discriminating filter until you notice the controls do it *better*: **+19.22pp of
selection, 19 cells significant at raw 5%, best p=0.0015**, versus zero significant cells on the
real Gate B label. A filter that finds bigger, more significant "selection" on days the gate
rejects is finding path-dependence in the outcome, not a signal — it is close kin to the MFE
excursion problem already documented (`analyze_reversal_timing_extended.py`, control MFE 68.4 pt vs
fires 71.4 pt, p=0.73). Traded-only returns are reported beside the denominator-inclusive means in
the JSON, with holding periods and per-minute rates, because 4-of-28-day cells are not comparable
to full-sample cells on total return alone.

---

## 5. E3 — Intraday drift profile

Half-hour buckets on the grid already used by `gate_b_early_exit_scan.py` (09:15–09:30, 09:30–10:00,
… 15:00–15:29 — 13 buckets, of which 12 are usable because no fire fills before 09:30). Buckets
**entirely after the fill**, so every observation is a full-length bucket; permutation p over 5,000
reassignments of the fire label; Bonferroni over the 12 usable buckets.

| Bucket | n fires | fires | per min | n ctrl | controls | difference | perm p | Bonferroni |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 09:30–10:00 | 15 | −8.76 pt | −0.292 | 41 | +1.68 pt | −10.44 pt | 0.4722 | 1.000 |
| 10:00–10:30 | 21 | −0.27 pt | −0.009 | 55 | −3.91 pt | +3.64 pt | 0.7186 | 1.000 |
| 10:30–11:00 | 25 | +4.31 pt | +0.144 | 62 | −4.10 pt | +8.42 pt | 0.4068 | 1.000 |
| 11:00–11:30 | 28 | +1.51 pt | +0.050 | 64 | +3.77 pt | −2.26 pt | 0.7382 | 1.000 |
| 11:30–12:00 | 28 | −5.32 pt | −0.177 | 64 | +1.21 pt | −6.53 pt | 0.3712 | 1.000 |
| 12:00–12:30 | 28 | −3.56 pt | −0.119 | 68 | +2.16 pt | −5.72 pt | 0.4160 | 1.000 |
| 12:30–13:00 | 28 | +2.01 pt | +0.067 | 68 | +4.04 pt | −2.03 pt | 0.8004 | 1.000 |
| 13:00–13:30 | 30 | +2.96 pt | +0.099 | 72 | +0.18 pt | +2.78 pt | 0.6504 | 1.000 |
| 13:30–14:00 | 31 | +8.56 pt | +0.285 | 77 | −1.16 pt | +9.72 pt | 0.2242 | 1.000 |
| 14:00–14:30 | 31 | −1.32 pt | −0.044 | 77 | +1.46 pt | −2.79 pt | 0.6788 | 1.000 |
| **14:30–15:00** | 33 | **+12.40 pt** | +0.413 | 80 | −1.66 pt | +14.06 pt | **0.0346** | 0.415 |
| 15:00–15:29 | 33 | +7.77 pt | +0.268 | 83 | −3.41 pt | +11.18 pt | 0.0886 | 1.000 |

**Plain answer: the move is not spread evenly, and it is not simply "back-loaded" either. The path
is a V.**

The context number that makes sense of everything above: the **fill-to-close spot move on Gate B
fires is +5.25 points, median −4.50, up on only 45.5% of days, p=0.7376** (controls −4.96 pt,
p=0.7105; difference +10.21 pt, Welch p=0.6192). *There is essentially no net move from the fill to
the close.* Cumulative mean signed move from the fill, common sample of 21 fires that filled by
10:00 (controls, 55 days, in brackets):

`10:00 −29.3 (−9.3) · 11:00 −30.4 (−16.5) · 12:00 −30.6 (−10.4) · 12:30 −33.3 (−6.1) · 13:00 −32.3
(−0.6) · 13:30 −27.4 (−2.3) · 14:00 −24.3 (−7.6) · 14:30 −17.3 (−7.1) · 15:00 −6.0 (−10.5)`

Gate B days drop about **30 points below the fill and stay there for four hours**, then recover into
the close to finish roughly flat. Post-fill spot drift confirms it directly: −7.10 pt at +5 min
(p=0.0386), **−23.43 pt at +20 min (p=0.0006)**, −20.97 pt at +30 min (p=0.0030), −27.93 pt at
+180 min (p=0.0512). The fire-minus-control differences are −4 to −19 pt with permutation p 0.06 to
0.97 — the *level* of the pullback is not established as Gate-B-specific even though the paired
option result in §2.6 is.

**Attribution.** The brief asked which of (a) selection, (b) back-loaded drift, (c) conditional
drift explains any positive result. It is **(b), in a form worth naming precisely: front-loaded
adverse drift rather than back-loaded favourable drift.** The reason a later entry works is not that
it captures a concentrated late move at a fraction of the cost; it is that it **skips a systematic
early loss**. Only the last two buckets carry the favourable move and neither survives Bonferroni.
(a) is excluded by construction — E1 skips no days. (c) is directly rejected by E2.

---

## 6. E4 — Placebo on the whole search

**Grid on controls.** The entire 144-cell E2 grid, unchanged, on the 87 VIX-rose non-Gate-B fill
days. Best control cell **+2.12%** (`10:00 / move≥50`) versus best fire cell **+9.97%**
(`12:30 / higher-high-30`). On raw conditional mean the fires look better — but on the
benchmark-disciplined statistic the controls win outright: **Δ vs same clock +13.03pp, p=0.027**
against the fires' +4.29pp, p=0.387, and **19 control cells significant at raw 5% against zero fire
cells**.

**Shuffled-label permutation of the whole search.** The 33-day fire label reassigned at random among
the 120 pool days, 2,000 draws, scoring the best-of-grid statistic:

| Statistic | observed | placebo median | placebo p90 | empirical p |
|---|---:|---:|---:|---:|
| best-of-grid conditional mean | +9.97% | +7.67% | — | **0.258** |
| best-of-grid Δ vs **same-clock** unconditional (never-trade cells excluded) | +4.29pp | **+12.50pp** | — | **0.9595** |

On the statistic that respects the benchmark, **the real Gate B label performs worse than the median
random label.** The E2 grid found noise. This must not be buried: a reader who saw only §4.2's
"+17.09pp of selection" would reasonably conclude the confirmation filter works, and it does not.

**E1 is not touched by this placebo** — E1 conditions on nothing and skips no days, and its own
placebo is the difference-in-differences in §2.6.

---

## 7. Verification

| Check | Result |
|---|---|
| N stated for every cell | Yes — every table above, and every entry in the JSON, carries N, the count dropped because the fill came after the clock, and the count unpriceable. |
| **ATM strike re-picked at the entry minute** | **17 of 28** fires with a 12:00 entry buy a different strike at 12:00 than at the fill (60.7%). |
| Worked example | **2023-01-04**: gap fills 09:31, spot 18235.35 → strike **18250**; at 12:00 spot 18071.10 → strike **18050**, a 200-point difference — four strikes apart. |
| No calendar-time IV inversion | Exactly **one** code line in either script contains a 365-day year, and it is inside the explicitly labelled `t_cal` calendar *diagnostic* used only for the §3.1 reconciliation. Every reported implied volatility uses 375 min/session × 252 sessions/yr. |
| No BS-proxy premium in any headline | **Zero** code lines in either script read `bs_prices` or `C0_bs`. `bs_call` is imported solely as the inversion target for implied volatility. |
| E2 benchmark is the same-clock unconditional cell | Yes — `unconditional_same_clock` in every cell, on the identical denominator; `delta_same_clock_pp` and its paired p are the reported statistic, and the fill-entry comparison is carried separately and decomposed. |
| Baseline reproduces published Gate B | −6.08% / −13.46% on N=33 and −7.61% / −13.22% on N=120; max per-day difference **0.00e+00pp** over 120 days. `reproduction_guard` passes. |
| Decomposition is exact | Residual (Δ vs fill − timing − selection) is 0.00e+00 to 7×10⁻¹⁵ across all 432 cells. |

**Hand check against the raw archive CSVs** — 2023-01-04, both entries, re-read from
`dhan_fresh_2021_2026` with the manifest, nothing cached consulted:

| | entry clock | strike | raw entry close | raw exit (15:29) | raw return | panel return | match |
|---|---|---:|---:|---:|---:|---:|---|
| fill entry | 09:31 | 18250 | ₹57.70 | ₹8.70 | −84.9220% | −84.9220% | ✅ |
| 12:00 entry | 12:00 | 18050 | ₹87.00 | ₹57.00 | −34.4828% | −34.4828% | ✅ |

Note this day is *not* cherry-picked to flatter the finding: it is the largest strike-gap example,
and both entries lose. It demonstrates the re-pick and the pricing chain, not the result.

**Power.** At α=5% and 80% power, the minimum detectable mean is **23.71pp** on the N=33 fill cell,
**11.62pp** on the N=120 cell, and **22.82pp** for the paired 12:30-minus-fill test on N=33 — where
the observed effect is +20.70pp. The study therefore had **slightly under 80% power to detect the
effect it found**; the finding sits on the resolution boundary. The established grid-resolution
limit stands: at N=120 the spread across cells that N can resolve is ~9.69pp, so the *ranking* of
E1 cells against each other (10:30 vs 13:30, say) carries no information. Only the fill-versus-later
contrast does, and only because it is paired.

---

## 8. Limitations and open questions

1. **In-sample, all of it.** These are the same 33 days that defined Gate B. Nothing here is
   walk-forward. The E1 result is the first thing in the Gate B branch that would be worth an
   honest out-of-sample test, and it has not had one.
2. **Multiplicity is real.** 16 entry cells, 144 conditional cells per population, plus the paired,
   DiD, stability and drift families. `fill+30`'s paired p=0.0006 survives Bonferroni within its
   own 15-cell family; it has not been corrected across the whole run.
3. **The 15/15 sign patterns are one fact, not fifteen.** Adjacent entry clocks on the same 33 days
   are near-perfectly correlated. Treat the sign consistency as coherence, not as independent
   replication — the same caution that applied to the four trendiness indicators.
4. **The pullback's cause is unidentified.** A first-passage selection effect on a noisy
   one-minute series would produce a pullback; so would genuine short-horizon reversal after a
   momentum spike; so would a real intraday demand pattern. The +1-minute test (§2.4) rules out the
   single-bar version, and the option tape independently prices the move, but a slower
   noise-reversion process over 10–30 minutes is not excluded by anything measured here.
5. **The fill-to-close move is ~zero (+5.25 pt, p=0.74, up on 45.5% of days).** Gate B's whole
   premise is a reversal continuing after the fill. On real spot over these 33 days it does not. The
   directional hit-rate statistic (84.8%) is measured on a different object (`initial_high_first` vs
   `target_high_first`) and does not contradict this, but the two should be reconciled explicitly
   before Gate B is discussed again.
6. **Costs are not applied here.** `gate_b_exit_grid_real.py`'s cost model would take roughly 1–2pp
   off every cell. The fill-versus-later *difference* is largely cost-neutral (one round trip
   either way), so §2.3 is unaffected, but the absolute levels in §2.1 are gross.
7. **Bar close is not a fill.** Every price is a one-minute bar close, not a marketable quote. The
   spread on a NIFTY weekly ATM CALL is a further real cost, and it is not modelled.
8. **2022 dissents.** The late-entry gain is negative in 2022 in 13 of 15 cells, and negative in
   2026 at the longer offsets. With 4–8 fires per year, one adverse year is not a refutation, but it
   is the pattern that killed the dealer-gamma result and it should be watched.
9. **Not tested, and deliberately so:** any exit rule other than hold-to-close (four null grids
   already), any instrument other than the ATM CALL, gap-up or non-mid-IV Gate B variants, and
   whether the post-fill pullback exists on Gate A days.

**What this does not change.** VAL-05 remains failed. The parked decision in the project record —
recording VAL-05 as failed and changing `GAP_FILL_SIGNAL_MODULE_SPEC.md`'s Gate B branch from
"hold to close, +1.8%" to "do not arm" — is untouched by this work and still awaits Aryan's explicit
word. Nothing in this report was written to any spec, traceability or findings file, and no gate was
armed.
