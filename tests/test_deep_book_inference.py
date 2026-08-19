from __future__ import annotations

import json
import stat
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from shaurya.signals.deep_book_inference import (
    REGISTERED_FAMILY_SIZE,
    DirectionalPromotionRequest,
    FamilyManifest,
    PowerArtifact,
    PowerCell,
    PowerCellStatus,
    RegimeSupport,
    SessionRecord,
    Sig19TrialRow,
    TrialStatus,
    calculate_outcome_independent_power,
    canonical_family_manifest,
    guard_directional_promotion,
    hac_newey_west_mean_difference,
    romano_wolf_stepdown,
    stationary_session_block_bootstrap,
    validate_sig19_trial_rows,
    write_sig19_jsonl_once,
)


def test_canonical_manifest_is_exactly_the_registered_384_cell_product() -> None:
    manifest = canonical_family_manifest()

    assert manifest.family_size == REGISTERED_FAMILY_SIZE == 384
    assert len(set(manifest.cell_ids)) == 384
    assert {cell.atomic_type for cell in manifest.cells} == set(type(manifest.cells[0].atomic_type))
    assert {cell.side for cell in manifest.cells} == {"bid", "ask"}
    assert {cell.distance_band for cell in manifest.cells} == {"20_50", "gt_50"}
    assert {cell.threshold for cell in manifest.cells} == {0.995, 0.999}
    assert {cell.gap_seconds for cell in manifest.cells} == {0.5, 1.0}
    assert {cell.horizon_seconds for cell in manifest.cells} == {1, 5, 10}


