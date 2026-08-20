# Dynamic order-flow-imbalance dashboard — frozen specification

**Task ID:** `ANL-06`
**Scan ID:** `X-OFI-DASHBOARD-2026-08-20`
**Frozen:** 2026-08-20, before any dashboard code was written and before any live
walk-forward score was inspected.
**Confirmatory eligible:** `false`
**Evidence boundary:** an exploratory, continuously refitted predictive comparison rendered on
screen. Never causal, confirmed, tradeable, economic, representative, or a signal. It does not
feed `H-SIG21`, does not consume `SIG-21` calibration authority, and carries no order path.

Owner decisions taken by voice 2026-08-20 ~10:24 IST, recorded here rather than assumed:
full grid; **both** placebo-benchmarked and raw out-of-sample R2 displayed; build first and
verify in replay, then attach; inherit the `ANL-05` shell (light/dark toggle, monospace type,
muted palette, hero band).

---

## 1. Claim and estimand

The question on screen is: **which causally available order-flow feature, measured over which
lookback, has the largest held-out incremental explanatory power for a later NIFTY front-month
futures midpoint return, at which forward horizon — and does that gain exceed what the same
apparatus produces on a backwards-facing placebo?**

The unit is a valid depth200 publication anchor. The estimand per cell is held-out OOS R2
against the training-mean target, incremental OOS R2 over the depth-only baseline `M0`, and the
same two quantities recomputed on a past-mirror return of identical geometry.

This is predictive, not causal. Time ordering does not identify a structural counterfactual. A
dashboard does not raise the evidence level of its inputs (`ANL` object ledger).

## 2. Why the placebo is on screen and not in an appendix

`DASH-00` (binding rationale, not commentary). A live leaderboard over a large grid is a
data-dredging surface: with 175 model-cells refitted every minute, some cell is always green.
This front's own evidence says the placebo is not hypothetical —

- `X-OFI-DAT20-03`: best cell +7.91 pp future incremental, **+13.29 pp past-mirror**.
- `X-DEEPBOOK-DAT20-02`: past-return placebo fired at roughly four times the real rate.
- `X-OFI-LATEPARTIAL-2026-08-20`, 09:55 read: scalar top-10 +5.00 pp forward, **+28.74 pp**
  past mirror.

Therefore the placebo-benchmarked increment is a **first-class displayed quantity, always
visible, never behind a toggle or a click**, and no cell may be rendered in a favourable state
while its past-mirror increment exceeds its future increment.

---

## 3. DATA — sample, drive modes and timing

- **DASH-DATA-01 — two drive modes, one engine.** `replay` reads a pinned retained tape and
  reproduces the session deterministically in tape time. `follow` tails a canonical JSONL tape
  that a separate `capture_dhan` process is currently writing.
- **DASH-DATA-02 — no new subscription.** The dashboard **opens no Dhan socket in either
  mode**. `follow` is a read-only file tail. This is specification, not an optimisation: it
  keeps the process outside the standing two-socket concurrency budget and outside any
  credential path. A future live-socket mode would be a specification change under §14 of the
  working instructions.
- **DASH-DATA-03 — torn-line safety.** While tailing a file under active write, only complete,
  newline-terminated, JSON-parsable lines are consumed. A truncated trailing line is retained
  in a buffer and re-read; it is never parsed, never zero-filled, never skipped silently. Torn
  and malformed line counts are published.
- **DASH-DATA-04 — grid.** Full frozen grid, as approved: predictor lookbacks
  `h1 in {0.5, 1, 2, 5, 10}` seconds; forward horizons `h2 in {0.5, 1, 2, 5, 10}` seconds;
  models `M0..M6`. 7 x 5 x 5 = **175 model-cells**, all evaluated, all displayed, including
  negative ones.
- **DASH-DATA-05 — gap and response.** Gap `Z = 0.5` s. Predictors end at anchor `t`. Future
  response is `mid(t + Z + h2) - mid(t + Z)` in NIFTY ticks (Rs 0.05), resolved as-of, never
  crossing a connection epoch.
- **DASH-DATA-06 — past mirror.** For every cell, the identical apparatus is run on
  `mid(t - Z) - mid(t - Z - h2)`: same gap, same horizon, same anchors, same models, same
  fitting protocol. Identical geometry is required; an approximate mirror is not a placebo.
- **DASH-DATA-07 — epoch and quality filters.** Reuse the `X-OFI-DAT20-03` quality and epoch
  filters, causal as-of resolution and complete-window guards without modification. No window
  spans a connection epoch. Capture time only; wall-clock is never used to order observations.
- **DASH-DATA-08 — anchors.** Valid depth200 publication anchors only, consistent with `D32`.
  depth20 remains response and near-book control measurement.

## 4. STATE/FLOW — predictor objects

`M0` through `M6` are **reused verbatim** from `docs/OFI-HORSERACE-SPEC-2026-08-19.md` §
"STATE/FLOW". No formula is restated here and no variant is introduced, so that a divergence
between the live dashboard and the offline horse race is impossible by construction:

