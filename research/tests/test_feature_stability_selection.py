from __future__ import annotations

import json

from shaurya.signals.feature_selection import (
    ClusterFoldStabilityResult,
    ElasticNetStabilityConfig,
    ImportanceClusterDefinition,
    PairedLossBlock,
    aggregate_cluster_stability_selection,
    elastic_net_cluster_stability_artifact_from_json,
    elastic_net_cluster_stability_artifact_to_json,
    fit_cluster_elastic_net_stability,
    stability_selection_artifact_from_json,
    stability_selection_artifact_to_json,
)

CLUSTER = ImportanceClusterDefinition(
    "cluster__signal",
    ("signal_a", "signal_b"),
    ("signal_a", "signal_b"),
    "ofi",
)


def _fold(
    index: int,
    *,
    sessions: tuple[str, ...] | None = None,
    delta: float = 0.05,
    direction: str = "positive",
    selected: bool = True,
    dominant: bool = False,
    mirror: float | None = 0.01,
) -> ClusterFoldStabilityResult:
    eligible = sessions or tuple(f"day-{4 * index + offset:02d}" for offset in range(4))
    omitted = tuple(
        (session, 0.0 if dominant and offset == 0 else delta * 0.8)
        for offset, session in enumerate(eligible)
    )
    return ClusterFoldStabilityResult(
        fold_id=f"fold-{index}",
        model_id="elastic_net_alpha_0p01_l1_0p5",
        cluster=CLUSTER,
        eligible_session_ids=eligible,
        selected=selected,
        delta_oos_r_squared=delta,
        direction=direction,  # type: ignore[arg-type]
        volatility_regimes=("low", "high") if index % 2 else ("medium",),
        spread_regimes=("tight", "wide"),
        time_phases=("open", "midday", "close"),
        leave_one_session_out_delta_oos_r_squared=omitted,
        past_mirror_delta_oos_r_squared=mirror,
        cost_latency_adjusted_value=0.02,
        support_training_rows=100 * (index + 1),
        support_evaluation_rows=40,
        paired_loss_blocks=(
            PairedLossBlock(0, "a", "b", 2, 1.0, 1.2, 0.1),
        ),
    )


def test_stable_cluster_passes_frozen_gates_with_regime_and_loss_diagnostics() -> None:
    artifact = aggregate_cluster_stability_selection(tuple(_fold(index) for index in range(5)))
    selection = artifact.selections[0]
    assert selection.status == "promoted"
    assert selection.reason_codes == ()
    assert selection.distinct_eligible_session_count == 20
    assert selection.selection_frequency == 1.0
    assert selection.fraction_positive_folds == 1.0
    assert selection.direction_consistency == 1.0
    assert selection.volatility_regime_coverage == ("high", "low", "medium")
    assert selection.aggregate_comparator_minus_full_mean_squared_loss == 0.1
    assert len(selection.learning_curve) == 5


def test_one_day_is_always_exploratory_insufficient_sessions() -> None:
    folds = tuple(_fold(index, sessions=("only-day",)) for index in range(5))
    selection = aggregate_cluster_stability_selection(folds).selections[0]
    assert selection.status == "exploratory_insufficient_sessions"
    assert "insufficient_distinct_sessions" in selection.reason_codes


def test_unstable_direction_fails_even_when_fold_deltas_are_positive() -> None:
    folds = tuple(
        _fold(index, direction="positive" if index < 3 else "negative")
        for index in range(5)
    )
    selection = aggregate_cluster_stability_selection(folds).selections[0]
    assert selection.status == "rejected"
    assert selection.direction_consistency == 0.6
    assert "direction_consistency_below_gate" in selection.reason_codes


def test_single_session_dominance_fails_promotion() -> None:
    folds = tuple(_fold(index, dominant=index == 0) for index in range(5))
    selection = aggregate_cluster_stability_selection(folds).selections[0]
    assert selection.status == "rejected"
    assert selection.one_session_dominance
    assert "one_session_dominance" in selection.reason_codes


def test_stronger_past_mirror_fails_promotion() -> None:
    folds = tuple(_fold(index, mirror=0.08) for index in range(5))
    selection = aggregate_cluster_stability_selection(folds).selections[0]
    assert selection.status == "rejected"
    assert "past_mirror_stronger" in selection.reason_codes


def test_correlated_elastic_net_members_are_selected_and_reported_jointly() -> None:
    rows = tuple(
        {
            "signal_a": float(index - 40),
            "signal_b": float(index - 40),
            "noise": float((index * 17) % 11 - 5),
        }
        for index in range(80)
    )
    targets = tuple(0.4 * row["signal_a"] for row in rows)
    clusters = (
        CLUSTER,
        ImportanceClusterDefinition("cluster__noise", ("noise",), ("noise",), "regime"),
    )
    config = ElasticNetStabilityConfig(
        resample_count=12,
        contiguous_block_size=8,
        sampled_block_fraction=0.7,
        base_seed=123,
    )
    artifact = fit_cluster_elastic_net_stability(
        rows,
        targets,
        cluster_definitions=clusters,
        config=config,
    )
    signal = next(
        item
        for item in artifact.cluster_selection_frequencies
        if item.cluster_id == "cluster__signal"
    )
    assert signal.selection_frequency == 1.0
    assert signal.members == ("signal_a", "signal_b")
    assert all(
        "cluster__signal" in resample.selected_cluster_ids for resample in artifact.resamples
    )
    encoded = elastic_net_cluster_stability_artifact_to_json(artifact)
    assert "coefficients" not in json.loads(encoded)


def test_stability_artifacts_are_deterministic_and_read_back_exactly() -> None:
    folds = tuple(_fold(index) for index in range(5))
    first = aggregate_cluster_stability_selection(folds)
    second = aggregate_cluster_stability_selection(folds)
    assert first == second
    encoded = stability_selection_artifact_to_json(first)
    assert stability_selection_artifact_from_json(encoded) == first

    rows = tuple({"signal_a": float(i), "signal_b": float(i)} for i in range(40))
    targets = tuple(float(i) for i in range(40))
    config = ElasticNetStabilityConfig(
        resample_count=5,
        contiguous_block_size=5,
        sampled_block_fraction=0.75,
        base_seed=9,
    )
    fit_one = fit_cluster_elastic_net_stability(
        rows, targets, cluster_definitions=(CLUSTER,), config=config
    )
    fit_two = fit_cluster_elastic_net_stability(
        rows, targets, cluster_definitions=(CLUSTER,), config=config
    )
    assert fit_one == fit_two
    encoded_fit = elastic_net_cluster_stability_artifact_to_json(fit_one)
    assert elastic_net_cluster_stability_artifact_from_json(encoded_fit) == fit_one