def test_manifest_rejects_missing_extra_and_duplicate_cells() -> None:
    cells = canonical_family_manifest().cells
    with pytest.raises(ValueError, match="canonical 384"):
        FamilyManifest(cells[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        FamilyManifest(cells[:-1] + (cells[0],))
    extra = replace(cells[-1], threshold=0.9)
    with pytest.raises(ValueError, match="extra=1"):
        FamilyManifest(cells[:-1] + (extra,))


def power_cell(
    cell_id: str,
    *,
    family_size: int = 384,
    mean_mde: float | None = 0.25,
    probability_mde: float | None = 0.05,
) -> PowerCell:
    return PowerCell(
        cell_id=cell_id,
        n=200,
        n_eff=150.0,
        family_size=family_size,
        critical_value=3.5,
        unconditional_sigma_ticks=0.5,
        unconditional_move_probability=0.2,
        mean_mde_ticks=mean_mde,
        move_probability_mde=probability_mde,
    )


def test_power_cell_defers_unavailable_or_above_gate_mdes() -> None:
    unavailable = power_cell("cell", mean_mde=None)
    weak = power_cell("cell", probability_mde=0.051)
    wrong_family = power_cell("cell", family_size=383)

    assert unavailable.status is PowerCellStatus.DEFERRED
    assert "mean_mde_unavailable" in unavailable.deferral_reasons
    assert weak.status is PowerCellStatus.DEFERRED
    assert "probability_mde_above_0.05" in weak.deferral_reasons
    assert wrong_family.status is PowerCellStatus.DEFERRED
    assert power_cell("cell").status is PowerCellStatus.ELIGIBLE


def calibration_sessions() -> tuple[SessionRecord, ...]:
    start = date(2026, 8, 20)
    return tuple(SessionRecord(f"cal-{index}", start + timedelta(days=index)) for index in range(5))


def evaluation_sessions() -> tuple[SessionRecord, ...]:
    start = date(2026, 8, 25)
    return tuple(
        SessionRecord(f"eval-{index}", start + timedelta(days=index)) for index in range(20)
    )


def valid_power_artifact() -> PowerArtifact:
    manifest = canonical_family_manifest()
    evaluation = evaluation_sessions()
    return PowerArtifact(
        registration_commit="r" * 40,
        code_commit="c" * 40,
        calibration_start=date(2026, 8, 20),
        calibration_end=date(2026, 8, 24),
        sample_start=date(2026, 8, 25),
        sample_end=date(2026, 9, 21),
        calibration_sessions=calibration_sessions(),
        evaluation_sessions=evaluation,
        regime_support=(
            RegimeSupport(
                "R1",
                tuple(session.session_id for session in evaluation[:5]),
                100.0,
                True,
            ),
        ),
        cells=tuple(power_cell(cell_id) for cell_id in manifest.cell_ids),
    )


def test_power_artifact_carries_pre_outcome_identity_and_complete_family() -> None:
    artifact = valid_power_artifact()

    assert artifact.outcome_joined is False
    assert len(artifact.cells) == 384
    assert all(cell.outcome_joined is False for cell in artifact.cells)


def test_power_artifact_rejects_incomplete_cell_family() -> None:
    manifest = canonical_family_manifest()
    with pytest.raises(ValueError, match="power artifact is incomplete"):
        PowerArtifact(
            registration_commit="r",
            code_commit="c",
            calibration_start=date(2026, 8, 20),
            calibration_end=date(2026, 8, 24),
            sample_start=date(2026, 8, 25),
            sample_end=date(2026, 9, 21),
            calibration_sessions=calibration_sessions(),
            evaluation_sessions=evaluation_sessions(),
            regime_support=(
                RegimeSupport("R1", tuple(f"eval-{index}" for index in range(5)), 100.0, True),
            ),
            cells=tuple(power_cell(cell_id) for cell_id in manifest.cell_ids[:-1]),
        )


def test_power_artifact_enforces_session_counts_disjointness_and_order() -> None:
    artifact = valid_power_artifact()
    with pytest.raises(ValueError, match="at least 5"):
        replace(artifact, calibration_sessions=artifact.calibration_sessions[:-1])
    with pytest.raises(ValueError, match="at least 20"):
        replace(artifact, evaluation_sessions=artifact.evaluation_sessions[:-1])
    overlapping = (replace(artifact.evaluation_sessions[0], session_id="cal-0"),) + tuple(
        artifact.evaluation_sessions[1:]
    )
    with pytest.raises(ValueError, match="disjoint"):
        replace(artifact, evaluation_sessions=overlapping)
    reversed_sessions = tuple(reversed(artifact.evaluation_sessions))
    with pytest.raises(ValueError, match="strictly increasing"):
        replace(artifact, evaluation_sessions=reversed_sessions)
    out_of_period = (
        replace(artifact.evaluation_sessions[0], session_date=date(2026, 8, 24)),
    ) + tuple(artifact.evaluation_sessions[1:])
    with pytest.raises(ValueError, match="outside its declared period"):
        replace(artifact, evaluation_sessions=out_of_period)


def test_power_artifact_enforces_regime_stability_support() -> None:
    artifact = valid_power_artifact()
    too_few_sessions = replace(
        artifact.regime_support[0],
        evaluation_session_ids=artifact.regime_support[0].evaluation_session_ids[:4],
    )
    with pytest.raises(ValueError, match=">=5 evaluation sessions"):
        replace(artifact, regime_support=(too_few_sessions,))
    low_n_eff = replace(artifact.regime_support[0], n_eff=99.9)
    with pytest.raises(ValueError, match="N_eff>=100"):
        replace(artifact, regime_support=(low_n_eff,))
    unknown_session = replace(
        artifact.regime_support[0],
        evaluation_session_ids=tuple(f"not-evaluation-{index}" for index in range(5)),
    )
    with pytest.raises(ValueError, match="non-evaluation session"):
        replace(artifact, regime_support=(unknown_session,))


def test_unconditional_calibration_power_formulas_and_provenance() -> None:
    cell = calculate_outcome_independent_power(
        cell_id="cell-1",
        n=150,
        n_eff=100.0,
        family_size=384,
        critical_value=2.0,
        unconditional_sigma_ticks=1.0,
        unconditional_move_probability=0.5,
    )

    assert cell.mean_mde_ticks == pytest.approx(2.0 * (2.0**0.5) / 10.0)
    assert cell.move_probability_mde == pytest.approx(2.0 * (0.5 / 100.0) ** 0.5)
    assert cell.provenance == "unconditional_calibration_only"
    assert cell.outcome_joined is False
    assert cell.status is PowerCellStatus.DEFERRED


def test_zero_effective_sample_power_is_explicitly_deferred() -> None:
    cell = calculate_outcome_independent_power(
        cell_id="cell-1",
        n=0,
        n_eff=0.0,
        family_size=384,
        critical_value=3.0,
        unconditional_sigma_ticks=1.0,
        unconditional_move_probability=0.25,
    )

    assert cell.mean_mde_ticks is None
    assert cell.move_probability_mde is None
    assert cell.status is PowerCellStatus.DEFERRED


def test_hac_mean_difference_enforces_registered_overlap_lag() -> None:
    event = [2.0, 4.0, 2.0, 4.0] * 5
    control = [1.0, 2.0, 1.0, 2.0] * 5

    estimate = hac_newey_west_mean_difference(event, control, lag=11)

    assert estimate.n == 20
    assert estimate.lag == 11
    assert estimate.mean_difference == pytest.approx(1.5)
    assert estimate.standard_error > 0
    assert estimate.t_statistic is not None
    with pytest.raises(ValueError, match="at least the registered overlap"):
        hac_newey_west_mean_difference(event, control, lag=10)


def test_stationary_bootstrap_is_seeded_and_never_crosses_sessions() -> None:
    sessions = {"day-a": (1.0, 2.0, 3.0), "day-b": (100.0, 200.0)}

    first = stationary_session_block_bootstrap(
        sessions, replicates=5, mean_block_length=2.0, seed=42
    )
    second = stationary_session_block_bootstrap(
        sessions, replicates=5, mean_block_length=2.0, seed=42
    )

    assert first == second
    assert all(len(sample) == 5 for sample in first)
    assert all(set(sample[:3]) <= {1.0, 2.0, 3.0} for sample in first)
    assert all(set(sample[3:]) <= {100.0, 200.0} for sample in first)


def test_romano_wolf_null_is_one_and_strong_signal_survives_complete_family() -> None:
    manifest = canonical_family_manifest()
    null_observed = dict.fromkeys(manifest.cell_ids, 0.0)
    null_bootstrap = [dict.fromkeys(manifest.cell_ids, 0.0) for _ in range(20)]

    null_result = romano_wolf_stepdown(manifest, null_observed, null_bootstrap)

    assert all(result.adjusted_p_value == 1.0 for result in null_result)

    signal_id = manifest.cell_ids[0]
    strong_observed = dict.fromkeys(manifest.cell_ids, 0.1)
    strong_observed[signal_id] = 10.0
    bootstrap = [dict.fromkeys(manifest.cell_ids, 1.0) for _ in range(20)]

    strong_result = romano_wolf_stepdown(manifest, strong_observed, bootstrap)
    by_id = {result.cell_id: result for result in strong_result}
    ordered = sorted(strong_result, key=lambda result: result.stepdown_rank)
    adjusted = [result.adjusted_p_value for result in ordered]

    assert by_id[signal_id].adjusted_p_value == pytest.approx(1 / 21)
    assert adjusted == sorted(adjusted)


def trial_rows() -> tuple[Sig19TrialRow, ...]:
    return tuple(
        Sig19TrialRow(
            trial_id=f"SIG19-{index:03d}",
            hypothesis_id="H-SIG21",
            registration_commit="r" * 40,
            code_commit="c" * 40,
            tape_start=date(2026, 8, 25),
            tape_end=date(2026, 9, 21),
            instrument_id="NIFTY-FUT",
            contract_id="NIFTY-AUG-2026",
            cell_id=cell_id,
            family_size=384,
            n=200,
            n_eff=150.0,
            mean_mde_ticks=0.25,
            move_probability_mde=0.05,
            power_artifact_sha256="a" * 64,
            status=TrialStatus.DEFERRED,
        )
        for index, cell_id in enumerate(canonical_family_manifest().cell_ids)
    )


def test_sig19_rows_are_immutable_and_complete() -> None:
    rows = trial_rows()

    validated = validate_sig19_trial_rows(rows, canonical_family_manifest())

    assert len(validated) == 384
    with pytest.raises(FrozenInstanceError):
        rows[0].status = TrialStatus.EXECUTED  # type: ignore[misc]


def test_sig19_completeness_rejects_missing_and_identity_mismatched_rows() -> None:
    rows = trial_rows()
    with pytest.raises(ValueError, match="incomplete"):
        validate_sig19_trial_rows(rows[:-1], canonical_family_manifest())
    mismatched = rows[:-1] + (replace(rows[-1], code_commit="different"),)
    with pytest.raises(ValueError, match="one complete trial identity"):
        validate_sig19_trial_rows(mismatched, canonical_family_manifest())


def test_sig19_rejects_invalid_power_provenance_fields() -> None:
    rows = trial_rows()
    bad_hash = rows[:-1] + (replace(rows[-1], power_artifact_sha256="not-a-sha"),)
    with pytest.raises(ValueError, match="invalid or incomplete"):
        validate_sig19_trial_rows(bad_hash, canonical_family_manifest())
    bad_support = rows[:-1] + (replace(rows[-1], n_eff=201.0),)
    with pytest.raises(ValueError, match="invalid or incomplete"):
        validate_sig19_trial_rows(bad_support, canonical_family_manifest())


def test_sig19_jsonl_is_complete_mode_0600_and_create_once(tmp_path: Path) -> None:
    destination = tmp_path / "sig19.jsonl"
    rows = trial_rows()

    written = write_sig19_jsonl_once(destination, rows, canonical_family_manifest())

    assert written == destination
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    payloads = [json.loads(line) for line in destination.read_text().splitlines()]
    assert len(payloads) == 384
    assert payloads[0]["schema_version"] == "sig19_trial_v1"
    assert payloads[0]["family_size"] == 384
    assert payloads[0]["n"] == 200
    assert payloads[0]["n_eff"] == 150.0
    assert payloads[0]["mean_mde_ticks"] == 0.25
    assert payloads[0]["move_probability_mde"] == 0.05
    assert payloads[0]["power_artifact_sha256"] == "a" * 64
    with pytest.raises(FileExistsError):
        write_sig19_jsonl_once(destination, rows, canonical_family_manifest())


def test_first_stage_cannot_promote_without_later_registered_confirmation_tape() -> None:
    first_stage_only = DirectionalPromotionRequest(
        first_stage_hypothesis_id="H-SIG21",
        confirmation_hypothesis_id=None,
        first_stage_tape_end=date(2026, 9, 21),
        confirmation_tape_start=None,
        confirmation_registered_before_tape=False,
    )
    same_tape = replace(
        first_stage_only,
        confirmation_hypothesis_id="H-SIG21C-BID-01",
        confirmation_tape_start=date(2026, 9, 21),
        confirmation_registered_before_tape=True,
    )
    later = replace(same_tape, confirmation_tape_start=date(2026, 9, 22))

    assert not guard_directional_promotion(first_stage_only).allowed
    assert guard_directional_promotion(same_tape).reason == "confirmation_requires_subsequent_tape"
    assert guard_directional_promotion(later).allowed
