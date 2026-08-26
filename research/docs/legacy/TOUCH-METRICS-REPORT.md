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

Run on a **bounded 15-minute slice** (05:30–05:45 UTC) of the 11:30 snapshot, read-only, with CCZ
level counts `(1, 5, 10)`. 3,433 observations; 2,403 train / 454 embargoed / 576 test. The Stoikov
chain was fitted on training rows only: 27 estimable states, converged, spectral radius 0.944.

This is a **bounded exploratory slice, not the frozen grid.** The full-session artifact at
`M = 200` across the whole ladder is hours of compute and was not run. Every number below inherits
this slice's sampling, and `n = 576` held-out rows is small.

Best incremental out-of-sample R² over `M0`, with each cell's own past mirror:

| reference · basis | model | h1 / h2 | future Δ pp | past mirror Δ pp | past mirror | IC | hit rate vs majority null |
|---|---|---|---:|---:|---|---:|---:|
| `displayed_mid` · displayed | M2 | 5s / 10s | +4.08 | +8.81 | fails | +0.092 | -0.233 |
| `displayed_mid` · displayed | M2 | 10s / 5s | +3.68 | +12.99 | fails | +0.225 | -0.272 |
| `displayed_mid` · displayed | M2 | 10s / 10s | +3.25 | +23.75 | fails | +0.032 | -0.306 |
| `displayed_mid` · effective_touch | **uncovered** | — | — | — | — | — |
| `last_trade` · displayed | M5 | 10s / 2s | +5.97 | -53.70 | **passes** | +0.234 | -0.393 |
| `last_trade` · displayed | M5 | 10s / 1s | +5.48 | -25.00 | **passes** | +0.228 | -0.404 |
| `last_trade` · displayed | M5 | 10s / 5s | +5.36 | -71.07 | **passes** | +0.313 | +0.000 |
| `last_trade` · effective_touch | **uncovered** | — | — | — | — | — |
| `effective_touch_mid` · displayed | M8 | 0.5s / 10s | +1.69 | -0.27 | **passes** | +0.037 | -0.215 |
| `effective_touch_mid` · displayed | M8 | 1s / 10s | +1.69 | -0.27 | **passes** | +0.037 | -0.215 |
| `effective_touch_mid` · displayed | M8 | 2s / 10s | +1.69 | -0.27 | **passes** | +0.037 | -0.215 |
| `effective_touch_mid` · effective_touch | **uncovered** | — | — | — | — | — |
| `microprice` · displayed | M7 | 0.5s / 2s | +8.63 | +7.42 | **passes** | +0.392 | -0.170 |
| `microprice` · displayed | M7 | 1s / 2s | +8.63 | +7.42 | **passes** | +0.392 | -0.170 |
| `microprice` · displayed | M7 | 2s / 2s | +8.63 | +7.42 | **passes** | +0.392 | -0.170 |
| `microprice` · effective_touch | **uncovered** | — | — | — | — | — |

**Three things come out of this, in order of importance.**

**1. The result that motivated the whole specification fails its own past mirror.** Signed trade
imbalance `M2` under the displayed mid gives +4.08 pp — reproducing the 11:30 finding that put it
above every book-derived object. Its past mirror gives **+8.81 to +23.75 pp**. The same
construction "predicts" past returns two to seven times better than future ones. A predictor
cannot have information about the past, so this is a property of the construction, not of the
signal. `M2`'s lead over the book-derived families should not be treated as a predictive result
until that is explained.

**2. The book-derived family does recover, and it survives the mirror.** Under the **last traded
price** as the return reference, with the predictors completely unchanged, depth-scaled
multi-level CCZ OFI `M5` takes the top cells at **+5.36 to +5.97 pp** against past mirrors of
**−25 to −71 pp** — it does far worse than the baseline on past returns, which is the opposite of
the leakage signature. Information coefficients of +0.23 to +0.31. **This is the specification's
hypothesis holding: the book-derived families were being scored against the wrong reference
price, and they recover when it is corrected.**

**3. Every one of these cells is a losing signal on sign accuracy.** Excess hit rate over the
majority-class null is **−0.17 to −0.40** almost everywhere. A positive R² increment with a hit
rate below the majority-class null means the fit is capturing magnitude, or a handful of large
moves, while getting the direction wrong more often than always guessing the common direction.
This is precisely the failure `METRIC-02` was added to make visible, and R² alone concealed it.

**Two caveats that are not rhetorical.**

