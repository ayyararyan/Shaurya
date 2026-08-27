"""Versioned target construction, intentionally separate from feature construction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from math import isclose

from shaurya.research.contracts import TargetObservation
from shaurya.research.registry import FrozenRegistry


def build_target_observation(
    *,
    observation_id: str,
    session_date: date,
    anchor_ts_ns: int,
    target_id: str,
    value: float | None,
    registry: FrozenRegistry,
    source_dataset_id: str,
    source_sha256: str,
    instrument_id: str = "",
    channel: str = "",
    connection_id: str = "",
    connection_epoch: int = 0,
    break_segment: int = 0,
    availability_ts_ns: int | None = None,
    observed_start_ts_ns: int | None = None,
    observed_end_ts_ns: int | None = None,
) -> TargetObservation:
    if registry.registry_type != "targets":
        raise ValueError("a target registry is required")
    targets = registry.payload.get("targets")
    if not isinstance(targets, tuple):
        raise ValueError("target registry requires targets")
    matches = [
        item
        for item in targets
        if isinstance(item, Mapping) and item.get("target_id") == target_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate target {target_id}")
    definition = matches[0]
    gap = float(definition["causal_gap_seconds"])
    horizon = float(definition["horizon_seconds"])
    encoded_horizon = target_id.rsplit("=", 1)[-1].removesuffix("s")
    try:
        parsed_horizon = float(encoded_horizon)
    except ValueError:
        parsed_horizon = horizon
    if not isclose(parsed_horizon, horizon):
        raise ValueError("target ID and declared horizon disagree")
    expected_start = anchor_ts_ns + round(gap * 1_000_000_000)
    expected_end = expected_start + round(horizon * 1_000_000_000)
    if bool(observed_start_ts_ns is None) != bool(observed_end_ts_ns is None):
        raise ValueError("target endpoint observations must be supplied together")
    tolerance = round(float(definition.get("endpoint_tolerance_seconds", 0)) * 1_000_000_000)
    start = expected_start if observed_start_ts_ns is None else observed_start_ts_ns
    end = expected_end if observed_end_ts_ns is None else observed_end_ts_ns
    if abs(start - expected_start) > tolerance or abs(end - expected_end) > tolerance:
        raise ValueError("observed target endpoint exceeds the registered tolerance")
    return TargetObservation(
        observation_id,
        target_id,
        session_date,
        start,
        end,
        end if availability_ts_ns is None else availability_ts_ns,
        value,
        registry.version,
        source_dataset_id,
        source_sha256,
        instrument_id,
        channel,
        connection_id,
        connection_epoch,
        break_segment,
    )
