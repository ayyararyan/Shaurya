"""Acceptance tests `VAL-CCZ-01` to `VAL-CCZ-08` for the CCZ OFI migration (`D37`)."""

from __future__ import annotations

import ast
from math import isclose
from pathlib import Path

import numpy as np
import pytest

from shaurya.data.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals.ccz_ofi import (
    DECLARED_LEVEL_COUNTS,
    ID_CCZ_01_LIMITATION,
    MINIMUM_DEPTH_DENOMINATOR,
    PRIMARY_LEVEL_COUNT,
    CczFeatureSchema,
    CczFeatureVector,
    CczFlowSeries,
    aggregate_window,
    ccz_level_flow,
    ccz_metadata,
    fit_integrated_weights,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def _state(
    stamp: int,
    bids: tuple[tuple[float, int, int], ...],
    asks: tuple[tuple[float, int, int], ...],
    *,
    channel: str = DEPTH200,
    epoch: int = 0,
) -> BookState:
    return BookState(
        channel=channel,
        receive_ts_ns=stamp,
        receive_sequence=stamp,
        connection_epoch=epoch,
        bids=bids,
        asks=asks,
        rows_in_burst=1,
        quality_flags=(),
    )


def test_val_ccz_01_per_level_order_flow_matches_equation_two_by_hand() -> None:
    """`VAL-CCZ-01`: Eq. (2) base terms on a hand-built two-snapshot fixture."""

    previous = _state(
        1,
        ((100.0, 10, 1), (99.0, 20, 1), (98.0, 30, 1), (97.0, 40, 1)),
        ((101.0, 11, 1), (102.0, 21, 1), (103.0, 31, 1), (104.0, 41, 1)),
    )
    current = _state(
        2,
        # level 1 bid unchanged price with +5; level 2 bid unchanged price with -2;
        # level 3 bid price improves to 98.5 carrying 7; level 4 bid price worsens to 96.5.
        ((100.0, 15, 1), (99.0, 18, 1), (98.5, 7, 1), (96.5, 4, 1)),
        # level 1 ask unchanged price with -3; level 2 ask unchanged price with +4;
        # level 3 ask price falls to 102.5 carrying 9; level 4 ask price rises to 105.0.
        ((101.0, 8, 1), (102.0, 25, 1), (102.5, 9, 1), (105.0, 6, 1)),
    )

    flow = ccz_level_flow(previous, current, levels=4)

    assert flow.invalid_reason is None
    assert flow.levels_covered == 4
    # OF^{m,b}: same price -> q_n - q_{n-1}; higher price -> q_n; lower price -> -q_n.
    assert flow.bid_flow == (5.0, -2.0, 7.0, -4.0)
    # OF^{m,a}: higher price -> -q_n; same price -> q_n - q_{n-1}; lower price -> q_n.
    assert flow.ask_flow == (-3.0, 4.0, 9.0, -6.0)
    # Eq. (2) summand is OF^{m,b} - OF^{m,a}, level by level, never accumulated.
    assert flow.order_flow == (8.0, -6.0, -2.0, 2.0)
    # q^{m,b}_n + q^{m,a}_n at the current state, used only by the Eq. (3) denominator.
    assert flow.depth == (23.0, 43.0, 16.0, 10.0)


def _declared_identifiers(path: Path) -> set[str]:
    """Every identifier a module actually binds or references, ignoring prose."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                found.add(node.asname)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
    return found


def test_val_ccz_02_no_code_path_sums_ofi_across_levels() -> None:
    """`VAL-CCZ-02`: the cumulative-across-levels construction is gone from the source tree.

    Prose that names the retired object is fine and in fact required by the migration record;
    what must not survive is any executable reference to it.
    """

    banned = {"price_keyed_ofi_transition", "cumulative_by_depth", "PriceKeyedOFITransition"}
    offending = sorted(
        f"{path}:{name}"
        for path in SOURCE_ROOT.rglob("*.py")
        for name in banned & _declared_identifiers(path)
    )
    assert offending == []


def test_val_ccz_02_level_ofi_is_that_level_only_not_a_running_total() -> None:
    """`VAL-CCZ-02`: an offsetting deeper level is not cancelled into a cumulative total."""

    previous = _state(1, ((100.0, 10, 1), (99.0, 20, 1)), ((101.0, 10, 1), (102.0, 20, 1)))
    current = _state(2, ((100.0, 18, 1), (99.0, 12, 1)), ((101.0, 10, 1), (102.0, 20, 1)))

    flow = ccz_level_flow(previous, current, levels=2)

    assert flow.order_flow[0] == 8.0
    assert flow.order_flow[1] == -8.0
    # A cumulative construction would report 0.0 at level 2; CCZ reports the level's own flow.
    assert flow.order_flow[1] != flow.order_flow[0] + flow.order_flow[1]


def test_val_ccz_03_one_common_denominator_divides_every_level() -> None:
    """`VAL-CCZ-03`: scaling any single level's raw OFI by ``Q^{M,h}`` reproduces ``ofi^m``."""

    previous = _state(
        1,
        ((100.0, 10, 1), (99.0, 20, 1), (98.0, 30, 1)),
        ((101.0, 11, 1), (102.0, 21, 1), (103.0, 31, 1)),
    )
    current = _state(
        2,
        ((100.0, 15, 1), (99.0, 18, 1), (98.0, 30, 1)),
        ((101.0, 8, 1), (102.0, 25, 1), (103.0, 31, 1)),
    )
    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(1, 3), invalid_reasons=[None]
    )

    window = series.window(0, 1, levels=3, window_seconds=1.0)

    assert window is not None
    # Q^{3,h} = (1/3) * sum_m (q^mb + q^ma) / (2 * dN) with dN = 1.
    expected = (23.0 + 43.0 + 61.0) / (2.0 * 3.0 * 1.0)
    assert isclose(window.denominator, expected)
    assert window.events == 1
    for level in range(3):
        assert isclose(window.normalised[level], window.raw[level] / window.denominator)
    # The denominator is the same scalar for every level: ratios of levels survive the scaling.
    assert isclose(window.normalised[0] / window.normalised[1], window.raw[0] / window.raw[1])
    # A per-level denominator would not be one scalar, so a shallower M changes it.
    shallow = series.window(0, 1, levels=1, window_seconds=1.0)
    assert shallow is not None
    assert not isclose(shallow.denominator, window.denominator)


