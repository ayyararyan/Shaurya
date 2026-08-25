# Does ex-ante dealer gamma predict BREAKOUT follow-through? — and is the "2023 only" result an artefact?

**Date:** 2026-08-23 · **Status:** exploratory, off the traceability matrix · **No spec change, no gate armed.**
**Trigger:** Aryan, 2026-08-23 12:16 — *"dealer gamma exposure and open interest gave no result, or a result
only in 2023 that looks very fishy. Dealer gamma is common among practitioners, so no signal on the breakout
looks wrong. Check."*

Files: `nge_breakout_test.py`, `nge_breakout_results.json`, `nge_breakout_panel_OR15.csv`,
`nge_breakout_panel_OR30.csv`. Population and regressors from the audited `nge_panel.csv` (1,320 sessions,
2021-01-01 … 2026-05-12). Offline only; no broker or order path.

---

## 0. The finding that matters most: the practitioner claim was never tested

`NGE_PATH_QUALITY_TEST.md` regressed **session-average 5-minute return autocorrelation (ρ₁)** on a
**continuous, linear** gamma-imbalance term, unconditionally, over all sessions.

The practitioner claim is a different object. It is **conditional on an event** (price breaks a level) and
**sign-dependent** (dealers short gamma amplify; dealers long gamma suppress). Grepping the 1,109-line
report: **zero occurrences** of `breakout`, `regime`, `negative gamma`, `zero-gamma`, `flip level`, or any
sign-split specification. `gate_b_breakout_threshold.py` (run 11:59 today) contains **no gamma or
open-interest variable at all**.

**So Aryan's instinct is correct on the point of fact: the existing null is a null on a different question.**
The breakout version is tested here for the first time.

## 1. Design (registered before running)

- **Event, spec OR15:** opening range = high/low of spot minute closes 09:15–09:29; breakout = first minute
  from 09:30 whose close exits that range. First passage only; direction = the side exited.
