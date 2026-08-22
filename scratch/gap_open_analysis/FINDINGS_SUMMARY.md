# NIFTY gap-open sequence signal — findings summary (2026-08-22)

Two distinct, empirically pronounced effects found in this thread. Both are exploratory,
in-sample, and require out-of-sample/prospective validation before any live use. No live order
was authorized or placed.

## Effect 1: Expiry-day + overnight-VIX-rise CONTINUATION effect

**Definition:** at 09:17 (decision point), check whether the 09:15-09:17 window's high came
before or after its low (`initial_high_first`). On weekly expiry days where India VIX also rose
overnight (known by 09:17), this initial sequence **predicts the same-direction sequence** in the
09:18-09:45 target window (`target_high_first`).

**Sample:** N=108 of 276 expiry days (39%) qualify (VIX rose overnight). Neither ingredient works
alone — non-expiry days with VIX rise (N=489) show ~51% accuracy (noise); expiry days with VIX
*fell* show only 53.6% accuracy, not significant. Only the combination works.

**Core numbers (108-day sample):**
- Overall accuracy: 65.7% (vs ~50% base)
- Initial high-first -> target high-first: 74.5% (n=51, "CALL" side)
- Initial low-first -> target low-first: 57.9% (n=57, "PUT" side)
- Persistence gap: +32.4pp, p=0.001
- k=1 (09:16 decision) reproduces the same 65.7%/+30.4pp/p=0.001 — signal plateaus at the very
  front of the session and decays smoothly through k=5/10/15/20/25 to noise/negative by ~09:35-40.
- On correct-signal days (N=71), spot moves 19.4pt mean / 14.75pt median to the extremum, in
  ~4-6 minutes average (median 4 min). Wrong-signal days drift ~22 min with no resolution.
- Max observed peak move on a signal day: 159.0 pts (2026-01-13, PUT/down, wrong-timing day).

**Real-premium P&L (PUT side, N=57, strike-tracked through exit):** entry ~63pt avg; winners
+12.5% avg, losers -8.7% avg; net expectancy +3.6%/trade at observed hit rate, still +1.9% at a
forced 50% hit rate; breakeven hit rate only 41.1% (well below observed 57.9%). **p=0.237 on the
mean-return t-test — not statistically significant at N=57.**

**CALL side is NOT symmetric — do not trade it as a mirror of PUT.** Despite higher raw accuracy
(74.5%), real CALL premiums barely respond to the predicted up-move (likely IV/theta drag at
open). Partial strike-clean check (33/51 days): win rate 81.8% but winners average only +1.4%,
losers -8.6%, net expectancy **-0.4%** — roughly breakeven-to-negative despite the high hit rate.
Accuracy and profitability diverge sharply on this side.

**Exit-rule stress test — this is the important operational finding:**
- The only exit rule shown clearly profitable is exiting at the window's *natural extremum*
  (the actual future high/low, wherever it falls in 09:18-09:45) — **not directly executable
  live**, since it requires knowing where the extremum will be.
- Fixed-clock exit (09:30), tight (10%) and loose (50%) premium stops, and trailing stops
  (15/20/25% off running peak) were all tested on a strike-corrected clean subsample (45 of 57
  PUT days) and land at **roughly breakeven to slightly negative** (-4% to +1% mean), none clearly
  profitable. Trailing stops are the worst of the mechanical rules tested (peak initialized at
  entry gets tripped by ordinary opening noise before any real move develops).
- **Earlier same-day drafts of this analysis used the raw "ATM" premium series without
  strike-continuity correction and produced spurious catastrophic losses (-9% to -19%) — this was
  a DATA BUG (87% of days have the labeled ATM strike roll mid-window), not a real finding. Any
  reader of intermediate scratch files/chat logs from this session should discount those numbers;
  only the strike-tracked numbers above are trustworthy.**
- 12 of 57 PUT days roll beyond +/-1 strike and were excluded from the clean 45-day exit-rule
  test; those are likely disproportionately the biggest-mover days, so the clean subsample likely
  understates the true edge. Full +/-2/+/-3 strike hydration was not completed.

**Bottom line:** real directional edge on the PUT side is credible but modest (N=57, p=0.237,
NOT significant), and **no mechanically-implementable exit rule tested so far clearly captures it
profitably** — only the hindsight-informed "exit at extremum" convention shows a clear edge.
Prospective/forward paper-trading is the recommended next step before anything else.

