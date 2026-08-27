"""D41: incremental forecast content of displayed-mid return lags and CCZ OFI.

The frozen object contains no state-control horse race.  It compares only past displayed-mid
returns, the ten depth-scaled rank-keyed CCZ OFI levels, and their exact union on identical
chronological held-out rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import ceil, isfinite, sqrt
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from shaurya.signals.ccz_ofi import normalised_level_feature
from shaurya.signals.deep_book_normal_activity import RidgeFit, fit_ridge
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.ofi_horserace import RIDGE_ALPHAS, HorseRaceObservation, HorseRaceTapeInput

SCAN_ID = "X-D41-MID-LAG-OFI-2026-08-20"
SPECIFICATION_ID = "D41 / MID-LAG-OFI-INCREMENTAL-2026-08-20"
DESIGN_DOCUMENT = "research/docs/results/D41-MID-LAG-OFI-INCREMENTAL-SPEC-2026-08-20.md"
CLAIM_ID = "EF-11/H1"
REGISTRATION_COMMIT = "4751d1a35ead6f15e6a3c6a9bf2b5819b90ccb87"

LAG_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
OFI_WINDOWS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
HORIZONS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
CONTEMPORANEOUS_WINDOWS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
PRIMARY_OFI_WINDOW_SECONDS = 10.0
CCZ_LEVELS = 10
EMBARGO_SECONDS = 30.5
TRAIN_FRACTION = 0.70
SIGNIFICANCE_LEVEL = 0.05
MINIMUM_FIT_OBSERVATIONS = 20

Alternative = Literal["greater", "two-sided"]


@dataclass(frozen=True, slots=True)
class D41Split:
    """Chronological 70/30 split with D41's 30.5-second embargo."""

    train: tuple[int, ...]
    test: tuple[int, ...]
    embargoed: tuple[int, ...]
    embargo_seconds: float
    boundaries: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class FittedForecast:
    """One training-only fit and its raw held-out predictions."""

    payload: Mapping[str, Any]
    prediction: NDArray[np.float64]
    fit: RidgeFit


def lag_feature_name(seconds: float) -> str:
    return f"displayed_mid_return_lag_{seconds:g}s"


def lag_feature_names() -> tuple[str, ...]:
    return tuple(lag_feature_name(value) for value in LAG_SECONDS)


def ofi_feature_names(window: float) -> tuple[str, ...]:
    return tuple(
        normalised_level_feature(window, level, CCZ_LEVELS)
        for level in range(1, CCZ_LEVELS + 1)
    )


def combined_feature_names(window: float) -> tuple[str, ...]:
    return (*lag_feature_names(), *ofi_feature_names(window))


def _split(observations: Sequence[HorseRaceObservation]) -> D41Split:
    if not observations:
        raise ValueError("D41 requires at least one observation")
    by_tape: dict[int, list[int]] = {}
    for position, observation in enumerate(observations):
        by_tape.setdefault(observation.tape_index, []).append(position)
    train: list[int] = []
    test: list[int] = []
    embargoed: list[int] = []
    boundaries: list[tuple[str, int, int]] = []
    embargo_ns = int(EMBARGO_SECONDS * 1_000_000_000)
    for tape_index in sorted(by_tape):
        positions = sorted(by_tape[tape_index], key=lambda item: observations[item].receive_ts_ns)
        if len(positions) < 2:
            train.extend(positions)
            continue
        cut = max(1, int(len(positions) * TRAIN_FRACTION))
        boundary = observations[positions[cut - 1]].receive_ts_ns
        boundaries.append((str(tape_index), boundary, boundary + embargo_ns))
        for position in positions:
            stamp = observations[position].receive_ts_ns
            if stamp <= boundary:
                train.append(position)
            elif stamp <= boundary + embargo_ns:
                embargoed.append(position)
            else:
                test.append(position)
    return D41Split(
        train=tuple(sorted(train)),
        test=tuple(sorted(test)),
        embargoed=tuple(sorted(embargoed)),
        embargo_seconds=EMBARGO_SECONDS,
        boundaries=tuple(boundaries),
    )


