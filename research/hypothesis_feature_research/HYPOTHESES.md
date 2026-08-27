# Master hypothesis catalogue

This is the human-readable view of `hypotheses.csv`. Source paths are clickable relative to this
directory. `Verified from code` means the implementation was inspected; `Verified from existing
documentation` means a retained document/result was read but not independently replayed;
`Inferred` is explicitly bounded; and unknowns require researcher input. A passing pytest test is
never empirical support.

## Families

| Family ID | Scope |
|---|---|
| `HF-research-integrity` | Source completion, causal timing, walk-forward, nulls, multiplicity, evidence lifecycle |
| `HF-data-quality` | Feed cadence, alignment, depth thinning, occupancy, normal activity |
| `HF-reference-price` | Displayed mid, last trade, effective-touch proxy, microprice |
| `HF-order-flow` | CKS/CCZ OFI construction, incremental prediction, horizon/state dependence |
| `HF-deep-book` | Price-keyed deep events and registered response family |
| `HF-options-surface` | eSSVI construction/readiness and IV-residual episodes |
| `HF-surface-alpha` | Incremental futures forecasting from option-surface state |
| `HF-feature-selection` | Quality/redundancy/usefulness/stability and post-close option markouts |
| `HF-infrastructure` | Packaging, schemas, public boundaries, CLI/dashboard read-only contracts |

## `H-research-integrity-001` — Completed-source and causal-boundary integrity

- **Family / basis:** `HF-research-integrity`; Verified from code.
- **Question and rationale:** Can a research run be bound to a completed, hash/index/coverage-
  verified tape and refuse future or caller-authored evidence? Without that boundary, a valid model
  result could still describe a partial/cancelled source or leaked feature.
- **Null / alternative / direction:** H0: the gates do not reliably prevent incomplete-source or
  future-information use. H1: inconsistent lifecycle, hashes, index, coverage, replay, or
  availability fail closed. No economic direction; rejection is expected on invalid inputs.
- **Scope and observation:** Dataset-level integrity plus instrument/anchor feature observations;
  any Shaurya Research instrument/venue represented by a catalogue handle. Receive-time is stored
  as an instant; session labels are IST. Raw inputs are catalogue lifecycle, manifests, coverage,
  tape/index hashes, replay rows, feature/anchor timestamps.
- **Features:** `F-source-completion-state`, `F-feature-availability-time`.
- **Method, filters, leakage:** Conjoin completion/identity/hash/index/coverage/full-replay checks;
  require `available_ts_ns <= anchor_ts_ns`; reject forged folds, caller evidence, cross-boundary
  joins, and private dataset entry points. No transformation invents missing integrity state.
- **Tests:** `T-research-adversarial-acceptance`
  ([source](../tests/test_adversarial_acceptance.py)),
  `T-research-contracts-and-planner`
  ([source](../tests/test_contracts_and_planner.py)),
  `T-research-v3-seeded-full-pipeline`
  ([source](../tests/test_v3_seeded_full_pipeline.py)),
  `T-research-v3-source-bound-e2e`
  ([source](../tests/test_v3_source_bound_e2e.py)), and
  `T-architecture-boundary` ([source](../tests/test_architecture_boundary.py)).
- **Evaluation / outputs:** Boolean accept/refuse, deterministic hashes, and temporary integration
  artifacts; no durable empirical result.
- **Status:** implementation `implemented`; evidence `unable to determine`.
- **Limits / unresolved:** Synthetic/adversarial cases cannot measure real false-negative rate or
  prove upstream packet completeness. Researcher must approve any relaxation of completion gates.

## `H-research-integrity-002` — Auditable selection and evidence lifecycle

- **Family / basis:** `HF-research-integrity`; Verified from code.
- **Question and rationale:** Do frozen nested walk-forward folds, complete-miner nulls,
  multiplicity, stability gates, and append-only state prevent winner-only reporting and unstable
  promotion?
- **Null / alternative / direction:** H0: the lifecycle can promote selectively reported or
  unstable results. H1: complete families are recorded and promotion remains blocked until all
  declared gates pass. No economic sign; stable injected alpha should recover and negative
  controls should warn.
- **Scope and observation:** Registered candidate/fold/session observations across Research;
  synthetic tests use dated sessions and causal rows. Inputs are registries, policies, feature and
  target observations, fold dates, null replicates, bootstrap blocks, and evidence ledger events.
- **Features:** `F-source-keyed-ar1-control`, `F-feature-correlation-cluster`,
  `F-feature-conditional-oos-delta`, `F-time-regime`.
- **Method, filters, leakage:** Freeze historical/inner/outer boundaries; rerun the full miner per
  null replicate; adjust declared families; block-bootstrap within sessions; require unique OOS
  sessions, sign/neighbor/adjusted-evidence gates; hash-chain and prevalidate ledger writes.
