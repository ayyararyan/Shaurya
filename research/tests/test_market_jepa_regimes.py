from __future__ import annotations

import numpy as np

from shaurya.research.market_jepa_regimes import (
    block_bootstrap_increment,
    causal_context_features,
    downstream_targets,
    fit_regimes,
    fit_ridge_probe,
    transition_statistics,
)


def test_context_features_ignore_future_values() -> None:
    values = np.arange(80, dtype=float).reshape(40, 2)
    ends = np.asarray([11, 15, 20], dtype=np.int64)
    original = causal_context_features(values, ends, 12)
    changed = values.copy()
    changed[21:] = -999_999.0
    observed = causal_context_features(changed, ends, 12)
    np.testing.assert_allclose(original, observed)


def test_targets_align_to_declared_horizon() -> None:
    columns = [
        "futures_log_mid",
        "atm_near_straddle_to_future",
        "surface__atm_iv__near",
        "atm__option_relative_spread__near__CE",
        "atm__option_relative_spread__near__PE",
        "surface__variance_skew__near",
    ]
    raw = np.column_stack(
        (
            np.arange(30, dtype=float),
            np.arange(30, dtype=float) * 2.0,
            np.arange(30, dtype=float) * 3.0,
            np.arange(30, dtype=float) * 4.0,
            np.arange(30, dtype=float) * 6.0,
            np.arange(30, dtype=float) * 0.5,
        )
    )
    target = downstream_targets(raw, np.asarray([12], dtype=np.int64), columns, 6)
    assert target["signed_futures_return"][0] == 6.0
    assert target["signed_atm_straddle_change"][0] == 12.0
    assert target["signed_atm_iv_change"][0] == 18.0
    assert target["near_atm_spread_change"][0] == 30.0


def test_probe_reports_auc_balanced_accuracy_and_r2() -> None:
    rng = np.random.default_rng(7)
    discovery = rng.normal(size=(200, 2))
    validation = rng.normal(size=(120, 2))
    test = rng.normal(size=(120, 2))
    discovery_target = discovery[:, 0]
    validation_target = validation[:, 0]
    test_target = test[:, 0]
    result = fit_ridge_probe(
        discovery,
        validation,
        test,
        discovery_target,
        validation_target,
        test_target,
        signed=True,
    )
    assert result.roc_auc is not None and result.roc_auc > 0.99
    assert result.balanced_accuracy is not None and result.balanced_accuracy > 0.95
    assert result.r2 > 0.99


def test_regime_fit_is_reproducible_and_transition_rows_normalize() -> None:
    rng = np.random.default_rng(11)
    embedding = rng.normal(size=(200, 5))
    left = fit_regimes(embedding, 4, 42).labels_
    right = fit_regimes(embedding, 4, 42).labels_
    np.testing.assert_array_equal(left, right)
    transition = transition_statistics(left.astype(np.int64), 4)
    probabilities = np.asarray(transition["probabilities"])
    np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)


def test_paired_bootstrap_preserves_positive_loss_reduction() -> None:
    base = np.full(240, 2.0)
    augmented = np.full(240, 1.0)
    result = block_bootstrap_increment(base, augmented, draws=200)
    assert result["mean_mae_reduction"] == 1.0
    assert result["ci_low"] == 1.0
    assert result["ci_high"] == 1.0