def _epoch_bounds(
    observations: Sequence[HorseRaceObservation],
) -> dict[tuple[int, int], tuple[int, int]]:
    values: dict[tuple[int, int], list[int]] = {}
    for observation in observations:
        values.setdefault((observation.tape_index, observation.connection_epoch), []).append(
            observation.receive_ts_ns
        )
    return {key: (min(stamps), max(stamps)) for key, stamps in values.items()}


def _all_ofi_names() -> tuple[str, ...]:
    return tuple(name for window in OFI_WINDOWS_SECONDS for name in ofi_feature_names(window))


def _future_positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    *,
    horizon: float,
    epoch_bounds: Mapping[tuple[int, int], tuple[int, int]],
) -> tuple[int, ...]:
    history_ns = int(max(LAG_SECONDS) * 1_000_000_000)
    future_ns = int((CAUSAL_GAP_SECONDS + horizon) * 1_000_000_000)
    required_ofi = _all_ofi_names()
    result: list[int] = []
    for position in candidates:
        observation = observations[position]
        lower, upper = epoch_bounds[(observation.tape_index, observation.connection_epoch)]
        if observation.receive_ts_ns - history_ns < lower:
            continue
        if observation.receive_ts_ns + future_ns > upper:
            continue
        if horizon not in observation.future_ticks:
            continue
        if any(lag not in observation.past_ticks for lag in LAG_SECONDS):
            continue
        if any(
            name not in observation.features
            or not isfinite(float(observation.features[name]))
            for name in required_ofi
        ):
            continue
        result.append(position)
    return tuple(result)


def _contemporaneous_positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    *,
    epoch_bounds: Mapping[tuple[int, int], tuple[int, int]],
) -> tuple[int, ...]:
    history_ns = int(max(CONTEMPORANEOUS_WINDOWS_SECONDS) * 1_000_000_000)
    required = tuple(
        name
        for window in CONTEMPORANEOUS_WINDOWS_SECONDS
        for name in ofi_feature_names(window)
    )
    result: list[int] = []
    for position in candidates:
        observation = observations[position]
        lower, _ = epoch_bounds[(observation.tape_index, observation.connection_epoch)]
        if observation.receive_ts_ns - history_ns < lower:
            continue
        if any(
            window not in observation.same_window_ticks
            for window in CONTEMPORANEOUS_WINDOWS_SECONDS
        ):
            continue
        if any(
            name not in observation.features
            or not isfinite(float(observation.features[name]))
            for name in required
        ):
            continue
        result.append(position)
    return tuple(result)


