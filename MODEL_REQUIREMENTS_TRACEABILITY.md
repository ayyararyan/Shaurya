# Requirements traceability — `D38 / TOUCH-METRICS-2026-08-20`

**Specification:** `docs/TOUCH-METRICS-SPEC-2026-08-20.md` (frozen 2026-08-20 14:25 IST)
**Branch:** `ccz-ofi-migration` in `/Users/maheit/Documents/Shaurya-ccz`
**Builds on:** `D37 / CCZ-OFI-MIGRATION-2026-08-20`, whose own matrix is in `CCZ-MIGRATION-REPORT.md`.

Status vocabulary is §10/§12 of the working contract. **Implemented** means code exists;
**Tested** means automated tests pass; neither is **Live verified**. Nothing in this table is
live verified — see the "Evidence level" column.

| ID | Requirement | Status | Code location | Test | Evidence level |
|---|---|---|---|---|---|
| `TOUCH-01` | Classify every print against the contemporaneous displayed L1; distribution overall, by hour, by displayed-spread bucket; confirm or refute 42–48% | **Implemented + measured** | `signals/effective_touch.py:classify_print_location`, `build_trade_prints`, `print_location_diagnostics`; `scripts/touch_metrics_scan.py` | `test_effective_touch.py::test_touch_01_reports_the_full_distribution_and_its_exclusion_accounting`, `::test_print_location_classification_is_on_the_quantised_tick_grid`, `::test_touch_01_buckets_by_hour_and_by_displayed_spread` | 3 — measured on three immutable snapshots |
| `TOUCH-02` | Rolling causal effective-touch estimator; per-anchor coverage and staleness; undefined emitted as missing | **Implemented + measured** | `signals/effective_touch.py:EffectiveTouchSeries`, `effective_touch_coverage` | `test_effective_touch.py::test_val_touch_01_*`, `::test_val_touch_02_*`, `::test_effective_touch_coverage_reports_staleness_and_missing_sides` | 3 — measured on three immutable snapshots |
| `TOUCH-03` | Four reference prices, applied on both sides of the regression, reported side by side | **Implemented, tested** | `signals/reference_prices.py` (`ReferencePrice`, `PricePath`, `build_reference_price_paths`); `ofi_horserace.py:_returns`, `evaluate_cells(reference=...)`, `build_horserace_artifact` | `test_reference_prices.py::test_val_touch_03_*`, `test_d38_acceptance.py::test_val_touch_03_every_reference_price_produces_a_comparable_cell_set` | 2 |
| `TOUCH-04` | Re-derive CCZ multi-level OFI, L1 queue imbalance and microprice against the effective touch; rerun the horse race under each reference price | **Implemented, tested; empirical rerun BOUNDED** | `signals/reference_prices.py:touch_relative_state`, `touch_relative_queue_imbalance`, `touch_relative_microprice_tilt_ticks`; `ofi_horserace.py` `basis="effective_touch"` | `test_reference_prices.py::test_touch_relative_*`, `test_d38_acceptance.py::test_touch_04_re_derivation_block_is_published` | 2 in code; see report §"TOUCH-04 empirical" for what was and was not run on a real tape |
| `METRIC-01` | Pearson and Spearman IC with stationary block-bootstrap CIs | **Implemented, tested** | `signals/evaluation_metrics.py:information_coefficient` | `test_evaluation_metrics.py::test_information_coefficient_*` (5 tests) | 2 |
| `METRIC-02` | Hit rate vs 50% null and majority-class null; also on strictly non-zero moves | **Implemented, tested** | `signals/evaluation_metrics.py:sign_accuracy` | `test_evaluation_metrics.py::test_sign_accuracy_*` | 2 |
| `METRIC-03` | CCZ §4.2.2 net-of-cost PnL: gross, net of half-spread plus fees, turnover, PnL per unit risk | **Implemented, tested** | `signals/evaluation_metrics.py:net_of_cost_pnl`, `COST_ARMS` | `test_evaluation_metrics.py::test_net_of_cost_pnl_*` (5 tests) | 2 |
| `METRIC-04` | R² retained but never alone; a cell reporting R² by itself is a defect | **Implemented, tested** | `signals/evaluation_metrics.py:metric_bundle`, `assert_companion_metrics`; enforced in `build_horserace_artifact` | `test_evaluation_metrics.py::test_val_metric_01_*`, `::test_val_metric_02_*`; `test_d38_acceptance.py::test_val_metric_01_and_02_every_cell_carries_its_companions` | 2 |
| `METRIC-05` | Inherit dependence-aware FDR, past-mirror comparison, per-tape sign check | **Implemented, tested** | `signals/evaluation_metrics.py:benjamini_yekutieli`, `past_mirror_verdict`, `per_tape_sign_check`; `ofi_horserace.py:_past_mirror_table` | `test_evaluation_metrics.py::test_benjamini_yekutieli_*`, `::test_past_mirror_verdict_*`, `::test_per_tape_sign_check_*`; `test_d38_acceptance.py::test_metric_05_past_mirror_table_and_by_correction_are_emitted` | 2 |
| `WINDOW-01` | Same-window grid extended to 30 s and 60 s | **Implemented, tested** | `ofi_horserace.py:SAME_WINDOW_SECONDS`, `evaluate_same_window`, feature build over all seven windows | `test_d38_acceptance.py::test_val_window_01_the_sixty_second_cell_is_present_and_labelled` | 2 |
| `WINDOW-02` | Promote from `descriptive_only` to a replication gate against CCZ's 71.16 / 64.64 / 87.14; record the gap explicitly | **Implemented, tested** | `ofi_horserace.py:_ccz_replication_gap`, `evaluate_same_window` | `test_d38_acceptance.py::test_window_02_the_replication_gap_is_recorded_not_inferred` | 2 |
| `WINDOW-03` | Full R²-versus-window curve at every depth | **Implemented, tested** | `ofi_horserace.py:same_window_curve` (per family) and `evaluate_same_window_by_depth` + `depth_r2_curve` (per declared CCZ level count `M`) | `test_d38_acceptance.py::test_window_03_curve_exposes_the_shape_at_every_window`, `::test_val_window_01_and_window_03_cover_every_declared_depth` | 2 |
| `MICRO-01` | Simple imbalance-weighted microprice as named arm `M7` | **Implemented, tested** | `signals/microprice.py:simple_microprice`, `microprice_tilt_ticks`; `ofi_horserace.py` `M7` | `test_microprice.py::test_simple_microprice_*`; `test_d38_acceptance.py::test_micro_03_both_microprice_arms_are_families_not_controls` | 2 |
| `MICRO-02` | Stoikov (2018) iterated estimator, fitted on training rows only, arm `M8` | **Implemented, tested** | `signals/microprice.py:fit_stoikov_microprice`, `build_stoikov_transitions`; `ofi_horserace.py:fit_stoikov_for_split`, `with_stoikov_feature` | `test_microprice.py::test_val_micro_01_*` (2), `::test_stoikov_adjustment_accumulates_*`; `test_d38_acceptance.py::test_val_micro_01_the_artifact_chain_is_fitted_on_training_rows_only` | 2 |
| `MICRO-03` | Both enter `MODEL_ORDER` as families, not controls, inheriting the section B metric set | **Implemented, tested** | `ofi_horserace.py:MODEL_ORDER`, `model_features`; `analytics/ofi_dashboard.py` | `test_d38_acceptance.py::test_micro_03_*`; `test_ofi_dashboard.py::test_grid_size_is_pinned_to_the_declared_family_and_axis_counts` | 2 |
| `OPS-CCZ-02` | Re-check commit pin and worktree cleanliness before every unit, fail closed, record observed HEAD per stage | **Implemented, tested** | `scripts/ofi_full_session_controller.py:assert_on_pin`, `capture`, `analysis_stage` | `test_d38_acceptance.py::test_ops_ccz_02_*` (2) | 2 — the *next* controller generation; the running 15:42 unit is untouched |
| `VAL-TOUCH-01` | Effective touch never uses a print at or after the anchor | **Implemented, tested** | `signals/effective_touch.py:EffectiveTouchSeries.at` | `test_effective_touch.py::test_val_touch_01_estimate_never_uses_a_print_at_or_after_the_anchor`, `::test_val_touch_01_holds_at_every_declared_window` | 2 |
| `VAL-TOUCH-02` | Undefined effective touch propagates as missing, never as displayed touch | **Implemented, tested** | `effective_touch.py:EffectiveTouch.defined`; `reference_prices.py:touch_relative_state` and friends | `test_effective_touch.py::test_val_touch_02_*`; `test_reference_prices.py::test_val_touch_02_re_derivation_never_falls_back_to_the_displayed_touch` | 2 |
| `VAL-TOUCH-03` | Every reference price produces a complete, comparable cell set | **Implemented, tested** | `reference_prices.py:reference_price_coverage`; `build_horserace_artifact` uncovered ledger | `test_reference_prices.py::test_val_touch_03_*`; `test_d38_acceptance.py::test_val_touch_03_*` | 2 |
| `VAL-METRIC-01` | IC, hit rate and net PnL computed on the identical held-out rows as R² | **Implemented, tested** | `ofi_horserace.py:cell_metrics`; `evaluation_metrics.py:assert_companion_metrics` row-count check | `test_evaluation_metrics.py::test_val_metric_01_*` (2); `test_d38_acceptance.py::test_val_metric_01_and_02_*` | 2 |
| `VAL-METRIC-02` | A cell emitting R² without companions fails the artifact check | **Implemented, tested** | `evaluation_metrics.py:CompanionMetricsMissing`; raised inside `build_horserace_artifact` | `test_evaluation_metrics.py::test_val_metric_02_*`; `test_d38_acceptance.py::test_val_metric_02_*` | 2 |
| `VAL-WINDOW-01` | 60 s same-window cell present at every depth and labelled the CCZ comparison cell | **Implemented, tested** | `evaluate_same_window` and `evaluate_same_window_by_depth`, both carrying `is_ccz_comparison_cell` | `test_d38_acceptance.py::test_val_window_01_the_sixty_second_cell_is_present_and_labelled`, `::test_val_window_01_and_window_03_cover_every_declared_depth` | 2 |
| `VAL-MICRO-01` | Stoikov state model fitted on training rows only | **Implemented, tested** | `microprice.py:StoikovLeakage` guard; `fit_stoikov_for_split` boundary | `test_microprice.py::test_val_micro_01_*` (2); `test_d38_acceptance.py::test_val_micro_01_*` | 2 |
| `VAL-ALL` | Full suite, ruff, strict mypy clean | **Implemented, tested** | — | see `TOUCH-METRICS-REPORT.md` verification section | 2 |