- **Tests:** `T-research-walkforward-and-synthetic`
  ([source](../tests/test_walkforward_and_synthetic.py)),
  `T-research-surfaces-nulls-multiplicity`
  ([source](../tests/test_surfaces_nulls_multiplicity.py)),
  `T-research-ledger-state-lifecycle-executor`
  ([source](../tests/test_ledger_state_lifecycle_executor.py)),
  `T-research-research-cli` ([source](../tests/test_research_cli.py)), and
  `T-research-v3-seeded-full-pipeline`
  ([source](../tests/test_v3_seeded_full_pipeline.py)).
- **Evaluation / outputs:** Outer scores, adjusted p-values, bootstrap intervals, stability/lifecycle
  status, ledger/state identities; test outputs are temporary.
- **Status:** implementation `implemented`; evidence `unable to determine`.
- **Limits / unresolved:** Synthetic calibration does not establish live-data error control.
  Researchers own family boundaries, promotion effect sizes, and amendment policy.

## `H-data-quality-001` — Publication cadence and channel alignment

- **Family / basis:** `HF-data-quality`; Verified from code and existing documentation.
- **Question and rationale:** What cadence, age, coalescing, and cross-depth alignment properties are
  observed? Channel asynchrony can otherwise be mistaken for market dynamics.
- **Null / alternative / direction:** H0: differences are indistinguishable from declared timing
  tolerances. H1: cadence/age/flip measures reveal systematic behavior. The code is descriptive and
  does not prespecify an economic sign.
- **Scope and observation:** Standard/Full, depth20, and depth200 NIFTY-related tape rows; venue NSE
  where instrument metadata says so; receive-time bursts/transitions within session/epoch. Inputs
  are channel, receive timestamp, state signatures, and quality/epoch fields.
- **Features:** `F-publication-cadence-gap-ms`, `F-receive-age-ms`,
  `F-depth-channel-agreement`.
- **Method, filters, leakage:** Collapse exact receive timestamps; compute gaps/change rates;
  compare last-at-or-before same-tier states; keep stale/degraded observations outside directional
  denominators. Phase-tolerant post-anchor matches are diagnostics, not causal predictors.
- **Tests:** `T-cadence-analysis` ([source](../tests/test_cadence_analysis.py)),
  `T-alignment-analysis` ([source](../tests/test_alignment_analysis.py)), and
  `T-depth-thinning-analysis` ([source](../tests/test_depth_thinning_analysis.py)).
- **Evaluation / outputs:** Counts, rates, gap/age quantiles, flip/coalescing and agreement summaries;
  retained [DAT-15](../docs/live-evidence/DAT-15-2026-08-19.md),
  [DAT-17](../docs/live-evidence/DAT-17-2026-08-19.md), and
  [DAT-20](../docs/live-evidence/DAT-20-2026-08-19.md) documents.
- **Status:** implementation `implemented`; evidence `result located but not validated`.
- **Limits / unresolved:** Retained runs were not replayed here; provider/version/session stability
  and native packet completeness remain unknown.

## `H-data-quality-002` — Depth occupancy and normal-activity boundary

- **Family / basis:** `HF-data-quality`; Verified from code; declining activity with distance is an
  inference motivated by `depth_thinning_analysis.py:895` and the existing normal-activity report.
- **Question and rationale:** Can ordinary deep-book mechanics be distinguished from unseen states
  and candidate anomalies? A rank-window slide must not become a false event.
- **Null / alternative / direction:** H0: activity and unseen-state rates do not vary meaningfully
  by distance/gaps. H1: distance, occupancy, containment, and matched skip windows expose structure.
  Inferred expected direction: activity declines with distance; no universal threshold is inferred.
- **Scope and observation:** Depth20/depth200/Full book states and transitions, by side/distance,
  within receive-time epoch. Raw ranked prices, quantities, order counts, best quote, padding, and
  quality flags are required.
- **Features:** `F-depth-occupancy-contiguity`, `F-depth-distance-activity`,
  `F-depth-channel-agreement`, `F-deep-book-edge-distance`.
- **Method, filters, leakage:** Measure populated levels/tick span/missing ticks, containment,
  distance exposure, skip-window unseen states, and duration-matched controls. Use pre-state
  references; exclude stale/invalid/boundary-slide transitions.
- **Tests:** `T-depth-thinning-analysis` ([source](../tests/test_depth_thinning_analysis.py)),
  `T-deepbook-normal-activity` ([source](../tests/test_deepbook_normal_activity.py)), and
  `T-deep-book-anomaly` ([source](../tests/test_deep_book_anomaly.py)).
- **Evaluation / outputs:** Rates, quantiles, Spearman/two-proportion diagnostics; retained
  [normal-activity](../docs/DEEPBOOK-NORMAL-ACTIVITY-2026-08-19.md) and
  [construction evidence](../docs/live-evidence/SIG-21-CONSTRUCTION-2026-08-19.md).
