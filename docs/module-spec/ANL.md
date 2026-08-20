# ANL — Analytics and reporting

## Objective

Produce canonical post-trade measurement: decomposed P&L, markouts, run/day reports, read-only dashboards, and notifications. ANL builds markout once for both reporting and SIG adverse-selection targets (D15).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Ledger events, fills, fees, positions, and market marks | Observed when sourced from broker/tape | Retain source/run identity and quality. |
| Markout and P&L decomposition | Deterministically derived from observed/estimated inputs | Greek components inherit GRK/SUR estimation labels. |
| Simulated-run attribution | Scenario/proxy | Inherits proxy fill labels; never mixed with realised P&L. |
| Dashboard/report | Presentation artifact | Does not raise the evidence level of its inputs. |
| ATM implied volatility at k = 0 | Estimated | The SUR-01 fit, after SUR-07 smoothing where smoothing applied, evaluated at log-moneyness zero on each fitted maturity. Read at the *forward*, so it moves when the forward moves even if no option reprinted; inherits the fit's labels and its smoothing state. Null with a reason when the slice cannot support the money — never filled in. |
| Held-out OOS R2 and incremental OOS R2 per (model, h1, h2) cell | Estimated | Produced by a fitted statistical model on a walk-forward split. Carries its support counts and its dependence-aware statistic; never reported as an iid significance claim. |
| Past-mirror placebo increment | Estimated (benchmark) | The identical apparatus run on a backwards-facing return of identical gap and horizon geometry. It is a benchmark for the future increment, not an independent finding, and is meaningless detached from the cell it benchmarks. |
| Placebo-benchmarked increment | Deterministically derived | Future incremental OOS R2 minus the past-mirror incremental OOS R2 for the same cell. Inherits both inputs' estimation labels. |
| Accumulated walk-forward score | Estimated | Pooled across all disjoint completed test blocks in a run. Genuinely out-of-sample only because of the one-way ratchet (`DASH-EST-03`); it is not interchangeable with a single most-recent block score. |
| Chance-expectation count | Deterministically derived | The number of the 175 cells expected to show a positive increment by chance alone at the displayed threshold. Displayed beside the observed green count so the comparison cannot be avoided. |
| Strike-held-out option fair value and band | Estimated | Fresh five-fold strike-held-out eSSVI price plus past-only empirical, forward and asynchrony uncertainty. The target strike's CE/PE cannot mark itself; unsupported or uncalibrated contracts stay explicit. |
| Confirmed surface-relative executable mispricing | Estimated classification | A fresh bid/ask outside the independent fair band that survives positive after-cost edge, displayed-lot, BH-FDR, exact leave-strike refit and two-frame persistence. It is not latent true value, arbitrage, fill, or order authority. |
| Mispricing correction duration and driver | Deterministically derived | Runs from first qualifying breach until two valid non-positive-net frames; stale/missing/failed paths are censored. Market/surface/mixed attribution is endpoint accounting, not causal identification. |

Gross P&L alone is insufficient: delta, gamma, vega, theta, spread capture, adverse selection, and fees must remain separately visible.

## Architecture and contracts