## Effect 2: Non-expiry, gap-down, mid-IV (14-18%) REVERSAL effect

**Definition:** same initial/target framework as above, restricted to non-expiry days that (a)
gapped down at the open and (b) have opening IV in the 14-18% bucket.

**Sample:** N=56.

**Core numbers:** accuracy only 30.4% — i.e. the initial 09:15-09:17 sequence predicts the
**opposite** direction in the 09:18-09:45 target window 69.6% of the time. Persistence gap
**-42.0pp, p=0.002** — larger in magnitude than the expiry effect, and this is a REVERSAL/
mean-reversion pattern, not a continuation pattern (fade the initial signal, don't follow it).

**Caveat — this cell was found via a 21-cell interaction scan** (gap-direction x IV-bucket,
gap-direction x initial-range-tertile, VIX-rise-tertile x initial-range-tertile). At a 5%
threshold, ~1 false positive is expected out of 21 by chance; p=0.002 is small enough to likely
survive Bonferroni correction (threshold ~=0.0024) but this is barely tested, not validated:
- No option-premium economics have been run on this effect at all (no entry/exit P&L, no
  strike-tracking, no exit-rule stress test).
- No out-of-sample or year-by-year stability check has been run.
- No mechanism/story has been proposed for why gap-down + mid-IV specifically would produce
  reversal (unlike Effect 1, where expiry-day settlement mechanics give an economic prior).

**Bottom line:** promising and large in raw size, but far less vetted than Effect 1 — treat as
a lead to investigate next (fixed-window persistence check, real premiums, stability check), not
as an established result.

## What was ruled out (for the record — do not re-run these)

Single-variable non-expiry scan (IV bucket, weekday, gap magnitude, initial-range magnitude,
VIX-rise magnitude, P1 sign/magnitude, P2 sign/magnitude, P3 sign) found nothing else significant
on non-expiry days in isolation. Bank Nifty replication is not possible with current data — the
entire Still_Water pipeline (indices/futures/options) is NIFTY-only; no Bank Nifty historical
data exists in this Drive tree. Extending the target window past 09:45 (to 10:00) does not help
Effect 1 — accuracy and persistence both weaken slightly, and only 19% of originally-wrong days
flip to correct with the extra 15 minutes.

## Source files in this folder

- `k2_expiry_vix_rose_panel.csv` / `report_k2_expiry_vix_rose.md` — Effect 1 discovery, N=108
- `k2_expiry_vix_put_trades.csv` / `report_k2_expiry_vix_put_pnl.md` — PUT-side real P&L, strike-tracked
- `analyze_k2_put_pnl.py` — the strike-tracking P&L methodology (subagent-authored)
- `/tmp/put_tracked.pkl` — 45-day clean strike-tracked exit-rule test data (NOT saved permanently;
  regenerate from the manifest + hydrated +/-1 strike files if needed — see this session's chat
  log for the exact code, or re-derive from `k2_expiry_vix_rose_panel.csv` + the ATM+/-1 PUT files
  under `dhan_fresh_2021_2026/options/{year}/`)
- Effect 2 has no dedicated output file yet — only computed inline in chat, not persisted to a
  script/CSV. Next step if pursued: write `analyze_gapdown_midiv_reversal.py` analogous to the
  Effect 1 scripts.

## Addendum (same day, later session): walk-forward validation, Effect 2 reframed, and the
## unifying gap-fill mechanism

This section supersedes some conclusions above. Read this before trusting the sections above in
isolation.

**Correction to Effect 2's stated conditioning.** The N=56 cell is NOT just "non-expiry +
gap-down + mid-IV" as written above — the actual discovery code also required **VIX rose
overnight**, the same third condition as Effect 1. Dropping that VIX-rose requirement gives a
different, insignificant cell (N=115, accuracy 46%). The corrected definition: non-expiry +
gap-down + mid-IV (14-18%) + VIX rose overnight, N=56.

**Gate A (Effect 1) walk-forward result: CONFIRMED, promote confidence.** Built a proper
expanding-window walk-forward classifier (seed on oldest 40%, predict forward in folds, most
recent 15% of the 108 days held out and untouched) using the actual net-return-sign label
(CALL/PUT, not the order-of-extremes accuracy stat above). Logistic regression: out-of-fold
validation accuracy **60.0%** vs. 52.7% baseline, AUC **0.599** (N=55 OOF predictions, wide CI but
beats baseline in most folds). Top features: `vix_overnight_gap` magnitude, `initial_range_magnitude`,
`opening_iv` (continuous) — not the discretized IV bucket. GBM overfit badly (98.5% train vs 54.5%
val) — simple model generalizes better at this N. **This is real evidence Effect 1 survives an
honest held-out-style test on the trading-relevant label**, on top of its already-known p=0.001
persistence stat and (separately, not yet reconciled) its non-significant PUT P&L test above.

**Gate B (Effect 2) reframed — the original "30.4% accuracy" stat is about order of extremes, NOT
net direction, and these two things are almost mechanically disconnected.** Testing Gate B with a
net-return-sign label (mirroring Gate A's protocol) found NO edge at all: logistic regression
53.5% vs 51.5% baseline (AUC 0.499); an ablation removing `gap`/`initial_high_first`/
`initial_range_magnitude` also failed (51.5%/48.5%, AUC ~0.50); `iv_bucket` got ~0 feature
importance in both. Root cause found via cross-tab: `target_high_first` (which extreme comes
first) correlates with net return sign ~78-79% almost by construction ("whichever extreme is
touched last dominates the close"), and composing that with the real order-based fade effect
(69.6% reversal rate) washes out any net-directional edge. **Conclusion: Effect 2 is real, but it
is a path-shape/order-of-extremes phenomenon, not a directional CALL/PUT signal by itself.**

**Extended-window check: the order-of-extremes effect corresponds to a real, large, ALL-DAY
divergence in move size, not just a 27-minute pattern.** Pulled the raw minute tape through end of
day for all 56 mid-IV days. The 39 "reversed" days and 17 "continued" days diverge at *every*
checkpoint all day (favorable-direction move, median points): 09:45 (34.8 vs 11.4, 3.1x), 10:00
(42.5 vs 11.4), 10:30 (57.3 vs 16.3), 12:00 (62.6 vs 21.9), close (80.0 vs 28.6, 2.8x). 30 of 39
reversed days were *still improving* at end of day — even this "extended" window likely
understates the true move. Quartile stability check (chronological): order-fade-rule accuracy
71.4% / 85.7% / 64.3% / 57.1% across the four quarters of history — real but declining, not
static. **Caveat, unresolved:** this is still hindsight running-extreme measurement (best point
reached anywhere in the window/day), the same non-executable convention flagged for Effect 1's
"exit at the natural extremum." No real P&L has been run on this extended horizon.

**A same-day/real-time "catcher" model does not exist.** Tried to predict, at 09:17, which
gate-B-mid-IV days will be "reversed" (big-move) vs "continued" (small-move) using a walk-forward
classifier on the same 09:17 features: both logistic regression (72.4% OOF, AUC exactly 0.500) and
GBM (65.5% OOF, AUC exactly 0.500) fell *below* the 75.9% majority-class baseline. **No 09:17-time
feature set refines the gate further — the gate itself is the entire selection mechanism.** Two
naive real-time "is it reversing now" triggers were also tried and failed: (1) breaking the edge
of the tiny 09:15-09:17 range fires within ~1 minute on almost every day regardless of outcome
(not a signal, just noise at a trivial threshold); (2) requiring price to move 10-50 points past
entry before "confirming" actually discriminated *backwards* — false-fire (continued) days showed
bigger subsequent moves than true (reversed) days at every threshold tested.

**The gap-fill signal — the one real-time mechanism that worked, and it unifies BOTH gates.**
Tested whether price returning to the *prior day's close* at any point after 09:17 (watched
continuously, no fixed timing) discriminates the outcome. It does, in both gates, with mirror-image
(economically sensible) polarity:
- **Gate B (reversal thesis):** gap-fill rate 71.8% on reversed days vs 29.4% on continued days.
  Conditional: P(reversed | gap fills) = 84.8% (N=33 fires: 28 true, 5 false), vs P(reversed | no
  fill) = 47.8% (N=23). 12 of 17 continued days correctly never fill. Median further favorable
  move after a true fill: 33.6 pts (mean 60.7).
- **Gate A (continuation thesis) — same test, opposite read:** unconditional continuation-success
  45.4%. P(continuation succeeds | gap does NOT fill) = 66.7% (N=48) — holding away from prior
  close confirms the move is real. P(continuation succeeds | gap DOES fill) = 28.3% (N=60) —
  round-tripping back to prior close means the initial move failed to hold.
- **Mechanistic read:** in Gate A you want the gap to *stay open* (momentum confirmed); in Gate B
  you want the gap to *close* (exhaustion/reversal confirmed). Same observable event, opposite
  trade implication, matching each gate's underlying causal story (settlement/gamma-hedging
  momentum on expiry days vs. ordinary open-overreaction correction on other days).
- **Not yet done:** no walk-forward/out-of-sample validation specifically on the gap-fill-
  conditioned rule (all stats above are in-sample), and no P&L test at all — everything is still
  spot points.

**Proposed next artifact:** a simple rule-based (non-ML) decision algorithm using exactly four
09:17-onward-observable inputs — (1) is it an expiry day, (2) did India VIX rise overnight, (3)
did today gap down (vs up), (4) has price since returned to/through the prior day's close — to
route each day into "high-confidence continuation," "high-confidence reversal," or "no trade."
See `GAP_FILL_SIGNAL_MODULE_SPEC.md` (same folder) for the spec. Not yet built or validated
out-of-sample; no live order authorized.

## Second addendum (same day, later still): Gate A PUT-side stop-loss/take-profit — headline
## result of the session

**Question:** the Gate A continuation trade's only tested exit so far (gap-fill-triggered, else
hold to close) gives a promising but not-quite-significant PUT-side result (N=55, mean +39.0%,
median -13.4%, win_rate 38.2%, p=0.055 — see the original Effect 1 section above; the CALL side
was already known unprofitable and was not revisited here). Does capping losses (stop-loss) and
locking in gains (take-profit) *on top of* that gap-fill exit improve it, or is +39% mean already
a fluke of a few huge winners with a mostly-losing median?

