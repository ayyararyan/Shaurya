"""Experiment- and family-level multiplicity accounting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

import numpy as np

from shaurya.research.contracts import canonical_sha256
from shaurya.research.walkforward import NestedWalkForwardResult
from shaurya.signals.deep_book_inference import stationary_session_block_bootstrap
from shaurya.signals.evaluation_metrics import benjamini_yekutieli


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    eligible = [
        (index, float(value))
        for index, value in enumerate(p_values)
        if value is not None and isfinite(float(value)) and 0 <= float(value) <= 1
    ]
    result: list[float | None] = [None] * len(p_values)
    total = len(eligible)
    running = 1.0
    for rank, (index, value) in reversed(
        list(enumerate(sorted(eligible, key=lambda item: item[1]), start=1))
    ):
        running = min(running, value * total / rank)
        result[index] = running
    return result


@dataclass(frozen=True, slots=True)
class AdjustedEvidence:
    hypothesis_id: str
    family: str
    raw_p_value: float
    family_adjusted_p_value: float
    experiment_adjusted_p_value: float
    method: str
    declared_family_size: int
    declared_experiment_size: int


@dataclass(frozen=True, slots=True)
class DependenceAwareInterval:
    estimate: float
    lower: float
    upper: float
    standard_error: float
    replicates: int
    mean_block_length: float


@dataclass(frozen=True, slots=True)
class CandidateBootstrapArtifact:
    hypothesis_id: str
    session_scores: tuple[tuple[str, tuple[float, ...]], ...]
    estimate: float | None
    lower: float | None
    upper: float | None
    standard_error: float | None
    replicates: int
    mean_block_length: float
    seed: int
    gate_pass: bool
    bootstrap_hash: str = ""

    def with_hash(self) -> CandidateBootstrapArtifact:
        payload = asdict(self)
        payload["bootstrap_hash"] = ""
        return CandidateBootstrapArtifact(
            **{**payload, "bootstrap_hash": canonical_sha256(payload)}
        )

    def __post_init__(self) -> None:
        if tuple(name for name, _ in self.session_scores) != tuple(
            sorted({name for name, _ in self.session_scores})
        ):
            raise ValueError("bootstrap sessions must be canonical and unique")
        available = self.estimate is not None
        if available != bool(self.session_scores) or any(
            value is None
            for value in (self.lower, self.upper, self.standard_error)
        ) != (not available):
            raise ValueError("bootstrap availability and interval disagree")
        if self.replicates < 2 or self.mean_block_length < 1:
            raise ValueError("bootstrap settings are invalid")
        if self.bootstrap_hash:
            payload = asdict(self)
            payload["bootstrap_hash"] = ""
            if canonical_sha256(payload) != self.bootstrap_hash:
                raise ValueError("candidate bootstrap artifact hash is invalid")


def candidate_bootstrap_from_mapping(raw: Mapping[str, Any]) -> CandidateBootstrapArtifact:
    return CandidateBootstrapArtifact(
        hypothesis_id=str(raw["hypothesis_id"]),
        session_scores=tuple(
            (str(item[0]), tuple(float(value) for value in item[1]))
            for item in raw["session_scores"]
        ),
        estimate=None if raw["estimate"] is None else float(raw["estimate"]),
        lower=None if raw["lower"] is None else float(raw["lower"]),
        upper=None if raw["upper"] is None else float(raw["upper"]),
        standard_error=(
            None if raw["standard_error"] is None else float(raw["standard_error"])
        ),
        replicates=int(raw["replicates"]),
        mean_block_length=float(raw["mean_block_length"]),
        seed=int(raw["seed"]),
        gate_pass=bool(raw["gate_pass"]),
        bootstrap_hash=str(raw["bootstrap_hash"]),
    )


def build_candidate_bootstrap_artifacts(
    walkforward: NestedWalkForwardResult,
    *,
    replicates: int,
    mean_block_length: float,
    seed: int,
) -> tuple[CandidateBootstrapArtifact, ...]:
    """Bootstrap exact candidate OOS fold scores without crossing session boundaries."""

    folds = {fold.fold_id: fold for fold in walkforward.folds}
    grouped: dict[str, dict[str, list[float]]] = {
        identity: {} for identity in walkforward.candidate_ids
    }
    for result in walkforward.candidate_results:
        if result.outer_score is None:
            continue
        fold = folds[result.fold_id]
        session_key = ",".join(value.isoformat() for value in fold.outer_evaluation_dates)
        grouped[result.hypothesis_id].setdefault(session_key, []).append(result.outer_score)
    artifacts: list[CandidateBootstrapArtifact] = []
    for identity in walkforward.candidate_ids:
        values = {name: tuple(scores) for name, scores in sorted(grouped[identity].items())}
        if values:
            interval = block_bootstrap_confidence_interval(
                values,
                replicates=replicates,
                mean_block_length=mean_block_length,
                seed=seed,
            )
            gate_pass = interval.lower > 0 or interval.upper < 0
            artifact = CandidateBootstrapArtifact(
                identity,
                tuple(values.items()),
                interval.estimate,
                interval.lower,
                interval.upper,
                interval.standard_error,
                replicates,
                mean_block_length,
                seed,
                gate_pass,
            )
        else:
            artifact = CandidateBootstrapArtifact(
                identity,
                (),
                None,
                None,
                None,
                None,
                replicates,
                mean_block_length,
                seed,
                False,
            )
        artifacts.append(artifact.with_hash())
    return tuple(artifacts)


def block_bootstrap_confidence_interval(
    values_by_session: Mapping[str, Sequence[float]],
    *,
    replicates: int = 399,
    mean_block_length: float = 8.0,
    seed: int = 20260826,
) -> DependenceAwareInterval:
    """Reuse Shaurya's session-preserving stationary block bootstrap."""

    samples = stationary_session_block_bootstrap(
        values_by_session,
        replicates=replicates,
        mean_block_length=mean_block_length,
        seed=seed,
    )
    draws = np.asarray([np.mean(sample) for sample in samples], dtype=np.float64)
    observed = [value for values in values_by_session.values() for value in values]
    return DependenceAwareInterval(
        float(np.mean(observed)),
        float(np.quantile(draws, 0.025)),
        float(np.quantile(draws, 0.975)),
        float(np.std(draws, ddof=1)) if replicates > 1 else 0.0,
        replicates,
        mean_block_length,
    )


