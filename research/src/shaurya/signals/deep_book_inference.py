"""Synthetic-only inference contracts and primitives for registered H-SIG21 cells."""

from __future__ import annotations

import json
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from math import isfinite, sqrt
from pathlib import Path
from typing import Literal

from shaurya.signals.deep_book_anomaly import AtomicEventType

Side = Literal["bid", "ask"]
DistanceBand = Literal["20_50", "gt_50"]

REGISTERED_FAMILY_SIZE = 384
REGISTERED_OVERLAP_LAG = 11
REGISTERED_THRESHOLDS = (0.995, 0.999)
REGISTERED_GAPS_SECONDS = (0.5, 1.0)
REGISTERED_HORIZONS_SECONDS = (1, 5, 10)
REGISTERED_SIDES: tuple[Side, ...] = ("bid", "ask")
REGISTERED_DISTANCE_BANDS: tuple[DistanceBand, ...] = ("20_50", "gt_50")
MAX_MEAN_MDE_TICKS = 0.25
MAX_MOVE_PROBABILITY_MDE = 0.05


@dataclass(frozen=True, slots=True, order=True)
class FamilyCell:
    atomic_type: AtomicEventType
    side: Side
    distance_band: DistanceBand
    threshold: float
    gap_seconds: float
    horizon_seconds: int

    @property
    def cell_id(self) -> str:
        threshold = int(round(self.threshold * 1_000))
        gap_milliseconds = int(round(self.gap_seconds * 1_000))
        return (
            f"{self.atomic_type.value}|{self.side}|{self.distance_band}|q{threshold:03d}"
            f"|z{gap_milliseconds}ms|h{self.horizon_seconds}s"
        )


def _canonical_cells() -> tuple[FamilyCell, ...]:
    return tuple(
        FamilyCell(atomic_type, side, band, threshold, gap, horizon)
        for atomic_type in AtomicEventType
        for side in REGISTERED_SIDES
        for band in REGISTERED_DISTANCE_BANDS
        for threshold in REGISTERED_THRESHOLDS
        for gap in REGISTERED_GAPS_SECONDS
        for horizon in REGISTERED_HORIZONS_SECONDS
    )


@dataclass(frozen=True, slots=True)
class FamilyManifest:
    cells: tuple[FamilyCell, ...]

    def __post_init__(self) -> None:
        ids = tuple(cell.cell_id for cell in self.cells)
        if len(ids) != len(set(ids)):
            raise ValueError("family manifest contains duplicate cells")
        expected = set(_canonical_cells())
        observed = set(self.cells)
        missing = expected - observed
        extra = observed - expected
        if missing or extra or len(self.cells) != REGISTERED_FAMILY_SIZE:
            raise ValueError(
                "family manifest must contain exactly the canonical 384 cells "
                f"(missing={len(missing)}, extra={len(extra)}, observed={len(self.cells)})"
            )

    @property
    def family_size(self) -> int:
        return len(self.cells)

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(cell.cell_id for cell in self.cells)


def canonical_family_manifest() -> FamilyManifest:
    """Return the immutable, complete two-sided H-SIG21 discovery family."""

    return FamilyManifest(_canonical_cells())


class PowerCellStatus(StrEnum):
    ELIGIBLE = "eligible"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class PowerCell:
    """Outcome-independent numeric power record for one registered cell."""

    cell_id: str
    n: int
    n_eff: float
    family_size: int
    critical_value: float
    unconditional_sigma_ticks: float
    unconditional_move_probability: float
    mean_mde_ticks: float | None
    move_probability_mde: float | None
    outcome_joined: Literal[False] = False
    provenance: Literal["unconditional_calibration_only"] = "unconditional_calibration_only"
    status: PowerCellStatus = field(init=False)
    deferral_reasons: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError("n must be non-negative")
        if not isfinite(self.n_eff) or self.n_eff < 0 or self.n_eff > self.n:
            raise ValueError("n_eff must be finite and lie in [0, n]")
        if not isfinite(self.critical_value) or self.critical_value <= 0:
            raise ValueError("critical_value must be finite and positive")
        if not isfinite(self.unconditional_sigma_ticks) or self.unconditional_sigma_ticks < 0:
            raise ValueError("unconditional_sigma_ticks must be finite and non-negative")
        if (
            not isfinite(self.unconditional_move_probability)
            or not 0 <= self.unconditional_move_probability <= 1
        ):
            raise ValueError("unconditional_move_probability must lie in [0, 1]")
        if self.outcome_joined is not False:
            raise ValueError("power records must be computed before any outcome join")
        if self.provenance != "unconditional_calibration_only":
            raise ValueError("power provenance must be unconditional calibration only")
        for name, value in (
            ("mean_mde_ticks", self.mean_mde_ticks),
            ("move_probability_mde", self.move_probability_mde),
        ):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when present")

        reasons: list[str] = []
        if self.family_size != REGISTERED_FAMILY_SIZE:
            reasons.append("family_size_not_384")
        if self.mean_mde_ticks is None:
            reasons.append("mean_mde_unavailable")
        elif self.mean_mde_ticks > MAX_MEAN_MDE_TICKS:
            reasons.append("mean_mde_above_0.25_tick")
        if self.move_probability_mde is None:
            reasons.append("probability_mde_unavailable")
        elif self.move_probability_mde > MAX_MOVE_PROBABILITY_MDE:
            reasons.append("probability_mde_above_0.05")
        object.__setattr__(
            self,
            "status",
            PowerCellStatus.DEFERRED if reasons else PowerCellStatus.ELIGIBLE,
        )
        object.__setattr__(self, "deferral_reasons", tuple(reasons))


