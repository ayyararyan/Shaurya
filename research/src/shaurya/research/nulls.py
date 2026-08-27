"""Dependence-preserving empirical nulls for the complete fitted mining procedure."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from random import Random
from typing import Protocol

from shaurya.research.contracts import (
    EvaluationRow,
    HypothesisDefinition,
    ResearchMode,
    canonical_sha256,
)
from shaurya.research.source import DerivedResearchDataset
from shaurya.research.walkforward import (
    FrozenWalkForwardFold,
    NestedWalkForwardResult,
    regime_predicates_from_policy,
    run_nested_walk_forward,
)


@dataclass(frozen=True, slots=True)
class MinerRefitResult:
    """Auditable output of one full fit/preprocess/select/score run."""

    scores: tuple[tuple[str, float], ...]
    feature_matrix_hash: str
    fitted_target_hash: str
    preprocessing_hash: str
    selection_hash: str
    model_hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        ids = tuple(identity for identity, _ in self.scores)
        if not ids or ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("miner scores require a complete, sorted, unique candidate universe")
        if any(not isfinite(score) for _, score in self.scores):
            raise ValueError("miner scores must be finite")
        if tuple(identity for identity, _ in self.model_hashes) != ids:
            raise ValueError("every candidate requires a fitted model identity")
        for digest in (
            self.feature_matrix_hash,
            self.fitted_target_hash,
            self.preprocessing_hash,
            self.selection_hash,
            *(value for _, value in self.model_hashes),
        ):
            if len(digest) != 64:
                raise ValueError("complete-miner phase identities must be SHA-256 hashes")


class CompleteMinerProcedure(Protocol):
    def refit_select_score(
        self,
        feature_rows: Sequence[Mapping[str, float | None]],
        targets: Sequence[float],
        *,
        replicate_id: str,
    ) -> MinerRefitResult: ...


@dataclass(frozen=True, slots=True)
class EmpiricalNullResult:
    method: str
    candidate_ids: tuple[str, ...]
    observed_best: float
    null_best_discoveries: tuple[float, ...]
    adjusted_p_value: float
    threshold_95: float
    complete_miner_rerun: bool
    replicate_fit_hashes: tuple[str, ...]
    fingerprint: str


def _circular_shift(values: Sequence[float], *, offset: int) -> tuple[float, ...]:
    return tuple(values[offset:]) + tuple(values[:offset])


def _block_permutation(
    values: Sequence[float], *, block_size: int, generator: Random
) -> tuple[float, ...]:
    complete = [
        tuple(values[start : start + block_size]) for start in range(0, len(values), block_size)
    ]
    tail = complete.pop() if complete and len(complete[-1]) != block_size else None
    generator.shuffle(complete)
    flattened = tuple(value for block in complete for value in block)
    return flattened + (() if tail is None else tail)


def _validate_run(
    run: MinerRefitResult,
    *,
    feature_rows: Sequence[Mapping[str, float | None]],
    targets: Sequence[float],
) -> None:
    if run.feature_matrix_hash != canonical_sha256(feature_rows):
        raise ValueError("miner did not bind its refit to the target-blind feature matrix")
    if run.fitted_target_hash != canonical_sha256(targets):
        raise ValueError("miner did not refit against this replicate target")


def complete_miner_empirical_null(
    feature_rows: Sequence[Mapping[str, float | None]],
    targets: Sequence[float],
    *,
    procedure: CompleteMinerProcedure,
    replicates: int,
    seed: int,
    method: str = "circular_shift",
    block_size: int = 20,
) -> EmpiricalNullResult:
    """Refit preprocessing, models, and selection on every null target realization.

    A callback over precomputed predictions is deliberately not accepted. The procedure receives
    the original target-blind matrix and must publish target-bound identities for every refit.
    """

    if len(feature_rows) != len(targets):
        raise ValueError("feature rows and targets must align")
    if len(targets) < 2 * block_size or replicates < 1:
        raise ValueError("null simulation requires at least two blocks and one replicate")
    if not all(isfinite(value) for value in targets):
        raise ValueError("targets must be finite")
    observed = procedure.refit_select_score(feature_rows, targets, replicate_id="observed")
    _validate_run(observed, feature_rows=feature_rows, targets=targets)
    candidate_ids = tuple(identity for identity, _ in observed.scores)
    generator = Random(seed)
    maxima: list[float] = []
    fit_hashes: list[str] = []
    for index in range(replicates):
        if method == "circular_shift":
            offset = generator.randrange(block_size, len(targets) - block_size + 1)
            null_targets = _circular_shift(targets, offset=offset)
        elif method == "block_permutation":
            null_targets = _block_permutation(targets, block_size=block_size, generator=generator)
        else:
            raise ValueError("unsupported empirical-null method")
        run = procedure.refit_select_score(
            feature_rows, null_targets, replicate_id=f"null-{index:06d}"
        )
        _validate_run(run, feature_rows=feature_rows, targets=null_targets)
        if tuple(identity for identity, _ in run.scores) != candidate_ids:
            raise ValueError("every null replicate must account for every declared candidate")
        maxima.append(max(abs(value) for _, value in run.scores))
        fit_hashes.append(
            canonical_sha256(
                {
                    "target": run.fitted_target_hash,
                    "preprocessing": run.preprocessing_hash,
                    "selection": run.selection_hash,
                    "models": run.model_hashes,
                }
            )
        )
    observed_best = max(abs(value) for _, value in observed.scores)
    exceedances = sum(value >= observed_best for value in maxima)
    p_value = (exceedances + 1) / (replicates + 1)
    threshold = sorted(maxima)[max(0, int(0.95 * replicates) - 1)]
    payload = {
        "method": method,
        "candidates": candidate_ids,
        "observed": observed_best,
        "maxima": maxima,
        "fit_hashes": fit_hashes,
        "seed": seed,
        "block_size": block_size,
    }
    return EmpiricalNullResult(
        method,
        candidate_ids,
        observed_best,
        tuple(maxima),
        p_value,
        threshold,
        True,
        tuple(fit_hashes),
        canonical_sha256(payload),
    )


def negative_control_warning(
    adjusted_p_values: Sequence[float], *, false_discovery_rate: float = 0.05
) -> bool:
    if not adjusted_p_values:
        raise ValueError("negative controls cannot be empty")
    discoveries = sum(value <= false_discovery_rate for value in adjusted_p_values)
    return discoveries / len(adjusted_p_values) > false_discovery_rate


@dataclass(frozen=True, slots=True)
class NestedEmpiricalNullResult:
    candidate_ids: tuple[str, ...]
    observed_scores: tuple[tuple[str, float], ...]
    candidate_adjusted_p_values: tuple[tuple[str, float], ...]
    null_best_discoveries: tuple[float, ...]
    observed_walkforward_hash: str
    replicate_walkforward_hashes: tuple[str, ...]
    method: str
    seed: int
    minimum_shift_blocks: int
    replicates: int
    complete_miner_rerun: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if self.candidate_ids != tuple(sorted(set(self.candidate_ids))) or not self.candidate_ids:
            raise ValueError("empirical null requires a canonical candidate universe")
        if tuple(identity for identity, _ in self.observed_scores) != self.candidate_ids:
            raise ValueError("empirical null observed scores do not cover the universe")
        if (
            tuple(identity for identity, _ in self.candidate_adjusted_p_values)
            != self.candidate_ids
        ):
            raise ValueError("empirical null p-values do not cover the universe")
        if (
            self.replicates < 1
            or self.minimum_shift_blocks < 1
            or len(self.null_best_discoveries) != self.replicates
            or len(self.replicate_walkforward_hashes) != self.replicates
            or not self.complete_miner_rerun
        ):
            raise ValueError("empirical null replicate evidence is incomplete")
        payload = {
            "candidates": self.candidate_ids,
            "observed_scores": self.observed_scores,
            "adjusted": self.candidate_adjusted_p_values,
            "null_best": self.null_best_discoveries,
            "observed_walkforward_hash": self.observed_walkforward_hash,
            "replicate_walkforward_hashes": self.replicate_walkforward_hashes,
            "method": self.method,
            "seed": self.seed,
            "minimum_shift_blocks": self.minimum_shift_blocks,
            "replicates": self.replicates,
            "complete_miner_rerun": self.complete_miner_rerun,
        }
        if canonical_sha256(payload) != self.fingerprint:
            raise ValueError("empirical null fingerprint is invalid")


def _aggregate_nested_scores(
    result: NestedWalkForwardResult,
) -> tuple[tuple[str, float], ...]:
    values: dict[str, list[float]] = {identity: [] for identity in result.candidate_ids}
    for item in result.candidate_results:
        if item.selected_for_outer and item.outer_score is not None:
            values[item.hypothesis_id].append(item.outer_score)
    return tuple(
        (identity, sum(scores) / len(scores) if scores else 0.0)
        for identity, scores in sorted(values.items())
    )


def _shift_nested_targets(
    dataset: DerivedResearchDataset, *, generator: Random, minimum_shift: int
) -> tuple[EvaluationRow, ...]:
    groups: dict[tuple[object, str, str, str, str, int, int], dict[str, list[EvaluationRow]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for row in dataset.rows:
        if row.target.value is None:
            continue
        groups[
            (
                row.feature.session_date,
                row.feature.source_dataset_id,
                row.feature.instrument_id,
                row.feature.channel,
                row.feature.connection_id,
                row.feature.connection_epoch,
                row.feature.break_segment,
            )
        ][row.target.target_id].append(row)
    replacements: dict[tuple[str, str], float] = {}
    for targets in groups.values():
        counts = {target_id: len(values) for target_id, values in targets.items()}
        if not counts or min(counts.values()) < 2 * minimum_shift + 1:
            raise ValueError("null group is undersized for the frozen common shift")
        maximum_common_shift = min(counts.values()) - minimum_shift
        offset = generator.randrange(minimum_shift, maximum_common_shift + 1)
        for target_id, rows in targets.items():
            rows.sort(key=lambda row: row.feature.anchor_ts_ns)
            values = [float(row.target.value) for row in rows if row.target.value is not None]
            shifted = values[offset:] + values[:offset]
            for row, value in zip(rows, shifted, strict=True):
                replacements[(row.feature.observation_id, target_id)] = value
    shifted_rows: list[EvaluationRow] = []
    for row in dataset.rows:
        key = (row.feature.observation_id, row.target.target_id)
        replacement = replacements.get(key)
        shifted_rows.append(
            row
            if replacement is None
            else EvaluationRow(row.feature, replace(row.target, value=replacement))
        )
    return tuple(shifted_rows)


def nested_walkforward_empirical_null(
    dataset: DerivedResearchDataset,
    hypotheses: tuple[HypothesisDefinition, ...],
    folds: tuple[FrozenWalkForwardFold, ...],
    *,
    policy: Mapping[str, object],
    mode: ResearchMode,
) -> tuple[NestedWalkForwardResult, NestedEmpiricalNullResult]:
    """Rerun exact nested preprocessing, fit, selection and OOS scoring under every null."""

    raw_settings = policy.get("null_simulation")
    if not isinstance(raw_settings, Mapping):
        raise ValueError("frozen empirical-null settings are required")
    if (
        raw_settings.get("method") != "circular_shift"
        or raw_settings.get("statistic") != "maximum_absolute_score"
        or raw_settings.get("rerun_complete_miner") is not True
    ):
        raise ValueError("unsupported frozen empirical-null procedure")
    replicates = int(raw_settings.get("replicates", 0))
    seed = raw_settings.get("seed")
    minimum_shift = int(raw_settings.get("minimum_shift_blocks", 0))
    if replicates < 1 or minimum_shift < 1 or not isinstance(seed, int):
        raise ValueError("nested empirical-null settings must be frozen and positive")
    predicates = regime_predicates_from_policy(policy)
    observed = run_nested_walk_forward(
        dataset.rows, hypotheses, folds, mode=mode, regime_predicates=predicates
    )
    observed_scores = _aggregate_nested_scores(observed)
    generator = Random(seed)
    null_maxima: list[float] = []
    hashes: list[str] = []
    for _ in range(replicates):
        shifted = _shift_nested_targets(dataset, generator=generator, minimum_shift=minimum_shift)
        rerun = run_nested_walk_forward(
            shifted, hypotheses, folds, mode=mode, regime_predicates=predicates
        )
        scores = _aggregate_nested_scores(rerun)
        if tuple(identity for identity, _ in scores) != observed.candidate_ids:
            raise ValueError("null walk-forward changed the frozen candidate universe")
        null_maxima.append(max(abs(value) for _, value in scores))
        hashes.append(rerun.result_hash)
    adjusted = tuple(
        (
            identity,
            (1 + sum(value >= abs(score) for value in null_maxima)) / (replicates + 1),
        )
        for identity, score in observed_scores
    )
    payload = {
        "candidates": observed.candidate_ids,
        "observed_scores": observed_scores,
        "adjusted": adjusted,
        "null_best": null_maxima,
        "observed_walkforward_hash": observed.result_hash,
        "replicate_walkforward_hashes": hashes,
        "method": "session_circular_shift",
        "seed": seed,
        "minimum_shift_blocks": minimum_shift,
        "replicates": replicates,
        "complete_miner_rerun": True,
    }
    return observed, NestedEmpiricalNullResult(
        observed.candidate_ids,
        observed_scores,
        adjusted,
        tuple(null_maxima),
        observed.result_hash,
        tuple(hashes),
        "session_circular_shift",
        seed,
        minimum_shift,
        replicates,
        True,
        canonical_sha256(payload),
    )