- **Status:** implementation `implemented`; evidence `result located but not validated`.
- **Limits / unresolved:** Short samples cannot define stable full-session “normal”; researcher must
  approve distance bands and evidence needed to label anomalous activity.

## `H-reference-price-001` — Alternative causal reference-price ladder

- **Family / basis:** `HF-reference-price`; Verified from code and existing documentation.
- **Question and rationale:** Do displayed mid, last trade, effective-touch proxy, and microprice
  provide distinct causal state/reference definitions? Measurement choice can change coverage and
  apparent predictiveness.
- **Null / alternative / direction:** H0: alternatives add no distinct state or held-out comparison.
  H1: at least one changes coverage/state/comparison. Microprice mechanically tilts toward the
  thinner side; predictive sign is not prespecified.
- **Scope and observation:** NIFTY futures BBO/depth20 plus aggregate standard-feed prints, per
  receive-time anchor/epoch. Inputs are BBO prices/queues, cumulative-volume increments,
  classifier/alignment versions, and print locations.
- **Features:** `F-displayed-mid`, `F-simple-microprice`, `F-microprice-tilt-ticks`,
  `F-queue-imbalance`, `F-effective-touch-mid`, `F-touch-relative-queue-imbalance`.
- **Method, filters, leakage:** Build four paths side-by-side using causal as-of matching; reject
  invalid BBO/coalesced/degraded/unversioned prints; never replace undefined effective touch with
  displayed mid; report coverage/staleness; re-key depth into outward fixed tick bands.
- **Tests:** `T-microprice` ([source](../tests/test_microprice.py)), `T-effective-touch`
  ([source](../tests/test_effective_touch.py)), `T-reference-prices`
  ([source](../tests/test_reference_prices.py)), and `T-d38-acceptance`
  ([source](../tests/test_d38_acceptance.py)).
- **Evaluation / outputs:** Coverage, staleness, path values, state/held-out comparison; D51
  [summary](../docs/results/D51-EXPLORATORY-SUMMARY-2026-08-21.json).
- **Status:** implementation `implemented`; evidence `result located but not validated`.
- **Limits / unresolved:** Effective touch is a stale print-derived proxy; undisplayed liquidity,
  order identity, and queue position are unavailable. Primary reference remains a researcher choice.

## `H-order-flow-001` — Causal L1 and multi-level OFI construction

- **Family / basis:** `HF-order-flow`; Verified from code.
- **Question and rationale:** Do CKS L1 and CCZ rank-keyed estimators encode signed displayed
  pressure without look-ahead? Formula correctness is prerequisite to prediction claims.
- **Null / alternative / direction:** H0: signs/windows disagree with declared formulas or include
  future states. H1: hand calculations, window sums, availability, and training-only weights agree.
  Positive means bid strengthening or ask depletion.
- **Scope and observation:** Consecutive valid NIFTY futures depth states within one connection
  epoch; transition and `(t-w,t]` window units. Raw ranked bid/ask prices/quantities are required.
- **Features:** `F-cks-l1-ofi`, `F-cks-l1-depth-normalized-pressure`, `F-ccz-level-ofi`,
  `F-ccz-integrated-ofi`.
- **Method, filters, leakage:** Apply exact branch formulas, reject invalid/cross-epoch spans,
  require complete windows, use one common CCZ depth denominator, and fit optional PC weights on
  training rows only. Unsupported level counts are refused.
- **Tests:** `T-cks-l1-ofi` ([source](../tests/test_cks_l1_ofi.py)), `T-ccz-ofi`
  ([source](../tests/test_ccz_ofi.py)), `T-deep-book-ofi`
  ([source](../tests/test_deep_book_ofi.py); superseded), and `T-ofi-replication`
  ([source](../tests/test_ofi_replication.py)).
- **Evaluation / outputs:** Hand equality, sign, coverage, deterministic artifact and metadata;
  [horse-race summary](../docs/results/OFI-HORSERACE-SUMMARY-2026-08-19.json).
- **Status:** implementation `implemented`; evidence `result located but not validated`.
- **Limits / unresolved:** Aggregate/rank-keyed OFI is not order identity/MBO; rank shifts can differ
  from price-keyed events. Denominator/level/window choices require researcher approval.

## `H-order-flow-002` — OFI incremental future-mid predictiveness

- **Family / basis:** `HF-order-flow`; Verified from code and existing documentation.
- **Question and rationale:** Does causal OFI improve held-out future displayed-mid forecasts beyond
  state, trade, microprice, and lagged-return controls?
- **Null / alternative / direction:** H0: adding OFI does not improve held-out error/R2. H1: at
  least one preregistered family improves performance with cross-tape/dependence support. Positive
  OFI is expected to associate with positive future mid return; tests remain two-sided.