def calculate_outcome_independent_power(
    *,
    cell_id: str,
    n: int,
    n_eff: float,
    family_size: int,
    critical_value: float,
    unconditional_sigma_ticks: float,
    unconditional_move_probability: float,
) -> PowerCell:
    """Calculate conservative two-arm MDEs from unconditional calibration quantities only."""

    if not isfinite(unconditional_sigma_ticks) or unconditional_sigma_ticks < 0:
        raise ValueError("unconditional_sigma_ticks must be finite and non-negative")
    if not isfinite(unconditional_move_probability) or not 0 <= unconditional_move_probability <= 1:
        raise ValueError("unconditional_move_probability must lie in [0, 1]")
    if not isfinite(n_eff) or n_eff < 0:
        raise ValueError("n_eff must be finite and non-negative")
    if n_eff == 0:
        mean_mde = None
        probability_mde = None
    else:
        mean_standard_error = sqrt(2.0) * unconditional_sigma_ticks / sqrt(n_eff)
        probability_standard_error = sqrt(
            2.0 * unconditional_move_probability * (1.0 - unconditional_move_probability) / n_eff
        )
        mean_mde = critical_value * mean_standard_error
        probability_mde = critical_value * probability_standard_error
    return PowerCell(
        cell_id=cell_id,
        n=n,
        n_eff=n_eff,
        family_size=family_size,
        critical_value=critical_value,
        unconditional_sigma_ticks=unconditional_sigma_ticks,
        unconditional_move_probability=unconditional_move_probability,
        mean_mde_ticks=mean_mde,
        move_probability_mde=probability_mde,
    )


@dataclass(frozen=True, slots=True, order=True)
class SessionRecord:
    session_id: str
    session_date: date


@dataclass(frozen=True, slots=True)
class RegimeSupport:
    regime_id: str
    evaluation_session_ids: tuple[str, ...]
    n_eff: float
    used_in_stability_verdict: bool


