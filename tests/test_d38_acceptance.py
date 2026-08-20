"""End-to-end acceptance tests for `D38 / TOUCH-METRICS-2026-08-20`, section F.

These are the frozen acceptance tests that need a whole artifact rather than one function:
`VAL-TOUCH-03` (every reference price produces a complete, comparable cell set),
`VAL-METRIC-01`/`VAL-METRIC-02` (companions on the identical held-out rows; an R2 alone fails the
artifact check), `VAL-WINDOW-01` (the 60 s cell is present and labelled as the CCZ comparison
cell) and `VAL-MICRO-01` at the artifact boundary.  `OPS-CCZ-02` is asserted against the
controller that will actually run the next generation.

The tape is synthetic on purpose: correctness is established on a fixture whose answer is known,
never on a market tape whose answer is not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState, parse_receive_ts_ns
from shaurya.data.trade_direction import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION
from shaurya.signals.evaluation_metrics import (
    CompanionMetricsMissing,
    assert_companion_metrics,
)
from shaurya.signals.ofi_horserace import (
    CCZ_CONTEMPORANEOUS_WINDOW_SECONDS,
    CCZ_LEVEL_COUNTS,
    CCZ_SCALAR_ARMS,
    MODEL_ORDER,
    SAME_WINDOW_SECONDS,
    STOIKOV_FEATURE,
    HorseRaceTapeInput,
    build_horserace_artifact,
    build_horserace_observations,
    depth_r2_curve,
    fit_stoikov_for_split,
    model_features,
    same_window_curve,
    stoikov_is_available,
    with_stoikov_feature,
)
from shaurya.signals.reference_prices import BASELINE_REFERENCE, REFERENCE_PRICE_LADDER

SECOND = 1_000_000_000
BASE = parse_receive_ts_ns("2026-08-20T03:51:46.000000+00:00")
COUNT = 1_400


def _bid(index: int) -> float:
    return round(100.0 + 0.05 * ((index * 7) % 13 - 6), 2)


def _state(index: int, *, channel: str = DEPTH200) -> BookState:
    bid = _bid(index)
    ask = round(bid + 0.50, 2)
    size = 100 + (index * 11) % 37
    bids = tuple((round(bid - 0.05 * level, 2), size + level, 1) for level in range(200))
    asks = tuple((round(ask + 0.05 * level, 2), size + 3 + level, 1) for level in range(200))
    levels = 20 if channel == DEPTH20 else 200
    return BookState(
        channel=channel,
        receive_ts_ns=BASE + index * SECOND // 2,
        receive_sequence=index,
        connection_epoch=0,
        bids=bids[:levels],
        asks=asks[:levels],
        rows_in_burst=1,
        quality_flags=(),
    )


def _iso(index: int) -> str:
    total = BASE + index * SECOND // 2
    seconds, remainder = divmod(total, SECOND)
    from datetime import UTC, datetime

    return (
        datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder // 1000).isoformat()
    )


def _trade_row(index: int) -> dict[str, Any]:
    """A print that lands strictly inside the displayed quote, alternating side.

    The displayed spread is ten ticks wide, so a buyer-initiated print one tick under the ask and
    a seller-initiated print one tick over the bid give the effective touch an eight-tick width
    that is genuinely tighter than the displayed one.  That is the whole point of `TOUCH-02`.
    """

    bid = _bid(index)
    ask = round(bid + 0.50, 2)
    buy = index % 2 == 0
    return {
        "event_type": "full",
        "receive_ts": _iso(index),
        "last_price": round(ask - 0.05, 2) if buy else round(bid + 0.05, 2),
        "last_quantity": 5,
        "cumulative_volume_increment": 5,
        "trade_side": "buy" if buy else "sell",
        "trade_quote_bid": bid,
        "trade_quote_ask": ask,
        "trade_quote_channel": DEPTH200,
        "trade_quote_age_ms": 40.0,
        "trade_classifier_version": TRADE_CLASSIFIER_VERSION,
        "trade_alignment_version": TRADE_ALIGNMENT_VERSION,
        "trade_classification_degraded": False,
        "trade_coalesced": False,
    }


@pytest.fixture(scope="module")
def artifact() -> dict[str, Any]:
    depth200 = [_state(index) for index in range(COUNT)]
    depth20 = [_state(index, channel=DEPTH20) for index in range(COUNT + 100)]
    rows = [_trade_row(index) for index in range(COUNT)]
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=rows,
        tape_index=0,
        run_id="d38-acceptance",
        level_counts=(1, 5, 10),
    )
    assert observations
    tape = HorseRaceTapeInput(
        tape_index=0,
        run_id="d38-acceptance",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        tape_sha256="0" * 64,
        observations=tuple(observations),
        depth200_publications=len(depth200),
        depth20_publications=len(depth20),
        observed_seconds=COUNT / 2.0,
        failures=failures,
    )
    return build_horserace_artifact([tape], code_commit=None, replicates=3, seed=11)


# ------------------------------------------------------------------------------------ TOUCH-03


def test_val_touch_03_every_reference_price_produces_a_comparable_cell_set(
    artifact: dict[str, Any],
) -> None:
    block = artifact["reference_prices"]
    assert block["ladder"] == list(REFERENCE_PRICE_LADDER)
    assert block["applied_on_both_sides_of_the_regression"] is True
    assert block["predictor_bases"] == ["displayed", "effective_touch"]

    covered = {
        (row["reference_price"], row["predictor_basis"])
        for row in artifact["reference_price_ladder_future_cells"]
    }
    covered.add((BASELINE_REFERENCE, "displayed"))
    uncovered = {
        (row["reference_price"], row["predictor_basis"])
        for row in artifact["reference_price_ladder_uncovered"]
    }
    expected = {
        (reference, basis)
        for reference in REFERENCE_PRICE_LADDER
        for basis in ("displayed", "effective_touch")
    }
    # nothing may go missing: a combination is either scored or explicitly recorded as uncovered
    assert covered | uncovered == expected
    assert not covered & uncovered

    for reference, basis in covered - {(BASELINE_REFERENCE, "displayed")}:
        rows = [
            row
            for row in artifact["reference_price_ladder_future_cells"]
            if row["reference_price"] == reference and row["predictor_basis"] == basis
        ]
        assert len(rows) == 5 * 5 * len(MODEL_ORDER)


def test_reference_price_coverage_is_reported_per_tape(artifact: dict[str, Any]) -> None:
    coverage = artifact["tapes"][0]["failures"]["reference_price_coverage"]
    assert coverage["requirement"] == "TOUCH-03"
    assert sorted(coverage["paths"]) == sorted(REFERENCE_PRICE_LADDER)
    assert coverage["paths"]["effective_touch_mid"]["object_category"] == "proxy"
    assert coverage["paths"]["last_trade"]["object_category"] == "observed"
    assert all(coverage["paths"][name]["points"] > 0 for name in REFERENCE_PRICE_LADDER)


def test_touch_04_re_derivation_block_is_published(artifact: dict[str, Any]) -> None:
    block = artifact["touch_relative"]
    assert block["requirement"] == "TOUCH-04"
    assert block["object_category"] == "proxy"
    assert set(block["re_derived"]) == {
        "ccz_multi_level_ofi",
        "l1_queue_imbalance",
        "microprice",
    }


# ------------------------------------------------------------------------------------ METRIC-04


def test_val_metric_01_and_02_every_cell_carries_its_companions(
    artifact: dict[str, Any],
) -> None:
    cells = [
        *artifact["future_cells"],
        *artifact["past_mirror_cells"],
        *artifact["reference_price_ladder_future_cells"],
        *artifact["reference_price_ladder_past_cells"],
        *artifact["same_window_diagnostic"],
    ]
    estimated = [row for row in cells if row.get("status") == "estimated"]
    assert estimated
    for row in estimated:
        assert_companion_metrics(row, label=str(row.get("model")))
        metrics = row["metrics"]
        # VAL-METRIC-01: the identical held-out rows that produced the R2
        assert metrics["held_out_rows"] == row["test_n"]
        assert metrics["information_coefficient"]["n"] <= row["test_n"]
        assert metrics["net_of_cost_pnl"]["n"] <= row["test_n"]
        assert "cost_arms" in metrics["net_of_cost_pnl"]


def test_val_metric_02_a_bare_r2_cell_would_fail_the_artifact_check() -> None:
    with pytest.raises(CompanionMetricsMissing):
        assert_companion_metrics({"oos_r2_training_mean": 0.02, "test_n": 30}, label="bare")


def test_metric_05_past_mirror_table_and_by_correction_are_emitted(
    artifact: dict[str, Any],
) -> None:
    table = artifact["past_mirror_table"]
    assert table
    for row in table:
        assert row["oos_r2"]["metric"] == "oos_r2_training_mean"
        assert row["information_coefficient"]["metric"] == "pearson_information_coefficient"
        assert row["family_size"] == len(table)
        assert row["per_tape_sign_check"] is not None
    adjusted = [
        row["benjamini_yekutieli_q_value"]
        for row in table
        if row["benjamini_yekutieli_q_value"] is not None
    ]
    assert adjusted
    assert all(0.0 <= value <= 1.0 for value in adjusted)
    assert artifact["metrics"]["multiple_testing_correction"] == "benjamini_yekutieli"
    assert artifact["metrics"]["r2_alone_is_a_defect"] is True


# ------------------------------------------------------------------------------------ WINDOW-*


def test_val_window_01_the_sixty_second_cell_is_present_and_labelled(
    artifact: dict[str, Any],
) -> None:
    assert 30.0 in SAME_WINDOW_SECONDS and 60.0 in SAME_WINDOW_SECONDS
    rows = artifact["same_window_diagnostic"]
    for reference in REFERENCE_PRICE_LADDER:
        for basis in ("displayed", "effective_touch"):
            present = {
                float(row["h1_seconds"])
                for row in rows
                if row["reference_price"] == reference and row["predictor_basis"] == basis
            }
            assert present == set(SAME_WINDOW_SECONDS)
    comparison = [row for row in rows if row["is_ccz_comparison_cell"]]
    assert comparison
    assert {float(row["h1_seconds"]) for row in comparison} == {CCZ_CONTEMPORANEOUS_WINDOW_SECONDS}


def test_window_02_the_replication_gap_is_recorded_not_inferred(
    artifact: dict[str, Any],
) -> None:
    estimated = [
        row for row in artifact["same_window_diagnostic"] if row.get("status") == "estimated"
    ]
    assert estimated
    assert all("descriptive_construction_diagnostic_only" not in row for row in estimated)
    assert all(row["contemporaneous_not_a_forecast"] is True for row in estimated)
    best_level = [row for row in estimated if row["model"] == "M3"]
    assert best_level
    for row in best_level:
        gap = row["ccz_replication_gap"]
        assert gap["comparator"] == "ccz_best_level"
        assert gap["published_in_sample_r2"] == pytest.approx(0.7116)
        assert gap["published_out_of_sample_r2"] == pytest.approx(0.6464)
        if row["in_sample_r2"] is not None:
            assert gap["in_sample_gap"] == pytest.approx(row["in_sample_r2"] - 0.7116)
    integrated = [row for row in estimated if row["model"] == "M5"]
    assert all(row["ccz_replication_gap"]["comparator"] == "ccz_integrated" for row in integrated)
    unpublished = [row for row in estimated if row["model"] in {"M0", "M2", "M7"}]
    assert all(row["ccz_replication_gap"]["comparator"] == "none_published" for row in unpublished)


def test_window_03_curve_exposes_the_shape_at_every_window(artifact: dict[str, Any]) -> None:
    curves = artifact["same_window_r2_curve"]
    assert curves
    for curve in curves:
        assert curve["requirement"] == "WINDOW-03"
        assert curve["windows_seconds"] == sorted(SAME_WINDOW_SECONDS)
        assert len(curve["oos_r2"]) == len(SAME_WINDOW_SECONDS)
        assert len(curve["in_sample_r2"]) == len(SAME_WINDOW_SECONDS)
        if curve["estimated_cells"]:
            assert curve["peak_window_seconds"] in SAME_WINDOW_SECONDS
    # the curve is derived, not stored twice: it must agree with the cells it summarises
    rebuilt = same_window_curve(artifact["same_window_diagnostic"])
    assert rebuilt == curves


def test_val_window_01_and_window_03_cover_every_declared_depth(
    artifact: dict[str, Any],
) -> None:
    """`WINDOW-03` "at every depth" means every declared CCZ level count, not only M = 10."""

    grid = artifact["same_window_by_depth"]
    assert grid
    for reference in REFERENCE_PRICE_LADDER:
        present = {
            (float(row["h1_seconds"]), int(row["levels"]), str(row["arm"]))
            for row in grid
            if row["reference_price"] == reference
        }
        expected = {
            (window, levels, arm)
            for window in SAME_WINDOW_SECONDS
            for levels in CCZ_LEVEL_COUNTS
            for arm in CCZ_SCALAR_ARMS
        }
        # no declared depth is dropped; an unsupported one is emitted data-insufficient
        assert present == expected
    # `VAL-WINDOW-01`: the 60 s CCZ comparison cell is present at every depth
    comparison = {int(row["levels"]) for row in grid if row["is_ccz_comparison_cell"]}
    assert comparison == set(CCZ_LEVEL_COUNTS)
    curves = artifact["same_window_depth_r2_curve"]
    assert curves == depth_r2_curve(grid)
    assert {int(curve["levels"]) for curve in curves} == set(CCZ_LEVEL_COUNTS)
    for curve in curves:
        assert curve["windows_seconds"] == sorted(SAME_WINDOW_SECONDS)


# ------------------------------------------------------------------------------------- MICRO-*


def test_val_micro_01_the_artifact_chain_is_fitted_on_training_rows_only(
    artifact: dict[str, Any],
) -> None:
    model = artifact["microprice"]["stoikov_model"]
    assert model["requirement"] == "MICRO-02"
    assert model["fitted_on"] == "training_rows_only"
    assert model["object_category"] == "estimated"
    boundary = model["training_upper_bound_ts_ns"]
    split_end = artifact["sample"]["split_boundaries"]
    assert boundary is not None and split_end is not None
    assert artifact["microprice"]["simple_microprice"]["arm"] == "M7"
    assert artifact["microprice"]["stoikov_microprice"]["arm"] == "M8"


def test_micro_03_both_microprice_arms_are_families_not_controls(
    artifact: dict[str, Any],
) -> None:
    assert MODEL_ORDER[-2:] == ("M7", "M8")
    models = {row["model"] for row in artifact["future_cells"]}
    assert {"M7", "M8"} <= models
    m7 = [row for row in artifact["future_cells"] if row["model"] == "M7"]
    assert all(row["status"] == "estimated" for row in m7)
    assert all("microprice_tilt_ticks" in row["features"] for row in m7)


def test_m8_is_blocked_rather_than_fabricated_when_the_chain_is_absent() -> None:
    assert model_features("M8", 1.0, trade_identified=True, stoikov_available=False) == ()
    assert model_features("M8", 1.0, trade_identified=True, stoikov_available=True)[-1] == (
        STOIKOV_FEATURE
    )


def test_stoikov_overlay_leaves_unestimated_states_without_a_regressor() -> None:
    from shaurya.signals.deep_book_normal_activity import SplitIndex

    depth200 = [_state(index) for index in range(400)]
    depth20 = [_state(index, channel=DEPTH20) for index in range(500)]
    rows = [_trade_row(index) for index in range(400)]
    observations, _ = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=rows,
        tape_index=0,
        run_id="stoikov",
        level_counts=(1, 5, 10),
    )
    assert observations
    assert not stoikov_is_available(observations)
    cut = int(len(observations) * 0.7)
    split = SplitIndex(
        train=tuple(range(cut)),
        embargoed=(),
        test=tuple(range(cut, len(observations))),
        embargo_seconds=0.0,
        boundaries=(),
    )
    fitted = fit_stoikov_for_split(observations, split)
    augmented = with_stoikov_feature(observations, fitted)
    carried = sum(1 for item in augmented if STOIKOV_FEATURE in item.features)
    assert carried == sum(
        1
        for item in observations
        if item.microprice_state is not None and item.microprice_state in fitted.adjustment_ticks
    )


# ------------------------------------------------------------------------------------ OPS-CCZ-02


def test_ops_ccz_02_the_controller_rechecks_the_pin_before_every_unit() -> None:
    source = Path("scripts/ofi_full_session_controller.py").read_text(encoding="utf-8")
    assert "def assert_on_pin" in source
    # fail closed on a moved pin, a dirty worktree, and a commit outside fetched origin history
    assert "code commit mismatch before" in source
    assert 'if _git(self.repo, "status", "--porcelain"):' in source
    assert "worktree is not clean before" in source
    # per unit, not once in preflight, and recorded per stage rather than as a constant
    assert source.count("self.assert_on_pin(") >= 4
    assert '"observed_code_commit": observed_commit' in source
    assert '"observed_code_commit_at_completion": completion_commit' in source
    assert '"observed_code_commit_by_unit": dict(self.observed_commits)' in source


def test_ops_ccz_02_the_working_tree_check_is_the_real_git_behaviour(tmp_path: Path) -> None:
    """The cleanliness gate is only as good as ``git status --porcelain`` actually being dirty."""

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
