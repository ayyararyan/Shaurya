# SIG — Signal research and validation

## Objective

Make “data leads, strategy follows” operational (D8): construct a taxonomy-complete feature system, define distinct prediction targets, separate contemporaneous impact from prediction, control dependence and multiple testing, measure residual information left in the raw book, and promote only sparse interpretable signals that survive statistical and economic gates.

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Canonical book, trades, quotes, OI, and timestamps | Observed | Consumed from retained DAT tape with quality flags. |
| Registered features | Deterministically derived unless explicitly labelled otherwise | Each declares taxonomy cell, causal timestamp, construction, and category. |
| VOL regime, surface variables, dealer exposures, fitted impact | Estimated | Inherit model/version/uncertainty; never presented as observed. |
| Queue-position-dependent fill target | Estimated, with reported bounds | Consumes EXE-09/10. Bounded rather than unidentified under D23; bounds propagate into every fill-conditional result. |
| Individual order identity, per-order lifetime, cancellation position in queue, hidden/iceberg quantity | Unidentified | Aggregated depth has no order IDs (SIG-07). Never silently proxied. |
| Own queue-ahead and queue-conditional arrival/cancel/trade intensities | Estimated, with reported bounds | Partially identified from price-time priority, level deltas, order counts and observed trades (D23). Bound width is measured, not assumed. |
| Statistical finding | Estimated/inferential | Carries search-grid size, dependence-aware uncertainty, effective sample size, and trial history. |
| Tradeable candidate | Estimated finding that passed an economic scenario gate | Still not realised P&L or live evidence. |

## Architecture and contracts

- Consumes retained `CON-01` tape, `CON-05` identity, `CON-06` labels, and `CON-07` causal timestamps.
- Emits `CON-09` opportunity/finding records upstream of any strategy decision.
- Reuses VOL estimators, SUR/GRK options state, ANL markouts, and EXE fill realism; none is reimplemented inside SIG.
- Feature computation supports bounded-state forward streaming for the permanent feature tier. Permanent raw retention (D12/DAT-09) makes later recomputation possible where the tape contains the information.
- Black-box models are diagnostic yardsticks for the residual information gap, not promotable strategies (D11).

## Shaurya quotes; it does not cross (D21)

Decided 2026-08-19: Shaurya trades as a **maker**, never a taker. The spread is not crossed.

This fixes SIG's primary estimand on the maker side and inverts the target of most
taker-oriented microstructure results. The governing question is not "will the price move" but
"conditional on a resting quote being filled, what is the markout, and what was the probability
of that fill". Concretely:

- SIG-08's leading target families are fill probability (censored hazard / EXE-09 intensity) and
  markout-conditional-on-fill supplied by ANL-01. Directional forecast regression remains in
  scope as an input to quote placement, not as the objective.
- SIG-17's economic gate is restated for a maker: expected spread capture must exceed adverse
  selection plus side-specific taxes, fees and hedging cost. This is a different inequality from
  the taker's half-spread hurdle, not a softer one.
- EXE-10's labelled queue-position estimator is load-bearing, because maker fill probability
  depends on queue rank while SIG-07 holds true rank unidentified. Its estimated/proxy label
  propagates into every fill-conditional result.
- The binding latency is cancel latency, not decision latency. The maker's characteristic loss is
  being executed on a quote that should already have been withdrawn.

Recorded risk, not a blocker: quoting from a retail broker's public feed into a market where a
majority of derivatives turnover is co-located is structurally adverse. What maker edge survives
for a non-co-located participant is an open empirical question, addressed by the commissioned
maker research rather than assumed either way.

## Queue priority is partially identified, not unidentified (D23)

Corrected 2026-08-19. SIG-07 previously treated "true queue position" as a single unidentified
object. That conflated two different objects with different identification status.

**Own queue-ahead is bounded, not unidentified.** NSE index F&O matches on price-time priority, so
at placement a resting order's queue-ahead equals the displayed quantity at that price. Trades at
that price decrement it exactly from the front and are observable from last price, last quantity
and cumulative volume. Cancellations at the level are observable in aggregate — the level delta net
of additions and trades — but their position relative to our own order is not, which produces a hard
upper and lower bound plus a point estimate under an explicit cancellation-position model.