def test_val_ccz_03_denominator_floor_is_recorded_not_absorbed() -> None:
    previous = _state(1, ((100.0, 0, 1),), ((101.0, 0, 1),))
    current = _state(2, ((100.0, 1, 1),), ((101.0, 0, 1),))
    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(1,), invalid_reasons=[None]
    )

    window = series.window(0, 1, levels=1, window_seconds=1.0)

    assert window is not None
    assert window.denominator == MINIMUM_DEPTH_DENOMINATOR
    assert window.denominator_floored is True
    assert window.unfloored_denominator < MINIMUM_DEPTH_DENOMINATOR


def _training_matrix(rows: int = 200, levels: int = 4) -> np.ndarray:
    generator = np.random.default_rng(11)
    factor = generator.normal(size=(rows, 1))
    loadings = np.asarray([[1.0, 0.8, 0.6, 0.4]])
    return factor @ loadings + 0.05 * generator.normal(size=(rows, levels))


def test_val_ccz_04_first_component_is_fitted_on_training_rows_only() -> None:
    """`VAL-CCZ-04`: test rows cannot influence ``w_1``."""

    train = _training_matrix()
    fitted = fit_integrated_weights(train)

    # Any test block, however extreme, is outside the fit and must not move the component.
    test_block = np.full((500, train.shape[1]), 1_000.0)
    refitted_on_train_only = fit_integrated_weights(train)
    assert fitted.weights == refitted_on_train_only.weights

    contaminated = fit_integrated_weights(np.vstack([train, test_block]))
    assert contaminated.weights != fitted.weights, "leakage guard is not sensitive"

    # Applying the training component out of sample is a projection, never a refit.
    projected = fitted.project(test_block)
    assert projected.shape == (500,)
    assert fitted.weights == refitted_on_train_only.weights


def test_val_ccz_05_l1_normalisation_makes_the_weights_sum_to_one() -> None:
    """`VAL-CCZ-05`: ``w_1 / ||w_1||_1`` has unit L1 norm, and sums to one when signs agree."""

    fitted = fit_integrated_weights(_training_matrix())

    assert isclose(sum(abs(value) for value in fitted.normalised_weights), 1.0)
    assert all(value > 0 for value in fitted.normalised_weights)
    assert isclose(sum(fitted.normalised_weights), 1.0)
    assert fitted.applied_sign in {-1.0, 1.0}
    assert fitted.weights[fitted.dominant_level - 1] > 0.0
    assert 0.0 <= fitted.explained_variance_ratio <= 1.0


def test_val_ccz_05_sign_fix_is_applied_and_recorded() -> None:
    flipped = fit_integrated_weights(-_training_matrix())

    assert flipped.weights[flipped.dominant_level - 1] > 0.0
    assert isclose(sum(abs(value) for value in flipped.normalised_weights), 1.0)


def test_val_ccz_06_pure_bid_side_size_increase_is_positive_at_that_level() -> None:
    """`VAL-CCZ-06`: sign convention, level by level."""

    previous = _state(
        1,
        ((100.0, 10, 1), (99.0, 20, 1), (98.0, 30, 1)),
        ((101.0, 10, 1), (102.0, 20, 1), (103.0, 30, 1)),
    )
    current = _state(
        2,
        ((100.0, 10, 1), (99.0, 33, 1), (98.0, 30, 1)),
        ((101.0, 10, 1), (102.0, 20, 1), (103.0, 30, 1)),
    )

    flow = ccz_level_flow(previous, current, levels=3)

    assert flow.order_flow[1] > 0.0
    assert flow.order_flow[0] == 0.0
    assert flow.order_flow[2] == 0.0

    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(3,), invalid_reasons=[None]
    )
    window = series.window(0, 1, levels=3, window_seconds=1.0)
    assert window is not None
    assert window.normalised[1] > 0.0


