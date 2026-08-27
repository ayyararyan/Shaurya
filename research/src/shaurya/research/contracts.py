"""Immutable contracts shared by the post-market research pipeline.

The feature-side contracts intentionally have no target field.  Targets only meet feature
observations inside an explicitly dated evaluation split.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path
from types import MappingProxyType

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def canonical_json(value: object) -> str:
    """Return the one canonical serialization used for every durable identity."""

    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc_iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _finite_optional(value: float | None, *, label: str) -> None:
    if value is not None and not isfinite(value):
        raise ValueError(f"{label} must be finite when present")


class ResearchMode(StrEnum):
    EXPLORATORY = "exploratory"
    CONFIRMATORY = "confirmatory_walk_forward"
    LIVE_SHADOW = "live_shadow"


class HypothesisStatus(StrEnum):
    UNTESTED = "UNTESTED"
    EXPLORATORY = "EXPLORATORY"
    PROVISIONAL = "PROVISIONAL"
    REPLICATED = "REPLICATED"
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    DECAYING = "DECAYING"
    DORMANT = "DORMANT"
    REJECTED = "REJECTED"


class EvidenceGrade(StrEnum):
    E0 = "E0_UNTESTED"
    E1 = "E1_EXPLORATORY"
    E2 = "E2_INTERNAL_RESAMPLING"
    E3 = "E3_NESTED_WALK_FORWARD"
    E4 = "E4_MULTI_SESSION_REPLICATION"
    E5 = "E5_PROSPECTIVE_SHADOW"


class ExperimentStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True, order=True)
class FeatureValue:
    feature_id: str
    value: float | None
    available_ts_ns: int | None

    def __post_init__(self) -> None:
        if not self.feature_id:
            raise ValueError("feature_id is required")
        _finite_optional(self.value, label=self.feature_id)
        if self.value is not None and self.available_ts_ns is None:
            raise ValueError("a non-missing feature requires an availability timestamp")


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """A deeply immutable, target-blind feature state at one causal anchor."""

    observation_id: str
    session_date: date
    anchor_ts_ns: int
    connection_epoch: int
    registry_version: str
    source_dataset_id: str
    source_sha256: str
    values: tuple[FeatureValue, ...]
    instrument_id: str = ""
    channel: str = ""
    connection_id: str = ""
    break_segment: int = 0
    reference_midpoint: float | None = None
    tick_size: float | None = None
    spread_price: float | None = None
    feature_run_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.observation_id or not self.registry_version or not self.source_dataset_id:
            raise ValueError("observation, registry and source identities are required")
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 must be a SHA-256 digest")
        identities = (self.instrument_id, self.channel, self.connection_id)
        if any(identities) and not all(identities):
            raise ValueError(
                "feature instrument, channel, and connection identities must be supplied together"
            )
        if self.break_segment < 0:
            raise ValueError("feature break segment cannot be negative")
        if self.reference_midpoint is not None and (
            not isfinite(self.reference_midpoint) or self.reference_midpoint <= 0
        ):
            raise ValueError("feature reference midpoint must be finite and positive")
        for label, value in (("tick size", self.tick_size), ("spread price", self.spread_price)):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"feature {label} must be finite and positive")
        if (self.tick_size is None) != (self.spread_price is None):
            raise ValueError("feature tick size and spread price must be retained together")
        names = tuple(item.feature_id for item in self.values)
        if len(names) != len(set(names)):
            raise ValueError("feature observation contains duplicate features")
        if names != tuple(sorted(names)):
            raise ValueError("feature values must be sorted by stable feature_id")
        for item in self.values:
            if item.available_ts_ns is not None and item.available_ts_ns > self.anchor_ts_ns:
                raise ValueError(f"feature {item.feature_id} is available after the anchor")
        object.__setattr__(self, "feature_run_hash", canonical_sha256(self.identity_payload()))

    def identity_payload(self) -> Mapping[str, object]:
        return {
            "observation_id": self.observation_id,
            "session_date": self.session_date.isoformat(),
            "anchor_ts_ns": self.anchor_ts_ns,
            "connection_epoch": self.connection_epoch,
            "registry_version": self.registry_version,
            "source_dataset_id": self.source_dataset_id,
            "source_sha256": self.source_sha256,
            "instrument_id": self.instrument_id,
            "channel": self.channel,
            "connection_id": self.connection_id,
            "break_segment": self.break_segment,
            "reference_midpoint": self.reference_midpoint,
            "tick_size": self.tick_size,
            "spread_price": self.spread_price,
            "values": [
                {
                    "feature_id": item.feature_id,
                    "value": item.value,
                    "available_ts_ns": item.available_ts_ns,
                }
                for item in self.values
            ],
        }

    @property
    def value_map(self) -> Mapping[str, float | None]:
        return MappingProxyType({item.feature_id: item.value for item in self.values})


@dataclass(frozen=True, slots=True)
class TargetObservation:
    observation_id: str
    target_id: str
    session_date: date
    interval_start_ts_ns: int
    interval_end_ts_ns: int
    available_ts_ns: int
    value: float | None
    registry_version: str
    source_dataset_id: str = ""
    source_sha256: str = ""
    instrument_id: str = ""
    channel: str = ""
    connection_id: str = ""
    connection_epoch: int = 0
    break_segment: int = 0
    target_run_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.interval_start_ts_ns >= self.interval_end_ts_ns:
            raise ValueError("target interval must be non-empty")
        if self.available_ts_ns < self.interval_end_ts_ns:
            raise ValueError("target cannot be available before its interval ends")
        _finite_optional(self.value, label=self.target_id)
        if bool(self.source_dataset_id) != bool(self.source_sha256):
            raise ValueError("target source dataset and SHA-256 must be supplied together")
        if self.source_sha256 and len(self.source_sha256) != 64:
            raise ValueError("target source_sha256 must be a SHA-256 digest")
        identities = (self.instrument_id, self.channel, self.connection_id)
        if any(identities) and not all(identities):
            raise ValueError(
                "target instrument, channel, and connection identities must be supplied together"
            )
        if self.connection_epoch < 0 or self.break_segment < 0:
            raise ValueError("target connection epoch and break segment cannot be negative")
        object.__setattr__(
            self,
            "target_run_hash",
            canonical_sha256(
                {
                    "observation_id": self.observation_id,
                    "target_id": self.target_id,
                    "session_date": self.session_date,
                    "interval_start_ts_ns": self.interval_start_ts_ns,
                    "interval_end_ts_ns": self.interval_end_ts_ns,
                    "available_ts_ns": self.available_ts_ns,
                    "value": self.value,
                    "registry_version": self.registry_version,
                    "source_dataset_id": self.source_dataset_id,
                    "source_sha256": self.source_sha256,
                    "instrument_id": self.instrument_id,
                    "channel": self.channel,
                    "connection_id": self.connection_id,
                    "connection_epoch": self.connection_epoch,
                    "break_segment": self.break_segment,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    """The only contract in which a target is joined to an immutable feature row."""

    feature: FeatureObservation
    target: TargetObservation

    def __post_init__(self) -> None:
        if self.feature.observation_id != self.target.observation_id:
            raise ValueError("feature and target observation IDs differ")
        if self.feature.session_date != self.target.session_date:
            raise ValueError("feature and target sessions differ")
        if self.target.interval_start_ts_ns <= self.feature.anchor_ts_ns:
            raise ValueError("target must start strictly after the feature anchor")
        if not self.feature.source_dataset_id or not self.target.source_dataset_id:
            raise ValueError("feature/target join requires non-empty canonical source identities")
        if self.feature.source_dataset_id != self.target.source_dataset_id:
            raise ValueError("feature and target source datasets differ")
        if self.feature.source_sha256 != self.target.source_sha256:
            raise ValueError("feature and target source hashes differ")
        if self.feature.instrument_id and (
            self.feature.instrument_id,
            self.feature.channel,
            self.feature.connection_id,
            self.feature.connection_epoch,
            self.feature.break_segment,
        ) != (
            self.target.instrument_id,
            self.target.channel,
            self.target.connection_id,
            self.target.connection_epoch,
            self.target.break_segment,
        ):
            raise ValueError("feature and target discontinuity identities differ")


@dataclass(frozen=True, slots=True)
class HypothesisDefinition:
    """A hypothesis identity; aliases never create new statistical evidence."""

    display_name: str
    family: str
    predictor_feature_ids: tuple[str, ...]
    target_id: str
    target_horizon_seconds: float
    conditioning_variables: tuple[str, ...]
    admissible_regime: str
    model_class: str
    fitting_window_sessions: int
    training_cadence_seconds: float
    regularization: tuple[tuple[str, JSONScalar], ...]
    evaluation_metric: str
    transaction_cost_relevance: str
    first_registration_date: date
    registry_version: str
    sampling_clock: str = "calendar_1s"
    pooling_coordinate: str = "instrument"
    selection_method: str = "nested_past_only"
    selection_threshold: float = 0.15
    minimum_observations: int = 100
    minimum_effective_sample_size: float = 50.0
    hypothesis_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.predictor_feature_ids:
            raise ValueError("a hypothesis requires at least one predictor")
        if len(self.predictor_feature_ids) != len(set(self.predictor_feature_ids)):
            raise ValueError("hypothesis predictors must be unique")
        if len(self.conditioning_variables) != len(set(self.conditioning_variables)):
            raise ValueError("hypothesis conditioning variables must be unique")
        if set(self.predictor_feature_ids) & set(self.conditioning_variables):
            raise ValueError("conditioning variables cannot duplicate predictors")
        if self.target_horizon_seconds <= 0 or self.fitting_window_sessions < 1:
            raise ValueError("target horizon and fitting window must be positive")
        if self.training_cadence_seconds <= 0:
            raise ValueError("training cadence must be positive")
        if not self.sampling_clock or not self.pooling_coordinate or not self.selection_method:
            raise ValueError("clock, pooling coordinate and selection method are required")
        if not 0 <= self.selection_threshold <= 1:
            raise ValueError("selection threshold must lie in [0,1]")
        if self.minimum_observations < 1:
            raise ValueError("minimum observations must be positive")
        if not 0 < self.minimum_effective_sample_size <= self.minimum_observations:
            raise ValueError("minimum effective sample size must lie within observations")
        object.__setattr__(
            self, "hypothesis_id", f"alpha-{canonical_sha256(self.semantic_payload())[:24]}"
        )

    def semantic_payload(self) -> Mapping[str, object]:
        """Fields defining the statistical atom; display name is deliberately excluded."""

        return {
            "family": self.family,
            "predictor_feature_ids": sorted(self.predictor_feature_ids),
            "target_id": self.target_id,
            "target_horizon_seconds": self.target_horizon_seconds,
            "conditioning_variables": sorted(self.conditioning_variables),
            "admissible_regime": self.admissible_regime,
            "model_class": self.model_class,
            "fitting_window_sessions": self.fitting_window_sessions,
            "training_cadence_seconds": self.training_cadence_seconds,
            "regularization": sorted(self.regularization),
            "evaluation_metric": self.evaluation_metric,
            "transaction_cost_relevance": self.transaction_cost_relevance,
            "sampling_clock": self.sampling_clock,
            "pooling_coordinate": self.pooling_coordinate,
            "selection_method": self.selection_method,
            "selection_threshold": self.selection_threshold,
            "minimum_observations": self.minimum_observations,
            "minimum_effective_sample_size": self.minimum_effective_sample_size,
        }


def immutable_feature_values(
    values: Mapping[str, float | None], availability: Mapping[str, int | None]
) -> tuple[FeatureValue, ...]:
    if set(values) != set(availability):
        raise ValueError("feature values and availability must have identical names")
    return tuple(FeatureValue(name, values[name], availability[name]) for name in sorted(values))


def require_unique_strings(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not value for value in result) or len(result) != len(set(result)):
        raise ValueError(f"{label} must be non-empty and unique")
    return result