**Intensities are estimable.** Arrival, cancellation and trade intensities conditional on queue size
— the actual inputs to the queue-reactive fill model consumed by EXE-09 — follow from level-by-level
deltas. That literature was built for aggregated Level-2 data and never required order IDs. Order
counts per level further give average order size and tighten the add/cancel decomposition.

**Still unidentified, unchanged:** the position of a cancellation within the queue; individual order
identity and per-order lifetime; and hidden or iceberg quantity, which corrupts queue-ahead directly
and is invisible at any depth tier.

**The binding limit is packet coalescing, and it is measurable.** At roughly eight packets per
second, several events net into a single observed delta and the decomposition is under-determined
within that interval. Bound width is therefore an empirical quantity EXE-10 measures and reports,
not a constant asserted in advance. EXE-10's CON-06 label is accordingly estimated with reported
bounds, not an unqualified proxy, and those bounds propagate into every fill-conditional result.

## The claim ledger is pre-registered (D22)

The SIG research agenda is decomposed to claim level with stable IDs, each claim recording its
mechanism, resolved citations, capture path from our own feed, confirming test, falsifying test
and CON-06 identification status. The ledger is the pre-registered hypothesis set against which
SIG-19's trial log is checked: anything tested appears in the ledger first, and additions are
recorded before results are inspected. Literature seeds claims; it does not settle them, and the
ledger stays open to mechanisms the literature does not anticipate.

## Measurement design is empirical (D20)

The sampling clock (event / calendar / volume time), the pooling coordinate (instrument identity
versus a stationary delta-moneyness x tenor coordinate), and the prediction horizon set are **not
specification constants**. Decided 2026-08-19: they are empirical questions resolved by
measurement, and the answer is permitted to change as more tape accumulates. D12's raw event-time
tape is the maximal-information capture choice, so none of the three is foreclosed at collection
time.