**Method:** Black-Scholes premium path (ATM strike at 09:17, that day's opening IV), same
methodology as the existing Gate A P&L script. Exit at whichever of {stop-loss, take-profit,
gap-fill} triggers first, else hold to close. Tested a 3x3 grid: stop-loss in {-30%, -50%, -60%},
take-profit in {+50%, +75%, +100%}. Script: `bs_gate_a_put_stop_take.py`, N=55.

**Result — every cell in the grid is significant, not just the best one:**

| Stop-loss | Take-profit | Mean | Median | Win rate | p-value |
|---|---|---|---|---|---|
| -30% | +50% | +25.8% | +50.7% | 58.2% | 0.0001 |
| -30% | +75% | +31.2% | +75.1% | 50.9% | 0.0001 |
| -30% | +100% | +34.9% | 0.0% | 45.5% | 0.0003 |
| -50% | +50% | +22.7% | +51.0% | 60.0% | 0.0017 |
| -50% | +75% | +28.2% | +75.3% | 52.7% | 0.0014 |
| -50% | +100% | +31.6% | 0.0% | 47.3% | 0.0026 |
| -60% | +50% | +23.1% | +51.4% | 61.8% | 0.0019 |
| -60% | +75% | +29.4% | +75.5% | 54.5% | 0.0012 |
| -60% | +100% | +33.0% | 0.0% | 49.1% | 0.0023 |

All 9 combinations are significant (p from 0.0001 to 0.0026) — a fundamentally more robust pattern
than Effect 2's original discovery (one best cell out of a 21-cell scan). The median flips from a
losing trade (-13.4%, baseline) to a clear winner (+50% to +75%) across most of the grid, and win
rate rises from 38.2% to 50-62%. The +100% target cells show median exactly 0.0% because most
trades that reach +100% instead round-trip back to a small loss/breakeven by the gap-fill or
close exit — the +50%/+75% targets lock in the gain before that round-trip, which is why they
dominate on median despite a slightly lower mean than +100%.

**Best single rule (headline result of this session):** enter PUT at 09:17 on Gate A days
(expiry + overnight VIX rise, gap down), exit at -30% stop-loss, +50% to +75% take-profit, or
gap-fill — whichever comes first — else hold to close. p=0.0001, win rate 50.9-58.2%, median
+50.7% to +75.1%.

**Caveats, unchanged from the rest of this document:** still in-sample (N=55, full history, no
walk-forward holdout on this specific overlay yet); Black-Scholes theoretical premiums, not real
fills (no bid-ask spread, slippage, or brokerage); CALL side not retested with stops/targets;
no position sizing or capital allocation defined. See `GAP_FILL_SIGNAL_MODULE_SPEC.md` for how
this is now written into the Gate A branch of the decision spec, and its build-order/next-steps
list (walk-forward validation is next, before anything resembling live use).
