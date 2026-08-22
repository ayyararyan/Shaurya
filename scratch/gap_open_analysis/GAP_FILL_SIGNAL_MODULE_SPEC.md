# Gap-fill conditioned continuation/reversal signal — module spec (draft, 2026-08-22)

**Status: spec only, not built, not validated out-of-sample, no live order authorized.**
See `FINDINGS_SUMMARY.md` addendum for the full evidence trail this spec is based on.

## Purpose

A simple, rule-based (no ML) daily classifier for NIFTY open-session behavior. It routes each
trading day into one of three states using four inputs that are all observable by/during the
session, and nothing else:

1. `is_expiry_day` (known at day start)
2. `vix_rose` — did India VIX rise overnight vs. its prior session close (known by 09:17)
3. `gap_dir` — did today gap up or down at 09:15 vs. yesterday's close (known at 09:15)
4. `gap_filled` — has price, at any point after 09:17, returned to/through yesterday's close
   (an ongoing observation, not known in advance — this is the one input that arrives *during*
   the session, at whatever time it happens, if it happens)

## Decision logic

```
if is_expiry_day and vix_rose:
    # Gate A: continuation regime (Effect 1)
    if NOT gap_filled (as of now / by end of day):
        -> HIGH-CONFIDENCE CONTINUATION
           direction = same as today's gap direction
           historical hit rate: 66.7% (N=48)
        EXIT RULE, PUT SIDE ONLY (finalized 2026-08-22, Black-Scholes P&L tested, N=55 trades):
           exit at whichever comes first: -30% stop-loss, +50% to +75% take-profit, or
           gap-fill (existing rule above), else hold to close. This transforms the PUT-side
           baseline (gap-fill exit only: mean +39.0%, median -13.4%, win_rate 38.2%,
           p=0.055 -- not quite significant) into mean +25.8% to +31.2%, MEDIAN +50.7% TO
           +75.1% (flips from a losing to a winning median trade), win_rate 50.9-58.2%,
           p=0.0001. Robust, not a cherry-pick: ALL 9 tested stop/target combinations
           (-30/-50/-60% stop x +50/+75/+100% target) are individually significant
           (p=0.0001 to p=0.0026) -- see `bs_gate_a_put_stop_take.py`. Best single cell:
           -30% stop / +50% target (p=0.0001, win_rate 58.2%); -30%/+75% has the highest
           mean (31.2%) at a similar win rate (50.9%). NOT YET TESTED on the CALL side
           (CALL-side baseline is already unprofitable pre-stop, -5.2% mean, and was not
           re-run with stops/targets in this pass).
    else:  # gap has filled
        -> LOW-CONFIDENCE / STAND ASIDE
           historical hit rate if forced to still trade continuation: 28.3% (N=60)

elif (not is_expiry_day) and gap_dir == "down" and vix_rose and iv_bucket == "mid_14_18":
    # Gate B: reversal regime (Effect 2)
    if gap_filled:
        -> HIGH-CONFIDENCE REVERSAL
           direction = opposite of today's gap direction (i.e. long/CALL, since gate B gap is always down)
           historical hit rate: 84.8% (N=33 fires)
           historical median further favorable move after fill: 33.6 pts (mean 60.7)
           EXIT RULE (finalized 2026-08-22, Black-Scholes P&L tested, N=33 trades):
             hold to close (15:29) or at minimum past 14:00. Do NOT use a trailing stop of
             any kind and do NOT exit on a fixed clock before 14:00 -- every exit tested at
             10:00/10:30/11:00/12:00/13:00 was a STATISTICALLY SIGNIFICANT LOSS (p<0.05,
             mean -10.9% to -13.2%). Only 14:00 (p=0.28, -7.7%) and close (p=0.82, +1.8%)
             are not significantly negative; close is the best of everything tested. This
             is not a proven positive edge (p=0.82) -- it is the least-bad option among a
             wide grid of exit designs, all others being demonstrably worse.
    else:
        -> LOW-CONFIDENCE / STAND ASIDE
           historical hit rate if forced to trade reversal anyway: 47.8% (N=23) -- coin flip

else:
    -> NO SIGNAL / NOT APPLICABLE
       (day does not qualify for either gate; no historical edge established)
```

## Important asymmetry between the two gates