Consequently each is an explicit swept axis in the SIG-19 trial log and is counted in SIG-12's
multiple-testing grid; none may be silently fixed by an implementation. Because an unbounded sweep
over clock x pooling x horizon x feature set is correctly annihilated by Romano-Wolf and deflated
Sharpe, the plausible ranges of the three axes must be narrowed from theory and prior evidence
before the sweep begins, never by inspecting outcomes.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-SIG-01 | Maintain a feature taxonomy/registry spanning static book, event flow, price path, cross-asset, options, and time/regime; every feature declares taxonomy cell, causal timestamp, and category. | SIG-01, D11 | TBD `src/shaurya/signals/registry.py` | Registry completeness/metadata tests; feature catalog |
| REQ-SIG-02 | Implement book-state features: spread, mid, microprice, depth imbalance, slope/curvature, notional within ticks, order-count/volume, and side asymmetry. | SIG-02 | TBD book feature module | Hand-calculated fixtures; feature frame |
| REQ-SIG-03 | Implement event-flow features: signed flow, multi-level OFI, arrival/cancel intensities, depletion, trade-size, and message intensity. | SIG-03 | TBD flow feature module | Event-sequence fixtures; feature frame |
| REQ-SIG-04 | Implement price-path features, consuming rather than duplicating VOL estimators, including returns, RV, variance ratio, microprice tilt, spreads, Kyle lambda, and Amihud. | SIG-04 | TBD path feature module | Lag/support/unit tests; feature frame |
| REQ-SIG-05 | Implement cross-asset features for underlying-to-option flow, index relationships, futures/spot basis and lead-lag, and cross-impact. | SIG-05 | TBD cross-asset module | Identity/alignment/lead-lag tests |
| REQ-SIG-06 | Implement options features for surface shape/velocity, term structure, dealer exposures, delta-space flow, and OI change. | SIG-06 | TBD options feature module | Surface/Greek alignment tests |
| REQ-SIG-07 | Encode the Dhan order-level identification boundary and forbid silent proxies for order identity, per-order lifetime, cancellation position within the queue, or hidden quantity. Own queue-ahead and queue-conditional intensities are excluded from this boundary: under D23 they are partially identified and carried as estimates with measured bounds, not as unidentified quantities. | SIG-07, D23 | TBD registry constraints/docs | Schema rejection and boundary tests; identification ledger |
| REQ-SIG-08 | Maintain separate target families, led by the maker-side pair under D21: censored hazard/intensity fill probability and ANL-derived markout conditional on fill, with price regression retained as a quote-placement input rather than the objective. | SIG-08, D15, D21 | TBD target registry | Target-family and provenance tests; target catalog |
| REQ-SIG-09 | Construct strictly lagged labels; separate contemporaneous impact from prediction and ban targets deterministic in current features. | SIG-09, CON-07 | TBD labels module | Leakage and deterministic-target rejection tests |
| REQ-SIG-10 | Cluster/PCA correlated features before selection and compute importance at cluster, not individual collinear-feature, level. | SIG-10, D11 | TBD redundancy module | Synthetic-collinearity tests; cluster artifact |
| REQ-SIG-11 | Use HAC/Newey–West with lag at least overlap, non-overlapping resampling, and stationary block bootstrap; report effective sample size with every t-statistic. | SIG-11 | TBD inference module | Coverage/calibration fixtures; inference report |
| REQ-SIG-12 | Control multiple testing over the full recorded search grid using Romano–Wolf or Hansen SPA; the grid includes the sampling-clock, pooling-coordinate, and horizon axes (D20), not features alone. | SIG-12, D20 | TBD multiple-testing module | Null-grid calibration tests; adjusted finding record |
| REQ-SIG-13 | Run stability selection inside purged/embargoed walk-forward CV, report per-cluster/window frequency, and use knockoffs as confirmation. | SIG-13, D11 | TBD selection module | Purge/embargo/FDR tests; selection-frequency artifact |
| REQ-SIG-14 | Decompose contemporaneous and predictive effects with a Hasbrouck VAR, impulse responses, and permanent/transitory impact. | SIG-14 | TBD impact module | Simulated-VAR recovery tests; decomposition report |
| REQ-SIG-15 | Evaluate OOS R² against no-change, compare forecasts with Diebold–Mariano/Giacomini–White, and report Hansen's Model Confidence Set. | SIG-15, D11 | TBD evaluation module | Known-ranking/equal-model tests; MCS report |
| REQ-SIG-16 | Condition every result on VOL's HMM regime and downgrade regime-unstable signs to regime indicators. | SIG-16 | TBD regime evaluation | Regime-slice/sign-stability tests |
| REQ-SIG-17 | Promote a finding only when expected maker spread capture clears adverse selection, side-specific taxes, fees and hedging cost under EXE-09 (D21); the taker half-spread hurdle does not apply because the spread is never crossed. | SIG-17, D21 | TBD economic gate | Boundary/cost/fill-model tests; promotion decision |
| REQ-SIG-18 | Measure the OOS gap between raw-book and engineered-feature models and diagnose residuals by time, regime, and raw-book slices; unexplained gaps create missing-feature tickets. | SIG-18, D11, D12 | TBD coverage module | Golden-tape residual-gap report and ticket output |
| REQ-SIG-19 | Log every tested configuration — including sampling clock, pooling coordinate, and horizon (D20) — and report a performance distribution using combinatorially purged CV and deflated Sharpe. | SIG-19, D20 | TBD trial registry | Append-only/completeness tests; trial log |
| REQ-SIG-20 | Require each permanent-tier feature to be computable in one bounded-state forward pass without future data or same-day refit. | SIG-20, DAT-09 | TBD streaming feature API | Streaming/batch parity, bounded-state, leakage tests |

## Outputs and acceptance tests

- Versioned feature and target registries, causal feature frames, cluster maps, trial logs, inference reports, Model Confidence Sets, coverage-gap reports, and `CON-09` findings.
- Purging/embargo tests prove overlapping labels cannot enter training validation improperly.
- Multiple-testing fixtures demonstrate family-wide rather than per-feature control.
- Streaming/batch parity proves online features match causal offline reconstruction.
- A candidate is “tradeable” only after interpretability, stability, MCS, and economic gates; this is not Live verified profitability.

## Exclusions

- Black-box models as deployed strategies.
- Regression for censored fill probability.
- Deterministic current-book labels presented as forecasts.
- Feature-wise importance under unresolved collinearity.
- Tick/order objects absent from the retained feed.
- Strategy-specific parameter tuning before a data-shown opportunity exists.

## Deferred items

- SIG-18 golden-set scale depends on the final DAT depth/universe plan, but permanent raw retention is resolved by D12/DAT-09.
- Unidentified SIG-07 objects remain permanently outside recoverable scope unless the data source itself changes under explicit change control.