- **Scope and observation:** NIFTY front future, NSE, retained intraday sessions; anchor/horizon
  observations across 0.5–30s and declared windows. Inputs are depth states, optional qualified
  volume increments, reference-price states, and matured future-mid endpoints.
- **Features:** `F-ccz-integrated-ofi`, `F-cks-l1-depth-normalized-pressure`,
  `F-future-mid-return`, `F-mid-return-lag`, `F-simple-microprice`.
- **Method, filters, leakage:** Fixed comparable panels, chronological split/embargo, training-only
  transforms/alpha, past-mirror controls, companion metrics, per-tape signs, HAC/bootstrap and
  multiplicity. Missing/invalid target/support cells remain explicit.
- **Tests:** `T-ofi-horserace` ([source](../tests/test_ofi_horserace.py)), `T-d38-acceptance`
  ([source](../tests/test_d38_acceptance.py)), `T-fixed-target-panel`
  ([source](../tests/test_fixed_target_panel.py)), `T-mid-lag-ofi`
  ([source](../tests/test_mid_lag_ofi.py)), `T-ofi-replication`
  ([source](../tests/test_ofi_replication.py)), `T-live-ofi-studies`
  ([source](../tests/test_live_ofi_studies.py)), and `T-ofi-live-partial`
  ([source](../tests/test_ofi_live_partial.py)).
- **Evaluation / outputs:** OOS R2/error, companion metrics, corrected p-values, tape signs;
  [horse race](../docs/results/OFI-HORSERACE-SUMMARY-2026-08-19.json) and
  [D41](../docs/results/D41-MID-LAG-OFI-INCREMENTAL-2026-08-20.json).
- **Status:** implementation `implemented`; evidence `mixed`.
- **Limits / unresolved:** Existing leads are exploratory, not cross-session promotion evidence;
  incomplete/partial sessions must remain labelled. Economic value after costs/fills is unknown.

## `H-order-flow-003` — OFI horizon and state dependence

- **Family / basis:** `HF-order-flow`; Verified from code and existing documentation.
- **Question and rationale:** Does forecast strength vary smoothly across windows, horizons,
  nonlinear geometry, regimes, and rolling calibration rather than appear as isolated spikes?
- **Null / alternative / direction:** H0: performance is flat/noise. H1: reproducible horizon or
  state structure exists. No global direction; D40 explicitly measures rise, peak, and decline.
- **Scope and observation:** NIFTY futures receive-time anchors, 0.5–120s outcomes depending on
  experiment, within-session rolling or chronological splits. Inputs are causal OFI observations,
  state geometry, and matured targets.
- **Features:** `F-ofi-response-surface`, `F-nonlinear-ofi-geometry`, `F-future-mid-return`,
  `F-time-regime`.
- **Method, filters, leakage:** Frozen grids, chronological validation, pending-label discipline,
  no fresh-tracker backfill, neighbor smoothness, nonlinear falsifiers/gates/Kalman, and explicit
  correction of corrupted tensor artifacts.
- **Tests:** `T-d40-ofi-horizon-extension`
  ([source](../tests/test_d40_ofi_horizon_extension.py)), `T-nonlinear-ofi-state`
  ([source](../tests/test_nonlinear_ofi_state.py)), `T-ofi-response-surface`
  ([source](../tests/test_ofi_response_surface.py)), `T-rolling-c8`
  ([source](../tests/test_rolling_c8.py)), and `T-ofi-dashboard`
  ([source](../tests/test_ofi_dashboard.py)).
- **Evaluation / outputs:** Horizon OOS R2 curves, 210-cell smoothness, gate AUC/Brier, model metrics;
  [D40](../docs/results/D40-OFI-HORIZON-EXTENSION-2026-08-20.json),
  [D49](../docs/results/D49-C8-RESPONSE-SURFACE-2026-08-21.md), and
  [D50](../docs/results/D50-NONLINEAR-OFI-GATE-KALMAN-2026-08-21.json).
- **Status:** implementation `implemented`; evidence `mixed`.
- **Limits / unresolved:** Same-day/short late-session evidence, heavy horizon overlap, no costs or
  multi-day stability. Researcher must define replication and effect thresholds.

## `H-deep-book-001` — Price-keyed deep-book event construction

- **Family / basis:** `HF-deep-book`; Verified from code and existing documentation.
- **Question and rationale:** Can price-keyed additions/removals/changes/relocation proxies be
  detected without rank-cascade or outer-boundary artifacts?
- **Null / alternative / direction:** H0: detector cannot distinguish events from window mechanics.
  H1: registered fixtures and retained construction produce reconciled event/exclusion counts. No
  response direction; magnitudes are nonnegative.
- **Scope and observation:** NIFTY front future depth200, NSE, receive-time burst/transition,
  construction-only retained DAT-20 tapes and synthetic cases. Inputs are displayed price,
  quantity, order count, side, same-side best, epoch, and quality flags.
