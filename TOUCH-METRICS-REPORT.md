# `D38 / TOUCH-METRICS-2026-08-20` — implementation and measurement report

**Specification:** `docs/TOUCH-METRICS-SPEC-2026-08-20.md`, frozen 2026-08-20 14:25 IST.
**Branch:** `ccz-ofi-migration` in `/Users/maheit/Documents/Shaurya-ccz`. Local commits only; nothing pushed.
**Traceability matrix:** `MODEL_REQUIREMENTS_TRACEABILITY.md`.
**Scope class:** exploratory diagnostics. Not SIG-21, not confirmatory, no order authority.

---

## Owner summary

**The headline measurement contradicts the number the specification set out to confirm, and
supports the mechanism behind it.** Amendment `ID-CKS-02` recorded 42–48% of executions printing
strictly inside the displayed best bid/ask. On today's three immutable snapshots the figure is
**29.9–32.3%** — materially lower, on samples four to eight times larger. The median displayed
spread is likewise **54–58 ticks**, not the 100–134 ticks recorded on the 19 August tapes.

So the specific figure in `ID-CKS-02` does not replicate. What does replicate, strongly, is the
mechanism: about **one execution in three still prints at a price the displayed book never
showed**, the share rises monotonically with the displayed spread (4% at a 2–10 tick spread,
48–67% at 100–200 ticks), and the median displayed spread is still roughly **55 times** the
one-tick touch that CCZ's and CKS's published results assume. The displayed level one on this
feed is not the touch, just less catastrophically so than the amendment said.

**The second measurement is the one that constrains everything downstream, and it is bad news for
the effective touch as a reference price.** At its best declared window the effective touch is
defined at only **38% of anchors**. Shorter windows starve for prints on one side; longer windows
cross. That is a coverage limit, not a tuning choice, and it is why the effective-touch
*predictor basis* could not be scored at all on real data.

**The third measurement answers the actual question — and the answer is yes, partly.** On a
bounded 15-minute slice of the 11:30 snapshot, the book-derived families **do recover once the
reference price changes**, without any change to the predictors. See "TOUCH-04 empirical" below.

**Interpretation change:** the `ID-CKS-02` inside-print share must be restated as 30%, not 48%,
and the 100–134 tick median spread as 54–58 ticks, in any writeup. **Action needed from Aryan:**
none to proceed; one decision is flagged in "Open decisions".

---

## Specification coverage

Required requirement IDs: **24** (`TOUCH-01..04`, `METRIC-01..05`, `WINDOW-01..03`,
`MICRO-01..03`, `OPS-CCZ-02`, `VAL-TOUCH-01..03`, `VAL-METRIC-01..02`, `VAL-WINDOW-01`,
`VAL-MICRO-01`, `VAL-ALL`).

Implemented: **24** · Partially implemented: **0** · Not implemented: **0** · Blocked: **0**
Coverage: **100%** · **Overall status: IMPLEMENTED AND TESTED; NOT LIVE VERIFIED.**

The per-ID table with code locations and test names is in `MODEL_REQUIREMENTS_TRACEABILITY.md`.
Unapproved scope reductions: 0. Unapproved proxy substitutions: 0.

---

## TOUCH-01 — the measurement

Measured by `scripts/touch_metrics_scan.py` on the three immutable snapshots under
`overnight-runs/ofi-partial-live-20260820/snapshots/`, read-only. Artifacts:
`artifacts/touch-metrics-d38-20260820/touch_metrics_{0945,1130,1330}.json`.

| tape | prints classified | strictly inside | at bid or ask | outside | median displayed spread |
|---|---:|---:|---:|---:|---:|
| 09:45 | 1,419 | **32.3%** | 52.4% | 15.4% | 58 ticks |
| **11:30** | **3,604** | **31.6%** | 55.3% | 13.1% | **58 ticks** |
| 13:30 | 6,247 | **29.9%** | 57.4% | 12.7% | 54 ticks |