@dataclass(frozen=True, slots=True)
class PowerArtifact:
    """Pre-outcome power artifact with immutable registration and sample identity."""

    registration_commit: str
    code_commit: str
    calibration_start: date
    calibration_end: date
    sample_start: date
    sample_end: date
    calibration_sessions: tuple[SessionRecord, ...]
    evaluation_sessions: tuple[SessionRecord, ...]
    regime_support: tuple[RegimeSupport, ...]
    cells: tuple[PowerCell, ...]
    outcome_joined: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.registration_commit or not self.code_commit:
            raise ValueError("registration_commit and code_commit are required")
        if self.calibration_start > self.calibration_end:
            raise ValueError("calibration dates are reversed")
        if self.sample_start > self.sample_end:
            raise ValueError("sample dates are reversed")
        if self.calibration_end >= self.sample_start:
            raise ValueError("evaluation sample must follow the calibration period")
        if self.outcome_joined is not False:
            raise ValueError("power artifact must precede every outcome join")
        manifest = canonical_family_manifest()
        observed_ids = tuple(cell.cell_id for cell in self.cells)
        _validate_complete_ids(observed_ids, manifest.cell_ids, label="power artifact")
        if any(cell.family_size != REGISTERED_FAMILY_SIZE for cell in self.cells):
            raise ValueError("every power cell must record G=384")
        if any(cell.outcome_joined is not False for cell in self.cells):
            raise ValueError("power artifact contains an outcome-joined cell")
        _validate_session_support(
            self.calibration_sessions,
            minimum=5,
            period_start=self.calibration_start,
            period_end=self.calibration_end,
            label="calibration",
        )
        _validate_session_support(
            self.evaluation_sessions,
            minimum=20,
            period_start=self.sample_start,
            period_end=self.sample_end,
            label="evaluation",
        )
        calibration_ids = {session.session_id for session in self.calibration_sessions}
        evaluation_ids = {session.session_id for session in self.evaluation_sessions}
        if calibration_ids & evaluation_ids:
            raise ValueError("calibration and evaluation session IDs must be disjoint")
        if self.calibration_sessions[-1].session_date >= self.evaluation_sessions[0].session_date:
            raise ValueError("all evaluation sessions must follow calibration sessions")
        if not self.regime_support:
            raise ValueError("explicit regime support records are required")
        regime_ids = tuple(record.regime_id for record in self.regime_support)
        if len(regime_ids) != len(set(regime_ids)) or any(not value for value in regime_ids):
            raise ValueError("regime support IDs must be non-empty and unique")
        for record in self.regime_support:
            session_ids = record.evaluation_session_ids
            if len(session_ids) != len(set(session_ids)):
                raise ValueError("regime support session IDs must be unique")
            if not set(session_ids) <= evaluation_ids:
                raise ValueError("regime support references a non-evaluation session")
            if not isfinite(record.n_eff) or record.n_eff < 0:
                raise ValueError("regime N_eff must be finite and non-negative")
            if record.used_in_stability_verdict and (len(session_ids) < 5 or record.n_eff < 100):
                raise ValueError(
                    "a regime used in a stability verdict requires >=5 evaluation sessions "
                    "and N_eff>=100"
                )


