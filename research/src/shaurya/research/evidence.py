"""Experiment evidence, selection provenance, lifecycle grades and decay rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from math import isfinite
from typing import Any

from shaurya.research.contracts import (
    EvidenceGrade,
    ExperimentStatus,
    HypothesisStatus,
    JSONScalar,
    ResearchMode,
    canonical_sha256,
)


@dataclass(frozen=True, slots=True)
class SelectionProvenance:
    candidate_ids: tuple[str, ...]
    selection_metric: str
    selection_information_ts: str
    evaluation_period_start: str
    selected_rank: int | None
    candidate_scores: tuple[tuple[str, float | None], ...]
    score_difference_from_next: float | None
    neighboring_results: tuple[tuple[str, float | None], ...]
    multiplicity_method: str
    mode: ResearchMode

    def __post_init__(self) -> None:
        if not self.candidate_ids or len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("selection context requires the complete unique candidate universe")
        if tuple(sorted(self.candidate_ids)) != self.candidate_ids:
            raise ValueError("candidate IDs must be canonically sorted")
        score_ids = tuple(item[0] for item in self.candidate_scores)
        if score_ids != self.candidate_ids:
            raise ValueError("candidate scores must account for every declared candidate")
        selection = datetime.fromisoformat(self.selection_information_ts)
        evaluation = datetime.fromisoformat(self.evaluation_period_start)
        if selection >= evaluation:
            raise ValueError("selection information must precede the evaluation period")
        if tuple(sorted(self.candidate_scores)) != self.candidate_scores:
            raise ValueError("candidate scores must be canonically ordered")
        if self.selected_rank is not None and not 1 <= self.selected_rank <= len(
            self.candidate_ids
        ):
            raise ValueError("selection rank is outside the frozen candidate universe")
        neighbor_ids = tuple(item[0] for item in self.neighboring_results)
        if (
            neighbor_ids != tuple(sorted(set(neighbor_ids)))
            or not set(neighbor_ids) <= set(self.candidate_ids)
        ):
            raise ValueError("selection neighbors must be canonical members of the universe")
        _finite_optional_selection(self.score_difference_from_next)


@dataclass(frozen=True, slots=True)
class EvidenceAuthority:
    """Exact scientific artifacts permitted to support lifecycle evidence."""

    plan_hash: str
    pre_session_state_hash: str
    source_derivation_hash: str
    candidate_ids: tuple[str, ...]
    registry_fingerprints: tuple[tuple[str, str], ...]
    policy_fingerprint: str
    walkforward_hash: str
    multiplicity_hash: str
    empirical_null_hash: str
    surface_hashes: tuple[tuple[str, str], ...]
    surface_robustness_hashes: tuple[tuple[str, str], ...]
    candidate_gate_hashes: tuple[tuple[str, str], ...]
    block_bootstrap_hashes: tuple[tuple[str, str], ...]
    mechanism_hashes: tuple[tuple[str, str], ...] = ()
    authority_hash: str = ""

    def with_hash(self) -> EvidenceAuthority:
        payload = asdict(self)
        payload["authority_hash"] = ""
        return EvidenceAuthority(**{**payload, "authority_hash": canonical_sha256(payload)})

    def __post_init__(self) -> None:
        if self.candidate_ids != tuple(sorted(self.candidate_ids)) or not self.candidate_ids:
            raise ValueError("evidence authority requires the exact sorted candidate universe")
        for digest in (
            self.plan_hash,
            self.pre_session_state_hash,
            self.source_derivation_hash,
            self.policy_fingerprint,
            self.walkforward_hash,
            self.multiplicity_hash,
            self.empirical_null_hash,
            *(value for _, value in self.registry_fingerprints),
            *(value for _, value in self.surface_hashes),
            *(value for _, value in self.surface_robustness_hashes),
            *(value for _, value in self.candidate_gate_hashes),
            *(value for _, value in self.block_bootstrap_hashes),
            *(value for _, value in self.mechanism_hashes),
        ):
            if len(digest) != 64:
                raise ValueError("evidence authority values must be SHA-256 digests")
        for label, values in (
            ("registry", self.registry_fingerprints),
            ("surface", self.surface_hashes),
            ("surface robustness", self.surface_robustness_hashes),
            ("candidate gate", self.candidate_gate_hashes),
            ("block bootstrap", self.block_bootstrap_hashes),
            ("mechanism", self.mechanism_hashes),
        ):
            identities = tuple(name for name, _ in values)
            if identities != tuple(sorted(set(identities))):
                raise ValueError(f"evidence authority {label} bindings are not canonical")
        if tuple(name for name, _ in self.candidate_gate_hashes) != self.candidate_ids:
            raise ValueError("candidate gate authority must exactly cover the candidate universe")
        if tuple(name for name, _ in self.block_bootstrap_hashes) != self.candidate_ids:
            raise ValueError("block-bootstrap authority must exactly cover the candidate universe")
        if tuple(name for name, _ in self.surface_hashes) != tuple(
            name for name, _ in self.surface_robustness_hashes
        ):
            raise ValueError("surface and robustness authority selectors disagree")
        if self.authority_hash:
            payload = asdict(self)
            payload["authority_hash"] = ""
            if canonical_sha256(payload) != self.authority_hash:
                raise ValueError("evidence authority hash is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    hypothesis_id: str
    evaluation_date: date
    mode: ResearchMode
    training_interval: tuple[str, str]
    validation_interval: tuple[str, str]
    test_interval: tuple[str, str]
    observation_count: int
    effective_sample_size: float
    model_class: str
    hyperparameters: tuple[tuple[str, JSONScalar], ...]
    feature_registry_version: str
    target_registry_version: str
    policy_registry_version: str
    feature_run_hashes: tuple[str, ...]
    metrics: tuple[tuple[str, float | int | bool | str | None], ...]
    uncertainty: tuple[tuple[str, float | int | bool | str | None], ...]
    selection: SelectionProvenance
    competing_hypotheses: int
    terminal_status: ExperimentStatus
    terminal_reason: str | None = None
    plan_hash: str = ""
    pre_session_state_hash: str = ""
    source_identity_hash: str = ""
    fold_hashes: tuple[str, ...] = ()
    authority_hash: str = ""
    coefficient_estimates: tuple[tuple[str, str, float, float], ...] = ()
    selected_for_outer: bool = False
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.competing_hypotheses != len(self.selection.candidate_ids):
            raise ValueError("competing-hypothesis count must match complete selection provenance")
        if self.hypothesis_id not in self.selection.candidate_ids:
            raise ValueError("evidence hypothesis must exist in the complete candidate universe")
        if self.mode is not self.selection.mode:
            raise ValueError("selection and evidence modes must match")
        if (
            self.observation_count < 0
            or not 0 <= self.effective_sample_size <= self.observation_count
        ):
            raise ValueError("effective sample size must lie within observation support")
        if any(len(value) != 64 for value in self.feature_run_hashes):
            raise ValueError("feature run identities must be SHA-256 hashes")
        if self.terminal_status is not ExperimentStatus.COMPLETED and not self.terminal_reason:
            raise ValueError("failed or skipped evidence requires a terminal reason")
        if self.terminal_status is ExperimentStatus.COMPLETED and self.mode in {
            ResearchMode.CONFIRMATORY,
            ResearchMode.LIVE_SHADOW,
        }:
            score = dict(self.metrics).get("score")
            if (
                self.observation_count < 1
                or self.effective_sample_size <= 0
                or not self.feature_run_hashes
                or not self.fold_hashes
                or not isinstance(score, (int, float))
            ):
                raise ValueError(
                    "completed OOS evidence requires genuine support, folds, and score"
                )
            if not self.selected_for_outer or self.selection.selected_rank is None:
                raise ValueError("completed OOS evidence must be nested-selected for outer use")
        for _, value in (*self.metrics, *self.uncertainty):
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("metrics and uncertainty must be finite when present")
        if self.coefficient_estimates != tuple(sorted(self.coefficient_estimates)):
            raise ValueError("coefficient estimates must preserve canonical identities")
        if any(
            not isfinite(value) or error < 0 or not isfinite(error)
            for _, _, value, error in self.coefficient_estimates
        ):
            raise ValueError("coefficient estimates and uncertainty must be finite")
        intervals = tuple(
            _parse_interval(value, label=label)
            for label, value in (
                ("training", self.training_interval),
                ("validation", self.validation_interval),
                ("test", self.test_interval),
            )
        )
        training, validation, test = intervals
        if training[1] >= validation[0] or validation[1] >= test[0]:
            raise ValueError("training, validation and test intervals must be ordered and disjoint")
        selection_ts = _parse_stamp(self.selection.selection_information_ts)
        if selection_ts >= test[0]:
            raise ValueError("selection must precede every claimed OOS evidence interval")
        if _parse_stamp(self.selection.evaluation_period_start) != test[0]:
            raise ValueError("selection evaluation start must match the evidence test interval")
        for label, digest in (
            ("plan_hash", self.plan_hash),
            ("pre_session_state_hash", self.pre_session_state_hash),
            ("source_identity_hash", self.source_identity_hash),
            ("authority_hash", self.authority_hash),
            *(("fold_hash", value) for value in self.fold_hashes),
        ):
            if digest and len(digest) != 64:
                raise ValueError(f"{label} must be a SHA-256 digest")
        object.__setattr__(self, "event_id", "")
        object.__setattr__(self, "event_id", f"evidence-{canonical_sha256(self.payload())[:24]}")

    def payload(self) -> Mapping[str, Any]:
        payload = asdict(self)
        payload.pop("event_id", None)
        return payload


@dataclass(frozen=True, slots=True)
class LifecycleAssessment:
    hypothesis_id: str
    as_of: date
    status: HypothesisStatus
    grade: EvidenceGrade
    distinct_sessions: int
    confirmatory_sessions: int
    live_shadow_sessions: int
    sign_consistency: float | None
    rolling_score: float | None
    reasons: tuple[str, ...]
    unique_oos_sessions: int = 0
    unique_outer_folds: int = 0
    gate_results: tuple[tuple[str, bool], ...] = ()


def _metric(record: EvidenceRecord, name: str) -> float | None:
    value = dict(record.metrics).get(name)
    return float(value) if isinstance(value, (int, float)) else None


def assess_lifecycle(
    hypothesis_id: str,
    history: Sequence[EvidenceRecord],
    *,
    as_of: date,
    sessions_for_provisional: int = 5,
    sessions_for_stable: int = 20,
    dormant_consecutive_sessions: int = 5,
    minimum_sign_consistency: float = 0.7,
    previous_status: HypothesisStatus = HypothesisStatus.UNTESTED,
    policy: Mapping[str, object] | None = None,
    interrupted_dates: Sequence[date] = (),
) -> LifecycleAssessment:
    records = sorted(
        (
            record
            for record in history
            if record.hypothesis_id == hypothesis_id and record.evaluation_date <= as_of
        ),
        key=lambda record: (record.evaluation_date, record.event_id),
    )
    if not records:
        return LifecycleAssessment(
            hypothesis_id,
            as_of,
            HypothesisStatus.UNTESTED,
            EvidenceGrade.E0,
            0,
            0,
            0,
            None,
            None,
            ("no_completed_evidence",),
        )
    policy_raw = dict(policy or {})
    minimum_raw = policy_raw.get("minimum_evidence", {})
    promotion_raw = policy_raw.get("promotion", {})
    decay_raw = policy_raw.get("decay", {})
    reactivation_raw = policy_raw.get("reactivation", {})
    minimum = dict(minimum_raw) if isinstance(minimum_raw, Mapping) else {}
    promotion = dict(promotion_raw) if isinstance(promotion_raw, Mapping) else {}
    decay_policy = dict(decay_raw) if isinstance(decay_raw, Mapping) else {}
    reactivation = dict(reactivation_raw) if isinstance(reactivation_raw, Mapping) else {}
    sessions_for_provisional = int(
        minimum.get("sessions_for_provisional", sessions_for_provisional)
    )
    sessions_for_stable = int(minimum.get("sessions_for_stable", sessions_for_stable))
    minimum_observations = int(minimum.get("observations", 1))
    minimum_neff = float(minimum.get("effective_sample_size", 1))
    minimum_folds = int(minimum.get("outer_folds_for_stable", 1))
    minimum_sign_consistency = float(
        promotion.get("minimum_sign_consistency", minimum_sign_consistency)
    )
    minimum_neighbor = float(promotion.get("minimum_neighbor_robustness", 0.0))
    minimum_adjusted = float(promotion.get("minimum_adjusted_evidence", 0.0))
    dormant_consecutive_sessions = int(
        decay_policy.get("dormant_consecutive_sessions", dormant_consecutive_sessions)
    )
    decaying_consecutive = int(decay_policy.get("decaying_consecutive_sessions", 3))
    weakening_ratio = float(decay_policy.get("weakening_ratio", 0.5))
    reactivation_sessions = int(reactivation.get("minimum_new_confirmatory_sessions", 3))
    sessions = {record.evaluation_date for record in records}
    oos_records = [
        record
        for record in records
        if record.mode in {ResearchMode.CONFIRMATORY, ResearchMode.LIVE_SHADOW}
    ]
    completed_oos = [
        record for record in oos_records if record.terminal_status is ExperimentStatus.COMPLETED
    ]
    confirmatory = {
        record.evaluation_date
        for record in completed_oos
        if record.mode is ResearchMode.CONFIRMATORY
    }
    shadow = {
        record.evaluation_date
        for record in completed_oos
        if record.mode is ResearchMode.LIVE_SHADOW
    }
    duplicate_sessions = {
        record.evaluation_date
        for record in oos_records
        if sum(other.evaluation_date == record.evaluation_date for other in oos_records) > 1
    }
    if duplicate_sessions:
        raise ValueError("lifecycle requires at most one OOS evidence record per session")
    scored_oos = [
        (
            record,
            _metric(record, "score")
            if record.terminal_status is ExperimentStatus.COMPLETED
            else None,
        )
        for record in oos_records
    ]
    scores = [value for _, value in scored_oos if value is not None]
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in scores]
    nonzero = [value for value in signs if value]
    consistency = max(nonzero.count(1), nonzero.count(-1)) / len(nonzero) if nonzero else None
    score_timeline = [(record.evaluation_date, value) for record, value in scored_oos]
    score_timeline.extend((value, None) for value in interrupted_dates if value <= as_of)
    score_timeline.sort(key=lambda item: item[0])
    consecutive_scores: list[float] = []
    for _, value in reversed(score_timeline):
        if value is None:
            break
        consecutive_scores.append(value)
    consecutive_scores.reverse()
    rolling = (
        float(sum(consecutive_scores[-5:]) / min(5, len(consecutive_scores)))
        if consecutive_scores
        else None
    )
    recent_nonpositive = len(consecutive_scores) >= dormant_consecutive_sessions and all(
        value <= 0 for value in consecutive_scores[-dormant_consecutive_sessions:]
    )
    reasons: list[str] = []
    if len(sessions) == 1:
        reasons.append("single_session_cannot_promote")
    if consistency is not None and consistency < minimum_sign_consistency:
        reasons.append("unstable_sign")

    def artifact_gates(record: EvidenceRecord) -> dict[str, bool]:
        metrics = dict(record.metrics)
        uncertainty = dict(record.uncertainty)
        adjusted_p = uncertainty.get("adjusted_p_value", metrics.get("adjusted_p_value"))
        null_p = uncertainty.get("empirical_null_p_value", metrics.get("empirical_null_p_value"))
        neighborhood = metrics.get("neighbor_robustness")
        return {
            "observations": record.observation_count >= minimum_observations,
            "effective_sample_size": record.effective_sample_size >= minimum_neff,
            "multiplicity": isinstance(adjusted_p, (int, float))
            and 1 - float(adjusted_p) >= minimum_adjusted,
            "empirical_null": isinstance(null_p, (int, float))
            and 1 - float(null_p) >= minimum_adjusted,
            "neighborhood": isinstance(neighborhood, (int, float))
            and float(neighborhood) >= minimum_neighbor,
            "score": metrics.get("score_gate_pass") is True,
            "economic": metrics.get("economic_gate_pass") is True,
            "regime_comparison": metrics.get("regime_comparison_pass", True) is True,
            "block_bootstrap": metrics.get("block_bootstrap_gate_pass") is True,
        }

    qualified_oos = [
        record
        for record in completed_oos
        if record.selected_for_outer
        and _metric(record, "score") is not None
        and all(artifact_gates(record).values())
    ]
    oos_sessions = {record.evaluation_date for record in qualified_oos}
    outer_folds = {fold for record in qualified_oos for fold in record.fold_hashes}
    gate_results = {
        "observations": bool(qualified_oos)
        and all(record.observation_count >= minimum_observations for record in qualified_oos),
        "effective_sample_size": bool(qualified_oos)
        and all(record.effective_sample_size >= minimum_neff for record in qualified_oos),
        "folds": len(outer_folds) >= minimum_folds,
        "multiplicity": bool(qualified_oos),
        "empirical_null": bool(qualified_oos),
        "neighborhood": bool(qualified_oos),
        "score": bool(qualified_oos),
        "economic": bool(qualified_oos),
        "regime_comparison": bool(qualified_oos),
        "block_bootstrap": bool(qualified_oos),
        "sign_consistency": consistency is not None and consistency >= minimum_sign_consistency,
    }
    for name, passed in gate_results.items():
        if not passed:
            reasons.append(f"{name}_gate_failed")

    if previous_status is HypothesisStatus.REJECTED:
        status = HypothesisStatus.REJECTED
        reasons.append("rejected_is_terminal_for_this_policy_version")
    elif recent_nonpositive:
        status = HypothesisStatus.DORMANT
        reasons.append("consecutive_nonpositive_oos_evidence")
    elif previous_status is HypothesisStatus.DORMANT:
        last_nonpositive = max(
            (
                index
                for index, record in enumerate(records)
                if record.mode not in {ResearchMode.CONFIRMATORY, ResearchMode.LIVE_SHADOW}
                or record.terminal_status is not ExperimentStatus.COMPLETED
                or not record.selected_for_outer
                or (_metric(record, "score") or 0) <= 0
                or not all(artifact_gates(record).values())
            ),
            default=None,
        )
        post_dormancy = records[last_nonpositive + 1 :] if last_nonpositive is not None else []
        recent_confirmatory = {
            record.evaluation_date
            for record in post_dormancy
            if record.mode in {ResearchMode.CONFIRMATORY, ResearchMode.LIVE_SHADOW}
            and record.terminal_status is ExperimentStatus.COMPLETED
            and record.selected_for_outer
            and (_metric(record, "score") or 0) > 0
            and all(artifact_gates(record).values())
        }
        if len(recent_confirmatory) < reactivation_sessions:
            status = HypothesisStatus.DORMANT
            reasons.append("reactivation_requires_three_new_preselected_sessions")
        else:
            status = HypothesisStatus.REPLICATED
            reasons.append("predeclared_reactivation_gate_passed")
    elif (
        previous_status in {HypothesisStatus.STABLE, HypothesisStatus.WEAKENING}
        and len(consecutive_scores) >= decaying_consecutive
        and all(value <= 0 for value in consecutive_scores[-decaying_consecutive:])
    ):
        status = HypothesisStatus.DECAYING
        reasons.append("consecutive_oos_decay")
    elif (
        previous_status is HypothesisStatus.STABLE
        and rolling is not None
        and scores
        and rolling > 0
        and rolling <= weakening_ratio * max(scores)
    ):
        status = HypothesisStatus.WEAKENING
        reasons.append("rolling_evidence_weakened")
    elif (
        len(oos_sessions) >= sessions_for_stable
        and all(gate_results.values())
        and (rolling or 0) > 0
    ):
        status = HypothesisStatus.STABLE
    elif len({record.evaluation_date for record in completed_oos}) >= sessions_for_stable:
        status = HypothesisStatus.REJECTED
        reasons.append("stable_policy_gates_not_met")
    elif len(oos_sessions) >= sessions_for_provisional + 1 and (rolling or 0) > 0:
        status = HypothesisStatus.REPLICATED
    elif len(oos_sessions) >= sessions_for_provisional and (rolling or 0) > 0:
        status = HypothesisStatus.PROVISIONAL
    else:
        status = HypothesisStatus.EXPLORATORY

    if len(shadow) >= sessions_for_stable and all(gate_results.values()):
        grade = EvidenceGrade.E5
    elif len(oos_sessions) >= sessions_for_stable and all(gate_results.values()):
        grade = EvidenceGrade.E4
    elif confirmatory or shadow:
        grade = EvidenceGrade.E3
    elif any(bool(dict(record.metrics).get("internal_resampling_pass")) for record in records):
        grade = EvidenceGrade.E2
    else:
        grade = EvidenceGrade.E1
    return LifecycleAssessment(
        hypothesis_id,
        as_of,
        status,
        grade,
        len(sessions),
        len(confirmatory),
        len(shadow),
        consistency,
        rolling,
        tuple(dict.fromkeys(reasons)),
        len(oos_sessions),
        len(outer_folds),
        tuple(sorted(gate_results.items())),
    )


def winners_curse(
    selection_scores: Sequence[float], subsequent_oos_scores: Sequence[float]
) -> Mapping[str, float | int | None]:
    count = min(len(selection_scores), len(subsequent_oos_scores))
    if count == 0:
        return {"n": 0, "mean_selection": None, "mean_subsequent_oos": None, "mean_shrinkage": None}
    selection = selection_scores[:count]
    subsequent = subsequent_oos_scores[:count]
    return {
        "n": count,
        "mean_selection": sum(selection) / count,
        "mean_subsequent_oos": sum(subsequent) / count,
        "mean_shrinkage": sum(a - b for a, b in zip(selection, subsequent, strict=True)) / count,
    }


def _finite_optional_selection(value: float | None) -> None:
    if value is not None and not isfinite(value):
        raise ValueError("selection score difference must be finite")


def _parse_stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


def _parse_interval(value: tuple[str, str], *, label: str) -> tuple[datetime, datetime]:
    if len(value) != 2:
        raise ValueError(f"{label} interval must contain two timestamps")
    start, end = (_parse_stamp(item) for item in value)
    if start >= end:
        raise ValueError(f"{label} interval must be non-empty and forward")
    return start, end


def evidence_record_from_mapping(raw: Mapping[str, Any]) -> EvidenceRecord:
    selection_raw = raw["selection"]
    if not isinstance(selection_raw, Mapping):
        raise ValueError("evidence selection must be an object")
    selection = SelectionProvenance(
        candidate_ids=tuple(selection_raw["candidate_ids"]),
        selection_metric=str(selection_raw["selection_metric"]),
        selection_information_ts=str(selection_raw["selection_information_ts"]),
        evaluation_period_start=str(selection_raw["evaluation_period_start"]),
        selected_rank=(
            None if selection_raw["selected_rank"] is None else int(selection_raw["selected_rank"])
        ),
        candidate_scores=tuple(
            (str(item[0]), None if item[1] is None else float(item[1]))
            for item in selection_raw["candidate_scores"]
        ),
        score_difference_from_next=(
            None
            if selection_raw["score_difference_from_next"] is None
            else float(selection_raw["score_difference_from_next"])
        ),
        neighboring_results=tuple(
            (str(item[0]), None if item[1] is None else float(item[1]))
            for item in selection_raw["neighboring_results"]
        ),
        multiplicity_method=str(selection_raw["multiplicity_method"]),
        mode=ResearchMode(str(selection_raw["mode"])),
    )
    return EvidenceRecord(
        hypothesis_id=str(raw["hypothesis_id"]),
        evaluation_date=date.fromisoformat(str(raw["evaluation_date"])),
        mode=ResearchMode(str(raw["mode"])),
        training_interval=tuple(raw["training_interval"]),
        validation_interval=tuple(raw["validation_interval"]),
        test_interval=tuple(raw["test_interval"]),
        observation_count=int(raw["observation_count"]),
        effective_sample_size=float(raw["effective_sample_size"]),
        model_class=str(raw["model_class"]),
        hyperparameters=tuple(tuple(item) for item in raw["hyperparameters"]),
        feature_registry_version=str(raw["feature_registry_version"]),
        target_registry_version=str(raw["target_registry_version"]),
        policy_registry_version=str(raw["policy_registry_version"]),
        feature_run_hashes=tuple(raw["feature_run_hashes"]),
        metrics=tuple(tuple(item) for item in raw["metrics"]),
        uncertainty=tuple(tuple(item) for item in raw["uncertainty"]),
        selection=selection,
        competing_hypotheses=int(raw["competing_hypotheses"]),
        terminal_status=ExperimentStatus(str(raw["terminal_status"])),
        terminal_reason=(
            None if raw.get("terminal_reason") is None else str(raw["terminal_reason"])
        ),
        plan_hash=str(raw.get("plan_hash", "")),
        pre_session_state_hash=str(raw.get("pre_session_state_hash", "")),
        source_identity_hash=str(raw.get("source_identity_hash", "")),
        fold_hashes=tuple(str(value) for value in raw.get("fold_hashes", ())),
        authority_hash=str(raw.get("authority_hash", "")),
        coefficient_estimates=tuple(
            (str(item[0]), str(item[1]), float(item[2]), float(item[3]))
            for item in raw.get("coefficient_estimates", ())
        ),
        selected_for_outer=bool(raw.get("selected_for_outer", False)),
    )


def evidence_authority_from_mapping(raw: Mapping[str, Any]) -> EvidenceAuthority:
    return EvidenceAuthority(
        plan_hash=str(raw["plan_hash"]),
        pre_session_state_hash=str(raw["pre_session_state_hash"]),
        source_derivation_hash=str(raw["source_derivation_hash"]),
        candidate_ids=tuple(str(value) for value in raw["candidate_ids"]),
        registry_fingerprints=tuple(
            (str(item[0]), str(item[1])) for item in raw["registry_fingerprints"]
        ),
        policy_fingerprint=str(raw["policy_fingerprint"]),
        walkforward_hash=str(raw["walkforward_hash"]),
        multiplicity_hash=str(raw["multiplicity_hash"]),
        empirical_null_hash=str(raw["empirical_null_hash"]),
        surface_hashes=tuple((str(item[0]), str(item[1])) for item in raw["surface_hashes"]),
        surface_robustness_hashes=tuple(
            (str(item[0]), str(item[1])) for item in raw["surface_robustness_hashes"]
        ),
        candidate_gate_hashes=tuple(
            (str(item[0]), str(item[1])) for item in raw["candidate_gate_hashes"]
        ),
        block_bootstrap_hashes=tuple(
            (str(item[0]), str(item[1])) for item in raw["block_bootstrap_hashes"]
        ),
        mechanism_hashes=tuple(
            (str(item[0]), str(item[1])) for item in raw.get("mechanism_hashes", ())
        ),
        authority_hash=str(raw["authority_hash"]),
    )