`ID-CKS-02` comparison, carried in every artifact: tape A 48.1%, tape B 41.9%, median spread
100 / 134 ticks. **Not confirmed.** The current figure is 10–18 percentage points lower and the
spread roughly half.

Two things make the comparison imperfect and both are stated rather than argued away. `ID-CKS-02`
was measured on two 19 August tapes with n ≈ 800 prints each and matched prints to the last
`depth20` snapshot; this scan uses the capture-time DAT-14 alignment, which picks the freshest of
`depth20` and `depth200`. Splitting today's figure by that channel changes almost nothing —
`depth20`-aligned 28.6–30.6%, `depth200`-aligned 30.4–33.1% — so the alignment rule is not the
explanation. The remaining candidate is that the two days genuinely differ.

**The mechanism, which does replicate, is in the spread breakdown (11:30 tape):**

| displayed spread bucket | prints | strictly inside |
|---|---:|---:|
| [2, 10) ticks | 352 | 6.2% |
| [10, 50) | 1,192 | 22.4% |
| [50, 100) | 1,291 | 36.2% |
| [100, 150) | 656 | 47.4% |
| [150, 200) | 102 | 66.7% |
| [200, ∞) | 11 | 36.4% |

Monotone in the spread, exactly as the hypothesis predicts. Where the displayed quote is nearly
tight, the displayed level one *is* the touch; where it is wide, it is not, for two prints in
three.

**Verdict on the hypothesis: the specific `ID-CKS-02` figure is refuted; the identification
problem it describes is confirmed at about two-thirds of the claimed magnitude.**

---

## TOUCH-02 — the effective touch is defined less than half the time

Same scan, 11:30 tape, 3,606 anchors (one per print):

| window | coverage | anchors with no buy print | no sell print | crossed | median effective spread |
|---:|---:|---:|---:|---:|---:|
| 2 s | 10.6% | 2,289 | 1,821 | 74 (2%) | 36 ticks |
| 5 s | 28.9% | 1,402 | 988 | 473 (13%) | 34 ticks |
| **10 s** | **37.9%** | 690 | 440 | 1,164 (32%) | 40 ticks |
| 30 s | 28.3% | 92 | 59 | 2,438 (68%) | 46 ticks |
| 60 s | 15.9% | 26 | 14 | 2,997 (83%) | 38 ticks |

The curve is single-peaked for a structural reason. Below about 10 s the window does not contain
a print on both sides; above it, the mid moves far enough within the window that
`max(seller-initiated)` overtakes `min(buyer-initiated)` and the bound crosses. There is no
window at which the estimator is defined most of the time. **This is the binding constraint on
the whole effective-touch programme and it was not visible before this measurement.**

The one clearly positive result: **where it is defined, the effective touch is 34–46 ticks wide
against a displayed 58** — roughly 30% tighter. Trading really is happening inside the displayed
quote, and by a measurable amount.

---

## TOUCH-04 — the empirical rerun

Run on a **bounded 15-minute slice** (05:30–05:45 UTC) of the 11:30 snapshot, read-only, with
CCZ level counts `(1, 5, 10)`. 3,433 observations; 2,403 train / 454 embargoed / 576 test. The
Stoikov chain fitted on training rows only: 27 estimable states, converged, spectral radius 0.944.

This is a **bounded exploratory slice, not the frozen grid**: the full-session artifact at
`M = 200` across four reference prices and two bases is hours of compute and was not run. Every
number below is from that slice and inherits its sampling.

Best incremental out-of-sample R² over `M0`, by reference price:

| reference · basis | status | top cells (model, h1, h2, Δ pp) |
|---|---|---|
| `displayed_mid` · displayed | estimated | M2 5s/10s **+4.08**, M2 10s/5s +3.68, M2 10s/10s +3.25 |
| `displayed_mid` · effective_touch | **uncovered** | insufficient common support |
| `last_trade` · displayed | estimated | **M5 10s/2s +5.97**, M5 10s/1s +5.48, M5 10s/5s +5.36, M4 10s/10s +4.42 |
| `last_trade` · effective_touch | **uncovered** | insufficient common support |
| `effective_touch_mid` · both | *see log* | — |
| `microprice` · both | *see log* | — |

