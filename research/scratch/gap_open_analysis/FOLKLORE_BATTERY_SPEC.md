# Indian Options Folklore Battery — Frozen Specification

**Date:** 2026-08-23
**Requested by:** Aryan (voice, 12:53 IST): *"test some really dumb and stupid hypotheses that
are possible in Indian markets… if it works statistically significant then it works… very
simple, you don't need hundreds of parameter optimization or stop losses or take profits…
find me if there are any statistically significant candidates that survive."*
**Status:** Exploratory screening battery. No gate armed. No change to any Gate A / Gate B
specification. Offline analysis; no broker, no credential, no order path.

---

## 1. Design principle

Every hypothesis below is **a single rule with zero free parameters**: no stop-loss, no
take-profit, no threshold search, no indicator tuning. This is deliberate and is Aryan's
explicit instruction. It has a statistical benefit — with no researcher degrees of freedom
inside each rule, a Bonferroni correction across the registered family is an honest
correction rather than a fig leaf.

Each hypothesis is sourced from Indian retail trading folklore found on the open web, not
invented here. Provenance is recorded per hypothesis.

## 2. Common protocol (applies to every hypothesis)

| ID | Requirement |
|---|---|
| PROT-01 | One number per session per hypothesis. Non-overlapping windows only. Report N. |
| PROT-02 | One-sample t-test against zero **and** Wilcoxon signed-rank. Report both. |
| PROT-03 | **Registered family size = 15.** Report the Bonferroni threshold (0.05/15 = 0.00333) next to every nominal p. A result is called a *survivor* only if it clears Bonferroni. |
| PROT-04 | For every *conditional* rule (one that selects a subset of sessions or a direction from a signal), run a **shuffled-label placebo**: permute the conditioning variable 2,000 times, `SEED = 20260823`, and report observed \|t\| against the placebo distribution with an empirical p. |
| PROT-05 | Report the lag-1 autocorrelation of each P&L series as a diagnostic. Daily non-overlapping observations are assumed independent; if ρ₁ is large, say so. |
| PROT-06 | Report per-year breakdown for every hypothesis. A result driven by one year is a lead, not a finding. |
| PROT-07 | **Breakeven cost.** For every option-leg hypothesis, report the round-trip transaction cost (in % of entry premium) that would reduce the mean to exactly zero. This converts "significant" into "significant by how much room". |
| PROT-08 | **Tail report.** For every hypothesis, report the worst single session, the worst five sessions, the max drawdown of the cumulative series, and the 1st/99th percentiles. Because no stops are used (by instruction), the tail is fully exposed and a positive mean with a catastrophic tail is not a strategy. |

## 3. Registered hypotheses

### A. Option selling

| ID | Rule | Folklore source |
|---|---|---|
| H1 | `SELL_STRADDLE_0920_ALL` — sell the ATM straddle at 09:20, buy it back at 15:29, every session. | The "9:20 short straddle", an Indian retail staple |
| H2 | `SELL_STRADDLE_0920_EXPIRY` — same rule, **expiry sessions only**. | "Theta decay is maximum on expiry day; premiums lose 50–80% in a session" |
| H3 | `SELL_STRADDLE_0920_NONEXPIRY` — same rule, non-expiry sessions. Control for H2. | complement |
| H4 | `SELL_STRADDLE_OVERNIGHT` — sell the ATM straddle at 15:29, buy it back at the next session's 09:15. | "Never hold options overnight / over the weekend", tested from the seller's side |
| H5 | `SELL_STRADDLE_HIGH_IV` — sell the 09:20 ATM straddle only when `atm_iv_open` exceeds its **trailing (past-only) median**; hold to 15:29. | "Sell premium when IV is high" |
| H6 | `SELL_STRADDLE_BY_DTE` — the 09:20→15:29 straddle P&L bucketed by `sessions_to_expiry`. | "Sell early in the week, buy near expiry" |

### B. Option buying

| ID | Rule | Folklore source |
|---|---|---|
| H7 | `BUY_OTM_EXPIRY_LOTTERY` — buy the ATM+5 CALL and the ATM−5 PUT at 09:20 on expiry day, hold to 15:29. | The expiry-day OTM lottery ticket |
| H8 | `BUY_STRADDLE_LOW_IV` — buy the 09:20 ATM straddle when `atm_iv_open` is below its trailing median. | The mirror of H5 |

### C. Directional spot folklore