## Explicit exclusions honoured (spec §G)

- The live capture `ofi-late-partial-20260820` and the running 15:42 checkpoint were not touched.
- No order path, no SIG-21 credit, no confirmatory status. Every artifact carries
  `confirmatory_eligible: false`.
- Pre-existing artifacts were preserved. Nothing was pooled across reference prices: every cell
  carries an explicit `reference_price` and `predictor_basis` column.

## D39 additive matrix — `FIXED-TARGET-COMPETITOR-PANEL`

**Specification:** `docs/D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md`
**Evidence boundary:** code and synthetic validation are evidence level 2. The 2026-08-20 replay,
when present, is a post-outcome partial-session exploration and cannot exceed level 3.

| ID | Requirement | Status | Code location | Test / acceptance evidence |
|---|---|---|---|---|
| `METHOD-D39-01` | One future target with 0.5 s causal gap; C0–C12 compete on identical rows | **Implemented, tested** | `signals/fixed_target_panel.py:evaluate_panel_cell` | `test_fixed_target_panel.py::test_val_d39_04_*` |
| `METHOD-D39-02` | Direct tests of lagged return C2, OFI C8, and their union C12 | **Implemented, tested** | `signals/fixed_target_panel.py:competitor_features` | `test_fixed_target_panel.py::test_val_d39_03_*`, `::test_val_d39_04_*` |
| `METHOD-D39-03` | All metrics accompany every estimated competitor; row mismatch refuses artifact | **Implemented, tested** | `signals/fixed_target_panel.py:evaluate_panel_cell`; `evaluation_metrics.py:assert_companion_metrics` | `test_fixed_target_panel.py::test_val_d39_04_*` |
| `BOUNCE-01` | Training-only Roll fit plus whole-tape and 15-minute diagnostics | **Implemented, tested** | `signals/fixed_target_panel.py:roll_effective_spread`, `roll_diagnostics` | `test_fixed_target_panel.py::test_val_bounce_01_*` |
| `BOUNCE-02` | Sign-corrected LTP from training Roll half-spread | **Implemented, tested** | `signals/fixed_target_panel.py:build_trade_sign_corrected_path` | `test_fixed_target_panel.py::test_val_bounce_02_*` |
| `BOUNCE-03` | Same-side print endpoints never mix trade sides | **Implemented, tested** | `signals/fixed_target_panel.py:SameSidePrintPath` | `test_fixed_target_panel.py::test_val_bounce_03_*` |
| `VAL-D39-01` | Future component is detected and past-only mirror trips its guard | **Tested synthetically** | `signals/fixed_target_panel.py:evaluate_panel_cell` | `test_fixed_target_panel.py::test_val_d39_04_*` |
| `VAL-D39-02` | Lagged return ends no later than anchor | **Tested synthetically** | `signals/fixed_target_panel.py:make_return_resolver` | `test_fixed_target_panel.py::test_val_d39_02_*` |
| `VAL-D39-03` | C12 is exactly C2 plus C8 | **Tested synthetically** | `signals/fixed_target_panel.py:competitor_features` | `test_fixed_target_panel.py::test_val_d39_03_*` |
| `VAL-D39-04` | Complete competitor set, metrics and common row hash | **Tested synthetically** | `signals/fixed_target_panel.py:evaluate_panel_cell` | `test_fixed_target_panel.py::test_val_d39_04_*` |
| `OPS-D39-01` | 2026-08-20 tape remains read-only, exploratory and non-confirmatory | **Implemented** | `scripts/d39_fixed_target_panel.py`; artifact claim-boundary fields | durable run manifest and artifact read-back |

