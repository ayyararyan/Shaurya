# Frozen-spec coverage — displayed eSSVI to five-second futures move

**Scan:** `X-SURFACE-FUT5-20260819-06`  
**Frozen design:** `docs/SURFACE-FUTURES-PREDICTIVE-SPEC-2026-08-19.md`  
**Evidence class:** permanently exploratory; `confirmatory_eligible=false`

This is the pre-execution static audit. It maps every frozen requirement to implementation, a
test or acceptance check, and its expected machine evidence before the full tape is allowed to run.
The final pass will replace the pending outcome/validation statuses with exact artifacts, hashes and
counts. A mapped completion-stage gate is not a silent omission.

## DATA

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| DATA-01 immutable tape | `scripts.surface_futures_predictive.replay_tape`: resolved-path refusal plus exact bytes, rows and streaming SHA-256 | durable controller; full replay is the only empirical acceptance | `summary.source`; manifest source hash and exact CLI | Ready; empirical acceptance pending |
| DATA-02 five-level Quote/Full boundary | `future_state`; `FutureBookSeries.usable`; no depth20/depth200 reader | `test_scan_identity_and_target_instrument_are_frozen`; five-level LOB tests | `summary.source.book_channel`; `feature_counts.lob_five_level` | Implemented |
| DATA-03 displayed surface parity | unchanged `SurfaceEngine` in `replay_tape`, exact expiries and 5 s cadence | cadence/identity test; replay metadata acceptance | `summary.replay.fit_engine`, fit counts and smoothing statuses | Ready; empirical acceptance pending |
| DATA-04 observation availability | `frame_draft`, `surface_economic_features`, `build_predictive_observations`; all predictors end at or before `t` | surface velocity and exact joined-geometry tests | observations JSONL; replay draft/join counts | Implemented |
| DATA-05 guarded future response | `FutureBookSeries.as_of`, `move`, `as_of_failure_reason`, `move_failure_reason`; exact 6 s/epoch/right-edge guards | `test_target_asof_enforces_age_epoch_and_right_edge_without_lookahead` | `summary.timing`, target-age quantiles, reason-separated join failures including epoch failures | Implemented |
| DATA-06 past/same controls | exact target construction in `build_predictive_observations` | `test_exact_future_past_and_same_geometry_from_one_surface_anchor` | three model-score source families; timing formulas | Implemented |
| DATA-07 exclusions | economic block is built only from emitted eSSVI parameter/shape values; no forward level; snapshot OFI is labelled displayed flow | `test_surface_features_include_levels_velocities_and_adjacent_terms` asserts no forward field | feature names and plain-English identification boundary | Implemented |

## SURFACE

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| SURFACE-A eSSVI equation, ATM support | `_parameter_levels`, `essvi_implied_volatility`; every expiry must contain `k=0` | analytic/finite-difference test and surface feature test | observation economic columns; feature count | Implemented |
| SURFACE-B ATM IV/skew/curvature | `essvi_atm_shape` uses the frozen analytic formula | `test_analytic_atm_skew_and_curvature_match_central_finite_difference` | per-expiry level columns and correlations | Implemented |
| SURFACE-C per-expiry levels/deltas/velocities | `surface_economic_features`, matched by absolute expiry date and actual elapsed seconds | `test_surface_features_include_levels_velocities_and_adjacent_terms` | observation economic columns; coefficients/correlations | Implemented |
| SURFACE-D adjacent term differences | `_parameter_levels` plus the same delta/velocity expansion | same surface feature test | two later-minus-earlier term families | Implemented |
| SURFACE-E quality isolation and fixed missingness | `QUALITY_NUMERIC_NAMES`, `QUALITY_CATEGORICAL_NAMES`, `surface_quality_features`, `FeaturePreprocessor` | training-only vocabulary/isolation and deterministic-artifact tests | SQ/LOSQ rows, missing indicators, smoothing counts and freshness rows | Implemented; live fit duration is explicitly unavailable in tape and fixed missing; replay CPU time excluded |

## LOB

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| LOB-A spread and microprice tilt | `lob_features` | five-level formula test | L/LO/LOS designs and observations | Implemented |
| LOB-B level/cumulative quantity imbalance | `lob_features` levels 1–5 and cumulative 1/5 | five-level formula test | observation LOB block | Implemented |
| LOB-C displayed totals/log totals | `lob_features` | deterministic artifact and formula path | observation LOB block | Implemented |
| LOB-D order-count imbalances | `lob_features` | five-level and missing-denominator tests | observation LOB block | Implemented |
| LOB-E average-order-size proxies | `lob_features`; names retain `proxy` | five-level proxy-semantics test | observation LOB block and report boundary | Implemented |
| LOB-F quadratic shape/asymmetry | `_quadratic_shape`, `lob_features`; singular fit is missing | five-level formula and missing-denominator tests | bid/ask slope/curvature and asymmetry columns | Implemented |

## OFI

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| OFI-01 canonical CKS L1 | `_canonical_full_adapter` calls existing `cks_l1_transition`; five levels are unchanged | `test_ofi_reuses_canonical_sign_and_price_keyed_marginal_bands` | 5 s raw/depth-adjusted CKS columns | Implemented |
| OFI-02 price-keyed marginal bands | existing `price_keyed_ofi_transition`, including canonical outer-window boundary rule | same OFI regression plus canonical module tests in full suite | 5 s L1 and L2–5 columns | Implemented |
| OFI-03 causal depth adjustment | `build_ofi_prefix`, `trailing_ofi_features`; one-contract floor and complete five-level states | OFI sign/band test; missing LOB/depth guards | raw and adjusted columns | Implemented |
| OFI-04 optional robustness windows | `trailing_ofi_features(windows=...)`; primary join requires only 5 s, optional 0.5/1/2/10 s windows never remove rows | all-window OFI assertion; `test_optional_ten_second_ofi_window_does_not_collapse_primary_sample` | `sample.ofi_window_support`; optional observation columns and attrition counters | Implemented after static-audit correction |