- **Gate A** does not currently require a specific `iv_bucket` or `gap_dir` value — it fires on
  any expiry day with an overnight VIX rise, whichever way the market gapped. The continuation
  direction is defined by today's own gap direction, not a fixed side.
- **Gate B** as validated only covers non-expiry, gap-**down**, mid-IV (14-18%) days. It has NOT
  been tested for gap-up non-expiry days, nor for the low-IV or high-IV buckets (those buckets
  showed no edge in the original 21-cell scan). Do not generalize Gate B beyond this exact cell
  without re-running the discovery process for the untested cells.

## What this spec deliberately does NOT include (and why)

- **No machine-learned "which days will move big" filter.** Tested extensively (logistic
  regression and gradient boosted trees, walk-forward validated) and found no discriminating
  power beyond the gate membership itself — AUC exactly 0.500 on held-out folds in Gate B. Adding
  an ML layer here would not help and risks overfitting on a small sample (N=56-108).
- **No fixed-clock entry/exit times.** The gap-fill event's timing is highly variable (09:18 to
  past 10:50 in the historical sample) — a fixed-clock rule would either miss most fills or fire
  on noise. `gap_filled` must be evaluated as a live, continuously-monitored condition, not a
  scheduled check.
- **No position sizing.** The Gate A PUT and Gate B exit rules above ARE tested against real
  Black-Scholes option premiums (ATM strike, ATM-day IV, live-executable stop/target/gap-fill/
  fixed-clock logic) — this is no longer a spot-points-only spec for those two cells. But nothing
  here says how much capital to risk per trade, how many concurrent positions to hold, or how to
  handle real (non-BS-theoretical) fills, spread, and slippage.
- **No out-of-sample test of the gap-fill conditioning, or of the Gate A stop/target overlay,
  specifically.** All the hit rates and P&L numbers above (66.7/28.3 directional hit rates for
  Gate A, 84.8/47.8 for Gate B, and the full Gate A PUT stop/target grid) are in-sample over the
  full available history. This needs the same expanding-window walk-forward discipline already
  applied to the unconditional Gate A directional signal (AUC 0.599, real out-of-fold result)
  before being trusted operationally.

## Build order (proposed, not started)

1. Walk-forward validate the gap-fill-conditioned hit rates for both gates (held-out most-recent
   slice untouched), the same protocol used for the unconditional Gate A/B tests.
2. If that holds up, build a real entry/exit P&L test: enter at the moment `gap_filled` becomes
   true (or, for Gate A's "no-fill" case, at some defined confirmation point once enough of the
   session has passed without a fill), strike-tracked, with mechanically executable exits (fixed
   time, trailing stop) — not the hindsight-extremum convention.
3. Only after (1) and (2) both hold up: consider a live monitoring module (not an execution
   module) that watches the four inputs during market hours and raises the classification above
   as a notification — execution decisions remain manual.

## Source data / provenance

- Gate definitions and historical panel: `k2_expiry_vix_rose_panel.csv` (N=1,318 days,
  2021-01-05 to 2026-05-14).
- Net-return-sign label: `r_after_r2_to_0945` column in `daily_measures.csv`.
- Prior-close reference for gap-fill: `prior_session_1529_spot` column in `daily_measures.csv`.
- Raw minute tape for gap-fill timing/detection: `analyze_still_water_spot.py`'s `load_spot()`
  (497,023 minute stamps, 2021-01-01 to 2026-05-14, ATM/CALL Still_Water Dhan cache).
- Scratch scripts from this session: `ml_gated_put_call.py`, `analyze_reversal_timing.py`,
  `analyze_reversal_timing_extended.py`, `ml_reversal_catcher.py` (none of these persist the
  gap-fill computation yet — it was run inline in chat; a dedicated
  `analyze_gap_fill_signal.py` should be written when build order step 1 starts).
- `bs_gate_a_pnl.py` — Gate A directional P&L (fill-triggered exit, fixed-clock exits, trailing
  stops, CALL/PUT split), Black-Scholes premiums, N=108 (55 PUT / 53 CALL).
- `bs_gate_a_put_stop_take.py` — the Gate A PUT-side stop-loss/take-profit grid (headline result
  above), same BS premium methodology, N=55.
- `bs_gap_fill_pnl.py` — shared BS pricing helpers (`bs_call`, `next_expiry`, `RISK_FREE_RATE`,
  `STRIKE_STEP`) and the Gate B exit-rule P&L test.
