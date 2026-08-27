"""Strict loader and expander for the checked-in JSON-compatible YAML registries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from shaurya.research.contracts import HypothesisDefinition, JSONScalar, canonical_sha256


@dataclass(frozen=True, slots=True)
class FrozenRegistry:
    registry_type: str
    version: str
    payload: Mapping[str, Any]
    source_path: Path
    fingerprint_sha256: str


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return cast(Mapping[str, Any], value)


def load_registry(path: Path, *, expected_type: str | None = None) -> FrozenRegistry:
    """Load JSON syntax from a ``.yaml`` file without adding a YAML dependency."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = _require_mapping(raw, label=str(path))
    registry_type = payload.get("registry_type")
    version = payload.get("version")
    if not isinstance(registry_type, str) or not isinstance(version, str):
        raise ValueError("registry_type and version are required strings")
    if expected_type is not None and registry_type != expected_type:
        raise ValueError(f"expected {expected_type} registry, found {registry_type}")
    if payload.get("frozen") is not True:
        raise ValueError("research registries must be explicitly frozen")
    return FrozenRegistry(
        registry_type,
        version,
        cast(Mapping[str, Any], _deep_freeze(dict(payload))),
        path,
        canonical_sha256(payload),
    )


def registry_by_version(directory: Path, version: str, *, expected_type: str) -> FrozenRegistry:
    matches = [
        registry
        for path in sorted(directory.glob("*.yaml"))
        if (registry := load_registry(path)).version == version
        and registry.registry_type == expected_type
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {expected_type} registry version {version}, found {len(matches)}"
        )
    return matches[0]


def _scalar_pairs(
    value: object, *, model_class: str | None = None
) -> tuple[tuple[str, JSONScalar], ...]:
    mapping = _require_mapping(value, label="regularization")
    relevant = {
        "ridge": {"ridge_penalty"},
        "elastic_net": {"elastic_alpha", "elastic_l1_ratio"},
    }.get(model_class or "", set(mapping))
    pairs: list[tuple[str, JSONScalar]] = []
    for key, item in sorted(mapping.items()):
        if key not in relevant:
            continue
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("regularization values must be JSON scalars")
        pairs.append((key, item))
    return tuple(pairs)


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, (int, str)):
        raise ValueError(f"{label} must be an integer")
    return int(value)


