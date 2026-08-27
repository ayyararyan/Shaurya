"""Target-blind construction and serialization of immutable feature state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

import numpy as np

from shaurya.research.contracts import (
    FeatureObservation,
    canonical_sha256,
    immutable_feature_values,
)
from shaurya.research.registry import FrozenRegistry, declared_feature_ids


def build_feature_observation(
    *,
    observation_id: str,
    session_date: date,
    anchor_ts_ns: int,
    connection_epoch: int,
    registry: FrozenRegistry,
    source_dataset_id: str,
    source_sha256: str,
    instrument_id: str = "",
    channel: str = "",
    connection_id: str = "",
    break_segment: int = 0,
    reference_midpoint: float | None = None,
    tick_size: float | None = None,
    spread_price: float | None = None,
    values: Mapping[str, float | None],
    availability: Mapping[str, int | None],
) -> FeatureObservation:
    """Build one exact-registry row without accepting any target or result object."""

    if not isinstance(values, MappingProxyType) or not isinstance(availability, MappingProxyType):
        raise TypeError("feature builders require loader-frozen mappingproxy inputs")
    declared = set(declared_feature_ids(registry))
    observed = set(values)
    if observed != declared:
        raise ValueError(
            f"feature state must match registry exactly (missing={sorted(declared - observed)}, "
            f"extra={sorted(observed - declared)})"
        )
    return FeatureObservation(
        observation_id=observation_id,
        session_date=session_date,
        anchor_ts_ns=anchor_ts_ns,
        connection_epoch=connection_epoch,
        registry_version=registry.version,
        source_dataset_id=source_dataset_id,
        source_sha256=source_sha256,
        values=immutable_feature_values(values, availability),
        instrument_id=instrument_id,
        channel=channel,
        connection_id=connection_id,
        break_segment=break_segment,
        reference_midpoint=reference_midpoint,
        tick_size=tick_size,
        spread_price=spread_price,
    )


def feature_run_hash(rows: Sequence[FeatureObservation]) -> str:
    return canonical_sha256([row.feature_run_hash for row in rows])


@dataclass(frozen=True, slots=True)
class FeatureRedundancyArtifact:
    training_observation_ids: tuple[str, ...]
    coverage: tuple[tuple[str, float], ...]
    clusters: tuple[tuple[str, ...], ...]
    absolute_correlation_threshold: float
    training_fingerprint: str


def fit_training_only_redundancy(
    rows: Sequence[FeatureObservation],
    *,
    training_observation_ids: Sequence[str],
    absolute_correlation_threshold: float = 0.9,
) -> FeatureRedundancyArtifact:
    """Cluster redundant features from explicitly named target-free training rows only."""

    if not 0 <= absolute_correlation_threshold <= 1:
        raise ValueError("correlation threshold must lie in [0,1]")
    ids = tuple(training_observation_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("training observation IDs must be non-empty and unique")
    by_id = {row.observation_id: row for row in rows}
    if not set(ids) <= set(by_id):
        raise ValueError("unknown training observation ID")
    training = [by_id[identity] for identity in ids]
    names = sorted({name for row in training for name in row.value_map})
    coverage = tuple(
        (
            name,
            sum(row.value_map.get(name) is not None for row in training) / len(training),
        )
        for name in names
    )
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            keep, merge = sorted((left_root, right_root))
            parent[merge] = keep

    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            pairs: list[tuple[float, float]] = []
            for row in training:
                left_value = row.value_map.get(left)
                right_value = row.value_map.get(right)
                if left_value is not None and right_value is not None:
                    pairs.append((left_value, right_value))
            if len(pairs) < 3:
                continue
            left_values = np.asarray([item[0] for item in pairs])
            right_values = np.asarray([item[1] for item in pairs])
            if np.std(left_values) == 0 or np.std(right_values) == 0:
                continue
            correlation = float(np.corrcoef(left_values, right_values)[0, 1])
            if abs(correlation) >= absolute_correlation_threshold:
                union(left, right)
    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(find(name), []).append(name)
    clusters = tuple(sorted(tuple(sorted(members)) for members in grouped.values()))
    fingerprint = canonical_sha256(
        {
            "training_rows": [row.identity_payload() for row in training],
            "threshold": absolute_correlation_threshold,
        }
    )
    return FeatureRedundancyArtifact(
        ids,
        coverage,
        clusters,
        absolute_correlation_threshold,
        fingerprint,
    )