- `M0 / STATE-01` depth only; `M1 / STATE-02` static L1 queue imbalance;
  `M2 / FLOW-01` signed trade imbalance; `M3 / FLOW-02` exact L1 CKS OFI;
  `M4 / FLOW-03` regularised multi-level price-keyed OFI in marginal rank bands
  `1, 2-5, 6-10, 11-20, 21-50, 51-100, 101-200`; `M5 / FLOW-04` depth-adjusted multi-level OFI;
  `M6 / EST-01` combined.
- **DASH-FLOW-01:** the canonical implementations in `src/shaurya/signals/` are called
  directly. If a live requirement cannot be met by the existing implementation, that is a
  finding to report, not a licence to write a second formula.
- **DASH-FLOW-02:** `M2` is scored honestly or classified `Blocked/Unidentified` with its
  support stated. Missing signed trades are never replaced by zero and `M2` never receives a
  fabricated score.

## 5. EST — walk-forward protocol on a growing tape

This section is the substantive difference from the offline horse race and the main place a
live dashboard can silently cheat.

- **DASH-EST-01 — expanding train, most-recent test block.** At each refit time `tau`, anchors
  are partitioned by capture time into: training (everything up to the embargo boundary),
  embargo, and one held-out **test block** of fixed duration (default 120 s of anchors).
- **DASH-EST-02 — embargo.** The embargo between training and test is
  `max(120 s, Z + h2)` per cell, so a response window can never straddle the split.
- **DASH-EST-03 — one-way ratchet.** Once an anchor has entered a training set it can never
  re-enter any test set. Consecutive test blocks are therefore **disjoint** and each is scored
  exactly once, before the model that scores it has ever seen it.
- **DASH-EST-04 — two displayed scores, and they are not interchangeable.**
  - **Block score:** the most recent completed test block alone. Live-feeling and very noisy.
  - **Accumulated walk-forward score:** pooled across **all disjoint completed test blocks**
    since the run began. This is the number the dashboard treats as authoritative, and the
    block score must never be presented as though it carried the same weight.
  The accumulated score is a genuine out-of-sample record because of `DASH-EST-03`; it is not a
  re-scored training set.
- **DASH-EST-05 — training-only everything.** Standardisation parameters, Ridge penalty
  selection (`alpha in {0, 0.01, 0.1, 1, 10, 100}` over three expanding embargoed inner folds,
  deterministic lowest-alpha tie-break) and every fitted transformation use training rows only.
  The response mean removed from test outcomes is the **training** mean, never the test mean.
- **DASH-EST-06 — common complete cases.** Within a cell, all identified models are scored on
  one common complete-case sample. Per-model construction and support loss before intersection
  is published.
- **DASH-EST-07 — warm-up gate.** A cell is not scored, ranked or coloured until it has at
  least `N_min` training anchors (default 600) **and** at least one completed test block. Before
  that it renders as `WARMING`, with its current support — never as a zero, a blank, or a
  neutral value that could be read as "no effect".
- **DASH-EST-08 — support floor.** A cell whose test block cannot support a dependence-aware
  statistic is rendered `INSUFFICIENT` with its counts. A number is not emitted for it.
- **DASH-EST-09 — refit cadence and honest lag.** Default cadence 60 s. If a refit cycle
  exceeds the cadence, the dashboard **skips** rather than queueing, and publishes
  `refits_skipped` and the age of the displayed fit. Falling behind silently is prohibited;
  a stale grid must announce that it is stale, in the manner of `SUR-07`.

## 6. ROB — dependence, multiplicity and the honesty panel

- **DASH-ROB-01 — dependence.** Overlapping `h2` windows are not independent. Report
  Newey-West/HAC with lag at least the response overlap, and a within-block stationary block
  bootstrap where support permits. No iid significance claim is made or displayed.
- **DASH-ROB-02 — multiplicity is displayed, not merely computed.** The family is all 175
  cells. Alongside the count of cells currently showing a positive benchmarked increment, the
  dashboard displays **the number expected by chance alone** at the same threshold. With 175
  cells at a 5% threshold that expectation is approximately 8.75. A green count of six is
  therefore not evidence, and the screen must make that arithmetic impossible to miss.
- **DASH-ROB-03 — BH-FDR view.** A Benjamini-Hochberg adjusted view across the 175-cell family
  is available on the same screen, computed from the dependence-aware statistic.
- **DASH-ROB-04 — churn.** Display `cells green now` against `cells ever green` and the
  identity of the current leader against how many distinct cells have led. High churn with a
  low persistent count is the signature of noise, and is precisely what a static end-of-day
  report hides.
- **DASH-ROB-05 — collinearity.** For `M4`, `M5` and `M6`, publish maximum feature-feature
  correlation and VIF. `X-OFI-LATEPARTIAL-2026-08-20` observed `M6` correlations of
  0.9966-0.9985 and VIF 155.9-356.1; where a cell is in that regime its individual coefficients
  are labelled unstable and its betas are not interpreted on screen.
