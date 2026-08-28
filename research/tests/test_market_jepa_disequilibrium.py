from __future__ import annotations

import numpy as np

from shaurya.research.market_jepa_disequilibrium import (
    classify_corrections,
    correction_decomposition,
    fit_development_ridge_map,
    latent_disequilibrium,
    subsystem_feature_lists,
)

SCHEMA = [
    "futures_log_mid",
    "futures_relative_spread",
    "futures_return_5s",
    "option_mid_to_future__near__CE",
    "option_mid_to_future__near__PE",
    "option_mid_to_future__far__CE",
    "option_mid_to_future__far__PE",
    "surface__atm_iv__near",
    "surface__atm_iv__far",
    "atm__strike__near",
    "atm__strike__far",
]


def test_subsystem_feature_separation() -> None:
    groups = subsystem_feature_lists(SCHEMA)
    assert not set(groups["futures"]) & set(groups["options"])
    assert not set(groups["near"]) & set(groups["far"])
    assert not set(groups["call"]) & set(groups["put"])
    assert all(not name.startswith("futures_") for name in groups["options"])
    assert all("strike" not in name for name in groups["options"])


def _mapping() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    discovery_source = rng.normal(size=(100, 3))
    validation_source = rng.normal(size=(60, 3))
    matrix = np.asarray([[1.0, 0.5, -0.2], [-0.3, 0.1, 0.7]])
    return (
        discovery_source,
        discovery_source @ matrix.T,
        validation_source,
        validation_source @ matrix.T,
    )


def test_futures_to_options_mapping_uses_development_only() -> None:
    mapping = fit_development_ridge_map(*_mapping())
    assert mapping.fit_roles == ("discovery", "validation")
    assert mapping.discovery_samples == 100
    assert mapping.validation_samples == 60


def test_options_to_futures_mapping_uses_development_only() -> None:
    discovery_source, discovery_target, validation_source, validation_target = _mapping()
    mapping = fit_development_ridge_map(
        discovery_target, discovery_source, validation_target, validation_source
    )
    assert mapping.fit_roles == ("discovery", "validation")
    assert mapping.predict(validation_target).shape == validation_source.shape


def test_near_far_and_call_put_feature_separation() -> None:
    groups = subsystem_feature_lists(SCHEMA)
    assert set(groups["near"]).isdisjoint(groups["far"])
    assert set(groups["call"]).isdisjoint(groups["put"])
    assert groups["call"] == [
        "option_mid_to_future__near__CE",
        "option_mid_to_future__far__CE",
    ]
    assert groups["put"] == [
        "option_mid_to_future__near__PE",
        "option_mid_to_future__far__PE",
    ]


def test_disequilibrium_and_correction_classification() -> None:
    discovery_source, discovery_target, validation_source, validation_target = _mapping()
    forward = fit_development_ridge_map(
        discovery_source, discovery_target, validation_source, validation_target
    )
    reverse = fit_development_ridge_map(
        discovery_target, discovery_source, validation_target, validation_source
    )
    source = validation_source[:10]
    target = validation_target[:10] + 2.0
    assert np.all(latent_disequilibrium(forward, source, target) > 1.0)
    correction = correction_decomposition(
        source,
        target,
        source,
        validation_target[:10],
        forward,
        reverse,
    )
    labels = classify_corrections(correction, high_forward=1.0, motion_threshold=0.1)
    assert set(labels) == {"source_led_correction"}
