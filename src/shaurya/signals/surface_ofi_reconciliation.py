"""Exact-sample reconciliation of displayed eSSVI with the prior DAT-20 OFI horse race."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from shaurya.signals.deep_book_normal_activity import chronological_embargoed_split
from shaurya.signals.ofi_horserace import (
    HorseRaceObservation,
    _fit_score,
    _inference,
    _per_tape_scores,
    as_normal_observation,
    cks_pressure_feature,
    model_features,
)
from shaurya.signals.surface_futures_predictive import (
    MAX_ASOF_AGE_SECONDS,
    SurfacePredictiveObservation,
)

RECONCILIATION_ID = "X-SURFACE-FUT5-RECONCILE-20260819-07"
CORRECTION_DOCUMENT = "docs/SURFACE-FUTURES-PREDICTIVE-CORRECTION-1-2026-08-19.md"
HORIZON_SECONDS = 5.0
M3B_WINDOW_SECONDS = 1.0
M4_WINDOW_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class SurfaceJoinRecord:
    tape_index: int
    run_id: str
    anchor_ts_ns: int
    connection_epoch: int
    surface_sequence: int
    surface_ts_ns: int
    carry_age_seconds: float
    y_future_ticks: float | None


def surface_observation_from_dict(raw: Mapping[str, Any]) -> SurfacePredictiveObservation:
    """Load the hash-pinned parent observation without weakening its required schema."""

    return SurfacePredictiveObservation(
        sequence=int(raw["sequence"]),
        receive_ts_ns=int(raw["receive_ts_ns"]),
        connection_epoch=int(raw["connection_epoch"]),
        economic={str(key): float(value) for key, value in raw["economic"].items()},
        quality_numeric={str(key): value for key, value in raw["quality_numeric"].items()},
        quality_categorical={
            str(key): str(value) for key, value in raw["quality_categorical"].items()
        },
        lob={str(key): float(value) for key, value in raw["lob"].items()},
        ofi={str(key): float(value) for key, value in raw["ofi"].items()},
        y_future_ticks=float(raw["y_future_ticks"]),
        y_past_ticks=float(raw["y_past_ticks"]),
        y_same_ticks=float(raw["y_same_ticks"]),
        target_start_age_seconds=float(raw["target_start_age_seconds"]),
        target_end_age_seconds=float(raw["target_end_age_seconds"]),
        surface_age_seconds=float(raw["surface_age_seconds"]),
        smoothing_status=str(raw["smoothing_status"]),
    )


def join_displayed_surface(
    horse_observations: Sequence[HorseRaceObservation],
    surface_observations: Sequence[SurfacePredictiveObservation],
    *,
    max_carry_seconds: float = MAX_ASOF_AGE_SECONDS,
) -> tuple[list[HorseRaceObservation], list[SurfaceJoinRecord], dict[str, int]]:
    """Past-only as-of join; a future, stale or cross-epoch surface is refused."""

    ordered = sorted(surface_observations, key=lambda item: item.receive_ts_ns)
    stamps = [item.receive_ts_ns for item in ordered]
    joined: list[HorseRaceObservation] = []
    records: list[SurfaceJoinRecord] = []
    failures = {"no_prior_surface": 0, "cross_epoch_surface": 0, "stale_surface_frame": 0}
    for observation in horse_observations:
        position = bisect_right(stamps, observation.receive_ts_ns) - 1
        if position < 0:
            failures["no_prior_surface"] += 1
            continue
        surface = ordered[position]
        if surface.connection_epoch != observation.connection_epoch:
            failures["cross_epoch_surface"] += 1
            continue
        age = (observation.receive_ts_ns - surface.receive_ts_ns) / 1_000_000_000
        if age < 0.0:
            raise AssertionError("as-of join selected a future surface")
        if age > max_carry_seconds:
            failures["stale_surface_frame"] += 1
            continue
        features = {**observation.features, **surface.economic}
        joined.append(replace(observation, features=features))
        records.append(
            SurfaceJoinRecord(
                tape_index=observation.tape_index,
                run_id=observation.run_id,
                anchor_ts_ns=observation.receive_ts_ns,
                connection_epoch=observation.connection_epoch,
                surface_sequence=surface.sequence,
                surface_ts_ns=surface.receive_ts_ns,
                carry_age_seconds=age,
                y_future_ticks=(
                    float(observation.future_ticks[HORIZON_SECONDS])
                    if HORIZON_SECONDS in observation.future_ticks
                    else None
                ),
            )
        )
    return joined, records, failures


def _quantiles(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "min": None, "median": None, "p95": None, "max": None}
    ordered = sorted(values)

    def at(probability: float) -> float:
        position = (len(ordered) - 1) * probability
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "n": len(ordered),
        "min": ordered[0],
        "median": at(0.5),
        "p95": at(0.95),
        "max": ordered[-1],
    }


def build_reconciliation_artifact(
    horse_observations: Sequence[HorseRaceObservation],
    surface_observations: Sequence[SurfacePredictiveObservation],
    *,
    source_metadata: Mapping[str, Any],
    reproduction_hashes: Mapping[str, Any],
    code_commit: str | None,
    replicates: int,
    seed: int,
) -> tuple[dict[str, Any], list[SurfaceJoinRecord]]:
    joined, records, failures = join_displayed_surface(
        horse_observations, surface_observations
    )
    if not joined:
        raise ValueError("no DAT-20 anchor accepted a causal displayed-surface join")
    split = chronological_embargoed_split(
        [as_normal_observation(item) for item in joined], embargo_seconds=120.0
    )
    train = tuple(
        position
        for position in split.train
        if HORIZON_SECONDS in joined[position].future_ticks
    )
    test = tuple(
        position
        for position in split.test
        if HORIZON_SECONDS in joined[position].future_ticks
    )
    if min(len(train), len(test)) < 20:
        raise ValueError("joined DAT-20 sample cannot support the frozen fit")

    surface_names = tuple(sorted(surface_observations[0].economic))
    m0_names = model_features("M0", M3B_WINDOW_SECONDS, trade_identified=True)
    m3b_names = (*m0_names, cks_pressure_feature(M3B_WINDOW_SECONDS))
    m4_names = model_features("M4", M4_WINDOW_SECONDS, trade_identified=True)
    specifications = (
        ("M0", m0_names, "M0", "M0"),
        ("M3b_h1_1s", m3b_names, "M3", "M0"),
        ("M4_h1_2s", m4_names, "M4", "M0"),
        ("S", surface_names, "M4", "M0"),
        ("M0S", (*m0_names, *surface_names), "M4", "M0"),
        ("M3bS", (*m3b_names, *surface_names), "M4", "M3b_h1_1s"),
        ("M4S", (*m4_names, *surface_names), "M4", "M4_h1_2s"),
    )
    fitted: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for label, names, fit_label, reference in specifications:
        score = _fit_score(
            joined,
            train,
            test,
            model=fit_label,
            names=names,
            horizon=HORIZON_SECONDS,
            source="future",
        )
        fitted[label] = score
        rows.append(
            {
                "model": label,
                "reference_model": reference,
                "features": list(names),
                **dict(score.payload),
            }
        )
    for row in rows:
        label = str(row["model"])
        reference = str(row["reference_model"])
        current = row.get("oos_r2_training_mean")
        reference_r2 = fitted[reference].payload.get("oos_r2_training_mean")
        row["incremental_oos_r2_over_reference"] = (
            None
            if current is None or reference_r2 is None
            else float(current) - float(reference_r2)
        )
        row["per_tape_vs_reference"] = _per_tape_scores(
            joined,
            test,
            horizon=HORIZON_SECONDS,
            source="future",
            score=fitted[label],
            baseline=fitted[reference],
        )

    inference: list[dict[str, Any]] = []
    for base, enhanced in (("M0", "M0S"), ("M3b_h1_1s", "M3bS"), ("M4_h1_2s", "M4S")):
        inference.append(
            {
                "base_model": base,
                "enhanced_model": enhanced,
                **_inference(
                    fitted[base],
                    fitted[enhanced],
                    joined,
                    test,
                    horizon=HORIZON_SECONDS,
                    seed=seed + len(inference),
                    replicates=replicates,
                ),
            }
        )

    model_index = {str(row["model"]): row for row in rows}
    return (
        {
            "reconciliation_id": RECONCILIATION_ID,
            "confirmatory_eligible": False,
            "correction_document": CORRECTION_DOCUMENT,
            "code_commit": code_commit,
            "seed": seed,
            "bootstrap_replicates": replicates,
            "source": dict(source_metadata),
            "exact_horserace_reproduction": dict(reproduction_hashes),
            "timing": {
                "surface_asof": "latest displayed frame at or before each depth200 anchor",
                "maximum_surface_frame_carry_seconds": MAX_ASOF_AGE_SECONDS,
                "ofi_candidate_lookbacks_seconds": {"M3b": 1.0, "M4": 2.0},
                "causal_gap_seconds": 0.5,
                "response_seconds": HORIZON_SECONDS,
            },
            "sample": {
                "joined_observations": len(joined),
                "unique_displayed_surface_frames": len(
                    {record.surface_sequence for record in records}
                ),
                "train_n": len(train),
                "embargoed_n": len(split.embargoed),
                "test_n": len(test),
                "join_failures": failures,
                "surface_frame_carry_age_seconds": _quantiles(
                    [record.carry_age_seconds for record in records]
                ),
            },
            "model_scores": rows,
            "paired_inference": inference,
            "headline": {
                "M3b_oos_r2": model_index["M3b_h1_1s"]["oos_r2_training_mean"],
                "M4_oos_r2": model_index["M4_h1_2s"]["oos_r2_training_mean"],
                "S_oos_r2": model_index["S"]["oos_r2_training_mean"],
                "M3bS_minus_M3b": model_index["M3bS"][
                    "incremental_oos_r2_over_reference"
                ],
                "M4S_minus_M4": model_index["M4S"][
                    "incremental_oos_r2_over_reference"
                ],
            },
        },
        records,
    )


def join_record_to_dict(record: SurfaceJoinRecord) -> dict[str, Any]:
    return asdict(record)