def _validate_session_support(
    sessions: tuple[SessionRecord, ...],
    *,
    minimum: int,
    period_start: date,
    period_end: date,
    label: str,
) -> None:
    if len(sessions) < minimum:
        raise ValueError(f"{label} requires at least {minimum} session IDs")
    ids = tuple(session.session_id for session in sessions)
    if any(not session_id for session_id in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{label} session IDs must be non-empty and unique")
    dates = tuple(session.session_date for session in sessions)
    if any(current <= previous for previous, current in zip(dates, dates[1:], strict=False)):
        raise ValueError(f"{label} sessions must be in strictly increasing date order")
    if any(session_date < period_start or session_date > period_end for session_date in dates):
        raise ValueError(f"{label} session date falls outside its declared period")


@dataclass(frozen=True, slots=True)
class HacMeanDifference:
    n: int
    lag: int
    mean_difference: float
    standard_error: float
    t_statistic: float | None


def hac_newey_west_mean_difference(
    event_values: Sequence[float],
    control_values: Sequence[float],
    *,
    lag: int = REGISTERED_OVERLAP_LAG,
) -> HacMeanDifference:
    """Estimate a paired mean difference with a Bartlett-kernel Newey-West variance."""

    if lag < REGISTERED_OVERLAP_LAG:
        raise ValueError(f"lag must be at least the registered overlap ({REGISTERED_OVERLAP_LAG})")
    if len(event_values) != len(control_values) or not event_values:
        raise ValueError("event and control samples must be non-empty and equally sized")
    differences = tuple(
        float(event - control) for event, control in zip(event_values, control_values, strict=True)
    )
    if not all(isfinite(value) for value in differences):
        raise ValueError("event-control differences must be finite")
    n = len(differences)
    mean = sum(differences) / n
    residuals = tuple(value - mean for value in differences)
    long_run_variance = sum(value * value for value in residuals) / n
    effective_lag = min(lag, n - 1)
    for offset in range(1, effective_lag + 1):
        covariance = (
            sum(residuals[index] * residuals[index - offset] for index in range(offset, n)) / n
        )
        weight = 1.0 - offset / (lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    standard_error = sqrt(max(long_run_variance, 0.0) / n)
    t_statistic = mean / standard_error if standard_error > 0 else None
    return HacMeanDifference(n, lag, mean, standard_error, t_statistic)


def stationary_session_block_bootstrap(
    values_by_session: Mapping[str, Sequence[float]],
    *,
    replicates: int,
    mean_block_length: float,
    seed: int,
) -> tuple[tuple[float, ...], ...]:
    """Draw deterministic stationary-bootstrap samples without crossing session boundaries."""

    if replicates < 1:
        raise ValueError("replicates must be positive")
    if not isfinite(mean_block_length) or mean_block_length < 1:
        raise ValueError("mean_block_length must be finite and at least one")
    if not values_by_session:
        raise ValueError("at least one session is required")
    sessions: list[tuple[str, tuple[float, ...]]] = []
    for session_id, raw_values in sorted(values_by_session.items()):
        values = tuple(float(value) for value in raw_values)
        if not session_id or not values or not all(isfinite(value) for value in values):
            raise ValueError("each named session must contain finite values")
        sessions.append((session_id, values))

    restart_probability = 1.0 / mean_block_length
    generator = random.Random(seed)
    samples: list[tuple[float, ...]] = []
    for _ in range(replicates):
        sample: list[float] = []
        for _, values in sessions:
            index = generator.randrange(len(values))
            for position in range(len(values)):
                if position and generator.random() < restart_probability:
                    index = generator.randrange(len(values))
                elif position:
                    index = (index + 1) % len(values)
                sample.append(values[index])
        samples.append(tuple(sample))
    return tuple(samples)


@dataclass(frozen=True, slots=True)
class RomanoWolfCell:
    cell_id: str
    observed_t: float
    stepdown_rank: int
    adjusted_p_value: float


def romano_wolf_stepdown(
    manifest: FamilyManifest,
    observed_t: Mapping[str, float],
    bootstrap_t: Sequence[Mapping[str, float]],
) -> tuple[RomanoWolfCell, ...]:
    """Compute two-sided max-|t| Romano-Wolf step-down adjusted p-values."""

    expected_ids = manifest.cell_ids
    _validate_complete_ids(tuple(observed_t), expected_ids, label="observed statistics")
    if not bootstrap_t:
        raise ValueError("at least one bootstrap replicate is required")
    if not all(isfinite(value) for value in observed_t.values()):
        raise ValueError("observed statistics must be finite")
    for index, replicate in enumerate(bootstrap_t):
        _validate_complete_ids(tuple(replicate), expected_ids, label=f"bootstrap replicate {index}")
        if not all(isfinite(value) for value in replicate.values()):
            raise ValueError("bootstrap statistics must be finite")

    ordered = sorted(expected_ids, key=lambda cell_id: (-abs(observed_t[cell_id]), cell_id))
    remaining = set(expected_ids)
    adjusted_by_id: dict[str, RomanoWolfCell] = {}
    previous_adjusted = 0.0
    denominator = len(bootstrap_t) + 1
    for rank, cell_id in enumerate(ordered, start=1):
        observed_absolute = abs(observed_t[cell_id])
        exceedances = sum(
            max(abs(replicate[remaining_id]) for remaining_id in remaining) >= observed_absolute
            for replicate in bootstrap_t
        )
        step_p = (exceedances + 1) / denominator
        adjusted = max(previous_adjusted, step_p)
        adjusted_by_id[cell_id] = RomanoWolfCell(
            cell_id,
            observed_t[cell_id],
            rank,
            min(adjusted, 1.0),
        )
        previous_adjusted = adjusted
        remaining.remove(cell_id)
    return tuple(adjusted_by_id[cell_id] for cell_id in expected_ids)


class TrialStatus(StrEnum):
    DEFERRED = "deferred"
    EXECUTED = "executed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class Sig19TrialRow:
    trial_id: str
    hypothesis_id: str
    registration_commit: str
    code_commit: str
    tape_start: date
    tape_end: date
    instrument_id: str
    contract_id: str
    cell_id: str
    family_size: int
    n: int
    n_eff: float
    mean_mde_ticks: float | None
    move_probability_mde: float | None
    power_artifact_sha256: str
    status: TrialStatus


def validate_sig19_trial_rows(
    rows: Sequence[Sig19TrialRow],
    manifest: FamilyManifest,
) -> tuple[Sig19TrialRow, ...]:
    """Validate one immutable, complete SIG-19 row set for one contract/tape stratum."""

    if not rows:
        raise ValueError("SIG-19 trial rows are empty")
    _validate_complete_ids(tuple(row.cell_id for row in rows), manifest.cell_ids, label="SIG-19")
    if any(
        not row.trial_id
        or row.hypothesis_id != "H-SIG21"
        or not row.registration_commit
        or not row.code_commit
        or not row.instrument_id
        or not row.contract_id
        or row.tape_start > row.tape_end
        or row.family_size != REGISTERED_FAMILY_SIZE
        or row.n < 0
        or not isfinite(row.n_eff)
        or row.n_eff < 0
        or row.n_eff > row.n
        or not _valid_optional_non_negative(row.mean_mde_ticks)
        or not _valid_optional_non_negative(row.move_probability_mde)
        or not _is_sha256(row.power_artifact_sha256)
        for row in rows
    ):
        raise ValueError("SIG-19 rows contain invalid or incomplete required identifiers")
    identity = {
        (
            row.hypothesis_id,
            row.registration_commit,
            row.code_commit,
            row.tape_start,
            row.tape_end,
            row.instrument_id,
            row.contract_id,
            row.power_artifact_sha256,
        )
        for row in rows
    }
    if len(identity) != 1:
        raise ValueError("SIG-19 rows must share one complete trial identity")
    trial_ids = tuple(row.trial_id for row in rows)
    if len(trial_ids) != len(set(trial_ids)):
        raise ValueError("SIG-19 trial_id values must be unique")
    return tuple(rows)


def _valid_optional_non_negative(value: float | None) -> bool:
    return value is None or (isfinite(value) and value >= 0)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def write_sig19_jsonl_once(
    path: Path,
    rows: Sequence[Sig19TrialRow],
    manifest: FamilyManifest,
) -> Path:
    """Create one durable complete-family SIG-19 JSONL artifact without overwrite."""

    validated = validate_sig19_trial_rows(rows, manifest)
    by_cell_id = {row.cell_id: row for row in validated}
    ordered = tuple(by_cell_id[cell_id] for cell_id in manifest.cell_ids)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            for row in ordered:
                payload = {
                    "schema_version": "sig19_trial_v1",
                    "trial_id": row.trial_id,
                    "hypothesis_id": row.hypothesis_id,
                    "registration_commit": row.registration_commit,
                    "code_commit": row.code_commit,
                    "tape_start": row.tape_start.isoformat(),
                    "tape_end": row.tape_end.isoformat(),
                    "instrument_id": row.instrument_id,
                    "contract_id": row.contract_id,
                    "cell_id": row.cell_id,
                    "family_size": row.family_size,
                    "n": row.n,
                    "n_eff": row.n_eff,
                    "mean_mde_ticks": row.mean_mde_ticks,
                    "move_probability_mde": row.move_probability_mde,
                    "power_artifact_sha256": row.power_artifact_sha256,
                    "status": row.status.value,
                }
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return path


def _validate_complete_ids(
    observed: tuple[str, ...],
    expected: tuple[str, ...],
    *,
    label: str,
) -> None:
    if len(observed) != len(set(observed)):
        raise ValueError(f"{label} contains duplicate cell IDs")
    missing = set(expected) - set(observed)
    extra = set(observed) - set(expected)
    if missing or extra or len(observed) != len(expected):
        raise ValueError(
            f"{label} is incomplete (missing={len(missing)}, extra={len(extra)}, "
            f"observed={len(observed)})"
        )


@dataclass(frozen=True, slots=True)
class DirectionalPromotionRequest:
    first_stage_hypothesis_id: str
    confirmation_hypothesis_id: str | None
    first_stage_tape_end: date
    confirmation_tape_start: date | None
    confirmation_registered_before_tape: bool


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    allowed: bool
    reason: str


def guard_directional_promotion(request: DirectionalPromotionRequest) -> PromotionDecision:
    """Enforce that first-stage H-SIG21 cannot itself promote a directional claim."""

    if request.first_stage_hypothesis_id != "H-SIG21":
        return PromotionDecision(False, "source_must_be_first_stage_H-SIG21")
    confirmation_prefix = "H-SIG21C-"
    if (
        request.confirmation_hypothesis_id is None
        or not request.confirmation_hypothesis_id.startswith(confirmation_prefix)
        or len(request.confirmation_hypothesis_id) == len(confirmation_prefix)
    ):
        return PromotionDecision(False, "later_H-SIG21C_registration_required")
    if not request.confirmation_registered_before_tape:
        return PromotionDecision(False, "confirmation_must_be_registered_before_new_tape")
    if (
        request.confirmation_tape_start is None
        or request.confirmation_tape_start <= request.first_stage_tape_end
    ):
        return PromotionDecision(False, "confirmation_requires_subsequent_tape")
    return PromotionDecision(True, "later_registered_confirmation_on_subsequent_tape")
