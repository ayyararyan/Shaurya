# SIG — Signal research and validation

## Objective

Make “data leads, strategy follows” operational (D8): construct a taxonomy-complete feature system, define distinct prediction targets, separate contemporaneous impact from prediction, control dependence and multiple testing, measure residual information left in the raw book, and promote only sparse interpretable signals that survive statistical and economic gates.

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Canonical book, trades, quotes, OI, and timestamps | Observed | Consumed from retained DAT tape with quality flags. |
| Registered features | Deterministically derived unless explicitly labelled otherwise | Each declares taxonomy cell, causal timestamp, construction, and category. |
| VOL regime, surface variables, dealer exposures, fitted impact | Estimated | Inherit model/version/uncertainty; never presented as observed. |
| Queue-position-dependent fill target | Estimated/proxy | Consumes EXE-09/10; true rank is unidentified. |
| Individual order identity, true queue rank, per-order lifetime, cancellation attribution | Unidentified | Aggregated depth has no order IDs (SIG-07). Never silently proxied. |
| Statistical finding | Estimated/inferential | Carries search-grid size, dependence-aware uncertainty, effective sample size, and trial history. |
| Tradeable candidate | Estimated finding that passed an economic scenario gate | Still not realised P&L or live evidence. |

## Architecture and contracts

- Consumes retained `CON-01` tape, `CON-05` identity, `CON-06` labels, and `CON-07` causal timestamps.
- Emits `CON-09` opportunity/finding records upstream of any strategy decision.
- Reuses VOL estimators, SUR/GRK options state, ANL markouts, and EXE fill realism; none is reimplemented inside SIG.
- Feature computation supports bounded-state forward streaming for the permanent feature tier. Permanent raw retention (D12/DAT-09) makes later recomputation possible where the tape contains the information.
- Black-box models are diagnostic yardsticks for the residual information gap, not promotable strategies (D11).

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-SIG-01 | Maintain a feature taxonomy/registry spanning static book, event flow, price path, cross-asset, options, and time/regime; every feature declares taxonomy cell, causal timestamp, and category. | SIG-01, D11 | TBD `src/shaurya/signals/registry.py` | Registry completeness/metadata tests; feature catalog |
| REQ-SIG-02 | Implement book-state features: spread, mid, microprice, depth imbalance, slope/curvature, notional within ticks, order-count/volume, and side asymmetry. | SIG-02 | TBD book feature module | Hand-calculated fixtures; feature frame |
| REQ-SIG-03 | Implement event-flow features: signed flow, multi-level OFI, arrival/cancel intensities, depletion, trade-size, and message intensity. | SIG-03 | TBD flow feature module | Event-sequence fixtures; feature frame |
| REQ-SIG-04 | Implement price-path features, consuming rather than duplicating VOL estimators, including returns, RV, variance ratio, microprice tilt, spreads, Kyle lambda, and Amihud. | SIG-04 | TBD path feature module | Lag/support/unit tests; feature frame |
| REQ-SIG-05 | Implement cross-asset features for underlying-to-option flow, index relationships, futures/spot basis and lead-lag, and cross-impact. | SIG-05 | TBD cross-asset module | Identity/alignment/lead-lag tests |
| REQ-SIG-06 | Implement options features for surface shape/velocity, term structure, dealer exposures, delta-space flow, and OI change. | SIG-06 | TBD options feature module | Surface/Greek alignment tests |
| REQ-SIG-07 | Encode the Dhan order-level identification boundary and forbid silent proxies for order identity, true rank, lifetime, or cancellation attribution. | SIG-07 | TBD registry constraints/docs | Schema rejection and boundary tests; identification ledger |
| REQ-SIG-08 | Maintain separate target families: price regression, censored hazard/intensity fill probability, and ANL-derived markout conditional on fill. | SIG-08, D15 | TBD target registry | Target-family and provenance tests; target catalog |
| REQ-SIG-09 | Construct strictly lagged labels; separate contemporaneous impact from prediction and ban targets deterministic in current features. | SIG-09, CON-07 | TBD labels module | Leakage and deterministic-target rejection tests |
| REQ-SIG-10 | Cluster/PCA correlated features before selection and compute importance at cluster, not individual collinear-feature, level. | SIG-10, D11 | TBD redundancy module | Synthetic-collinearity tests; cluster artifact |
| REQ-SIG-11 | Use HAC/Newey–West with lag at least overlap, non-overlapping resampling, and stationary block bootstrap; report effective sample size with every t-statistic. | SIG-11 | TBD inference module | Coverage/calibration fixtures; inference report |
| REQ-SIG-12 | Control multiple testing over the full recorded search grid using Romano–Wolf or Hansen SPA. | SIG-12 | TBD multiple-testing module | Null-grid calibration tests; adjusted finding record |
| REQ-SIG-13 | Run stability selection inside purged/embargoed walk-forward CV, report per-cluster/window frequency, and use knockoffs as confirmation. | SIG-13, D11 | TBD selection module | Purge/embargo/FDR tests; selection-frequency artifact |
| REQ-SIG-14 | Decompose contemporaneous and predictive effects with a Hasbrouck VAR, impulse responses, and permanent/transitory impact. | SIG-14 | TBD impact module | Simulated-VAR recovery tests; decomposition report |
| REQ-SIG-15 | Evaluate OOS R² against no-change, compare forecasts with Diebold–Mariano/Giacomini–White, and report Hansen's Model Confidence Set. | SIG-15, D11 | TBD evaluation module | Known-ranking/equal-model tests; MCS report |
| REQ-SIG-16 | Condition every result on VOL's HMM regime and downgrade regime-unstable signs to regime indicators. | SIG-16 | TBD regime evaluation | Regime-slice/sign-stability tests |
| REQ-SIG-17 | Promote a finding only when predicted edge clears half-spread, fees, and adverse selection under EXE-09. | SIG-17 | TBD economic gate | Boundary/cost/fill-model tests; promotion decision |
| REQ-SIG-18 | Measure the OOS gap between raw-book and engineered-feature models and diagnose residuals by time, regime, and raw-book slices; unexplained gaps create missing-feature tickets. | SIG-18, D11, D12 | TBD coverage module | Golden-tape residual-gap report and ticket output |
| REQ-SIG-19 | Log every tested configuration and report a performance distribution using combinatorially purged CV and deflated Sharpe. | SIG-19 | TBD trial registry | Append-only/completeness tests; trial log |
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
