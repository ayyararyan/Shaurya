"""Complete predictive surfaces and neighborhood robustness diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite

import numpy as np

from shaurya.research.contracts import HypothesisDefinition, canonical_sha256


@dataclass(frozen=True, slots=True, order=True)
class SurfaceCell:
    coordinates: tuple[tuple[str, float | str], ...]
    hypothesis_id: str
    score: float | None
    sign: int | None
    sample_count: int

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.coordinates)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("surface coordinates must be uniquely named and sorted")
        if self.score is not None and not isfinite(self.score):
            raise ValueError("surface score must be finite")
        if self.sign not in {-1, 0, 1, None} or self.sample_count < 0:
            raise ValueError("invalid sign or support")


@dataclass(frozen=True, slots=True)
class PredictiveSurface:
    surface_id: str
    mechanism: str
    axes: tuple[str, ...]
    expected_coordinates: tuple[tuple[tuple[str, float | str], ...], ...]
    cells: tuple[SurfaceCell, ...]
    surface_hash: str
    axis_adjacency: tuple[
        tuple[str, tuple[tuple[float | str, float | str], ...]], ...
    ] = ()


def hypothesis_surface(
    hypotheses: Sequence[HypothesisDefinition],
    *,
    scores: Mapping[str, float | None],
    support: Mapping[str, int],
) -> PredictiveSurface:
    """Materialize every registered OFI axis cell rather than retaining a winner."""

    ids = {item.hypothesis_id for item in hypotheses}
    if ids != set(scores) or ids != set(support) or not ids:
        raise ValueError("surface evidence must cover the exact hypothesis universe")
    cells: list[SurfaceCell] = []
    axis_values: dict[str, set[float | str]] = {
        name: set()
        for name in (
            "depth",
            "model",
            "pooling",
            "regime",
            "sampling_clock",
            "target_horizon",
            "window",
        )
    }
    for hypothesis in hypotheses:
        predictor = hypothesis.predictor_feature_ids[0]
        if predictor == "control.source_keyed_ar1_phi_0_8":
            depth, window = 0.0, 0.8
        else:
            try:
                depth = float(predictor.split("depth=", 1)[1].split(".", 1)[0])
                window = float(predictor.split("window=", 1)[1].removesuffix("s"))
            except (IndexError, ValueError) as exc:
                raise ValueError(
                    "registered surface predictor has no executable coordinates"
                ) from exc
        coordinates: tuple[tuple[str, float | str], ...] = tuple(
            sorted(
                (
                    ("depth", depth),
                    ("model", hypothesis.model_class),
                    ("pooling", hypothesis.pooling_coordinate),
                    ("regime", hypothesis.admissible_regime),
                    ("sampling_clock", hypothesis.sampling_clock),
                    ("target_horizon", hypothesis.target_horizon_seconds),
                    ("window", window),
                )
            )
        )
        for name, value in coordinates:
            axis_values[name].add(value)
        score = scores[hypothesis.hypothesis_id]
        cells.append(
            SurfaceCell(
                coordinates,
                hypothesis.hypothesis_id,
                score,
                None if score is None else (1 if score > 0 else -1 if score < 0 else 0),
                support[hypothesis.hypothesis_id],
            )
        )
    axes = tuple(sorted(axis_values))
    mechanism = (
        "NEGATIVE_CONTROL"
        if all(item.family.upper().startswith("NEGATIVE_CONTROL") for item in hypotheses)
        else "ORDER_FLOW_IMPACT"
    )
    return build_complete_surface(
        mechanism=mechanism,
        axes=axes,
        axis_values={
            name: tuple(sorted(values, key=lambda value: (isinstance(value, str), value)))
            for name, values in axis_values.items()
        },
        cells=cells,
    )


def partitioned_hypothesis_surfaces(
    hypotheses: Sequence[HypothesisDefinition],
    *,
    scores: Mapping[str, float | None],
    support: Mapping[str, int],
) -> dict[str, tuple[PredictiveSurface, SurfaceRobustness]]:
    """Keep diagnostic controls out of real-alpha surface geometry."""

    controls = tuple(
        item for item in hypotheses if item.family.upper().startswith("NEGATIVE_CONTROL")
    )
    alpha = tuple(item for item in hypotheses if item not in controls)
    groups = (("ORDER_FLOW_IMPACT", alpha), ("NEGATIVE_CONTROL", controls))
    result: dict[str, tuple[PredictiveSurface, SurfaceRobustness]] = {}
    for name, members in groups:
        if not members:
            continue
        ids = {item.hypothesis_id for item in members}
        surface = hypothesis_surface(
            members,
            scores={identity: scores[identity] for identity in ids},
            support={identity: support[identity] for identity in ids},
        )
        result[name] = (surface, surface_robustness(surface))
    return result


def build_complete_surface(
    *,
    mechanism: str,
    axes: Sequence[str],
    axis_values: Mapping[str, Sequence[float | str]],
    cells: Sequence[SurfaceCell],
) -> PredictiveSurface:
    ordered_axes = tuple(axes)
    if set(ordered_axes) != set(axis_values) or len(ordered_axes) != len(set(ordered_axes)):
        raise ValueError("axis names and values differ")
    if any(not values or len(tuple(values)) != len(set(values)) for values in axis_values.values()):
        raise ValueError("surface axis coordinates must be non-empty and unique")
    expected: list[tuple[tuple[str, float | str], ...]] = [()]
    for axis in ordered_axes:
        expected = [
            (*coordinates, (axis, value)) for coordinates in expected for value in axis_values[axis]
        ]
    normalized_expected = tuple(tuple(sorted(item)) for item in expected)
    by_coordinates = {cell.coordinates: cell for cell in cells}
    if len(by_coordinates) != len(cells):
        raise ValueError("surface contains duplicate cells")
    if set(by_coordinates) != set(normalized_expected):
        missing = set(normalized_expected) - set(by_coordinates)
        extra = set(by_coordinates) - set(normalized_expected)
        raise ValueError(f"surface is incomplete (missing={len(missing)}, extra={len(extra)})")
    ordered_cells = tuple(by_coordinates[item] for item in normalized_expected)
    payload: dict[str, object] = {
        "mechanism": mechanism,
        "axes": ordered_axes,
        "expected": normalized_expected,
        "cells": [asdict(cell) for cell in ordered_cells],
        "axis_adjacency": (),
    }
    adjacency: list[tuple[str, tuple[tuple[float | str, float | str], ...]]] = []
    for axis in ordered_axes:
        values = tuple(axis_values[axis])
        if all(isinstance(value, (int, float)) for value in values):
            edges = tuple(
                (left, right) for left, right in zip(values, values[1:], strict=False)
            )
        else:
            # Categorical topology is explicit (a complete graph), never inferred by ordinal
            # position. Registries may narrow this graph in a future version.
            edges = tuple(
                (left, right)
                for index, left in enumerate(values)
                for right in values[index + 1 :]
            )
        adjacency.append((axis, edges))
    payload["axis_adjacency"] = adjacency
    digest = canonical_sha256(payload)
    return PredictiveSurface(
        f"surface-{digest[:24]}",
        mechanism,
        ordered_axes,
        normalized_expected,
        ordered_cells,
        digest,
        tuple(adjacency),
    )


def _adjacent(surface: PredictiveSurface, axis: str, left: object, right: object) -> bool:
    edges = dict(surface.axis_adjacency).get(axis, ())
    return (left, right) in edges or (right, left) in edges


@dataclass(frozen=True, slots=True)
class SurfaceRobustness:
    best_hypothesis_id: str | None
    best_coordinates: tuple[tuple[str, float | str], ...] | None
    neighbor_count: int
    neighbor_sign_agreement: float | None
    local_rank_stability: float | None
    predictive_region_width: int
    isolated_spike: bool
    robustness_score: float
    indistinguishable_hypothesis_ids: tuple[str, ...]
    axes: tuple[str, ...] = ()
    region_average_score: float | None = None
    robustness_hash: str = ""


def surface_robustness(surface: PredictiveSurface, *, tolerance: float = 0.15) -> SurfaceRobustness:
    finite = [cell for cell in surface.cells if cell.score is not None]
    if not finite:
        return _with_robustness_hash(
            SurfaceRobustness(None, None, 0, None, None, 0, False, 0.0, (), surface.axes),
            surface.surface_hash,
            tolerance,
        )

    def score(cell: SurfaceCell) -> float:
        if cell.score is None:
            raise AssertionError("only finite cells may reach surface diagnostics")
        return cell.score

    best = max(finite, key=lambda cell: (abs(score(cell)), cell.hypothesis_id))
    best_map = dict(best.coordinates)
    neighbors: list[SurfaceCell] = []
    for cell in finite:
        if cell == best:
            continue
        differences = 0
        adjacent = True
        current = dict(cell.coordinates)
        for axis in surface.axes:
            if current[axis] == best_map[axis]:
                continue
            differences += 1
            if not _adjacent(surface, axis, current[axis], best_map[axis]):
                adjacent = False
        if differences == 1 and adjacent:
            neighbors.append(cell)
    agreement = (
        sum(cell.sign == best.sign for cell in neighbors) / len(neighbors) if neighbors else None
    )
    best_abs = abs(score(best))
    threshold = best_abs * (1 - tolerance)
    eligible = {cell.coordinates: cell for cell in finite if abs(score(cell)) >= threshold}
    connected: dict[tuple[tuple[str, float | str], ...], SurfaceCell] = {best.coordinates: best}
    frontier = [best.coordinates]
    while frontier:
        origin = frontier.pop()
        origin_map = dict(origin)
        for coordinates, cell in eligible.items():
            if coordinates in connected:
                continue
            current = dict(coordinates)
            differences = 0
            adjacent = True
            for axis in surface.axes:
                if current[axis] == origin_map[axis]:
                    continue
                differences += 1
                if not _adjacent(surface, axis, current[axis], origin_map[axis]):
                    adjacent = False
            if differences == 1 and adjacent:
                connected[coordinates] = cell
                frontier.append(coordinates)
    indistinguishable = tuple(sorted(cell.hypothesis_id for cell in connected.values()))
    region_width = len(indistinguishable)
    local_scores = [abs(score(cell)) for cell in neighbors]
    local_rank = (
        float(np.mean([score / best_abs for score in local_scores]))
        if local_scores and best_abs > 0
        else None
    )
    isolated = bool(neighbors and all(score < 0.25 * best_abs for score in local_scores))
    robustness = (agreement or 0.0) * min(1.0, region_width / max(1, len(neighbors) + 1))
    if isolated:
        robustness *= 0.5
    return _with_robustness_hash(
        SurfaceRobustness(
            best.hypothesis_id,
            best.coordinates,
            len(neighbors),
            agreement,
            local_rank,
            region_width,
            isolated,
            robustness,
            indistinguishable,
            surface.axes,
            float(np.mean([score(cell) for cell in connected.values()])),
        ),
        surface.surface_hash,
        tolerance,
    )


def _with_robustness_hash(
    result: SurfaceRobustness, surface_hash: str, tolerance: float
) -> SurfaceRobustness:
    payload = asdict(result)
    payload["robustness_hash"] = ""
    return SurfaceRobustness(
        **{
            **payload,
            "robustness_hash": canonical_sha256(
                {"surface_hash": surface_hash, "tolerance": tolerance, "result": payload}
            ),
        }
    )


def validate_surface_artifacts(
    surface: PredictiveSurface, robustness: SurfaceRobustness, *, tolerance: float = 0.15
) -> None:
    rebuilt = build_complete_surface(
        mechanism=surface.mechanism,
        axes=surface.axes,
        axis_values={
            axis: tuple(
                dict.fromkeys(
                    dict(coordinates)[axis] for coordinates in surface.expected_coordinates
                )
            )
            for axis in surface.axes
        },
        cells=surface.cells,
    )
    if rebuilt != surface:
        raise ValueError("predictive surface content/hash is invalid")
    if surface_robustness(surface, tolerance=tolerance) != robustness:
        raise ValueError("surface robustness content/hash is invalid")


def candidate_local_robustness(surface: PredictiveSurface) -> tuple[tuple[str, float], ...]:
    """Compute a distinct local sign-and-magnitude continuity score for every cell."""

    results: list[tuple[str, float]] = []
    for cell in surface.cells:
        if cell.score is None or cell.sign is None:
            results.append((cell.hypothesis_id, 0.0))
            continue
        origin = dict(cell.coordinates)
        neighbors: list[SurfaceCell] = []
        for other in surface.cells:
            if other == cell or other.score is None:
                continue
            current = dict(other.coordinates)
            changed = [axis for axis in surface.axes if current[axis] != origin[axis]]
            if len(changed) != 1:
                continue
            axis = changed[0]
            if _adjacent(surface, axis, current[axis], origin[axis]):
                neighbors.append(other)
        if not neighbors:
            results.append((cell.hypothesis_id, 0.0))
            continue
        sign_agreement = sum(item.sign == cell.sign for item in neighbors) / len(neighbors)
        cell_score = abs(cell.score)
        neighbor_scores = [abs(item.score) for item in neighbors if item.score is not None]
        magnitude = sum(
            min(item_score, cell_score) / max(item_score, cell_score, 1e-12)
            for item_score in neighbor_scores
        ) / len(neighbor_scores)
        results.append((cell.hypothesis_id, sign_agreement * magnitude))
    return tuple(sorted(results))


def candidate_neighbors(
    surface: PredictiveSurface, hypothesis_id: str
) -> tuple[tuple[str, float | None], ...]:
    by_id = {cell.hypothesis_id: cell for cell in surface.cells}
    if hypothesis_id not in by_id:
        raise ValueError("candidate is absent from the predictive surface")
    origin = dict(by_id[hypothesis_id].coordinates)
    neighbors: list[tuple[str, float | None]] = []
    for cell in surface.cells:
        if cell.hypothesis_id == hypothesis_id:
            continue
        current = dict(cell.coordinates)
        changed = [axis for axis in surface.axes if current[axis] != origin[axis]]
        if len(changed) == 1 and _adjacent(
            surface, changed[0], current[changed[0]], origin[changed[0]]
        ):
            neighbors.append((cell.hypothesis_id, cell.score))
    return tuple(sorted(neighbors))


def parameter_movement(
    previous: SurfaceRobustness,
    current: SurfaceRobustness,
    *,
    current_surface: PredictiveSurface | None = None,
) -> Mapping[str, object]:
    if previous.best_coordinates is None or current.best_coordinates is None:
        return {"classification": "insufficient", "distance": None}
    if previous.axes != current.axes:
        raise ValueError("parameter movement surfaces must have identical registered axes")
    previous_map = dict(previous.best_coordinates)
    distance = sum(previous_map.get(axis) != value for axis, value in current.best_coordinates)
    overlap = bool(
        set(previous.indistinguishable_hypothesis_ids)
        & set(current.indistinguishable_hypothesis_ids)
    )
    previous_rank: int | None = None
    if current_surface is not None and previous.best_hypothesis_id is not None:
        def absolute_score(cell: SurfaceCell) -> float:
            if cell.score is None:
                raise AssertionError("ranked cells must have finite scores")
            return abs(cell.score)

        ranked = sorted(
            (cell for cell in current_surface.cells if cell.score is not None),
            key=lambda cell: (-absolute_score(cell), cell.hypothesis_id),
        )
        previous_rank = next(
            (
                index
                for index, cell in enumerate(ranked, start=1)
                if cell.hypothesis_id == previous.best_hypothesis_id
            ),
            None,
        )
    return {
        "classification": "parameter_movement_within_uncertainty"
        if overlap
        else "parameter_instability",
        "distance": distance,
        "confidence_regions_overlap": overlap,
        "previous_optimum_rank": previous_rank,
        "previous_optimum_in_current_region": previous.best_hypothesis_id
        in current.indistinguishable_hypothesis_ids,
    }