- **DASH-ROB-06 — same-window diagnostic separated.** Any contemporaneous-window fit is a
  construction diagnostic only, visually and structurally separated from ranked future results,
  never in the leaderboard.

## 7. OUT — display contract

Presentation inherits the `ANL-05` shell: light/dark toggle persisted to `localStorage`
defaulting to `prefers-color-scheme`; monospace type scale with tabular numerals; muted palette
(slate `#46586b`/`#8199b0`, brass `#b5851f`/`#d3a44a`, brick `#8f3327`/`#c05c46`, sage
`#5b7a52`/`#8faa7c`, ivory `#f4f2ec`, charcoal `#17191c`); hairline rules and a full-bleed
status rail. No bright palette.

- **DASH-OUT-01 — hero band.** The current leader by **accumulated placebo-benchmarked
  incremental OOS R2**, large, with its model, `h1`, `h2`, its raw increment, its past-mirror
  increment, and the chance-expectation figure from `DASH-ROB-02` beside it. The hero never
  shows a raw increment alone.
- **DASH-OUT-02 — both scores, always.** Every cell view shows raw OOS R2 **and** the
  placebo-benchmarked increment simultaneously, per the owner decision. Neither is hidden
  behind interaction.
- **DASH-OUT-03 — grid.** An `h1 x h2` heatmap per model family. Magnitude is a single-hue
  slate ramp. **Brick is reserved** for the condition "past-mirror increment >= future
  increment" — the one visual state that must be unmissable. Sign is carried by a glyph and a
  signed number, never by hue alone.
- **DASH-OUT-04 — status rail.** Drive mode, tape identity and run ID, anchors consumed, rows
  parsed, torn/malformed lines, current epoch, fit age, refits completed and skipped, warm-up
  and insufficient-support counts, and the wall-clock of the last completed refit.
- **DASH-OUT-05 — read-only server.** `GET /`, `/api/state`, `/api/history`, `/api/cells`. No
  write method is implemented. The full per-cell record — including every quantity not drawn on
  screen — is retrievable at `/api/cells`, so nothing measured is lost by a presentation choice
  (the `ANL-05` precedent).
- **DASH-OUT-06 — labels travel with numbers.** Every displayed quantity carries its object
  category from the `ANL` ledger. Estimated stays estimated; a proxy stays labelled a proxy.
- **DASH-OUT-07 — persisted record.** Each completed refit appends a deterministic JSONL row
  per cell to the run artifact directory, so the session's walk-forward record is reproducible
  after the screen is closed. Large outputs are gitignored; a compact summary is committed.

## 8. VAL — acceptance

- **DASH-VAL-01:** Hand-worked tests for the walk-forward partition: one-way ratchet
  (`DASH-EST-03`) proven by construction, embargo width per cell, disjointness of consecutive
  test blocks, training-only standardisation, and refusal to score below the warm-up gate.
- **DASH-VAL-02:** A leakage probe — a synthetic tape carrying a known future-only signal must
  be detected, and a synthetic tape carrying a known **past-only** signal must produce a
  benchmarked increment at or below zero. A dashboard that cannot fail this test cannot be
  trusted to report a negative.
- **DASH-VAL-03:** Torn-line probe: a tape written byte-by-byte under an active tail must
  produce identical output to the same tape read complete.
- **DASH-VAL-04:** Parity probe: `replay` mode over a pinned `DAT-20` tape must reproduce the
  offline `X-OFI-HORSERACE-DAT20-05` cell scores for the equivalent split, within stated
  tolerance. Divergence is a defect in one of the two, to be diagnosed, not averaged away.
- **DASH-VAL-05:** Rendering and theme tests, field-parity audit against this contract, and
  dry-run screenshots in both themes and in a degraded state.
- **DASH-VAL-06:** Ruff, strict mypy, full Python suite, compileall, diff check, staged secret
  scan, deterministic replay hash.
- **DASH-VAL-07:** Update `TASKS.md` and `CHANGELOG.md` with `ANL-06` and the scan ID. Do not
  edit `H-SIG21.md`.

## 9. Explicit exclusions

No orders, no order path, no credentials beyond those already held by the capture process, no
new socket or subscription, no live trading decision, no transaction-cost claim, no strategy
promotion, no causal interpretation, no confirmation claim, no `SIG-21` calibration authority,
no outcome-driven change to any registered grid, and no result that alters immutable
`H-SIG21`. The dashboard's output is not a signal and may not be described as one.

## 10. Completion criterion

`ANL-06` is complete when: all 175 cells are evaluated and displayed including negative and
insufficient ones; both raw and placebo-benchmarked scores are simultaneously visible; block
and accumulated walk-forward scores are separately labelled; the multiplicity, chance-expectation
and churn panels are live; `M2` is honestly scored or classified unidentified; the leakage,
torn-line and offline-parity probes pass; artifacts replay deterministically; tests and static
checks are reported; and the work is committed and pushed with local `HEAD == origin/main`
clean.

Live verification is a separate and later statement: implemented and tested is not live
verified, and attaching to a growing tape is not a result.