| ID | Rule | Folklore source |
|---|---|---|
| H9 | `GAP_FADE` — if the 09:15 spot is above the previous 15:29 close, go short; if below, go long. Hold to 15:29. | "Gaps fill"; a widely repeated Indian intraday setup |
| H10 | `GAP_CONTINUATION` — the exact mirror of H9. Reported alongside; counts as one registered test with H9. | the opposing claim |
| H11 | `PCR_CONTRARIAN` — total put OI / total call OI across the available chain at 09:15; above its trailing median → long, below → short. Hold to 15:29. | PCR as a contrarian sentiment rule (claimed bands 0.7–1.3) |
| H12 | `WEEKDAY` — mean 09:15→15:29 spot return by weekday (5 cells; joint F-test, then per-cell). | weekday seasonality folklore |
| H13 | `OVERNIGHT_VS_INTRADAY` — decompose the NIFTY total return into overnight (prev 15:29 → 09:15) and intraday (09:15 → 15:29); test each against zero and against the other. | "all the gains happen overnight" |

### D. Expiry-day structure

| ID | Rule | Folklore source |
|---|---|---|
| H14 | `MAX_PAIN_PIN` — compute the max-pain strike from the 09:15 OI chain. On expiry sessions test whether \|close − maxpain\| < \|open − maxpain\|. Controls: (a) the same statistic on non-expiry sessions, (b) a placebo pin drawn at random from the available strikes. | "Max pain pins the expiry", claimed 60–70% accuracy |
| H15 | `ROUND_NUMBER_PIN` — is \|close mod 100 − 50\| larger than a uniform draw implies, i.e. does the close sit closer to a 100-multiple than chance? Test on expiry vs non-expiry sessions. | round-number magnetism folklore |

## 4. Data

| ID | Requirement |
|---|---|
| DATA-01 | Spot minute closes via `analyze_still_water_spot.load_spot()`, 09:15–15:29. |
| DATA-02 | Option minute bars from `nge_common.CACHE` (2,772 CSVs, WEEK1 expiry, ATM−10..ATM+10, CALL and PUT, 2021–2026). Enumerate via `nge_common.manifest_rows()` / `cached_path()`. |
| DATA-03 | Dedup convention identical to `nge_common.build_snapshot`: key `(date, clock, side, strike)`, keep highest `volume`. |
| DATA-04 | Session metadata (`is_expiry_day`, `sessions_to_expiry`, `atm_iv_open`) from `nge_panel.csv`. **Use `is_expiry_day`, never a hardcoded weekday** — NIFTY weekly expiry moved from Thursday to Tuesday on 2025-09-01. |
| DATA-05 | ATM and ATM±5 resolved on the **absolute strike** nearest the spot at the entry minute, never the rolling `rel_strike` filename label. |
| DATA-06 | Cache the 09:15 / 09:20 / 15:29 bars of the chain to a **new** `.pkl` filename. Do not overwrite `nge_open_snapshot.pkl` or any existing cache. |

## 5. Known limitations that must be stated in the report

- **No bid–ask.** All option P&L is traded-close to traded-close. This flatters **both**
  buyers and sellers. PROT-07's breakeven cost is the honest way to read every option result.
- **Truncated chain.** The archive holds ATM−10..ATM+10 only. Max pain (H14) and PCR (H11)
  computed on a truncated chain are **proxies** for the full-chain quantities, not the
  quantities themselves. Label them as proxies (working contract §7.1) and say so wherever
  they appear.
- **WEEK1 expiry only.** No WEEK2/WEEK3, no monthly, no futures tape.
- **No margin model.** Short-straddle results are gross of SPAN margin and of any
  intraday margin call. Report the tail (PROT-08) so the omission is visible.
- **No stops or targets, by instruction.** Every tail is fully realised.

## 6. Outputs

| ID | Artifact |
|---|---|
| OUT-01 | `FOLKLORE_BATTERY_RESULTS.md` — the report, led by a single summary table: hypothesis, N, mean, t, nominal p, Bonferroni pass/fail, placebo p, breakeven cost, worst session. |
| OUT-02 | `folklore_battery_panel.csv` — one row per session per hypothesis. |
| OUT-03 | `folklore_battery_results.json` |
| OUT-04 | `folklore_battery.py` |

## 7. Completion criteria

All 15 hypotheses run or explicitly reported as Blocked with a reason. PROT-01..08 reported
for each. The report must open with an explicit list of **survivors after Bonferroni** — and
must say "none" if none survive, without softening.
