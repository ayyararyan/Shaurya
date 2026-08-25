# VRP-on-Breakout Test — Frozen Specification

**Date:** 2026-08-23
**Requested by:** Aryan (voice, 12:33 IST): *"Let us actually run this test and see. I want to
see what the results look like."*
**Status:** Exploratory. No change to any Gate A / Gate B specification. No gate armed.
No broker, no credential, no order path. Offline analysis only.

---

## 1. Research question

Conditional on an opening-range breakout in NIFTY, does realised volatility over the
remaining session exceed the at-the-money implied volatility prevailing **at the moment of
the break**?

## 2. Why it matters

The retail ORB folklore (e.g. the Groww 5-minute ORB article) instructs the trader to buy an
ATM option on the break. Buying the option is only the correct instrument if realised
volatility after the break exceeds the volatility embedded in the premium being paid. If the
variance risk premium remains positive conditional on the break, then the correct expression
of the same view is **short vol on the breakout, not long** — and this holds *independently*
of whether the directional signal exists at all. That makes this test separable from, and
logically prior to, the direction question already answered in `NGE_BREAKOUT_TEST.md`.

Existing project results this must be read against:
- `NGE_BREAKOUT_TEST.md`: a breakout occurs on 100% of sessions; expected continuation to
  close is zero; price re-enters the range 92% of the time.
- `CORRECTION_GATE_B_VOL_CRUSH.md`: Gate B's apparent entry-to-close IV decline was a
  **calendar-time measurement artifact**. Any IV work in this project must use a
  **trading-time** maturity convention.
- `GATE_A_HORIZON_CENSORING.md` §6: on same-day-expiry options there *is* a genuine opening
  IV crush (~1 IV point by 20 minutes, ~3 by an hour), unaffected by that artifact.

## 3. Estimand

    VRP_break = IV_ATM(break)  −  RV(break → 15:29)

Both annualised in the **same** trading-time convention (375 minutes per session, 252
sessions per year). Units: volatility points. Positive VRP = the option was expensive
relative to what the market subsequently delivered = seller's edge.

Primary reported objects: mean, median, standard deviation, share of sessions with
VRP_break > 0, and tests against zero.

---

## 4. Requirements

### Data

| ID | Requirement |
|---|---|
| DATA-01 | Session universe = `nge_panel.csv`, the already-audited NGE panel. Report N and date span. |
| DATA-02 | Spot minute closes via `analyze_still_water_spot.load_spot()`, restricted to 09:15–15:29. |
| DATA-03 | Option minute bars from the hydrated local archive at `nge_common.CACHE` (2,772 CSVs, WEEK1 expiry, ATM−10..ATM+10, 2021–2026). Enumerate via `nge_common.manifest_rows()` / `nge_common.cached_path()`. Use columns `close, iv, strike, oi, spot, datetime, volume`. |
| DATA-04 | Deduplication convention identical to `nge_common.build_snapshot`: key `(date, clock, side, strike)`, keep the highest-`volume` row. Two `rel_strike` files can describe the same absolute contract. |

### State construction

| ID | Requirement |
|---|---|
| STATE-01 | Breakout event = `nge_breakout_test.breakout_row()`, **imported and reused unchanged**. Both specs: OR15 (range 09:15–09:29, scan from 09:30) and OR30 (range 09:15–09:44, scan from 09:45). Do not reimplement the breakout logic. |
| STATE-02 | ATM strike at the break = the archive strike closest to spot at the breakout minute, resolved on the **absolute strike**, never on the rolling `rel_strike` filename label. |
| STATE-03 | `IV_ATM(break)` = own Black–Scholes inversion (r = `nge_common.RISK_FREE_RATE` = 0.065) from the traded `close` of the ATM CALL and the ATM PUT at the breakout minute, averaged. **Trading-time maturity (STATE-04).** The vendor `iv` column must NOT be used for the headline; carry it as a secondary column for comparison only. |
| STATE-04 | `T(break)` in trading-time years = `[minutes remaining in the trade session after the break + 375 × (sessions_to_expiry − 1)] / (375 × 252)`. Sessions from `nge_common.trading_sessions_between` against the archive session list. |
| STATE-05 | `RV(break → 15:29)`, annualised = `sqrt( mean(r_i²) × 375 × 252 )`, with `r_i` the 1-minute log spot returns from the breakout minute to 15:29. Report `n_minutes` per session. No overnight period is involved, so no overnight-gap estimator is required. |
| STATE-06 | `RV(09:15 → break)` computed identically, as a descriptive companion. |

### Estimation

| ID | Requirement |
|---|---|
| EST-01 | `VRP_break` per STATE definitions. Report mean, median, sd, share > 0, one-sample t-test and Wilcoxon signed-rank against zero. |
| EST-02 | **Placebo.** For each session, draw pseudo-break minutes from the empirical time-of-day distribution of *actual* break minutes (matched to the same distribution, same session), and compute `VRP_placebo` by the identical pipeline. ≥200 draws per session, `SEED = 20260823`. Report the mean placebo and the **paired** `VRP_break − VRP_placebo` test. This isolates whether the breakout *event* changes the premium, or whether it merely reflects the unconditional level. |
| EST-03 | Splits: breakout direction (up/down); OR15 vs OR30; year; expiry-day vs not; opening-IV quartile; dealer net-gamma sign (`gex_otm_trade_w10 < 0`); and the `failed` breakout label from `breakout_row`. |
| EST-04 | **Direct instrument check.** Model-free realised P&L of buying the ATM option at the break and holding to 15:29, traded `close` to traded `close`, in % of premium: (a) the directional option (CALL on an up-break, PUT on a down-break), and (b) the ATM straddle. Report mean, median, win rate, and the paired comparison against the spot-points leg over the identical window. |

### Validation

| ID | Requirement |
|---|---|
| VAL-01 | **Reproduction guard.** Recompute `atm_iv_open` for a sample of dates from the 09:15 bar under this module's own inversion, and report the correlation and mean level difference against the panel's vendor-derived `atm_iv_open`. A large divergence must be reported explicitly, not silently absorbed. |
| VAL-02 | **Multiple-testing ledger.** Register every test before running. Report the count and the Bonferroni threshold alongside every nominal p-value. |
| VAL-03 | **Lookahead audit.** Every quantity defining the event uses only information at or before the break minute; `IV_ATM(break)` uses the break minute only. State the check performed, not merely the intent. |
| VAL-04 | Report the hydration/coverage rate: sessions in the panel, sessions with a resolvable breakout, sessions with an ATM quote at the break minute, and the final N. Do not silently drop sessions. |

### Outputs

| ID | Artifact |
|---|---|
| OUT-01 | `VRP_BREAKOUT_TEST.md` — the report |
| OUT-02 | `vrp_breakout_panel_OR15.csv`, `vrp_breakout_panel_OR30.csv` |
| OUT-03 | `vrp_breakout_results.json` |
| OUT-04 | `vrp_breakout_test.py` — the script |

## 5. Explicit exclusions

- No bid–ask spread modelling. Traded closes only. **This makes every option result an
  upper bound on what a real trader achieves** — state this in the report.
- No brokerage, STT, or other transaction costs.
- No change to any Gate A / Gate B specification; no gate armed; no live path.

## 6. Completion criteria

All of OUT-01..04 produced; every requirement above either Implemented or explicitly
reported as Blocked/Unidentified with a reason; VAL-01..04 reported; the headline estimand
reported with its placebo comparison and its multiple-testing context.