## D40 additive matrix — `OFI-HORIZON-EXTENSION-2026-08-20`

**Specification:** `docs/D40-OFI-HORIZON-EXTENSION-SPEC-2026-08-20.md`
**Evidence boundary:** retrospective displayed-mid extension on the immutable 2026-08-20 partial
session. It does not modify or validate the locked 2026-08-21 D39 test.

| ID | Requirement | Status | Code location | Test / acceptance evidence |
|---|---|---|---|---|
| `D40-OBJ-01` | Fixed C8/M10/10 s model; displayed-mid target; seven 10–120 s horizons | **Implemented** | `scripts/d40_ofi_horizon_extension.py` | exact-axis refusal in `_c8_summary` |
| `D40-DATA-01` | Immutable late-partial tape with SHA identity | **Implemented** | `scripts/d40_ofi_horizon_extension.py`; `scripts/ofi_horserace.py:build_tape_input` | artifact and summary SHA fields |
| `D40-EST-01` | Existing ten-level depth-scaled CCZ OFI construction is unchanged | **Implemented, tested** | `signals/ccz_ofi.py`; `fixed_target_panel.py:competitor_features` | existing CCZ/D39 tests plus focused D40 tests |
| `D40-TARGET-01` | Materialise custom future displayed-mid horizons with 0.5 s gap | **Implemented, tested** | `signals/ofi_horserace.py:build_horserace_observations` | `test_custom_response_horizons_are_materialised_without_changing_predictors` |
| `D40-OOS-01` | Chronological 70/30 split; embargo covers gap plus longest response | **Implemented, tested** | `signals/fixed_target_panel.py:build_fixed_target_panel` | `test_long_horizon_panel_requires_gap_plus_horizon_embargo` |
| `D40-METRIC-01` | Report only C8 absolute OOS R² horizon curve | **Dry-run verified** | `scripts/d40_ofi_horizon_extension.py:_c8_summary` | corrected 7/7-cell artifact and committed compact result |
| `D40-OUT-01` | Full artifact, compact summary, report and next-session prompt | **Dry-run verified** | runner; `docs/results/D40-OFI-HORIZON-EXTENSION-2026-08-20.json`; D40 report and next prompt | full artifact SHA `e291e0f8…`; summary SHA `37a37e42…` |
| `D40-VAL-01` | Custom response horizons materialise without changing D39 anchors | **Tested** | `signals/ofi_horserace.py:build_horserace_observations` | custom-vs-default full timestamp-sequence regression |
| `D40-VAL-02` | Embargo shorter than gap plus longest response is refused | **Tested** | `signals/fixed_target_panel.py:build_fixed_target_panel` | `test_long_horizon_panel_requires_gap_plus_horizon_embargo` |
| `D40-VAL-03` | Exactly seven fixed displayed-mid cells are estimated | **Dry-run verified** | D40 runner exact-axis refusal | authoritative full artifact: 7/7 estimated |
| `D40-VAL-04` | Committed summary/report contain C8 absolute R² only and no LTP result | **Dry-run verified** | D40 summary extractor and committed outputs | artifact-to-committed-result parity check passed |
| `D40-VAL-05` | Tape, code, split, row and artifact identities are recorded | **Dry-run verified** | full artifact, compact summary and report | SHA/split/row-hash acceptance checks passed |
| `D40-VAL-ALL` | Full tests, Ruff, strict mypy, compile and diff checks | **Tested** | repository-wide | 676 pytest; Ruff; 65-file strict mypy; compileall; diff checks passed |

