"""Tests for `D38 / TOUCH-METRICS-2026-08-20` section B.

`VAL-METRIC-01` (companions computed on the identical held-out rows as R2) and `VAL-METRIC-02`
(a cell emitting R2 by itself fails the artifact check) are the frozen acceptance tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from shaurya.signals.evaluation_metrics import (
    COST_ARMS,
    PRIMARY_COST_ARM,
    REQUIRED_COMPANION_METRICS,
    CompanionMetricsMissing,
    assert_companion_metrics,
    benjamini_yekutieli,
    declared_cost_arms,
    information_coefficient,
    metric_bundle,
    metric_metadata,
    net_of_cost_pnl,
    past_mirror_verdict,
    per_tape_sign_check,
    sign_accuracy,
)

# ------------------------------------------------------------------------------------ METRIC-01


def test_information_coefficient_recovers_a_planted_linear_association() -> None:
    generator = np.random.default_rng(7)
    x = generator.normal(size=400)
    y = 0.6 * x + 0.8 * generator.normal(size=400)
    report = information_coefficient(x, y, tapes=[0] * 400, replicates=99, seed=1)
    assert report["requirement"] == "METRIC-01"
    assert report["n"] == 400
    assert report["pearson"]["estimate"] == pytest.approx(0.6, abs=0.12)
    assert report["pearson"]["lower"] < report["pearson"]["estimate"] < report["pearson"]["upper"]
    assert report["pearson"]["excludes_zero"] is True
    assert report["spearman"]["estimate"] == pytest.approx(0.58, abs=0.15)
    assert report["resampled_within_tape"] is True


def test_information_coefficient_separates_pearson_from_spearman_on_a_monotone_kink() -> None:
    x = np.linspace(-3.0, 3.0, 300)
    y = np.sign(x) * x**4
    report = information_coefficient(x, y, tapes=[0] * 300, replicates=49, seed=2)
    # A perfectly monotone but strongly non-linear map: Spearman is one, Pearson is not.
    assert report["spearman"]["estimate"] == pytest.approx(1.0, abs=1e-9)
    assert report["pearson"]["estimate"] < 0.9


def test_information_coefficient_is_none_without_variation_or_support() -> None:
    flat = information_coefficient([1.0] * 20, list(range(20)), tapes=[0] * 20, replicates=9)
    assert flat["pearson"]["estimate"] is None
    thin = information_coefficient([1.0, 2.0], [1.0, 2.0], tapes=[0, 0], replicates=9)
    assert thin["pearson"]["estimate"] is None


def test_information_coefficient_never_splices_two_tapes_in_one_replicate() -> None:
    # Tape 0 carries a positive association, tape 1 the negative mirror; a resampler that spliced
    # them would produce replicates far outside the range either tape can generate on its own.
    x = np.concatenate([np.linspace(-1, 1, 100), np.linspace(-1, 1, 100)])
    y = np.concatenate([np.linspace(-1, 1, 100), np.linspace(1, -1, 100)])
    tapes = [0] * 100 + [1] * 100
    report = information_coefficient(x, y, tapes=tapes, replicates=99, seed=3)
    assert report["pearson"]["estimate"] == pytest.approx(0.0, abs=1e-9)
    assert report["pearson"]["lower"] is not None


def test_information_coefficient_rejects_unaligned_inputs() -> None:
    with pytest.raises(ValueError):
        information_coefficient([1.0, 2.0], [1.0], tapes=[0, 0])


# ------------------------------------------------------------------------------------ METRIC-02


def test_sign_accuracy_reports_both_nulls_and_the_non_zero_panel() -> None:
    predictions = [1.0, 1.0, 1.0, 1.0, -1.0, 1.0]
    realised = [1.0, 2.0, 3.0, 0.0, 1.0, -1.0]
    report = sign_accuracy(predictions, realised)
    assert report["requirement"] == "METRIC-02"
    everything = report["all_rows"]
    assert everything["n"] == 6
    assert everything["hits"] == 3
    assert everything["hit_rate"] == pytest.approx(0.5)
    assert everything["up_share"] == pytest.approx(4 / 6)
    assert everything["majority_class_share"] == pytest.approx(4 / 6)
    assert everything["excess_over_coin_flip"] == pytest.approx(0.0)
    # A 50% hit rate against a 67% up-share is a losing signal, and only the majority null says so.
    assert everything["excess_over_majority_class"] < 0.0
    non_zero = report["strictly_non_zero_moves"]
    assert non_zero["n"] == 5
    assert non_zero["flat_share"] == pytest.approx(0.0)


def test_sign_accuracy_on_an_empty_panel_is_missing_not_zero() -> None:
    report = sign_accuracy([1.0, 1.0], [0.0, 0.0])
    assert report["strictly_non_zero_moves"]["n"] == 0
    assert report["strictly_non_zero_moves"]["hit_rate"] is None
    assert report["strictly_non_zero_moves"]["excess_over_majority_class"] is None


# ------------------------------------------------------------------------------------ METRIC-03


def test_net_of_cost_pnl_only_trades_when_the_forecast_beats_the_spread() -> None:
    predictions = [10.0, 1.0, -10.0, 0.0]
    realised = [4.0, 100.0, -4.0, 100.0]
    spreads = [2.0, 2.0, 2.0, 2.0]
    report = net_of_cost_pnl(predictions, realised, spreads)
    assert report["requirement"] == "METRIC-03"
    assert report["n"] == 4
    # rows 1 and 3 forecast below the spread and must not trade, however large the realised move
    assert report["trades"] == 2
    assert report["participation_rate"] == pytest.approx(0.5)
    assert report["gross_total_pnl_ticks"] == pytest.approx(8.0)
    assert report["cost_arms"]["gross"]["total_pnl_ticks"] == pytest.approx(8.0)
    # half-spread charged on both traded rows
    assert report["cost_arms"]["half_spread_only"]["total_pnl_ticks"] == pytest.approx(4.0)


def test_net_of_cost_pnl_cost_arms_are_ordered_and_the_statutory_arm_is_the_headline() -> None:
    arms = declared_cost_arms()
    assert [arm.name for arm in arms] == [name for name, _, _ in COST_ARMS]
    assert arms[0].fee_ticks == 0.0 and not arms[0].charge_half_spread
    fees = [arm.fee_ticks for arm in arms]
    assert fees == sorted(fees)
    assert arms[-1].name == PRIMARY_COST_ARM
    # The post-2024 futures STT alone is worth roughly a hundred ticks of NIFTY round trip; the
    # arm must actually carry it rather than round it away.
    assert arms[-1].fee_ticks > arms[-2].fee_ticks + 90.0


def test_net_of_cost_pnl_reports_turnover_and_risk_adjusted_pnl() -> None:
    predictions = [10.0, 10.0, -10.0]
    realised = [1.0, 1.0, 1.0]
    spreads = [1.0, 1.0, 1.0]
    report = net_of_cost_pnl(predictions, realised, spreads)
    # 0 -> +1 (1), +1 -> +1 (0), +1 -> -1 (2)
    assert report["turnover_units"] == pytest.approx(3.0)
    assert report["cost_arms"]["gross"]["pnl_per_unit_risk"] is not None
    assert report["cost_arms"]["gross"]["mean_pnl_ticks_per_trade"] == pytest.approx(1 / 3)


def test_net_of_cost_pnl_drops_rows_with_an_unusable_spread() -> None:
    report = net_of_cost_pnl([10.0, 10.0], [1.0, 1.0], [1.0, float("nan")])
    assert report["n"] == 1


def test_net_of_cost_pnl_rejects_unaligned_inputs() -> None:
    with pytest.raises(ValueError):
        net_of_cost_pnl([1.0], [1.0], [1.0, 2.0])


# ------------------------------------------------------------------------------------ METRIC-04


def test_val_metric_01_bundle_is_computed_on_the_identical_held_out_rows() -> None:
    generator = np.random.default_rng(11)
    x = generator.normal(size=120)
    y = 0.4 * x + generator.normal(size=120)
    bundle = metric_bundle(
        x, y, spread_ticks=[1.0] * 120, tapes=[0] * 60 + [1] * 60, replicates=49, seed=5
    )
    assert bundle["held_out_rows"] == 120
    assert set(REQUIRED_COMPANION_METRICS) <= set(bundle)
    assert bundle["information_coefficient"]["n"] == 120
    assert bundle["sign_accuracy"]["all_rows"]["n"] == 120
    assert bundle["net_of_cost_pnl"]["n"] == 120
    cell = {"model": "M2", "oos_r2_training_mean": 0.01, "test_n": 120, "metrics": bundle}
    assert_companion_metrics(cell, label="M2")


def test_val_metric_02_r2_without_companions_fails_the_artifact_check() -> None:
    with pytest.raises(CompanionMetricsMissing):
        assert_companion_metrics({"oos_r2_training_mean": 0.01, "test_n": 10}, label="bare")
    with pytest.raises(CompanionMetricsMissing):
        assert_companion_metrics(
            {"in_sample_r2": 0.5, "metrics": {"sign_accuracy": {}}}, label="partial"
        )
    # a cell with no R2 at all is not in scope for this check
    assert_companion_metrics({"model": "M0", "status": "blocked"}, label="blocked")


def test_val_metric_01_refuses_a_bundle_built_on_a_different_row_count() -> None:
    bundle = metric_bundle(
        [1.0] * 10, [1.0] * 10, spread_ticks=[1.0] * 10, tapes=[0] * 10, replicates=9
    )
    with pytest.raises(CompanionMetricsMissing):
        assert_companion_metrics(
            {"oos_r2_training_mean": 0.0, "test_n": 40, "metrics": bundle}, label="mismatched"
        )


# ------------------------------------------------------------------------------------ METRIC-05


def test_benjamini_yekutieli_is_more_conservative_than_the_uncorrected_p_value() -> None:
    raw = [0.001, 0.02, 0.2, 0.5, None]
    adjusted = benjamini_yekutieli(raw)
    assert adjusted[4] is None
    for index in range(4):
        assert adjusted[index] is not None
        assert adjusted[index] >= raw[index]
    # monotone in the sorted order, and bounded above by one
    assert adjusted[0] <= adjusted[1] <= adjusted[2] <= adjusted[3] <= 1.0


def test_benjamini_yekutieli_handles_an_empty_family() -> None:
    assert benjamini_yekutieli([]) == []
    assert benjamini_yekutieli([None, None]) == [None, None]


def test_past_mirror_verdict_fails_a_metric_the_mirror_reproduces() -> None:
    assert (
        past_mirror_verdict(future_value=0.05, past_value=0.01, label="ic")["verdict"] == "passes"
    )
    failing = past_mirror_verdict(future_value=0.02, past_value=0.06, label="ic")
    assert failing["verdict"] == "fails_past_mirror"
    assert failing["passes_past_mirror"] is False
    assert past_mirror_verdict(future_value=None, past_value=0.01, label="ic")["verdict"] == (
        "unevaluable"
    )


def test_per_tape_sign_check_flags_a_result_carried_by_one_tape() -> None:
    consistent = per_tape_sign_check({"0": 0.02, "1": 0.03}, label="ic")
    assert consistent["consistent"] is True
    split = per_tape_sign_check({"0": 0.08, "1": -0.02}, label="ic")
    assert split["consistent"] is False
    assert split["positive_tapes"] == 1 and split["negative_tapes"] == 1


def test_metric_metadata_declares_the_discipline() -> None:
    metadata = metric_metadata()
    assert metadata["r2_alone_is_a_defect"] is True
    assert metadata["naive_iid_inference_valid"] is False
    assert metadata["multiple_testing_correction"] == "benjamini_yekutieli"
    assert metadata["primary_cost_arm"] == PRIMARY_COST_ARM