def adjust_hierarchical(
    p_values: Mapping[str, float],
    families: Mapping[str, str],
    *,
    method: str = "benjamini_yekutieli",
    declared_candidate_ids: Sequence[str] | None = None,
) -> tuple[AdjustedEvidence, ...]:
    if set(p_values) != set(families):
        raise ValueError("p-values and hierarchy must contain identical hypotheses")
    ids = sorted(p_values)
    if declared_candidate_ids is not None and set(ids) != set(declared_candidate_ids):
        raise ValueError("multiplicity input must account for every declared candidate")
    if not ids or any(not 0 <= p_values[item] <= 1 for item in ids):
        raise ValueError("finite p-values in [0,1] are required")
    adjust = benjamini_yekutieli if method == "benjamini_yekutieli" else benjamini_hochberg
    if method not in {"benjamini_yekutieli", "benjamini_hochberg"}:
        raise ValueError("unsupported multiplicity method")
    experiment = adjust([p_values[item] for item in ids])
    family_adjusted: dict[str, float] = {}
    for family in sorted(set(families.values())):
        family_ids = [item for item in ids if families[item] == family]
        values = adjust([p_values[item] for item in family_ids])
        for item, value in zip(family_ids, values, strict=True):
            if value is None:
                raise AssertionError("finite p-values must produce finite adjustments")
            family_adjusted[item] = value
    experiment_adjusted = []
    for value in experiment:
        if value is None:
            raise AssertionError("finite p-values must produce finite adjustments")
        experiment_adjusted.append(value)
    return tuple(
        AdjustedEvidence(
            item,
            families[item],
            p_values[item],
            family_adjusted[item],
            experiment_adjusted[index],
            method,
            sum(families[other] == families[item] for other in ids),
            len(ids),
        )
        for index, item in enumerate(ids)
    )