- **The `last_trade` path is thin.** It carries 255 points on this slice against 1,793 for the
  displayed mid, because prints are far sparser than depth20 publications. Its as-of returns are
  coarser and staler, and part of the R² gain could be that a staler reference is a smoother, more
  predictable series. The past mirror is the test that separates a smoother series from real
  information, and `M5` passes it by a wide margin — but on 576 held-out rows from one 15-minute
  slice, that is a screening result, not a finding.
- **The effective-touch predictor basis could not be scored at all.** With the touch undefined at
  2,387 of 3,739 depth200 states on this slice, the common-sample intersection leaves too few rows
  at every reference price. All four `effective_touch` combinations are recorded as `uncovered`,
  never silently omitted. **`TOUCH-04`'s re-derived predictors are implemented and tested but are
  not evaluable on this feed at the current print rate.** The `microprice` and `M7` cell
  (+8.63 pp, past mirror +7.42 pp) passes only marginally and should be read as near-mechanical:
  the microprice mean-reverts toward the mid, so its own tilt predicts its own reversion.

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

Run from `/Users/maheit/Documents/Shaurya-ccz` at commit `693f0bb`.

```
$ .venv/bin/python -m pytest -q
657 passed, 10 warnings in 173.97s (0:02:53)

$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m ruff format --check .
30 files would be reformatted, 165 files already formatted

$ .venv/bin/python -m ruff format --check <the 15 files this work touched>
15 files already formatted

$ .venv/bin/python -m mypy src
Success: no issues found in 64 source files
```

**On the test count.** The brief records a 576-test baseline. At `a63e6a5` — the salvaged-draft
commit this work started from — the suite was **577**; it is now **657**, so this work added
**80 tests** and removed none. No test was weakened: three assertions in
`test_ofi_horserace.py` and `test_ofi_dashboard.py` were updated because the model grid genuinely
grew from seven families to nine (`M7`, `M8`), and `test_ofi_dashboard.py` gained
`test_grid_size_is_pinned_to_the_declared_family_and_axis_counts`, which pins the new grid size
explicitly so a future change to `MODEL_ORDER` cannot silently resize it.

**On `ruff format --check .`.** It did not pass before this work and does not pass now. At
`a63e6a5` **48 files** would have been reformatted; at `693f0bb` it is **30**. Every one of the
15 files this work touched is formatted; the remaining 30 are a pre-existing backlog that
predates `D37` and was not in scope to churn.

**Causal / leakage audit: passed.** `assert_no_lookahead` runs on every artifact build.
`VAL-TOUCH-01` asserts that a print stamped exactly at the anchor is excluded, at every declared
window. `VAL-MICRO-01` refuses any Stoikov transition whose mid change *resolves* at or after the
training boundary, rather than trimming it. The reference-price paths refuse to resolve an
endpoint past their last observation, so a right-edge return is missing rather than a fabricated
zero.

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
   series. The past mirror is the discriminating test, `M5` passes it by −25 to −71 pp, and that
   is the strongest evidence available — but it rests on 576 held-out rows from one 15-minute
   slice with 255 reference points. It needs the full session before it is more than a screen.
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

## Contradictions found against the specification

- **`ID-CKS-02`'s 42–48% does not replicate** (see `TOUCH-01`). The specification's §0 motivation
  is built on it. The mechanism survives; the magnitude does not.
- **The effective touch is not usable as a general reference price on this feed.** §A of the
  specification treats `TOUCH-02` as the estimator that fixes the reference; the measurement says
  it is defined at 38% of anchors at best. Nothing in the specification anticipated that, and it
  is the reason `TOUCH-04`'s re-derived predictor basis is implemented but unevaluable.
- **The specification assumes the 11:30 `M2` result is the thing to be explained.** The past
  mirror says `M2`'s lead may itself be an artefact of the construction. That reframes the
  question rather than answering it.
- **`WINDOW-03`'s "at every depth" was ambiguous.** For a CCZ object, depth is the level count
  `M`, not the model family. Implemented both ways: `same_window_curve` per family and
  `evaluate_same_window_by_depth` / `depth_r2_curve` across every declared `M ∈ {1, 5, 10, 20,
  200}`.
- **`METRIC-03` does not define "fees".** Implemented as a declared four-arm grid — gross, half
  spread only, half spread plus exchange and stamp, half spread plus full statutory — rather than
  one hidden number, and labelled `object_category: scenario_based`.

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

## Open decisions

**One decision is genuinely Aryan's and I did not take it.** `TOUCH-01` refutes the `ID-CKS-02`
figure on today's tape but not the mechanism. `ID-CKS-02` is a frozen amendment to a different
specification (`CKS-L1-OFI`), and correcting its recorded numbers is a change to that document,
not to `D38`. I have recorded the discrepancy here and in the artifacts; I have **not** edited
`docs/CKS-L1-OFI-SPEC-AMENDMENT-1-2026-08-19.md`. If the amendment should carry the updated
range, that is a one-line change-control note against it.