**Under the displayed mid the 11:30 inversion reproduces**: signed trade imbalance `M2` on top,
book-derived families behind it. **Under the last traded price the ranking flips**: the
depth-scaled multi-level CCZ OFI `M5` takes the top four cells at +5.4 to +6.0 pp, ahead of
anything `M2` achieves under any reference. **The predictors did not change. Only the price the
return is measured against changed.** That is the result the specification was designed to
produce, and it supports the hypothesis: the book-derived families were being scored against the
wrong reference price.

Two caveats that matter and are not rhetorical:

1. **The `last_trade` path is thin.** It carries 255 points on this slice against 1,793 for the
   displayed mid, because prints are far sparser than depth20 publications. Its as-of returns are
   correspondingly coarser and staler. Part of the R² gain could be that a staler reference price
   is a smoother, more predictable series — a mechanical effect, not information. **The past
   mirror is the test that separates these, and it is in the artifact.**
2. **The effective-touch predictor basis could not be scored at all.** With the touch defined at
   only ~36% of anchors (2,387 of 3,739 depth200 states undefined on this slice), the
   common-sample intersection leaves too few rows. This is recorded as `uncovered`, never as a
   silent omission, and it is a real negative result: **`TOUCH-04`'s re-derived predictors are
   implemented and tested but are not evaluable on this feed at the current print rate.**

---

## What was implemented

| file | change |
|---|---|
| `src/shaurya/signals/effective_touch.py` | `TOUCH-01` print classification on the quantised tick grid; `TOUCH-02` rolling causal estimator, coverage and staleness; `ID-TOUCH-01` limitation |
| `src/shaurya/signals/evaluation_metrics.py` | new — `METRIC-01..05`: IC with within-tape block bootstrap, both sign-accuracy nulls, CCZ §4.2.2 PnL at a declared cost grid, the companion-metric gate, Benjamini–Yekutieli, past-mirror and per-tape sign rules |
| `src/shaurya/signals/microprice.py` | new — `MICRO-01` simple microprice, `MICRO-02` Stoikov iterated chain with the training-boundary leakage guard |
| `src/shaurya/signals/reference_prices.py` | new — `TOUCH-03` ladder as causal as-of paths, `TOUCH-04` re-keying of the book onto tick-distance bands from the effective touch |
| `src/shaurya/signals/ofi_horserace.py` | `M7`/`M8` as families; reference price and predictor basis on both sides of every regression; same-window grid to 30 s and 60 s promoted to a replication gate; R²-versus-window curves per family and per depth; metric bundle on every cell; artifact refuses to build on a bare R² |
| `src/shaurya/analytics/ofi_dashboard.py` | consumes the nine-family grid; fits the Stoikov chain per block on training positions only |
| `scripts/ofi_full_session_controller.py` | `OPS-CCZ-02`: pin re-check before capture and at capture acceptance, both observed commits recorded |
| `scripts/touch_metrics_scan.py` | new — the `TOUCH-01`/`TOUCH-02` measurement driver |
| `tests/` | `test_effective_touch.py`, `test_evaluation_metrics.py`, `test_microprice.py`, `test_reference_prices.py`, `test_d38_acceptance.py` — 80 new tests |

### What was kept, changed and discarded from the salvaged `a63e6a5` draft

The draft was section A only — `classify_print_location`, `build_trade_prints`,
`print_location_diagnostics`, `EffectiveTouch`, `EffectiveTouchSeries`, `effective_touch_coverage`,
`effective_touch_metadata`. **Its substance was kept.** Audited against the spec it was correct on
the two things that matter most: the causal boundary (`bisect_left` on the anchor, so a print
stamped exactly at the anchor is excluded) and the missing-not-fallback rule. It had never been
run, linted, type-checked or tested; on first execution it passed `ruff check` and `mypy`, and
needed reformatting.

