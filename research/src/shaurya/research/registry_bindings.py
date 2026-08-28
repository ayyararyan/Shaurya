"""Named immutable registry bundles for explicit research-system selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegistryBinding:
    feature_registry: str
    target_registry: str
    hypothesis_registry: str
    policy_registry: str


HIGH_FREQUENCY_REGISTRY_BINDING = RegistryBinding(
    "microstructure_features_v2",
    "microstructure_targets_v2",
    "alpha_hypotheses_v2",
    "alpha_research_policy_v2",
)