def test_val_ccz_06_ask_side_retreat_is_also_buy_pressure() -> None:
    previous = _state(1, ((100.0, 10, 1),), ((101.0, 12, 1),))
    current = _state(2, ((100.0, 10, 1),), ((101.5, 12, 1),))

    flow = ccz_level_flow(previous, current, levels=1)

    assert flow.ask_flow[0] == -12.0
    assert flow.order_flow[0] == 12.0


def test_val_ccz_08_metadata_carries_estimator_levels_evr_and_the_limitation() -> None:
    """`VAL-CCZ-08`: the estimator block every artifact must carry."""

    metadata = ccz_metadata(explained_variance_ratio={"w10__m10": 0.62})

    assert metadata["estimator"] == "CCZ"
    assert metadata["primary_level_count"] == PRIMARY_LEVEL_COUNT
    assert metadata["declared_level_counts"] == list(DECLARED_LEVEL_COUNTS)
    assert metadata["explained_variance_ratio"] == {"w10__m10": 0.62}
    assert metadata["limitation"] == ID_CCZ_01_LIMITATION
    assert "ID-CCZ-01" in metadata["limitation"]
    assert metadata["cumulates_across_levels"] is False
    assert metadata["per_band_denominator"] is False


def test_window_refuses_a_span_containing_a_refused_transition() -> None:
    states = [_state(index, ((100.0, 10 + index, 1),), ((101.0, 10, 1),)) for index in range(1, 4)]
    series = CczFlowSeries.from_states(
        states, level_counts=(1,), invalid_reasons=[None, "connection_epoch_boundary"]
    )

    assert series.window(0, 2, levels=1, window_seconds=1.0) is None
    assert series.window(0, 1, levels=1, window_seconds=1.0) is not None


def test_window_refuses_a_level_count_the_book_does_not_support() -> None:
    previous = _state(1, ((100.0, 10, 1), (99.0, 5, 1)), ((101.0, 10, 1), (102.0, 5, 1)))
    current = _state(2, ((100.0, 12, 1), (99.0, 5, 1)), ((101.0, 10, 1), (102.0, 5, 1)))
    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(1, 5), invalid_reasons=[None]
    )

    assert series.window(0, 1, levels=5, window_seconds=1.0) is None
    assert series.window(0, 1, levels=1, window_seconds=1.0) is not None


def test_undeclared_level_count_is_refused_rather_than_silently_approximated() -> None:
    previous = _state(1, ((100.0, 10, 1),), ((101.0, 10, 1),))
    current = _state(2, ((100.0, 12, 1),), ((101.0, 10, 1),))
    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(1,), invalid_reasons=[None]
    )

    with pytest.raises(ValueError, match="not declared"):
        series.window(0, 1, levels=7, window_seconds=1.0)


def test_aggregation_arms_cover_the_declared_set() -> None:
    previous = _state(1, ((100.0, 10, 1), (99.0, 20, 1)), ((101.0, 11, 1), (102.0, 21, 1)))
    current = _state(2, ((100.0, 15, 1), (99.0, 18, 1)), ((101.0, 8, 1), (102.0, 25, 1)))
    series = CczFlowSeries.from_states(
        [previous, current], level_counts=(2,), invalid_reasons=[None]
    )
    window = series.window(0, 1, levels=2, window_seconds=1.0)
    assert window is not None
    weights = fit_integrated_weights(np.asarray([[1.0, 0.5], [0.9, 0.4], [1.2, 0.7]]))

    arms = aggregate_window(window, weights)

    assert isclose(arms["simple_average"], sum(window.normalised) / 2.0)
    assert isclose(arms["best_level"], window.normalised[0])
    assert isclose(
        arms["integrated"],
        sum(
            weight * value
            for weight, value in zip(weights.normalised_weights, window.normalised, strict=True)
        ),
    )


def test_feature_vector_behaves_as_a_mapping_and_keeps_absence_explicit() -> None:
    schema = CczFeatureSchema(("a", "b", "c"))

    vector = CczFeatureVector.build(schema, {"a": 1.5, "c": -2.0})

    assert vector["a"] == 1.5
    assert vector["c"] == -2.0
    assert "b" not in vector
    assert set(vector) == {"a", "c"}
    assert len(vector) == 2
    with pytest.raises(KeyError):
        vector["b"]
    with pytest.raises(KeyError):
        CczFeatureVector.build(schema, {"undeclared": 1.0})


def test_no_module_declares_a_per_band_depth_denominator() -> None:
    """`VAL-CCZ-02` companion: the retired per-band normalisation names are gone."""

    banned = {"adjusted_band_feature", "pk_band_feature", "_band_depths"}
    offending = sorted(
        f"{path}:{name}"
        for path in SOURCE_ROOT.rglob("*.py")
        for name in banned & _declared_identifiers(path)
    )
    assert offending == []


def test_ccz_module_has_no_import_time_dependency_on_the_retired_scan() -> None:
    module = ast.parse((SOURCE_ROOT / "shaurya/signals/ccz_ofi.py").read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "shaurya.signals.deep_book_ofi" not in imported