## EST

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| EST-A identical common sample and N/S/SQ/L/O/LO/LOS/LOSQ | `build_predictive_observations`, `model_raw_names`, `fit_model_family` | exact join, quality isolation and deterministic family assertions | 24 primary score rows: 8 models × future/past/same | Implemented |
| EST-B train-only transformations and Ridge selection | `FeaturePreprocessor`, `_inner_folds`, `select_alpha`, canonical Ridge fit/path | unseen-category test and outside-training-target invariance test | alpha, feature counts, training centre/scale in coefficient output | Implemented |
| EST-C 70/30 clock split, 120 s embargo, held-out halves | `chronological_split`, `fit_model` | `test_chronological_split_has_120_second_embargo` | sample clocks/counts and per-model held-out halves | Implemented |
| EST-D declared paired comparisons | `paired_error_inference`; exact pairs S→L/O/LO, LO→LOS, S→SQ, LOS→LOSQ for all targets | deterministic artifact asserts exact 18 records | paired-inference CSV and summary | Implemented after static-audit correction |

## CORR

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| CORR-01 all surface features, targets, scopes and two methods; coefficients/contributions | `correlation_rows`, `coefficient_diagnostics`, `coefficient_rows` | deterministic artifact family/field assertions; full-suite execution | correlation and coefficient CSVs | Implemented |
| CORR-02 HAC lag 2 and BH-FDR | `_correlation_with_hac`, `_bh_adjust`; adjustment is within each declared target/scope/method surface-feature family | deterministic artifact assertions; empirical row-count acceptance | HAC t/p and BH q columns | Implemented |

## ROB

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| ROB-01 three paired dependence checks | `paired_error_inference`: NW lag 2, stationary bootstrap block 6, non-overlap 10 s | deterministic replay test | paired-inference CSV | Implemented |
| ROB-02 full past mirror and same-window diagnostic | common three-source model loop | exact geometry and family assertion tests | model/correlation/inference rows by source | Implemented |
| ROB-03 300 s no-wrap placebo | `lagged_surface_source_positions`, `lagged_surface_placebo` | `test_lag_placebo_uses_same_epoch_past_without_wrap` | lag-placebo CSV and paired inference in summary | Implemented after static-audit test expansion |
| ROB-04 480/240 s freshness | `_filtered_positions`, `freshness_rows`; original split positions retained; minimum support explicit | `test_freshness_filter_preserves_primary_split_positions` | freshness CSV and fitted-arm list/status | Implemented |
| ROB-05 fit/smoothing/age/attrition/collinearity/epoch diagnostics | replay counters, reason-separated joins, `_quantiles`, `surface_collinearity_summary` | stale/epoch guards and deterministic collinearity assertions | replay/sample diagnostics; full/training/held-out top-25 collinear pairs, ranks and threshold counts | Implemented after static-audit correction |

## Comparison boundary

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| Same-tape comparison primary; DAT-20 context non-apples-to-apples | same observation rows for all model families; report-only comparison to the two named OFI reports | report review | explicit five-level-versus-depth20/depth200 boundary | Report text pending outcome; no implementation gap |

## OUT / VAL

| Requirement | Implementation | Test / acceptance | Expected evidence | Pre-run status |
|---|---|---|---|---|
| OUT-01 full deterministic machine bundle | atomic `write_artifacts` writes summary, observations, scores, correlations, coefficients, paired inference, freshness, lag placebo; manifest hashes all eight payloads | controller reread/hash/nonempty acceptance | gitignored artifact directory plus manifest | Ready; empirical output pending |
| OUT-02 committed compact bundle/report/traceability | this file plus planned compact JSON/table and plain-English report | hash audit after deterministic replay | `docs/results/` and report | Completion-stage pending |
| VAL-01 required unit coverage | `tests/test_surface_futures_predictive.py` now covers timing/cadence, guards, derivatives, formulas, common-case semantics, train-only transforms/CV, quality isolation, canonical OFI, missingness, staleness, mirror, placebo and determinism | focused pytest | exact pass/warning counts | Implemented; rerun pending |
| VAL-02 full validation, deterministic replay, immutable claim | validation commands plus two full accepted replays; immutable file diff/hash check; staged secret scan | recorded command outputs and artifact hashes | report validation section | Completion-stage pending |
| VAL-03 ledger/changelog and no operational side effects | isolated read-only tape workflow; final `TASKS.md`/`CHANGELOG.md` update only | clean-tree/remote equality and diff review | pushed final commit | Completion-stage pending |

## Pre-run audit disposition

- **39/39 frozen rows are mapped.** There are no unmapped requirements.
- **35 rows are implementation-complete or execution-ready; four are explicitly outcome/finalization
  gates** (`OUT-01`, `OUT-02`, `VAL-02`, `VAL-03`).
- One requested live diagnostic is source-unavailable: live fit duration was not persisted. Its
  fixed column is missing with a training-only missing indicator; replay runtime is excluded.
- Static audit corrections made before accepting any empirical output:
  1. added S-versus-L/O/LO paired inference (six comparisons × three targets = 18 rows);
  2. added direct collinearity and reason-separated epoch-failure evidence;
  3. stopped optional OFI windows from shrinking the 5 s primary common sample;
  4. added direct 300 s no-wrap placebo, cadence and strict staleness regression checks.