- **Features:** `F-deep-book-atomic-event`, `F-deep-book-edge-distance`,
  `F-depth-distance-activity`.
- **Method, filters, leakage:** Compare price-key maps; pair relocation proxies at <=25% quantity
  mismatch; use pre-event >Rs20 boundary; collapse exact timestamps; exclude reconnect/invalid and
  boundary churn; construction schema forbids response fields.
- **Tests:** `T-deep-book-anomaly` ([source](../tests/test_deep_book_anomaly.py)),
  `T-deep-book-inference` ([source](../tests/test_deep_book_inference.py)),
  `T-sig21-construction-replay` ([source](../tests/test_sig21_construction_replay.py)), and
  `T-deepbook-normal-activity` ([source](../tests/test_deepbook_normal_activity.py)).
- **Evaluation / outputs:** Candidate/exclusion reconciliation, construction grid, source hashes;
  [construction evidence](../docs/live-evidence/SIG-21-CONSTRUCTION-2026-08-19.md).
- **Status:** implementation `implemented`; evidence `supports hypothesis` (construction only).
- **Limits / unresolved:** Candidates are not proven anomalies; relocation is proxy-only; no order
  identity. Construction support must not be stated as predictive support.

## `H-deep-book-002` — Deep-book event response association

- **Family / basis:** `HF-deep-book`; Verified from existing registration/code.
- **Question and rationale:** Do registered far-book events precede depth20 midpoint responses after
  causal gaps and matched controls?
- **Null / alternative / direction:** H0: event responses do not differ from controls after family
  adjustment. H1: at least one adequately powered registered cell differs and passes robustness.
  Two-sided; a discovered direction requires later confirmation.
- **Scope and observation:** NIFTY front future, NSE, full post-registration sessions; event episode
  by 8 types x 2 sides x 2 bands x 2 thresholds x 2 gaps x 3 horizons (384 cells). Inputs include
  depth200 events, depth20 midpoint, pre-event state/regime, and quiet risk-set instants.
- **Features:** `F-deep-book-atomic-event`, `F-deep-book-response`,
  `F-deep-book-edge-distance`, `F-time-regime`.
- **Method, filters, leakage:** Prior-session baselines, full right-edge/same-epoch coverage,
  cell-specific nonoverlap, outcome-blind matching, full-family HAC/bootstrap/adjustment, negative
  controls, numeric MDE gate. Preregistration tapes cannot become confirmatory.
- **Tests:** `T-deep-book-response` ([source](../tests/test_deep_book_response.py)),
  `T-sig21-exploratory-response` ([source](../tests/test_sig21_exploratory_response.py)), and
  `T-sig21-construction-replay` ([source](../tests/test_sig21_construction_replay.py)).
- **Evaluation / outputs:** Raw/control differences, N/N_eff, intervals, adjusted p-values, MDE and
  controls. Expected output is not generated; see [registration](../docs/sig-claims/H-SIG21.md).
- **Status:** implementation `partially_implemented`; evidence `no result located`.
- **Limits / unresolved:** Five calibration plus twenty evaluation sessions and pushed pre-outcome
  power artifact were not located as complete. Outcome execution is a researcher-governed gate.

## `H-options-surface-001` — Causal arbitrage-diagnosed eSSVI surface

- **Family / basis:** `HF-options-surface`; Verified from code and existing documentation.
- **Question and rationale:** Can option chains produce causal eSSVI frames with forward, support,
  staleness, smoothing, and arbitrage diagnostics?
- **Null / alternative / direction:** H0: construction cannot satisfy readiness/causal/arbitrage
  contracts. H1: supported slices fit; unsupported cells remain null; invalid uses fail. No alpha
  sign; arbitrage violations are adverse diagnostics.
- **Scope and observation:** NSE NIFTY options across expiry/strike at surface fit decisions;
  date-versioned session/expiry close. Inputs are option BBO, strike/expiry, traded future or parity
  forward, maturity, and receive times.
- **Features:** `F-surface-essvi-parameters`, `F-surface-atm-shape`, `F-surface-quality`.
- **Method, filters, leakage:** Latest causal rows only; forward hierarchy labelled; IV inversion,
  constrained eSSVI fit, butterfly/calendar checks, support/age/staleness, optional temporal
  smoother. Failed/unsupported fits remain visible; raw quoting use is refused.
- **Tests:** `T-essvi-surface` ([source](../tests/test_essvi_surface.py)),
  `T-surface-interface` ([source](../tests/test_surface_interface.py)),
  `T-surface-arbitrage` ([source](../tests/test_surface_arbitrage.py)),
  `T-anl03-dashboard` ([source](../tests/test_anl03_dashboard.py)), and
  `T-remaining-contracts` ([source](../tests/test_remaining_contracts.py)).