- Consumes `CON-02` ledger rows, GRK surface-consistent Greeks, and market marks.
- Exposes one markout implementation to SIG-08; SIG does not duplicate it.
- Consumes `CON-03` for surface dashboards.
- Dashboards and servers are read-only; notifications report state but cannot authorise or place orders.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-ANL-01 | Compute markouts and decompose P&L into delta, gamma, vega, theta, spread capture, adverse selection, and fees. | ANL-01, D15 | TBD `src/shaurya/analytics/attribution.py` | Hand-reconciled ledger fixtures; attribution artifact |
| REQ-ANL-02 | Produce per-run and per-day summaries from canonical attribution. | ANL-02 | TBD reporting module | Aggregate/reconciliation tests; run/day reports |
| REQ-ANL-03 | Provide a read-only dashboard/server for surface and trading analytics. | ANL-03 | TBD dashboard/server | Read-only and rendering/API tests; dashboard views |
| REQ-ANL-04 | Provide notifications and alerts with explicit component/run state. | ANL-04 | TBD notifier | Routing/deduplication/lifecycle tests; alert record |
| REQ-ANL-05 | Redesign ANL-03's presentation using the approved muted visual system, with a light/dark theme, preserving every measured field, object label, threshold and the arbitrage banner exactly. Aesthetic work may change layout, typography, colour and hierarchy only; it may not change model meaning or the value of any displayed number. **Amended 2026-08-19 on Aryan's explicit instruction:** the sustained-latency chart and the forward-source table are no longer drawn on screen. Both remain published in full at `/api/state`, so the forward choice per expiry stays a stated, retrievable model object under §7.1 — it is no longer a visible disclosure. No other panel may be dropped without the same explicit approval. **Extended 2026-08-19 on Aryan's instruction:** the dashboard must (a) let the viewer rotate, pan and zoom the surface freely while it keeps updating, holding the viewer's camera across every refresh until they reset it, and (b) display at-the-money implied volatility live as a hero number with its change since the previous fitted frame. ATM IV is the ledger's estimated k = 0 object above, not a new measurement. | ANL-05, ANL-03 | `src/shaurya/analytics/dashboard.py`, `src/shaurya/analytics/surface_feed.py` | Rendering/snapshot/accessibility tests; before/after field-parity audit; ATM-vs-grid parity test; headless camera-persistence probe; dashboard screenshots |
| REQ-ANL-06 | Provide a read-only **dynamic order-flow-imbalance dashboard**: the frozen `X-OFI-HORSERACE-DAT20-05` predictor apparatus (`M0`-`M6`) refitted continuously on a walk-forward split over the full 7 x 5 x 5 = 175-cell grid, driven either by replay of a pinned tape or by a read-only tail of a tape another process is writing. **It opens no socket and holds no order path.** Binding display constraints, approved by Aryan 2026-08-20: raw OOS R2 **and** the past-mirror placebo-benchmarked increment are both always visible; block and accumulated walk-forward scores are separately labelled and not interchangeable; the multiplicity chance-expectation count and leader churn are on screen; negative and insufficient-support cells stay visible; brick colour is reserved for the past-mirror-exceeds-future condition. Presentation inherits the `ANL-05` shell. The `M0`-`M6` formulas are called from `src/shaurya/signals/`, never restated. Exploratory and non-confirmatory: it is not a signal, carries no `SIG-21` authority, and does not alter `H-SIG21`. | ANL-06, ANL-05, ANL-03, D32 | TBD `src/shaurya/analytics/ofi_dashboard.py`, `src/shaurya/cli/ofi_dashboard.py`, reusing `src/shaurya/signals/ofi_horserace.py` | Walk-forward partition and one-way-ratchet tests; future-only/past-only leakage probe; torn-line tail probe; offline horse-race parity probe; theme and field-parity audit; per-cell JSONL record and compact summary |
| REQ-ANL-07 | Add the approved read-only **surface-relative executable option-mispricing monitor** below ANL-03. Fair value must be strike-held-out rather than the target's in-sample residual; eligibility requires fresh valid BBO, held-out support and dated tick/lot metadata; uncertainty is past-only and explicit; cheap uses ask, rich uses bid; positive after-cost edge must survive BH-FDR, an exact leave-strike refit and two-frame persistence. Correction needs two valid non-positive-net frames; unavailable data is censored. Show active and corrected/censored episode tables with gross/net size, duration and driver. No order, signal, arbitrage, fill or latent-true-value claim. | ANL-07, ANL-03, SUR-02/05/08, CON-01/05/06/07 | `src/shaurya/analytics/mispricing.py`, `surface_feed.py`, `dashboard.py`, `cli/surface_dashboard.py` | `tests/test_surface_mispricing.py`, `tests/test_anl03_dashboard.py`; frozen `docs/SURFACE-MISPRICING-SPEC-2026-08-20.md`; focused/full static and test gates; live verification pending |

## Outputs and acceptance tests

- Per-fill/per-cycle markouts, decomposed attribution, per-run/day summaries, read-only dashboard output, and alert audit records.
- Component sums reconcile to total P&L and fees; missing components are explicit, not zero-filled.
- Real and simulated results remain segregated and visibly labelled.
- SIG consumes the same markout output proven against ledger fixtures.
- Alerts distinguish expected completion, invalidation, degradation, and failure.
- Mispricing payloads preserve full policy/assumption provenance and separate active,
  corrected and censored episodes; no missing data is rewritten as correction.

## Exclusions

- Gross-only performance reporting.
- A second markout implementation inside SIG.
- Order placement, risk re-arm, or live authorisation through dashboards/notifications.
- Treating simulated fills or fitted Greeks as observed.

## Deferred items

- ANL-03 is Live verified for the surface-dashboard scope. ANL-05 is Implemented and
  Tested (27 dashboard tests, dry-run screenshots in both themes and in the degraded
  state, an ATM-vs-grid parity check and a headless camera-persistence probe); it is not
  yet Live verified, because no live session has run against the redesigned shell. ANL-01, ANL-02 and ANL-04 remain not started; D15 fixes
  attribution/markout ownership and decomposition.
- ANL-06 is specified and frozen at `docs/OFI-DASHBOARD-SPEC-2026-08-20.md` (scan `X-OFI-DASHBOARD-2026-08-20`) and not yet implemented. Its authority boundary is exploratory only; live verification against a growing tape is a separate and later statement than implemented and tested.
- ANL-07 is Implemented and Tested against synthetic causal chains; real-chain replay and live
  verification remain pending. Until then the detector is not Dry-run or Live verified even
  though the dashboard and API plumbing are tested.