- **Event, spec OR30:** identical with a 09:15–09:44 range, from 09:45.
- **Ex-ante regressors, all read at 09:15** from the snapshot whose ex-ante status §1 of the NGE report
  verifies decisively (09:15 OI sits 3.7% from the *prior* session's close, 35% from its own):
  `g10` = gamma imbalance (calls − puts)/(calls + puts) over ±10 strikes; `g3` = the ±3 near-ATM version;
  `neg_gamma` = 1{gex < 0}.
- **Outcomes:** `ft_pct` = signed follow-through from the breakout close to 15:29, in the breakout
  direction, % of spot (primary); `mfe` beyond the break; `failed` = price re-enters the opening range.
- **7 registered tests per spec, 14 total. Bonferroni α = 0.0036.** Placebo: 2,000 label shuffles of the
  gamma regressor against the primary t. Seed 20260823.

## 2. Base rates — worth having independently of gamma

| | OR15 | OR30 |
|---|---:|---:|
| sessions with a breakout | 1,320 (100%) | 1,318 (99.8%) |
| upside share | 49.1% | 49.3% |
| mean follow-through to close | **−0.008%** | **+0.017%** |
| median follow-through | −0.002% | +0.032% |
| **breakout re-enters the range** | **91.9%** | **91.7%** |

An opening-range breakout on NIFTY is not a rare event, it is a daily one, its expected continuation is
zero, and **it comes back inside the range 92% of the time.** That is the honest base rate any dealer-gamma
overlay has to beat.

## 3. Results

### OR15 — nothing, in any specification

| test | result |
|---|---|
| T1 follow-through on `g10` | β +0.060, t **+0.59**, p 0.56, R² 0.03% — *wrong sign* |
| T1 Spearman | +0.017, p 0.53 |
| T2 near-ATM `g3` | t +0.75, p 0.45 |
| T3 regime, negative vs positive gamma | −0.020% vs −0.005%, diff **−0.015%**, Welch p 0.77, MW p 0.89 — *wrong sign* |
| T4 quintile ladder | non-monotone (−0.031, −0.033, +0.026, +0.008, −0.008) |
| T5 failure rate, low vs high gamma | 91.6% vs 93.2%, Fisher p 0.45 |
| T6 \|follow-through\| | t −1.63, p 0.10 |
| T7 MFE beyond the break | t −0.91, p 0.36 |
| placebo (2,000 shuffles) | obs \|t\| 0.585 vs placebo median **0.659**, empirical p **0.55** — the random label does better |

### OR30 — the practitioner sign appears, consistently, and nothing is significant

| test | result |
|---|---|
| T1 follow-through on `g10` | β −0.133, t **−1.39**, p 0.16 — *correct sign* |
| T1 Spearman | −0.052, p 0.061 |
| T2 near-ATM `g3` | t −1.38, p 0.17 — correct sign |
| T3 regime | negative gamma **+0.055%** vs positive **+0.008%**, diff **+0.047%**, Welch p 0.30 — correct sign |
| T4 quintile ladder | +0.048, +0.031, +0.059, **−0.008**, **−0.048** — broadly monotone, low gamma continues |
| T5 failure rate | low gamma **90.0%** vs high gamma **93.0%**, Fisher p 0.12 — correct sign, monotone across quintiles (88.6 → 92.0 → 91.3 → 92.4 → 93.9) |
| T6 \|follow-through\| | t −1.16, p 0.25 |
| T7 MFE beyond the break | β −0.167, t **−2.50, p 0.0125** — correct sign, **fails Bonferroni 0.0036** |
| placebo | obs \|t\| 1.394 vs placebo median 0.683, empirical p **0.15** |

**Reading.** Six of seven OR30 statistics carry the Barbon–Buraschi / SqueezeMetrics sign, and the failure
ladder is monotone across all five quintiles. That is more coherence than chance usually delivers. But the
single best p-value in fourteen registered tests is 0.0125 against a 0.0036 threshold, the primary test's own
placebo returns p = 0.15, and the Q1−Q5 follow-through spread is 0.096% of spot ≈ **24 NIFTY points**, which
one-minute weekly-option spreads eat before any of it reaches an account.

**Verdict: not established, not refuted, and pointing the right way at OR30 only.** This is a lead, not a
result. The honest statement is that the study is **underpowered against an effect this size**, not that the
effect is absent.

### The breakout channel is not a 2023 story

Per-year t on the primary, OR30: 2021 −0.53, 2022 −0.66, **2023 +0.45 (wrong sign)**, **2024 −1.92**,
2025 +0.64, 2026 −1.09. The ρ₁ result lives in 2023; whatever is in the breakout channel is in 2024. If one
lucky year were driving both, it would be the same year. It is not.

## 4. Is "2023 only" an artefact? — three checks, no artefact found

1. **Arithmetic reproduces.** The report's per-1-sd β = −0.0320 for 2023 equals the raw β −0.2563 × sd(gimb)
   0.125. No scaling error. Full-sample −0.0086 = −0.0268 × 0.150. Consistent.
2. **2023 is internally robust, which rules out the cheap explanations.** Both halves of 2023 are
   individually significant (H1 β −0.225, t −2.09, n 122; H2 β −0.273, t −3.13, n 123). Trimming the extreme
   2.5% of the regressor leaves β −0.234, t −2.77, p 0.006. It is not one or two outlier days.
   It is also **not** a variance artefact: 2023 has the **lowest** gamma-imbalance dispersion of any year
   (sd 0.125 against 0.14–0.27), which should *reduce* the t-statistic, not inflate it.
3. **The truncation/measurement-error story does not fit either.** 2023 had by far the lowest median opening
   IV (13.3 vs 17–22), so ±10 strikes captures more of the true chain gamma and the regressor is least
   attenuated — but slicing **all** years by opening IV puts the lowest-IV quartile at t −1.48 (p 0.14),
   where 2023 supplies 120 of 330 days. The mechanical explanation predicts the wrong quartile.

**One thing the year-split hides.** Slicing on opening IV rather than calendar, the **third** IV quartile
(IV 17.1–22.3) gives β −0.139, t **−3.17**, p 0.0017, n 330 — and it survives **dropping 2023 entirely**:
β −0.130, t **−2.80**, p 0.0054, n 288. So "the effect exists only in 2023" is **not exactly right**; there
is a second, non-2023 pocket at mid-to-high implied volatility. It is a post-hoc slice found inside a study
that has already run 81 registered tests (Bonferroni over 4 quartiles → 0.022), so it is a lead, not a
finding, and it needs data this project has not touched.

## 5. What was newly tested and came back null

The **regime test on ρ₁** — the natural form of the practitioner claim, and never previously run:
negative net gamma ρ₁ = −0.0528 (n 226) vs positive −0.0612 (n 1,094), diff +0.0084, p **0.37**; excluding
2023, diff **+0.0001, p 0.996.** The pooled quintile ladder on ρ₁ is non-monotone ex-2023
(−0.059, −0.037, −0.072, −0.061, −0.072). **There is no gamma-flip effect on session path shape.**

## 6. What would actually settle it

1. **NSE participant-wise open interest** (free, daily, FII/DII/Pro/Client). The §9.4 objection — that the
   gamma legs are reproduced by *where* the OI sits relative to spot — is fatal to the dealer-position
   reading and cannot be resolved from this archive. This remains the highest-value acquisition.
2. **A wider strike chain and non-WEEK1 expiries.** Current measure is nearest-weekly, ±500 points. The
   OR30 lead sits at exactly the effect size that measurement error would attenuate.
3. **A directional-move-magnitude outcome rather than a P&L outcome.** T7 (MFE beyond the break) is the
   strongest statistic in the file, and it is the one closest to the actual mechanism — dealers hedging push
   the move further, they do not make it end higher.
