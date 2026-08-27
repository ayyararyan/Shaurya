# CCZ OFI migration — requirements traceability

**Specification:** `docs/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md` (`D37 / CCZ-OFI-MIGRATION-2026-08-20`)
**Branch:** `ccz-ofi-migration`, based at `be2dd99`
**Status vocabulary:** §12 of `OPENCLAW_WORKING_INSTRUCTIONS_REVISED.md`. "Implemented" and
"Tested" are Level 1 and Level 2. Nothing here is Level 4 (live verified).

Every frozen requirement has exactly one row. No requirement was dropped.

## Estimator definitions

| ID | Requirement | Status | Code location | Test | Notes |
|---|---|---|---|---|---|
| `EST-CCZ-01` | Rank-keyed per-level order flow, Eq. (2) base terms | Implemented, Tested | `src/shaurya/signals/ccz_ofi.py:ccz_level_flow`, `_bid_order_flow`, `_ask_order_flow` | `test_val_ccz_01_per_level_order_flow_matches_equation_two_by_hand` | Rank-keyed, not price-keyed, per Aryan's decision (a) |
| `EST-CCZ-02` | Level-`m` OFI over horizon `h`, Eq. (2), no sum over levels | Implemented, Tested | `ccz_ofi.py:CczFlowSeries.window` (`raw`) | `test_val_ccz_02_level_ofi_is_that_level_only_not_a_running_total`, `test_val_ccz_02_no_code_path_sums_ofi_across_levels` | Prefix sums over transitions; per level, never across |
| `EST-CCZ-03` | Depth scaling by one common `Q^{M,h}`, Eq. (3) | Implemented, Tested | `ccz_ofi.py:CczFlowSeries.window` (`denominator`, `normalised`) | `test_val_ccz_03_one_common_denominator_divides_every_level`, `test_val_ccz_03_denominator_floor_is_recorded_not_absorbed` | Floor `1.0` contract; every flooring event counted into `ccz_depth_denominator_floored` |
| `EST-CCZ-04` | Integrated OFI, Eq. (4), PC1 on training rows only | Implemented, Tested | `ccz_ofi.py:fit_integrated_weights`, `IntegratedWeights.project` | `test_val_ccz_04_first_component_is_fitted_on_training_rows_only`, `test_integrated_weights_ignore_test_rows_entirely`, `test_ccz_integrated_weights_are_fitted_on_the_training_block_only` | EVR and applied sign recorded per fit |
| `EST-CCZ-05` | Four declared aggregation arms | Implemented, Tested | `ccz_ofi.py:aggregate_window`; `ofi_horserace.py:evaluate_ccz_aggregation_arms`; `model_features` (`M4`, `M5`); `cks_l1_ofi.py` (best level) | `test_ccz_aggregation_arms_cover_every_declared_arm_and_level_count`, `test_aggregation_arms_cover_the_declared_set` | `integrated` is the primary arm; `best_level` (`m=1`) is the CKS baseline |
| `EST-CCZ-06` | `M = 10` primary; `M ∈ {1, 5, 20, 200}` declared robustness | Implemented, Tested | `ccz_ofi.py:DECLARED_LEVEL_COUNTS`; `ofi_horserace.py:CCZ_LEVEL_COUNTS` | `test_ccz_aggregation_arms_cover_every_declared_arm_and_level_count`, `test_val_ccz_08_horse_race_artifact_carries_the_estimator_block` | An unsupported arm is emitted `data_insufficient_level_support`, never dropped |

## Code change scope

| ID | Requirement | Status | Code location | Test | Notes |
|---|---|---|---|---|---|
| `CCZ-IMPL-01` | New module implementing `EST-CCZ-01..05` | Implemented, Tested | `src/shaurya/signals/ccz_ofi.py` | `tests/test_ccz_ofi.py` (18 tests) | Self-contained; no import of the retired module |
| `CCZ-IMPL-02` | Remove cumulative-across-levels construction | Implemented, Tested | `src/shaurya/signals/deep_book_ofi.py` | `test_val_ccz_02_no_code_path_sums_ofi_across_levels`, `test_module_no_longer_exports_the_cumulative_construction` | Module reduced to shared primitives; `scripts/deepbook_ofi_scan.py` and the controller's `scalar_ofi` stage removed with it |
| `CCZ-IMPL-03` | Remove per-band depth normalisation (M5) | Implemented, Tested | `src/shaurya/signals/ofi_horserace.py` | `test_no_module_declares_a_per_band_depth_denominator`, `test_construction_uses_canonical_cks_and_causal_depth_adjustment` | `BANDS`, `pk_band_feature`, `adjusted_band_feature`, `_band_depths` all gone |
| `CCZ-IMPL-04` | Rebuild horse-race families on CCZ objects | Implemented, Tested | `ofi_horserace.py:model_features`, `build_horserace_observations`, `evaluate_ccz_aggregation_arms`, `_level_contribution_diagnostics` | `tests/test_ofi_horserace.py` (22 tests) | `M4` = Eq. (2) per level, `M5` = Eq. (3) per level, `M6` combined |
| `CCZ-IMPL-05` | Retain level-1 CKS unchanged as Eq. (1) base case | Implemented, Tested | `src/shaurya/signals/cks_l1_ofi.py:cks_l1_transition` | `tests/test_cks_l1_ofi.py` (33 tests) | Estimator byte-unchanged; only the comparison feature moved to the CCZ ten-level average |
| `CCZ-IMPL-06` | Dashboard consumes CCZ estimators | Implemented, Tested | `src/shaurya/analytics/ofi_dashboard.py`, `src/shaurya/cli/ofi_dashboard.py` | `test_val_ccz_08_dashboard_payload_carries_the_estimator_block`, `test_ccz_integrated_weights_are_fitted_on_the_training_block_only` | Cell geometry `M0..M6 × 5 × 5` unchanged, so the frozen multiplicity accounting is unaffected |
| `CCZ-IMPL-07` | Update replication / live-partial drivers | Implemented, Tested | `src/shaurya/data/ofi_replication.py`, `src/shaurya/data/ofi_live_partial.py` | `tests/test_ofi_replication.py`, `tests/test_ofi_live_partial.py` | Neither computes an estimator; both now record which estimator downstream analysis used |
| `CCZ-IMPL-08` | Per-unit commit-pin re-check | Implemented, Tested | `scripts/ofi_full_session_controller.py:assert_on_pin`, `analysis_stage` | `test_ops_ccz_01_pin_is_rechecked_per_unit_and_records_the_observed_head` and the two fail-closed tests | See `OPS-CCZ-01` |