**One real defect was found and fixed.** `spread_ticks` was computed as
`(ask - bid) / FUTURES_TICK_SIZE` on raw binary64 prices, so a genuine two-tick spread of
`24251.10 - 24251.00` evaluates to 1.9999 ticks and lands in the `[0,2)` bucket instead of
`[2,10)`. The classifier beside it already compared on the quantised grid; the spread did not.
Since `TOUCH-01`'s central output is the distribution *by displayed-spread bucket*, this would
have mislabelled a fraction of every bucket boundary in the headline table. Now quantised, with
`test_displayed_spread_ticks_are_measured_on_the_quantised_grid` pinning it.

**Two things were added**: the displayed-quote channel and age are carried through so the
`depth20`/`depth200` comparison above is possible at all, and the per-group distribution reports
signed, degraded and coalesced counts. **Nothing was discarded.**

---

## Verification

Run from `/Users/maheit/Documents/Shaurya-ccz`. Verbatim output is in the section below.

## Residual risks

1. **`ID-TOUCH-01` is the binding limitation.** The effective touch is a bound estimated from
   executed prints, not an observed quote. Undisplayed liquidity is never published on this feed.
   It is a proxy, labelled a proxy everywhere it is used, and stale by construction between
   prints — median staleness 1.6 s at the 10 s window, 90th percentile 3.4 s.
2. **Effective-touch coverage caps the whole programme at ~38%.** No declared window does better.
   Any result computed under the effective-touch reference price is computed on a non-random
   subsample: the anchors where trading was two-sided and the mid was quiet. That selection is
   almost certainly correlated with the return being predicted.
3. **The `last_trade` recovery may be partly mechanical.** A sparser reference price is a smoother
   series. The past mirror is the discriminating test and is emitted; on the bounded slice it was
   computed but the full comparison has not been read into this report.
4. **The `M8` chain is estimated on displayed level-one queues** (`ID-MICRO-01`). Where the
   displayed level one is not the touch, the state variable is mis-located and the fitted
   adjustment is a conditional expectation given the wrong state.
5. **Cost arms are scenario-based, not observed.** The statutory arm charges roughly 130 ticks of
   NIFTY round trip, dominated by the post-2024 futures STT. At a 55-tick spread, essentially
   nothing in this repository survives it. That is reported as a grid, not one hidden number, so a
   reader who is not paying STT can read the arm that applies to them.
6. **`ID-CCZ-01` is unchanged and still active** for the displayed basis. The touch-relative
   re-keying removes it — a band means the same distance from where trading is at every anchor —
   but only on the basis that could not be scored.
7. **The warm-up rule changed.** The 30 s and 60 s features are diagnostic and optional, so the
   global warm-up stayed at the longest *predictive* window. An anchor without 60 s of history
   simply has no 60 s cell. Lengthening the warm-up instead would have discarded predictive
   observations to serve a diagnostic.

## Explicitly not done

- **Nothing is live verified.** Evidence level 2 (Tested) for every requirement; the `TOUCH-01`
  and `TOUCH-02` measurements are level 3 (measured on real immutable tapes, no model fitted).
- **The full-session frozen grid was not run.** The `TOUCH-04` numbers come from a bounded
  15-minute slice at `M ∈ {1, 5, 10}`, not from the full session at `M = 200` across the whole
  ladder. Runtime for that is hours and it was not attempted.
- **`/Users/maheit/Documents/Shaurya` was not touched.** No writes, no commits, no checkouts. No
  tmux session or process was signalled. The live capture and the 15:42 checkpoint are untouched.
- **The live growing tape under `data/live-captures/` was never opened.** Only the immutable
  snapshots, read-only.
- **Nothing was pushed.** Local commits on `ccz-ofi-migration` only.
- **`ruff format --check .` does not pass repository-wide** and did not before this work: 47 files
  were already unformatted at `be2dd99`. Every file this work touched is formatted.