- **Evaluation / outputs:** Fit/readiness/support/arbitrage/frame-age diagnostics and read-only
  dashboard; [ANL-03](../docs/live-evidence/ANL-03-2026-08-19.md) and
  [ANL-07 amendment](../docs/live-evidence/ANL-07-AMENDMENT-5-2026-08-21.md).
- **Status:** implementation `implemented`; evidence `result located but not validated`.
- **Limits / unresolved:** Unit fits do not establish live source completeness or cross-session
  calibration. Researchers choose forward hierarchy/support/staleness thresholds.

## `H-options-surface-002` — Read-only IV-residual convergence episodes

- **Family / basis:** `HF-options-surface`; Verified from code.
- **Question and rationale:** Do large smoothed IV residual dislocations converge without being
  explained by reference-market movement?
- **Null / alternative / direction:** H0: qualified gaps do not converge under gates. H1: qualified
  episodes show target-led convergence. Cheap (negative residual) options are expected to rise
  relative to fair; rich options fall.
- **Scope and observation:** NIFTY option instrument/fit episodes during NSE session; causal quote
  and surface frames. Inputs are option quote, strike/maturity, forward, fitted IV, past residual
  uncertainty, and reference-market path.
- **Features:** `F-surface-iv-residual`, `F-surface-quality`, `F-effective-touch-mid`.
- **Method, filters, leakage:** Black-76 inversion; six-fit default smoother warm-up; current
  residual excluded from its uncertainty training; lot-size/agreement/reference-jump gates;
  missing/closed quotes censor rather than “correct” episodes; no order/execution dependencies.
- **Tests:** `T-surface-mispricing` ([source](../tests/test_surface_mispricing.py)) and
  `T-anl03-dashboard` ([source](../tests/test_anl03_dashboard.py)).
- **Evaluation / outputs:** Residual magnitude/uncertainty, episode lifecycle, target/reference
  movement; no persisted empirical episode output located.
- **Status:** implementation `implemented`; evidence `no result located`.
- **Limits / unresolved:** Synthetic scenarios validate behavior, not frequency/economics.
  Researchers must set episode benchmark, economic threshold, horizon, and replication requirement.

## `H-surface-alpha-001` — Surface state incremental futures predictiveness

- **Family / basis:** `HF-surface-alpha`; Verified from code and existing documentation.
- **Question and rationale:** Does causal option-surface state improve five-second NIFTY-futures
  forecasting beyond LOB plus OFI?
- **Null / alternative / direction:** H0: no incremental held-out performance. H1: levels, changes,
  terms, or innovations add positive held-out performance. No global coefficient sign; lag placebo
  should not improve performance.
- **Scope and observation:** Fixed NIFTY future and three expiries in the registered 2026-08-19
  exploratory scan; Full-book/surface receive-time anchors; 0.5s gap and 5s response. Inputs are
  causal surface frames, Full book, CCZ OFI, and future mid.
- **Features:** `F-surface-essvi-parameters`, `F-surface-atm-shape`, `F-surface-innovation`,
  `F-surface-quality`, `F-ccz-integrated-ofi`, `F-future-mid-return`.
- **Method, filters, leakage:** Same-epoch causal as-of surface with max age/right-edge, 70/30
  chronology, 120s embargo, training-only vocabulary/preprocessing/alpha, identical test rows,
  freshness filters, 300s lag placebo, paired inference, and collinearity diagnostics.
- **Tests:** `T-surface-futures-predictive`
  ([source](../tests/test_surface_futures_predictive.py)) and
  `T-surface-ofi-reconciliation` ([source](../tests/test_surface_ofi_reconciliation.py)).
- **Evaluation / outputs:** Model OOS R2, paired errors, correlations, coefficients, freshness,
  placebo, coverage/hashes; [summary](../docs/results/SURFACE-FUTURES-PREDICTIVE-SUMMARY-2026-08-19.json)
  and [models](../docs/results/SURFACE-FUTURES-PREDICTIVE-MODELS-2026-08-19.md).
- **Status:** implementation `implemented`; evidence `rejects hypothesis` for this tested design.
- **Limits / unresolved:** Exploratory source-specific result, high collinearity, fixed expiries,
  displayed-mid target, no costs/fills. Universal rejection is not justified.

## `H-feature-selection-001` — Quality-gated stable feature usefulness

- **Family / basis:** `HF-feature-selection`; Verified from code and existing documentation.
- **Question and rationale:** Do registered features survive causal quality, redundancy,
  conditional-usefulness, and multi-session stability gates while improving OOS forecasts?
- **Null / alternative / direction:** H0: no cluster has stable positive conditional usefulness.
  H1: at least one complete cluster/model identity clears all gates. Positive delta OOS R2 is
  favorable; promotion requires mirror/economic/stability guards.
- **Scope and observation:** NIFTY futures/surface causal rows targeting ten-second future-mid,
  fixed one-second engineering grid in D51; fold/cluster/model units. Inputs are 220 registered
  feature candidates, surface/futures state, targets, fold/regime identities.