def expand_hypotheses(registry: FrozenRegistry) -> tuple[HypothesisDefinition, ...]:
    if registry.registry_type != "hypotheses":
        raise ValueError("a hypothesis registry is required")
    templates = registry.payload.get("templates")
    if not isinstance(templates, (list, tuple)):
        raise ValueError("hypothesis registry requires templates")
    hypotheses: list[HypothesisDefinition] = []
    seen: dict[str, HypothesisDefinition] = {}
    for raw_template in templates:
        template = _require_mapping(raw_template, label="hypothesis template")
        axes = _require_mapping(template.get("axes", {}), label="hypothesis axes")
        allowed_axes = {
            "depth",
            "window",
            "model_class",
            "regime",
            "target_horizon_seconds",
            "sampling_clock",
            "pooling_coordinate",
            "fitting_window_sessions",
        }
        if set(axes) - allowed_axes:
            raise ValueError(f"undeclared hypothesis axes: {sorted(set(axes) - allowed_axes)}")
        axis_items: list[tuple[str, tuple[object, ...]]] = []
        for name, raw_values in sorted(axes.items()):
            if not isinstance(raw_values, (list, tuple)) or not raw_values:
                raise ValueError(f"axis {name} must be a non-empty list")
            axis_items.append((name, tuple(raw_values)))

        combinations: list[dict[str, object]] = [{}]
        for name, values in axis_items:
            combinations = [
                {**combination, name: value} for combination in combinations for value in values
            ]
        for combination in combinations:
            format_values = {key: str(value) for key, value in combination.items()}
            predictor_templates = template.get("predictor_feature_ids")
            if not isinstance(predictor_templates, (list, tuple)) or not predictor_templates:
                raise ValueError("predictor_feature_ids must be a non-empty list")
            predictors = tuple(str(value).format(**format_values) for value in predictor_templates)
            hypothesis = HypothesisDefinition(
                display_name=str(template["display_name"]).format(**format_values),
                family=str(template["family"]),
                predictor_feature_ids=predictors,
                target_id=str(template["target_id"]).format(**format_values),
                target_horizon_seconds=_number(
                    combination.get("target_horizon_seconds", template["target_horizon_seconds"]),
                    label="target_horizon_seconds",
                ),
                conditioning_variables=tuple(
                    str(value) for value in template.get("conditioning_variables", [])
                ),
                admissible_regime=str(
                    combination.get("regime", template.get("admissible_regime", "global"))
                ),
                model_class=str(combination.get("model_class", template["model_class"])),
                fitting_window_sessions=_integer(
                    combination.get("fitting_window_sessions", template["fitting_window_sessions"]),
                    label="fitting_window_sessions",
                ),
                training_cadence_seconds=float(template["training_cadence_seconds"]),
                regularization=_scalar_pairs(
                    template.get("regularization", {}),
                    model_class=str(combination.get("model_class", template["model_class"])),
                ),
                evaluation_metric=str(template["evaluation_metric"]),
                transaction_cost_relevance=str(
                    template.get("transaction_cost_relevance", "diagnostic_only")
                ),
                first_registration_date=date.fromisoformat(
                    str(template["first_registration_date"])
                ),
                registry_version=registry.version,
                sampling_clock=str(
                    combination.get("sampling_clock", template.get("sampling_clock", "calendar_1s"))
                ),
                pooling_coordinate=str(
                    combination.get(
                        "pooling_coordinate", template.get("pooling_coordinate", "instrument")
                    )
                ),
                selection_method=str(template.get("selection_method", "nested_past_only")),
                selection_threshold=_number(
                    template.get("selection_threshold", 0.15), label="selection_threshold"
                ),
                minimum_observations=_integer(
                    template.get("minimum_observations", 100), label="minimum_observations"
                ),
                minimum_effective_sample_size=_number(
                    template.get("minimum_effective_sample_size", 50),
                    label="minimum_effective_sample_size",
                ),
            )
            previous = seen.get(hypothesis.hypothesis_id)
            if previous is not None:
                if previous.semantic_payload() != hypothesis.semantic_payload():
                    raise ValueError("hypothesis identity collision")
                raise ValueError(
                    f"duplicate semantic hypothesis registered as {previous.display_name!r} and "
                    f"{hypothesis.display_name!r}"
                )
            seen[hypothesis.hypothesis_id] = hypothesis
            hypotheses.append(hypothesis)
    return tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))


def declared_feature_ids(registry: FrozenRegistry) -> tuple[str, ...]:
    if registry.registry_type != "features":
        raise ValueError("a feature registry is required")
    features = registry.payload.get("features", [])
    templates = registry.payload.get("templates", [])
    if not isinstance(features, (list, tuple)) or not isinstance(templates, (list, tuple)):
        raise ValueError("feature registry features/templates must be lists")
    expanded: list[str] = [
        str(_require_mapping(item, label="feature")["feature_id"]) for item in features
    ]
    for raw_template in templates:
        template = _require_mapping(raw_template, label="feature template")
        pattern = str(template["feature_id_pattern"])
        axes = _require_mapping(template.get("axes", {}), label="feature axes")
        combinations: list[dict[str, object]] = [{}]
        for name, raw_values in sorted(axes.items()):
            if not isinstance(raw_values, (list, tuple)) or not raw_values:
                raise ValueError(f"axis {name} must be a non-empty list")
            combinations = [
                {**combination, name: value} for combination in combinations for value in raw_values
            ]
        expanded.extend(pattern.format(**combination) for combination in combinations)
    ids = tuple(expanded)
    if len(ids) != len(set(ids)):
        raise ValueError("feature registry contains duplicate IDs")
    return ids


def declared_target_ids(registry: FrozenRegistry) -> tuple[str, ...]:
    if registry.registry_type != "targets":
        raise ValueError("a target registry is required")
    targets = registry.payload.get("targets")
    if not isinstance(targets, (list, tuple)):
        raise ValueError("target registry requires targets")
    ids = tuple(str(_require_mapping(item, label="target")["target_id"]) for item in targets)
    if len(ids) != len(set(ids)):
        raise ValueError("target registry contains duplicate IDs")
    return ids