## Identification and operations

| ID | Requirement | Status | Code location | Test | Notes |
|---|---|---|---|---|---|
| `ID-CCZ-01` | Snapshot relabelling documented, never patched | Implemented, Tested | `ccz_ofi.py:ID_CCZ_01_LIMITATION`, emitted by `ccz_metadata` | `test_val_ccz_08_metadata_carries_estimator_levels_evr_and_the_limitation`, and the artifact tests | Carried verbatim in the horse-race, CKS, surface, dashboard, replication-receipt and partial-claim artifacts |
| `OPS-CCZ-01` | Pin re-checked before every unit, fail closed, per-stage HEAD recorded | Implemented, Tested | `scripts/ofi_full_session_controller.py` | `test_ops_ccz_01_*` (3 tests) | Re-checked before *and* after each unit; `observed_code_commit_by_unit` replaces the constant in the hash manifest |

## Acceptance tests

| ID | Requirement | Status | Test |
|---|---|---|---|
| `VAL-CCZ-01` | Per-level OFI matches Eq. (2) by hand | Tested | `test_val_ccz_01_per_level_order_flow_matches_equation_two_by_hand` |
| `VAL-CCZ-02` | No code path sums OFI across levels | Tested | `test_val_ccz_02_no_code_path_sums_ofi_across_levels` (AST scan of `src/`), `test_val_ccz_02_level_ofi_is_that_level_only_not_a_running_total` |
| `VAL-CCZ-03` | All `M` levels share one denominator | Tested | `test_val_ccz_03_one_common_denominator_divides_every_level` |
| `VAL-CCZ-04` | PC1 fit on train only; leakage test fails if test rows influence `w_1` | Tested | `test_val_ccz_04_first_component_is_fitted_on_training_rows_only`, `test_integrated_weights_ignore_test_rows_entirely` |
| `VAL-CCZ-05` | `‖w_1‖_1` normalisation | Tested | `test_val_ccz_05_l1_normalisation_makes_the_weights_sum_to_one`, `test_val_ccz_05_sign_fix_is_applied_and_recorded` |
| `VAL-CCZ-06` | Sign convention | Tested | `test_val_ccz_06_pure_bid_side_size_increase_is_positive_at_that_level`, `test_val_ccz_06_ask_side_retreat_is_also_buy_pressure` |
| `VAL-CCZ-07` | Full suite, ruff, strict mypy clean; no lookahead regressions | Tested | `pytest` 576 passed; `ruff check .` clean; `mypy src` clean; `assert_no_lookahead` retained and exercised |
| `VAL-CCZ-08` | Every artifact carries estimator, `M`, EVR, `ID-CCZ-01` | Tested, Dry-run verified | `test_val_ccz_08_metadata_carries_estimator_levels_evr_and_the_limitation`, `test_val_ccz_08_horse_race_artifact_carries_the_estimator_block` (also writes every artifact file), `test_val_ccz_08_dashboard_payload_carries_the_estimator_block`, `test_the_artifact_refuses_a_confirmatory_reading` |

## Counts

Required components: 21 (`EST-CCZ-01..06`, `CCZ-IMPL-01..08`, `ID-CCZ-01`, `OPS-CCZ-01`,
`VAL-CCZ-01..08` counted as the acceptance set).

- Implemented: 16 of 16 non-test requirements
- Partially implemented: 0
- Not implemented: 0
- Blocked: 0
- Acceptance tests passing: 8 of 8
- Unapproved scope reductions: 0
- Unapproved proxy substitutions: 0

Overall: **IMPLEMENTED AND TESTED; LIVE VERIFICATION PENDING.**