- **Features:** `F-feature-correlation-cluster`, `F-feature-conditional-oos-delta`,
  `F-source-keyed-ar1-control`, `F-time-regime`, `F-surface-innovation`,
  `F-ccz-integrated-ofi`.
- **Method, filters, leakage:** Training-only quality gates/correlation clusters/PC/model selection;
  outer apply-only tests; elastic net/tree/baselines; cluster/family ablation and block permutation;
  stability by complete identity, sessions/folds/regimes, mirror/economic guards.
- **Tests:** `T-feature-selection` ([source](../tests/test_feature_selection.py)),
  `T-feature-correlation-reduction` ([source](../tests/test_feature_correlation_reduction.py)),
  `T-feature-conditional-usefulness` ([source](../tests/test_feature_conditional_usefulness.py)),
  `T-feature-predictive-models` ([source](../tests/test_feature_predictive_models.py)),
  `T-feature-stability-selection` ([source](../tests/test_feature_stability_selection.py)),
  `T-feature-selection-walkforward` ([source](../tests/test_feature_selection_walkforward.py)),
  `T-feature-selection-experiment-cli` ([source](../tests/test_feature_selection_experiment_cli.py)),
  `T-compute-feature-correlations` ([source](../tests/test_compute_feature_correlations.py)),
  `T-validated-ridge-analysis` ([source](../tests/test_validated_ridge_analysis.py)), and
  `T-evaluation-metrics` ([source](../tests/test_evaluation_metrics.py)).
- **Evaluation / outputs:** Gates/clusters/model metrics/ablations/stability/regimes; [D51 report](../docs/results/D51-EXPLORATORY-RESULT-2026-08-21.md),
  [summary](../docs/results/D51-EXPLORATORY-SUMMARY-2026-08-21.json), and referenced CSVs in
  `feature_data/manifest.csv`.
- **Status:** implementation `implemented`; evidence `inconclusive`.
- **Limits / unresolved:** One session; surface economic fields mostly failed coverage; every
  stability row insufficient; mirror/economic guards unavailable. No promoted feature exists.

## `H-feature-selection-002` — Futures microstructure increment for option markouts

- **Family / basis:** `HF-feature-selection`; Verified from code and existing documentation.
- **Question and rationale:** Does aggregate futures microstructure add information to option-state
  controls for five/30-second option-mid markouts?
- **Null / alternative / direction:** H0: augmented models do not improve held-out squared error.
  H1: futures features yield positive distinguishable delta OOS R2. Signed direction is not
  prespecified; absolute movement proxies are nonnegative.
- **Scope and observation:** One completed 2026-08-26 NIFTY futures/options NSE standard-feed
  session; option instrument x five-second grid anchor; horizons 5/30s. Inputs are option/futures
  BBO/five-level depth, cumulative-volume increments, receive/epoch/quality state.
- **Features:** `F-futures-trade-intensity-10s`, `F-realized-volatility-30s`,
  `F-option-markout-half-spread`, `F-option-adverse-proxy`, `F-simple-microprice`,
  `F-queue-imbalance`.
- **Method, filters, leakage:** Completed-source gate/full replay; quality intervals and 30s primary
  buffers; same-epoch exact grid; 60/20/20 chronological split with 30s embargo; development-only
  clipping/scaling/alpha; HAC and block reweighting; stricter buffer/tail checks.
- **Tests:** `T-post-close-alpha-research`
  ([source](../tests/test_post_close_alpha_research.py)).
- **Evaluation / outputs:** Baseline/augmented OOS R2 and MAE deltas with intervals;
  [post-close memo](../docs/results/POST-CLOSE-ALPHA-2026-08-26.md).
- **Status:** implementation `implemented`; evidence `mixed`.
- **Limits / unresolved:** 30s signed incremental R2 is small/distinguishable but augmented absolute
  R2 is negative; no 5s or absolute-proxy support. One session, aggregate feed, no fills/costs/
  capacity, and source packet sequence unavailable require preregistered replication.

## `H-infrastructure-001` — Versioned research contracts and runnable boundaries

- **Family / basis:** `HF-infrastructure`; Verified from code.
- **Question and rationale:** Do packaging, CLI, schemas, dashboards, and fixtures preserve
  versioned read-only research interfaces?
- **Null / alternative / direction:** H0: incompatible schemas or forbidden package/write
  boundaries are accepted. H1: supported contracts round-trip and invalid versions/imports/writes
  fail. No economic direction.
- **Scope and observation:** Repository/package/contract request units, not market observations.
  Inputs are `pyproject.toml`, JSON fixtures, timestamps/session dates, contract objects, CLI args,
  AST imports, and HTTP methods.