## D41 additive matrix — `MID-LAG-OFI-INCREMENTAL-2026-08-20`

**Specification:** `docs/D41-MID-LAG-OFI-INCREMENTAL-SPEC-2026-08-20.md`
**Evidence boundary:** specification commit `4751d1a` was pushed before D41 outcome execution;
empirical result is permanently retrospective on the already-inspected 2026-08-20 late-partial
tape and is evidence level 3, not confirmatory.

| ID | Requirement | Status | Code location | Test / acceptance evidence |
|---|---|---|---|---|
| `D41-OBJ-01` | Test lag predictiveness, lag versus OFI accuracy, and both incremental directions | **Dry-run verified** | `signals/mid_lag_ofi.py:build_mid_lag_ofi_artifact` | 35-cell comparison plus report direct answers |
| `D41-DATA-01` | Exact immutable 15:42 tape and SHA; receive-time clock | **Dry-run verified** | D41 runner hash gate | tape SHA `93456eda…a43`; accepted receipt |
| `D41-TARGET-01` | Displayed-mid returns after 0.5 s gap at 0.5–30 s | **Implemented, tested** | `mid_lag_ofi.py:_target`; canonical observation builder | `test_mid_lag_ofi.py`; seven scored horizons |
| `D41-X-01` | Seven trailing displayed-mid returns plus fixed all-lag bank | **Implemented, tested** | `mid_lag_ofi.py:lag_feature_names`, `_lag_design` | 49 single-lag cells plus 7 lag-bank cells |
| `D41-X-02` | Ten-level depth-scaled CCZ OFI alone at five windows | **Implemented, tested** | `signals/ccz_ofi.py`; `mid_lag_ofi.py:ofi_feature_names`, `_ofi_design` | existing CCZ equation tests plus 35 OFI cells |
| `D41-EST-01` | `L_k`, `L_ALL`, `O_w`, and exact `LO_w` panel only | **Dry-run verified** | `mid_lag_ofi.py:_fit_forecast`, `build_mid_lag_ofi_artifact` | exact-union synthetic and artifact assertions |
| `D41-INST-01` | Separate contemporaneous construction check | **Dry-run verified** | `mid_lag_ofi.py:_contemporaneous_panel` | 6/6 cells; all Holm-significant |
| `D41-OOS-01` | Preserved anchor universe; 70/30 chronological split; 30.5 s embargo; common rows | **Dry-run verified** | `mid_lag_ofi.py:_split`, `_future_positions` | common train/test row hashes at every horizon |
| `D41-INF-01` | HAC loss tests, DM, nested Clark--West and Holm families | **Implemented, tested, dry-run verified** | `mid_lag_ofi.py:hac_mean_test`, `holm_adjust`, `_comparison_tests` | deterministic synthetic tests and complete artifact-family audit |
| `D41-OUT-01` | Full/compact artifacts, report, trial row and hashes | **Dry-run verified** | D41 runner; committed report/result | full SHA `19d1ee96…2b04`; compact SHA `96a96f55…bb9a` |
| `D41-VAL-ALL` | Focused/full tests, Ruff, mypy, compile, artifact/hash/secret gates | **Tested** | repository-wide | 679 pytest; Ruff; 66-file strict mypy; compileall; artifact parity/hash checks |
