from __future__ import annotations

import math
from dataclasses import asdict

import pytest

from shaurya.research.contracts import canonical_sha256
from shaurya.research.multiplicity import (
    CandidateBootstrapArtifact,
    adjust_hierarchical,
    block_bootstrap_confidence_interval,
    candidate_bootstrap_from_mapping,
)
from shaurya.research.nulls import (
    MinerRefitResult,
    complete_miner_empirical_null,
    negative_control_warning,
)
from shaurya.research.surfaces import (
    SurfaceCell,
    build_complete_surface,
    parameter_movement,
    surface_robustness,
)


def _cell(window: int, horizon: int, score: float) -> SurfaceCell:
    return SurfaceCell(
        (("horizon", horizon), ("window", window)),
        f"w{window}-h{horizon}",
        score,
        1 if score > 0 else -1 if score < 0 else 0,
        100,
    )


def test_complete_surface_penalizes_an_isolated_parameter_spike() -> None:
    coherent = build_complete_surface(
        mechanism="ORDER_FLOW_IMPACT",
        axes=("window", "horizon"),
        axis_values={"window": (1, 2, 3), "horizon": (1, 2, 3)},
        cells=[
            _cell(w, h, 1.0 - 0.1 * (abs(w - 2) + abs(h - 2))) for w in (1, 2, 3) for h in (1, 2, 3)
        ],
    )
    isolated = build_complete_surface(
        mechanism="ORDER_FLOW_IMPACT",
        axes=("window", "horizon"),
        axis_values={"window": (1, 2, 3), "horizon": (1, 2, 3)},
        cells=[
            _cell(w, h, 1.0 if (w, h) == (2, 2) else 0.05) for w in (1, 2, 3) for h in (1, 2, 3)
        ],
    )
    coherent_diagnostic = surface_robustness(coherent)
    isolated_diagnostic = surface_robustness(isolated)
    assert not coherent_diagnostic.isolated_spike
    assert isolated_diagnostic.isolated_spike
    assert isolated_diagnostic.robustness_score < coherent_diagnostic.robustness_score


def test_horizon_drift_with_overlapping_regions_is_parameter_movement() -> None:
    first = build_complete_surface(
        mechanism="ORDER_FLOW_IMPACT",
        axes=("window", "horizon"),
        axis_values={"window": (20, 30), "horizon": (5, 10)},
        cells=[_cell(20, 5, 1.0), _cell(20, 10, 0.9), _cell(30, 5, 0.85), _cell(30, 10, 0.88)],
    )
    second = build_complete_surface(
        mechanism="ORDER_FLOW_IMPACT",
        axes=("window", "horizon"),
        axis_values={"window": (20, 30), "horizon": (5, 10)},
        cells=[_cell(20, 5, 0.86), _cell(20, 10, 0.9), _cell(30, 5, 0.91), _cell(30, 10, 1.0)],
    )
    movement = parameter_movement(surface_robustness(first), surface_robustness(second))
    assert movement["classification"] == "parameter_movement_within_uncertainty"


def test_empirical_null_reruns_complete_miner_not_only_the_winner() -> None:
    targets = [math.sin(index / 7) for index in range(120)]
    features = tuple(
        {
            "a": math.cos(index / 9),
            "b": math.sin(index / 11),
            "c": float(index % 5),
        }
        for index in range(120)
    )

    class Procedure:
        calls = 0

        def refit_select_score(self, feature_rows, values, *, replicate_id):
            self.calls += 1
            scores = tuple(
                (
                    name,
                    sum(float(row[name]) * y for row, y in zip(feature_rows, values, strict=True))
                    / len(values),
                )
                for name in ("a", "b", "c")
            )
            target_hash = canonical_sha256(values)
            return MinerRefitResult(
                scores,
                canonical_sha256(feature_rows),
                target_hash,
                canonical_sha256(("preprocess", target_hash)),
                canonical_sha256(("select", target_hash)),
                tuple((name, canonical_sha256((name, target_hash))) for name in ("a", "b", "c")),
            )

    procedure = Procedure()

    result = complete_miner_empirical_null(
        features, targets, procedure=procedure, replicates=19, seed=7, block_size=10
    )
    assert procedure.calls == 20
    assert result.candidate_ids == ("a", "b", "c")
    assert result.complete_miner_rerun
    assert 0 < result.adjusted_p_value <= 1


def test_hierarchical_multiplicity_records_full_declared_family() -> None:
    adjusted = adjust_hierarchical(
        {"a": 0.001, "b": 0.02, "c": 0.04},
        {"a": "ofi", "b": "ofi", "c": "book"},
    )
    assert all(item.declared_experiment_size == 3 for item in adjusted)
    assert next(item for item in adjusted if item.hypothesis_id == "a").declared_family_size == 2
    assert all(item.experiment_adjusted_p_value >= item.raw_p_value for item in adjusted)


def test_session_block_bootstrap_is_deterministic_and_never_splices_sessions() -> None:
    first = block_bootstrap_confidence_interval(
        {"day-1": (1.0, 2.0, 3.0), "day-2": (4.0, 5.0, 6.0)},
        replicates=19,
        mean_block_length=2,
        seed=7,
    )
    second = block_bootstrap_confidence_interval(
        {"day-1": (1.0, 2.0, 3.0), "day-2": (4.0, 5.0, 6.0)},
        replicates=19,
        mean_block_length=2,
        seed=7,
    )
    assert first == second
    assert first.lower <= first.estimate <= first.upper


def test_candidate_block_bootstrap_hash_rejects_a_copied_tampered_interval() -> None:
    artifact = CandidateBootstrapArtifact(
        "alpha-control",
        (("2026-08-26", (0.1, 0.2, 0.3)),),
        0.2,
        0.1,
        0.3,
        0.05,
        19,
        2.0,
        7,
        True,
    ).with_hash()
    raw = asdict(artifact)
    raw["lower"] = -0.5
    with pytest.raises(ValueError, match="bootstrap artifact hash"):
        candidate_bootstrap_from_mapping(raw)


def test_repeated_significant_negative_controls_emit_methodology_warning() -> None:
    assert negative_control_warning((0.01, 0.02, 0.01, 0.03, 0.01)) is True
    assert negative_control_warning((0.2, 0.3, 0.4, 0.5, 0.6)) is False