- **Features:** `F-source-completion-state`, `F-feature-availability-time` (contract fields only).
- **Method, filters, leakage:** Golden exact round-trip and unsupported-version rejection; causal
  timestamp/session validation; public Data facade/import scan; distribution/dependency match;
  deterministic CLI inspection; dashboard refuses mutation methods.
- **Tests:** `T-conftest` ([source](../tests/conftest.py)), fixture
  [finding](../tests/fixtures/contracts/finding_v1.json) and
  [surface](../tests/fixtures/contracts/surface_v1.json), `T-release-metadata`
  ([source](../tests/test_release_metadata.py)), `T-remaining-contracts`
  ([source](../tests/test_remaining_contracts.py)), `T-architecture-boundary`
  ([source](../tests/test_architecture_boundary.py)), `T-anl03-dashboard`
  ([source](../tests/test_anl03_dashboard.py)), and `T-research-research-cli`
  ([source](../tests/test_research_cli.py)).
- **Evaluation / outputs:** Boolean round-trip/refusal/import/package assertions; no durable empirical
  result.
- **Status:** implementation `implemented`; evidence `unable to determine`.
- **Limits / unresolved:** Tested versions do not guarantee future provider/deployment compatibility.
  Schema/public-boundary/session-calendar changes require explicit owner decisions.

## High-frequency construction freeze (`HF-high-frequency`)

The entries below are implemented measurement contracts with `result located but not validated`
evidence status. The cited three sessions freeze shadow candidates, not broad regime validity,
executable profitability, or live promotion. Exact formulas and missingness rules are in
[high-frequency constructions](methodology/high-frequency-constructions.md).

## `H-high-frequency-001` — Parity pressure convergence

- **Question:** Does `parity.pressure.v1` predict sign-aligned displayed-futures midpoint movement
  over ten seconds, with high-volatility/tight-spread and parity/L1 agreement as confidence states?
- **Null / alternative:** No stable held-out association versus a positive sign-aligned
  association after declared controls and costs.
- **Implementation / evidence:** `implemented`; `result located but not validated`.
- **Limits:** Three-session mechanism evidence; fresh v2 walk-forward and shadow scoring required.

## `H-high-frequency-002` — Futures L1 quantity pressure

- **Question:** Does current L1 displayed-quantity imbalance predict the next one-second midpoint
  move, especially in low relative volatility and medium relative depth?
- **Null / alternative:** No stable held-out association versus a positive sign-aligned
  association. Microprice tilt is a redundant representation, not a second unconstrained head.
- **Implementation / evidence:** `implemented`; `result located but not validated`.

## `H-high-frequency-003` — Persistent order-count imbalance

- **Question:** Does current five-level resting order-count imbalance predict the next ten-second
  midpoint move conditionally when signal strength is high and the IST bucket is midday?
- **Null / alternative:** No stable held-out conditional association versus positive sign
  alignment. This is book state across depth, never cumulative flow through time.
- **Implementation / evidence:** `implemented`; `result located but not validated`.

## `H-high-frequency-004` — Five-second midpoint reversal

- **Question:** Does negative prior five-second midpoint movement predict the next five-second move
  when prior-move strength is high and parity dispersion is medium?
- **Null / alternative:** No stable negative autocorrelation versus sign-aligned reversal.
- **Implementation / evidence:** `implemented`; `result located but not validated`.

## `H-high-frequency-005` — Leave-ATM surface convergence

- **Question:** Does the v2 CE-minus-PE leave-ATM residual difference predict actual-futures-hedged
  option convergence under the large/noisy-parity confidence state?
- **Null / alternative:** No stable costed hedged convergence versus convergence in the residual
  direction. `change(F_exatm)` is prohibited as the hedge leg.
- **Implementation / evidence:** `implemented`; `result located but not validated`.
- **Limits:** V2 intentionally has no inherited legacy `surface_centered` statistics.

## `H-high-frequency-006` — ATM-IV shock reversal

- **Question:** Does the five-second ATM-IV shock mean-revert over ten seconds when trailing IV
  vol-of-vol is in its causal medium tertile?
- **Null / alternative:** No stable negative association versus shock reversal.
- **Implementation / evidence:** `implemented`; `result located but not validated`.

## `H-high-frequency-007` — Liquidity and future range

- **Question:** Do displayed L1 depth and short midpoint volatility explain future ten-second
  displayed-futures range after current spread control?
- **Null / alternative:** No stable held-out magnitude information versus positive incremental
  range information; no directional sign is asserted.
- **Implementation / evidence:** `implemented`; `result located but not validated`.

## `H-high-frequency-008` — Fast OFI transportability diagnostic

- **Question:** Does exact half-second M1 CCZ average OFI regain one-second directional
  transportability under low-volatility/trending state on additional untouched sessions?
- **Null / alternative:** No transportable held-out association versus positive sign alignment.
- **Implementation / evidence:** `implemented`; `result located but not validated`.
- **Limits:** Diagnostic/quarantined; current policy assigns no automatic live weight.