def _row_hash(
    observations: Sequence[HorseRaceObservation], positions: Sequence[int]
) -> str:
    digest = sha256()
    for position in positions:
        digest.update(str(observations[position].receive_ts_ns).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _lag_design(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    lags: Sequence[float],
) -> NDArray[np.float64]:
    return np.asarray(
        [
            [float(observations[position].past_ticks[lag]) for lag in lags]
            for position in positions
        ],
        dtype=np.float64,
    ).reshape(len(positions), len(lags))


def _ofi_design(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    window: float,
) -> NDArray[np.float64]:
    names = ofi_feature_names(window)
    return np.asarray(
        [
            [float(observations[position].features[name]) for name in names]
            for position in positions
        ],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


def _target(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    *,
    source: Literal["future", "same_window"],
    horizon: float,
) -> NDArray[np.float64]:
    return np.asarray(
        [
            float(
                observations[position].future_ticks[horizon]
                if source == "future"
                else observations[position].same_window_ticks[horizon]
            )
            for position in positions
        ],
        dtype=np.float64,
    )


def _inner_validation_indices(
    timestamps: NDArray[np.int64],
) -> tuple[tuple[int, NDArray[np.int64]], ...]:
    size = len(timestamps)
    embargo_ns = int(EMBARGO_SECONDS * 1_000_000_000)
    folds: list[tuple[int, NDArray[np.int64]]] = []
    for fraction in (0.5, 0.65, 0.8):
        cut = max(1, int(size * fraction))
        boundary = int(timestamps[cut - 1])
        validation = np.flatnonzero(timestamps > boundary + embargo_ns)
        validation = validation[validation < min(size, cut + max(1, size // 10))]
        if cut >= MINIMUM_FIT_OBSERVATIONS and validation.size:
            folds.append((cut, np.asarray(validation, dtype=np.int64)))
    return tuple(folds)


def _select_alpha(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    timestamps: NDArray[np.int64],
    names: Sequence[str],
) -> tuple[float, list[dict[str, Any]]]:
    scores: dict[float, list[float]] = {alpha: [] for alpha in RIDGE_ALPHAS}
    for cut, validation in _inner_validation_indices(timestamps):
        inner_target = target[:cut]
        drift = float(inner_target.mean())
        for alpha in RIDGE_ALPHAS:
            fit = fit_ridge(
                design[:cut], inner_target - drift, feature_names=names, penalty=alpha
            )
            prediction = drift + fit.predict(design[validation])
            scores[alpha].append(float(np.mean((target[validation] - prediction) ** 2)))
    means = {
        alpha: (float(np.mean(values)) if values else float("inf"))
        for alpha, values in scores.items()
    }
    selected = min(RIDGE_ALPHAS, key=lambda alpha: (means[alpha], alpha))
    if not isfinite(means[selected]):
        selected = RIDGE_ALPHAS[0]
    return selected, [
        {"alpha": alpha, "mean_validation_mse": means[alpha], "folds": len(scores[alpha])}
        for alpha in RIDGE_ALPHAS
    ]


def _fit_forecast(
    train_design: NDArray[np.float64],
    test_design: NDArray[np.float64],
    train_target: NDArray[np.float64],
    test_target: NDArray[np.float64],
    train_timestamps: NDArray[np.int64],
    *,
    names: Sequence[str],
    regularised: bool,
) -> FittedForecast:
    drift = float(train_target.mean())
    alpha, inner_cv = (
        _select_alpha(train_design, train_target, train_timestamps, names)
        if regularised
        else (0.0, [])
    )
    fit = fit_ridge(
        train_design, train_target - drift, feature_names=names, penalty=alpha
    )
    prediction = drift + fit.predict(test_design)
    payload: dict[str, Any] = {
        "features": list(names),
        "feature_count": len(names),
        "train_n": len(train_target),
        "test_n": len(test_target),
        "target_training_mean_ticks": drift,
        "selected_alpha": alpha,
        "inner_cv": inner_cv,
        "absolute_oos_r2": _oos_r2(test_target, prediction, drift),
        "rmse_ticks": sqrt(float(np.mean((test_target - prediction) ** 2))),
        "mae_ticks": float(np.mean(np.abs(test_target - prediction))),
        "coefficients_ticks_per_training_sd": {
            name: float(fit.coefficients[index]) for index, name in enumerate(names)
        },
        "raw_coefficients_ticks_per_unit": {
            name: float(fit.coefficients[index] / fit.scale[index])
            for index, name in enumerate(names)
        },
        "training_standardisation": {
            "source": "training_only",
            "centre": {name: float(fit.centre[index]) for index, name in enumerate(names)},
            "scale": {name: float(fit.scale[index]) for index, name in enumerate(names)},
        },
        "prediction_sha256": _float_array_hash(prediction),
    }
    return FittedForecast(payload=payload, prediction=prediction, fit=fit)


def _oos_r2(
    target: NDArray[np.float64], prediction: NDArray[np.float64], train_mean: float
) -> float | None:
    denominator = float(np.sum((target - train_mean) ** 2))
    if denominator <= 0.0:
        return None
    return 1.0 - float(np.sum((target - prediction) ** 2)) / denominator


def _float_array_hash(values: NDArray[np.float64]) -> str:
    return sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def _hac_lag(timestamps: NDArray[np.int64], *, horizon: float) -> tuple[int, float]:
    if len(timestamps) < 2:
        return 0, float("nan")
    spacing = float(np.median(np.diff(timestamps))) / 1_000_000_000
    if spacing <= 0.0 or not isfinite(spacing):
        raise ValueError("test anchors must be strictly time ordered")
    dependence_seconds = max(max(LAG_SECONDS), horizon + CAUSAL_GAP_SECONDS)
    lag = min(len(timestamps) - 1, max(1, ceil(dependence_seconds / spacing)))
    return lag, spacing


def hac_mean_test(
    values: Sequence[float] | NDArray[np.float64],
    *,
    max_lag: int,
    alternative: Alternative,
) -> dict[str, Any]:
    """Newey--West test of a loss-differential mean."""

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size < 2 or np.any(~np.isfinite(array)):
        raise ValueError("HAC input must be a finite vector with at least two observations")
    lag = min(max(0, int(max_lag)), len(array) - 1)
    centred = array - array.mean()
    gamma0 = float(np.dot(centred, centred) / len(array))
    long_run = gamma0
    for current_lag in range(1, lag + 1):
        covariance = float(
            np.dot(centred[current_lag:], centred[:-current_lag]) / len(array)
        )
        long_run += 2.0 * (1.0 - current_lag / (lag + 1.0)) * covariance
    long_run = max(long_run, float(np.finfo(np.float64).eps))
    standard_error = sqrt(long_run / len(array))
    mean = float(array.mean())
    statistic = mean / standard_error
    p_value = (
        float(norm.sf(statistic))
        if alternative == "greater"
        else float(2.0 * norm.sf(abs(statistic)))
    )
    effective_n = (
        float(len(array))
        if gamma0 <= 0.0
        else float(min(len(array), max(1.0, len(array) * gamma0 / long_run)))
    )
    return {
        "mean_loss_improvement_ticks2": mean,
        "hac_max_lag_rows": lag,
        "hac_long_run_variance": long_run,
        "standard_error": standard_error,
        "t_statistic": statistic,
        "alternative": alternative,
        "p_value_raw": p_value,
        "effective_n": effective_n,
    }


def holm_adjust(p_values: Sequence[float]) -> tuple[float, ...]:
    """Holm step-down adjusted p-values in the original order."""

    if any(not isfinite(value) or value < 0.0 or value > 1.0 for value in p_values):
        raise ValueError("p-values must be finite and lie in [0,1]")
    size = len(p_values)
    order = sorted(range(size), key=lambda index: (p_values[index], index))
    adjusted = [0.0] * size
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (size - rank) * p_values[index]))
        adjusted[index] = running
    return tuple(adjusted)


def _approx_mde_oos_r2(test: Mapping[str, Any], *, family_size: int) -> float:
    effective_n = max(1.0, float(test["effective_n"]))
    tail_alpha = SIGNIFICANCE_LEVEL / family_size
    if test["alternative"] == "two-sided":
        tail_alpha /= 2.0
    critical = float(norm.isf(tail_alpha))
    return critical**2 / effective_n


def _comparison_tests(
    target: NDArray[np.float64],
    *,
    train_mean: float,
    lag: FittedForecast,
    ofi: FittedForecast,
    combined: FittedForecast,
    hac_lag: int,
) -> dict[str, dict[str, Any]]:
    mean_prediction = np.full(target.shape, train_mean, dtype=np.float64)
    mean_loss = (target - mean_prediction) ** 2
    lag_loss = (target - lag.prediction) ** 2
    ofi_loss = (target - ofi.prediction) ** 2
    combined_loss = (target - combined.prediction) ** 2
    return {
        "lag_predictiveness": hac_mean_test(
            mean_loss - lag_loss, max_lag=hac_lag, alternative="greater"
        ),
        "ofi_predictiveness": hac_mean_test(
            mean_loss - ofi_loss, max_lag=hac_lag, alternative="greater"
        ),
        "lag_vs_ofi_dm": hac_mean_test(
            ofi_loss - lag_loss, max_lag=hac_lag, alternative="two-sided"
        ),
        "ofi_beyond_lags_clark_west": hac_mean_test(
            lag_loss - (combined_loss - (lag.prediction - combined.prediction) ** 2),
            max_lag=hac_lag,
            alternative="greater",
        ),
        "lags_beyond_ofi_clark_west": hac_mean_test(
            ofi_loss - (combined_loss - (ofi.prediction - combined.prediction) ** 2),
            max_lag=hac_lag,
            alternative="greater",
        ),
    }


def _attach_holm(rows: list[dict[str, Any]]) -> None:
    questions = (
        "ofi_predictiveness",
        "lag_vs_ofi_dm",
        "ofi_beyond_lags_clark_west",
        "lags_beyond_ofi_clark_west",
    )
    for question in questions:
        surface = [float(row["inference"][question]["p_value_raw"]) for row in rows]
        for row, adjusted in zip(rows, holm_adjust(surface), strict=True):
            test = row["inference"][question]
            test["p_value_holm_surface_35"] = adjusted
            test["significant_holm_surface_35"] = adjusted < SIGNIFICANCE_LEVEL
            test["approx_mde_oos_r2_surface_35"] = _approx_mde_oos_r2(
                test, family_size=35
            )
        primary = [row for row in rows if row["ofi_window_seconds"] == PRIMARY_OFI_WINDOW_SECONDS]
        primary.sort(key=lambda row: HORIZONS_SECONDS.index(row["horizon_seconds"]))
        values = [float(row["inference"][question]["p_value_raw"]) for row in primary]
        for row, adjusted in zip(primary, holm_adjust(values), strict=True):
            test = row["inference"][question]
            test["p_value_holm_primary_7"] = adjusted
            test["significant_holm_primary_7"] = adjusted < SIGNIFICANCE_LEVEL
            test["approx_mde_oos_r2_primary_7"] = _approx_mde_oos_r2(
                test, family_size=7
            )


def _attach_lag_holm(rows: list[dict[str, Any]]) -> None:
    values = [float(row["lag_predictiveness"]["p_value_raw"]) for row in rows]
    for row, adjusted in zip(rows, holm_adjust(values), strict=True):
        test = row["lag_predictiveness"]
        test["p_value_holm_7"] = adjusted
        test["significant_holm_7"] = adjusted < SIGNIFICANCE_LEVEL
        test["approx_mde_oos_r2_7"] = _approx_mde_oos_r2(test, family_size=7)


def _cross_family_correlation(
    lag_design: NDArray[np.float64], ofi_design: NDArray[np.float64]
) -> float | None:
    joined = np.column_stack((lag_design, ofi_design))
    if len(joined) < 2:
        return None
    correlation = np.corrcoef(joined, rowvar=False)
    block = np.abs(correlation[: lag_design.shape[1], lag_design.shape[1] :])
    finite = block[np.isfinite(block)]
    return float(finite.max()) if finite.size else None


def _model_payload(forecast: FittedForecast) -> dict[str, Any]:
    return dict(forecast.payload)


def build_mid_lag_ofi_artifact(tape: HorseRaceTapeInput) -> dict[str, Any]:
    """Estimate the complete frozen D41 model and inference grid."""

    observations = tuple(tape.observations)
    split = _split(observations)
    bounds = _epoch_bounds(observations)
    lag_rows: list[dict[str, Any]] = []
    future_rows: list[dict[str, Any]] = []
    row_support: list[dict[str, Any]] = []

    for horizon in HORIZONS_SECONDS:
        train = _future_positions(
            observations, split.train, horizon=horizon, epoch_bounds=bounds
        )
        test = _future_positions(
            observations, split.test, horizon=horizon, epoch_bounds=bounds
        )
        if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
            raise RuntimeError(f"D41 horizon {horizon:g} has insufficient common support")
        train_target = _target(observations, train, source="future", horizon=horizon)
        test_target = _target(observations, test, source="future", horizon=horizon)
        train_timestamps = np.asarray(
            [observations[position].receive_ts_ns for position in train], dtype=np.int64
        )
        test_timestamps = np.asarray(
            [observations[position].receive_ts_ns for position in test], dtype=np.int64
        )
        lag_matrix_train = _lag_design(observations, train, LAG_SECONDS)
        lag_matrix_test = _lag_design(observations, test, LAG_SECONDS)
        lag_bank = _fit_forecast(
            lag_matrix_train,
            lag_matrix_test,
            train_target,
            test_target,
            train_timestamps,
            names=lag_feature_names(),
            regularised=True,
        )
        hac_lag, median_spacing = _hac_lag(test_timestamps, horizon=horizon)
        mean_loss = (test_target - float(train_target.mean())) ** 2
        lag_loss = (test_target - lag_bank.prediction) ** 2
        lag_test = hac_mean_test(
            mean_loss - lag_loss, max_lag=hac_lag, alternative="greater"
        )
        lag_rows.append(
            {
                "horizon_seconds": horizon,
                "train_n": len(train),
                "test_n": len(test),
                "train_row_hash": _row_hash(observations, train),
                "test_row_hash": _row_hash(observations, test),
                "model": _model_payload(lag_bank),
                "lag_predictiveness": lag_test,
            }
        )
        row_support.append(
            {
                "horizon_seconds": horizon,
                "train_n": len(train),
                "test_n": len(test),
                "train_row_hash": _row_hash(observations, train),
                "test_row_hash": _row_hash(observations, test),
                "median_test_anchor_spacing_seconds": median_spacing,
                "hac_max_lag_rows": hac_lag,
            }
        )
        for lag_index, lag_seconds in enumerate(LAG_SECONDS):
            univariate = _fit_forecast(
                lag_matrix_train[:, [lag_index]],
                lag_matrix_test[:, [lag_index]],
                train_target,
                test_target,
                train_timestamps,
                names=(lag_feature_name(lag_seconds),),
                regularised=False,
            )
            lag_rows[-1].setdefault("single_lags", []).append(
                {
                    "lag_seconds": lag_seconds,
                    **_model_payload(univariate),
                }
            )
        for window in OFI_WINDOWS_SECONDS:
            ofi_train = _ofi_design(observations, train, window)
            ofi_test = _ofi_design(observations, test, window)
            ofi = _fit_forecast(
                ofi_train,
                ofi_test,
                train_target,
                test_target,
                train_timestamps,
                names=ofi_feature_names(window),
                regularised=True,
            )
            combined = _fit_forecast(
                np.column_stack((lag_matrix_train, ofi_train)),
                np.column_stack((lag_matrix_test, ofi_test)),
                train_target,
                test_target,
                train_timestamps,
                names=combined_feature_names(window),
                regularised=True,
            )
            lag_r2 = lag_bank.payload["absolute_oos_r2"]
            ofi_r2 = ofi.payload["absolute_oos_r2"]
            combined_r2 = combined.payload["absolute_oos_r2"]
            if lag_r2 is None or ofi_r2 is None or combined_r2 is None:
                raise RuntimeError("D41 target variance is zero")
            future_rows.append(
                {
                    "ofi_window_seconds": window,
                    "horizon_seconds": horizon,
                    "train_n": len(train),
                    "test_n": len(test),
                    "train_row_hash": _row_hash(observations, train),
                    "test_row_hash": _row_hash(observations, test),
                    "lag_bank": _model_payload(lag_bank),
                    "ofi_alone": _model_payload(ofi),
                    "lag_plus_ofi": _model_payload(combined),
                    "oos_r2_increment_ofi_over_lags": float(combined_r2) - float(lag_r2),
                    "oos_r2_increment_lags_over_ofi": float(combined_r2) - float(ofi_r2),
                    "oos_r2_difference_lags_minus_ofi": float(lag_r2) - float(ofi_r2),
                    "max_abs_training_cross_family_correlation": _cross_family_correlation(
                        lag_matrix_train, ofi_train
                    ),
                    "inference": _comparison_tests(
                        test_target,
                        train_mean=float(train_target.mean()),
                        lag=lag_bank,
                        ofi=ofi,
                        combined=combined,
                        hac_lag=hac_lag,
                    ),
                }
            )

    _attach_lag_holm(lag_rows)
    _attach_holm(future_rows)
    contemporaneous_rows = _contemporaneous_panel(observations, split, bounds)
    return {
        "schema_version": 1,
        "scan_id": SCAN_ID,
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "claim_id": CLAIM_ID,
        "registration_commit": REGISTRATION_COMMIT,
        "sample_role": "retrospective_partial_session_exploration",
        "confirmatory_eligible": False,
        "registered_replication_eligible": False,
        "order_entry_enabled": False,
        "tape": {
            "run_id": tape.run_id,
            "instrument_id": tape.instrument_id,
            "sha256": tape.tape_sha256,
            "observations": len(observations),
            "depth20_publications": tape.depth20_publications,
            "depth200_publications": tape.depth200_publications,
            "observed_seconds": tape.observed_seconds,
            "failures": tape.failures,
        },
        "split": {
            "train_n": len(split.train),
            "embargoed_n": len(split.embargoed),
            "test_n": len(split.test),
            "embargo_seconds": split.embargo_seconds,
            "boundaries": split.boundaries,
        },
        "axes": {
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "lag_seconds": list(LAG_SECONDS),
            "ofi_windows_seconds": list(OFI_WINDOWS_SECONDS),
            "horizons_seconds": list(HORIZONS_SECONDS),
            "contemporaneous_windows_seconds": list(CONTEMPORANEOUS_WINDOWS_SECONDS),
            "levels": CCZ_LEVELS,
            "primary_ofi_window_seconds": PRIMARY_OFI_WINDOW_SECONDS,
            "future_model_cells": 126,
            "contemporaneous_cells": 6,
            "declared_grid_cells": 132,
        },
        "row_support": row_support,
        "lag_models": lag_rows,
        "future_comparisons": future_rows,
        "contemporaneous_check": contemporaneous_rows,
        "sig19_trial": {
            "hypothesis_id": CLAIM_ID,
            "registration_commit": REGISTRATION_COMMIT,
            "code_commit": None,
            "tape_sha256": tape.tape_sha256,
            "sample_role": "retrospective_partial_session_exploration",
            "grid_cells": 132,
            "status": "estimated",
        },
    }


def _contemporaneous_panel(
    observations: Sequence[HorseRaceObservation],
    split: D41Split,
    bounds: Mapping[tuple[int, int], tuple[int, int]],
) -> list[dict[str, Any]]:
    train = _contemporaneous_positions(observations, split.train, epoch_bounds=bounds)
    test = _contemporaneous_positions(observations, split.test, epoch_bounds=bounds)
    if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
        raise RuntimeError("D41 contemporaneous check has insufficient common support")
    train_timestamps = np.asarray(
        [observations[position].receive_ts_ns for position in train], dtype=np.int64
    )
    test_timestamps = np.asarray(
        [observations[position].receive_ts_ns for position in test], dtype=np.int64
    )
    rows: list[dict[str, Any]] = []
    for window in CONTEMPORANEOUS_WINDOWS_SECONDS:
        train_target = _target(observations, train, source="same_window", horizon=window)
        test_target = _target(observations, test, source="same_window", horizon=window)
        forecast = _fit_forecast(
            _ofi_design(observations, train, window),
            _ofi_design(observations, test, window),
            train_target,
            test_target,
            train_timestamps,
            names=ofi_feature_names(window),
            regularised=True,
        )
        hac_lag, spacing = _hac_lag(test_timestamps, horizon=window)
        mean_loss = (test_target - float(train_target.mean())) ** 2
        model_loss = (test_target - forecast.prediction) ** 2
        rows.append(
            {
                "window_seconds": window,
                "train_n": len(train),
                "test_n": len(test),
                "train_row_hash": _row_hash(observations, train),
                "test_row_hash": _row_hash(observations, test),
                "median_test_anchor_spacing_seconds": spacing,
                "model": _model_payload(forecast),
                "predictiveness": hac_mean_test(
                    mean_loss - model_loss, max_lag=hac_lag, alternative="greater"
                ),
            }
        )
    adjusted = holm_adjust(
        [float(row["predictiveness"]["p_value_raw"]) for row in rows]
    )
    for row, value in zip(rows, adjusted, strict=True):
        test = row["predictiveness"]
        test["p_value_holm_6"] = value
        test["significant_holm_6"] = value < SIGNIFICANCE_LEVEL
        test["approx_mde_oos_r2_6"] = _approx_mde_oos_r2(test, family_size=6)
    return rows


def compact_result(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Lossless compact D41 result surface used for the committed machine summary."""

    future_rows = artifact["future_comparisons"]
    lag_rows = artifact["lag_models"]
    contemporaneous = artifact["contemporaneous_check"]
    if not isinstance(future_rows, list) or len(future_rows) != 35:
        raise RuntimeError("D41 future comparison grid is incomplete")
    if not isinstance(lag_rows, list) or len(lag_rows) != 7:
        raise RuntimeError("D41 lag grid is incomplete")
    if not isinstance(contemporaneous, list) or len(contemporaneous) != 6:
        raise RuntimeError("D41 contemporaneous grid is incomplete")
    return {
        "schema_version": 1,
        "scan_id": artifact["scan_id"],
        "specification_id": artifact["specification_id"],
        "claim_id": artifact["claim_id"],
        "registration_commit": artifact["registration_commit"],
        "code_commit": artifact.get("code_commit"),
        "source_tape": artifact.get("source_tape"),
        "source_tape_sha256": artifact["tape"]["sha256"],
        "sample_role": artifact["sample_role"],
        "split": artifact["split"],
        "axes": artifact["axes"],
        "contemporaneous_check": [
            {
                "window_seconds": row["window_seconds"],
                "absolute_oos_r2": row["model"]["absolute_oos_r2"],
                "p_value_holm_6": row["predictiveness"]["p_value_holm_6"],
                "approx_mde_oos_r2_6": row["predictiveness"]["approx_mde_oos_r2_6"],
                "train_n": row["train_n"],
                "test_n": row["test_n"],
            }
            for row in contemporaneous
        ],
        "lag_models": [
            {
                "horizon_seconds": row["horizon_seconds"],
                "lag_bank_absolute_oos_r2": row["model"]["absolute_oos_r2"],
                "lag_bank_p_value_holm_7": row["lag_predictiveness"]["p_value_holm_7"],
                "lag_bank_approx_mde_oos_r2_7": row["lag_predictiveness"][
                    "approx_mde_oos_r2_7"
                ],
                "selected_alpha": row["model"]["selected_alpha"],
                "single_lags": [
                    {
                        "lag_seconds": single["lag_seconds"],
                        "absolute_oos_r2": single["absolute_oos_r2"],
                    }
                    for single in row["single_lags"]
                ],
                "train_n": row["train_n"],
                "test_n": row["test_n"],
            }
            for row in lag_rows
        ],
        "future_comparisons": [
            {
                "ofi_window_seconds": row["ofi_window_seconds"],
                "horizon_seconds": row["horizon_seconds"],
                "lag_bank_absolute_oos_r2": row["lag_bank"]["absolute_oos_r2"],
                "ofi_alone_absolute_oos_r2": row["ofi_alone"]["absolute_oos_r2"],
                "lag_plus_ofi_absolute_oos_r2": row["lag_plus_ofi"]["absolute_oos_r2"],
                "oos_r2_increment_ofi_over_lags": row["oos_r2_increment_ofi_over_lags"],
                "oos_r2_increment_lags_over_ofi": row["oos_r2_increment_lags_over_ofi"],
                "oos_r2_difference_lags_minus_ofi": row["oos_r2_difference_lags_minus_ofi"],
                "max_abs_training_cross_family_correlation": row[
                    "max_abs_training_cross_family_correlation"
                ],
                "inference": {
                    name: {
                        "t_statistic": test["t_statistic"],
                        "effective_n": test["effective_n"],
                        "p_value_raw": test["p_value_raw"],
                        "p_value_holm_surface_35": test.get("p_value_holm_surface_35"),
                        "p_value_holm_primary_7": test.get("p_value_holm_primary_7"),
                        "approx_mde_oos_r2_surface_35": test.get(
                            "approx_mde_oos_r2_surface_35"
                        ),
                        "approx_mde_oos_r2_primary_7": test.get(
                            "approx_mde_oos_r2_primary_7"
                        ),
                    }
                    for name, test in row["inference"].items()
                },
                "train_n": row["train_n"],
                "test_n": row["test_n"],
                "test_row_hash": row["test_row_hash"],
            }
            for row in future_rows
        ],
    }