**Everything else in the frozen `D38` scope was implemented without asking**, per §17.

---

## Addendum, 2026-08-20 16:05 IST — absolute R², and two admitted method defects

### Absolute out-of-sample R² (the frozen probe recorded only increments)

The probe was rerun on the identical slice, identical seeds, with `oos_r2_training_mean`
recorded per cell. Every increment reproduced exactly, so this is the same run with a
restored column. Artifact:
`artifacts/touch-metrics-d38-20260820/touch04_reference_ladder_probe_1130_0530-0545utc_with_absolute_r2.json`.

| reference · model | h1/h2 | **abs OOS R²** | incr over M0 | past-mirror abs | IC | hit vs majority null | test n |
|---|---|---:|---:|---:|---:|---:|---:|
| `displayed_mid` · M2 | 5s/10s | +2.302% | +4.082 pp | +6.746% | +0.092 | −0.233 | 468 |
| `displayed_mid` · M2 | 10s/5s | +4.449% | +3.681 pp | +4.008% | +0.225 | −0.272 | 478 |
| `last_trade` · **M5** | **10s/2s** | **+5.029%** | +5.968 pp | **−60.696%** | +0.234 | −0.393 | 468 |
| `last_trade` · M5 | 10s/1s | +4.717% | +5.478 pp | −28.709% | +0.228 | −0.404 | 473 |
| `last_trade` · M5 | 10s/5s | +2.722% | +5.358 pp | −83.101% | +0.313 | +0.000 | 456 |
| `effective_touch_mid` · M8 | 0.5s/10s | +3.436% | +1.694 pp | −6.036% | +0.037 | −0.215 | 405 |
| `microprice` · M7 | 0.5s/2s | +10.223% | +8.631 pp | −1.176% | +0.392 | −0.170 | 483 |

**Report the absolute, not the increment.** Baseline `M0` absolute R² varies enormously by
reference price — `last_trade` −13.426% .. −0.426%, `microprice` +0.612% .. +12.009% — so an
increment over `M0` is not comparable across references. The `microprice` · `M7` cell is the
clearest case: +8.631 pp of increment sits on an `M0` that already reaches +12.009%, and the
reference price is doing the work. **The headline defensible figure is `last_trade` · `M5`,
10s/2s, absolute OOS R² = +5.029% on 468 held-out rows.**

### Defect 1 — the evaluation standard moved between reports (`ID-METHOD-01`)

Across `X-OFI-DAT20-03`, the 11:30 horse race and this report, the stated bar changed from
"beats `M0` on R²", to "beats its own past mirror", to "beats the majority-class sign null."
Those are three different objects: a baseline, a **leakage guard**, and a **different metric's
null**. Rotating between them is a moving goalpost and it invalidates cross-report comparison
even where the individual numbers are correct.

The past mirror is a *falsifier*, not a benchmark. It can only ever disqualify. It must never be
a ranking key and must never be quoted as evidence of strength.

The correct question is single and fixed: **for one declared target, which candidate predicts it
best?** — with lagged returns, signed trade sign, and the majority-class rule all entered as
ordinary competitors on the same held-out rows, not as hurdles applied selectively. This is
`D39`'s mandate.

### Defect 2 — bid-ask bounce is unaddressed under the `last_trade` reference (`ID-BOUNCE-01`)

The headline +5.029% is measured on returns of the **last traded price**. Consecutive prints
alternate between the bid and the ask, so the target contains a mechanical bounce component. On
this feed that is not second-order: median displayed spread is 54–58 ticks and ~30% of prints
execute strictly inside it.

This cuts both ways and the direction is not yet known:

- Bounce is noise in the target, which *depresses* R² — under which +5.029% is conservative.
- But bounce is also a mechanically **forward-predictable** reversal. Any predictor carrying
  information about the side of the last print can forecast the next print's reversal without
  carrying any information about value. `M5`'s pipeline uses trade-direction classification.
- **The past mirror does not catch this.** Bounce reversal genuinely predicts forward and not
  backward, so it passes the guard while being economically empty. This is precisely the failure
  mode the guard cannot see.

`ID-BOUNCE-01` is therefore an open threat to the headline result, not a caveat. It is discharged
only by a bounce-free reference price and by entering lagged returns as a competitor — a pure
autoregression should absorb most of a bounce-driven R², since bounce is a mechanical negative
AR(1). Specified for `D39`.

**Status of `last_trade` · `M5` +5.029%: a screening lead under an unresolved mechanical
alternative explanation. Not a finding.**
