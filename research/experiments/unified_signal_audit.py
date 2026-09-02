"""Retrospective cross-session audit of reusable Shaurya signals.

This runner deliberately separates forecast utility from executable alpha.  It
uses completed August 2026 sessions only and reports every session separately.
Surface studies use 19/21 August for development and 26/27 August as unchanged
diagnostics.  Futures L1 studies use 26 August for development, 27 August for
validation, and the later 28 August futures-only capture as final diagnostic.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score

NS = 1_000_000_000
SURFACE_STEP_NS = 5 * NS
SURFACE_BLOCK = 12
FUTURES_BLOCK = 60
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0)


@dataclass(frozen=True)
class SurfaceSession:
    date: str
    timestamps: np.ndarray
    values: np.ndarray
    columns: tuple[str, ...]


def load_surface(path: Path) -> SurfaceSession:
    payload = np.load(path, allow_pickle=False)
    return SurfaceSession(
        date=str(payload["trading_date"].tolist()[0]),
        timestamps=payload["timestamps"].astype(np.int64),
        values=payload["values"].astype(np.float64),
        columns=tuple(str(value) for value in payload["columns"].tolist()),
    )


def valid_surface_ends(session: SurfaceSession, horizon: int, lag: int = 12) -> np.ndarray:
    output: list[int] = []
    for end in range(lag, len(session.timestamps) - horizon):
        window = session.timestamps[end - lag : end + horizon + 1]
        if np.all(np.diff(window) == SURFACE_STEP_NS):
            output.append(end)
    return np.asarray(output, dtype=np.int64)


def rank_correlation(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 50 or np.unique(x[finite]).size < 3 or np.unique(y[finite]).size < 3:
        return float("nan"), int(finite.sum())
    return float(spearmanr(x[finite], y[finite]).statistic), int(finite.sum())


def moving_block_ci(
    x: np.ndarray,
    y: np.ndarray,
    *,
    block: int,
    seed: int,
    draws: int = 1000,
) -> list[float]:
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if len(x) < block * 4:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    starts = np.arange(0, len(x) - block + 1)
    correlations: list[float] = []
    blocks_needed = int(np.ceil(len(x) / block))
    for _ in range(draws):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        indices = np.concatenate([np.arange(start, start + block) for start in chosen])[: len(x)]
        value, _ = rank_correlation(x[indices], y[indices])
        correlations.append(value)
    return [float(value) for value in np.nanquantile(correlations, [0.025, 0.975])]


def paired_skill_ci(
    y: np.ndarray,
    base: np.ndarray,
    augmented: np.ndarray,
    *,
    block: int,
    seed: int,
    constant: float | None = None,
    draws: int = 1000,
) -> list[float]:
    finite = np.isfinite(y) & np.isfinite(base) & np.isfinite(augmented)
    differences = np.abs(y[finite] - base[finite]) - np.abs(y[finite] - augmented[finite])
    benchmark = float(np.median(y[finite])) if constant is None else constant
    denominator = float(np.mean(np.abs(y[finite] - benchmark)))
    if len(differences) < block * 4 or denominator <= 0:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    starts = np.arange(0, len(differences) - block + 1)
    blocks_needed = int(np.ceil(len(differences) / block))
    samples = []
    for _ in range(draws):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        indices = np.concatenate([np.arange(start, start + block) for start in chosen])[
            : len(differences)
        ]
        samples.append(float(np.mean(differences[indices]) / denominator))
    return [float(value) for value in np.quantile(samples, [0.025, 0.975])]


def surface_targets(
    session: SurfaceSession, ends: np.ndarray, horizon: int
) -> dict[str, np.ndarray]:
    column = {name: index for index, name in enumerate(session.columns)}
    future = ends + horizon
    returns = session.values[:, column["futures_return_5s"]]
    realized = np.asarray(
        [np.sqrt(float(np.square(returns[end + 1 : end + horizon + 1]).sum())) for end in ends]
    )
    iv = session.values[:, column["surface__atm_iv__near"]]
    term = session.values[:, column["surface__atm_iv__far"]] - iv
    straddle = session.values[:, column["atm_near_straddle_to_future"]]
    stable_strike = (
        session.values[future, column["atm__strike__near"]]
        == session.values[ends, column["atm__strike__near"]]
    )
    straddle_change = (straddle[future] - straddle[ends]) * 10_000.0
    return {
        "realized_futures_volatility": realized,
        "signed_atm_iv_change": iv[future] - iv[ends],
        "absolute_atm_iv_change": np.abs(iv[future] - iv[ends]),
        "signed_term_iv_change": term[future] - term[ends],
        "absolute_straddle_change_bps": np.where(
            stable_strike, np.abs(straddle_change), np.nan
        ),
    }


def surface_signal_arrays(
    session: SurfaceSession, ends: np.ndarray
) -> dict[str, np.ndarray]:
    column = {name: index for index, name in enumerate(session.columns)}
    values = session.values
    iv = values[:, column["surface__atm_iv__near"]]
    term = values[:, column["surface__atm_iv__far"]] - iv
    curvature = values[:, column["surface__variance_curvature__near"]]
    return {
        "volatility_persistence": values[ends, column["futures_realized_volatility_30s"]],
        "futures_volume_intensity": values[ends, column["futures_log_trade_intensity_10s"]],
        "iv_30s_mean_reversion": -(iv[ends] - iv[ends - 6]),
        "near_curvature_level": curvature[ends],
        "near_curvature_delta_30s": curvature[ends] - curvature[ends - 6],
        "term_iv_30s_mean_reversion": -(term[ends] - term[ends - 6]),
        "current_straddle_level": values[ends, column["atm_near_straddle_to_future"]],
    }


def audit_surface_univariate(sessions: list[SurfaceSession]) -> list[dict[str, Any]]:
    definitions = (
        ("volatility_persistence", "realized_futures_volatility", (6, 12, 60)),
        ("futures_volume_intensity", "realized_futures_volatility", (6, 12, 60)),
        ("iv_30s_mean_reversion", "signed_atm_iv_change", (6, 12)),
        ("near_curvature_level", "signed_atm_iv_change", (6, 12, 60)),
        ("near_curvature_delta_30s", "signed_atm_iv_change", (6, 12)),
        ("term_iv_30s_mean_reversion", "signed_term_iv_change", (6, 12)),
        ("current_straddle_level", "absolute_straddle_change_bps", (60,)),
    )
    output: list[dict[str, Any]] = []
    for signal_name, target_name, horizons in definitions:
        for horizon in horizons:
            by_session = []
            for session_index, session in enumerate(sessions):
                ends = valid_surface_ends(session, horizon)
                x = surface_signal_arrays(session, ends)[signal_name]
                y = surface_targets(session, ends, horizon)[target_name]
                rho, count = rank_correlation(x, y)
                by_session.append(
                    {
                        "date": session.date,
                        "samples": count,
                        "spearman_rho": rho,
                        "block_ci95": moving_block_ci(
                            x, y, block=SURFACE_BLOCK, seed=1000 + session_index + horizon
                        ),
                    }
                )
            correlations = [row["spearman_rho"] for row in by_session]
            output.append(
                {
                    "signal": signal_name,
                    "target": target_name,
                    "horizon_seconds": horizon * 5,
                    "sessions": by_session,
                    "same_sign_all_sessions": bool(
                        all(np.sign(value) == np.sign(correlations[0]) for value in correlations)
                    ),
                    "minimum_absolute_rho": float(min(abs(value) for value in correlations)),
                }
            )
    return output


def audit_surface_embargo(sessions: list[SurfaceSession]) -> list[dict[str, Any]]:
    """Check whether surface mean reversion survives a delayed target start."""
    output: list[dict[str, Any]] = []
    for signal_name, target_name in (
        ("iv_30s_mean_reversion", "signed_atm_iv_change"),
        ("term_iv_30s_mean_reversion", "signed_term_iv_change"),
    ):
        for embargo in (1, 2):
            by_session = []
            for session_index, session in enumerate(sessions):
                horizon = 6
                ends = valid_surface_ends(session, horizon + embargo)
                column = {name: index for index, name in enumerate(session.columns)}
                values = session.values
                iv = values[:, column["surface__atm_iv__near"]]
                term = values[:, column["surface__atm_iv__far"]] - iv
                x = surface_signal_arrays(session, ends)[signal_name]
                series = iv if target_name == "signed_atm_iv_change" else term
                y = series[ends + embargo + horizon] - series[ends + embargo]
                rho, count = rank_correlation(x, y)
                by_session.append(
                    {
                        "date": session.date,
                        "samples": count,
                        "spearman_rho": rho,
                        "block_ci95": moving_block_ci(
                            x,
                            y,
                            block=SURFACE_BLOCK,
                            seed=4000 + session_index + embargo,
                        ),
                    }
                )
            correlations = [row["spearman_rho"] for row in by_session]
            output.append(
                {
                    "signal": signal_name,
                    "target": target_name,
                    "forecast_horizon_seconds": 30,
                    "target_start_embargo_seconds": embargo * 5,
                    "sessions": by_session,
                    "same_sign_all_sessions": bool(
                        all(np.sign(value) == np.sign(correlations[0]) for value in correlations)
                    ),
                    "minimum_absolute_rho": float(min(abs(value) for value in correlations)),
                }
            )
    return output


def audit_option_forward_lead(sessions: list[SurfaceSession]) -> list[dict[str, Any]]:
    """Test ATM call-minus-put movement against later futures movement."""
    output: list[dict[str, Any]] = []
    for horizon in (1, 2, 6):
        for embargo in (0, 1, 2):
            by_session = []
            for session_index, session in enumerate(sessions):
                ends = valid_surface_ends(session, horizon + embargo)
                column = {name: index for index, name in enumerate(session.columns)}
                values = session.values
                call = values[:, column["atm__option_mid_to_future__near__CE"]]
                put = values[:, column["atm__option_mid_to_future__near__PE"]]
                x = (call[ends] - call[ends - 6]) - (put[ends] - put[ends - 6])
                start = ends + embargo
                future = start + horizon
                log_mid = values[:, column["futures_log_mid"]]
                y = log_mid[future] - log_mid[start]
                strike = values[:, column["atm__strike__near"]]
                stable = (strike[ends - 6] == strike[ends]) & (strike[ends] == strike[future])
                x = np.where(stable, x, np.nan)
                y = np.where(stable, y, np.nan)
                correlation, count = rank_correlation(x, y)
                by_session.append(
                    {
                        "date": session.date,
                        "samples": count,
                        "spearman_rho": correlation,
                        "block_ci95": moving_block_ci(
                            x,
                            y,
                            block=SURFACE_BLOCK,
                            seed=6000 + session_index + horizon + embargo,
                        ),
                    }
                )
            correlations = [row["spearman_rho"] for row in by_session]
            output.append(
                {
                    "signal": "atm_call_minus_put_30s_change",
                    "target": "signed_futures_mid_return",
                    "horizon_seconds": horizon * 5,
                    "target_start_embargo_seconds": embargo * 5,
                    "sessions": by_session,
                    "same_sign_all_sessions": bool(
                        all(np.sign(value) == np.sign(correlations[0]) for value in correlations)
                    ),
                    "minimum_absolute_rho": float(min(abs(value) for value in correlations)),
                }
            )
    return output


def _surface_model_rows(
    session: SurfaceSession, horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ends = valid_surface_ends(session, horizon)
    c = {name: index for index, name in enumerate(session.columns)}
    v = session.values
    iv = v[:, c["surface__atm_iv__near"]]
    curvature = v[:, c["surface__variance_curvature__near"]]
    skew = v[:, c["surface__variance_skew__near"]]
    seconds = ((session.timestamps[ends] // NS) % 86_400).astype(np.float64)
    angle = 2.0 * np.pi * seconds / 86_400.0
    base = np.column_stack(
        (
            iv[ends],
            iv[ends] - iv[ends - 6],
            iv[ends] - iv[ends - 12],
            v[ends, c["futures_realized_volatility_30s"]],
            v[ends, c["futures_return_5s"]],
            v[ends, c["surface__median_relative_spread__near"]],
            v[ends, c["surface__quote_count__near"]],
            np.sin(angle),
            np.cos(angle),
        )
    )
    curvature_block = np.column_stack(
        (
            curvature[ends],
            curvature[ends] - curvature[ends - 6],
            curvature[ends] - curvature[ends - 12],
            skew[ends],
            skew[ends] - skew[ends - 6],
        )
    )
    target = surface_targets(session, ends, horizon)["signed_atm_iv_change"]
    return base, np.column_stack((base, curvature_block)), target


class PreparedRidge:
    def __init__(self, alpha: float) -> None:
        self.alpha = alpha
        self.center: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.low: np.ndarray | None = None
        self.high: np.ndarray | None = None
        self.model = Ridge(alpha=alpha)

    def _transform(self, values: np.ndarray) -> np.ndarray:
        assert self.center is not None and self.scale is not None
        assert self.low is not None and self.high is not None
        filled = np.where(np.isfinite(values), values, self.center)
        clipped = np.clip(filled, self.low, self.high)
        return (clipped - self.center) / self.scale

    def fit(self, x: np.ndarray, y: np.ndarray) -> PreparedRidge:
        finite_y = np.isfinite(y)
        x = x[finite_y]
        y = y[finite_y]
        self.center = np.nanmedian(x, axis=0)
        filled = np.where(np.isfinite(x), x, self.center)
        self.low = np.nanquantile(filled, 0.005, axis=0)
        self.high = np.nanquantile(filled, 0.995, axis=0)
        clipped = np.clip(filled, self.low, self.high)
        self.scale = np.nanstd(clipped, axis=0)
        self.scale = np.where(self.scale > 1e-12, self.scale, 1.0)
        self.model.fit((clipped - self.center) / self.scale, y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.model.predict(self._transform(x))


def _choose_alpha(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
) -> float:
    finite = np.isfinite(validation_y)
    return min(
        RIDGE_ALPHAS,
        key=lambda alpha: float(
            np.mean(
                np.abs(
                    validation_y[finite]
                    - PreparedRidge(alpha).fit(train_x, train_y).predict(validation_x)[finite]
                )
            )
        ),
    )


def model_metrics(
    y: np.ndarray, prediction: np.ndarray, constant: float
) -> dict[str, float | int | None]:
    finite = np.isfinite(y) & np.isfinite(prediction)
    y = y[finite]
    prediction = prediction[finite]
    constant_mae = float(np.mean(np.abs(y - constant)))
    skill = 1.0 - float(np.mean(np.abs(y - prediction))) / constant_mae
    nonzero = y != 0
    auc: float | None = None
    if np.unique(y[nonzero] > 0).size == 2:
        auc = float(roc_auc_score(y[nonzero] > 0, prediction[nonzero]))
    return {
        "samples": len(y),
        "mae_skill_vs_development_median": skill,
        "direction_accuracy": float(np.mean(np.sign(y[nonzero]) == np.sign(prediction[nonzero]))),
        "roc_auc": auc,
    }


def audit_curvature_increment(sessions: list[SurfaceSession]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in (6, 12):
        rows = [_surface_model_rows(session, horizon) for session in sessions]
        base_alpha = _choose_alpha(*rows[0][::2], rows[1][0], rows[1][2])
        augmented_alpha = _choose_alpha(rows[0][1], rows[0][2], rows[1][1], rows[1][2])
        base_dev_x = np.vstack((rows[0][0], rows[1][0]))
        augmented_dev_x = np.vstack((rows[0][1], rows[1][1]))
        dev_y = np.concatenate((rows[0][2], rows[1][2]))
        base_model = PreparedRidge(base_alpha).fit(base_dev_x, dev_y)
        augmented_model = PreparedRidge(augmented_alpha).fit(augmented_dev_x, dev_y)
        constant = float(np.nanmedian(dev_y))
        diagnostics = []
        for index, (session, (base_x, augmented_x, y)) in enumerate(
            zip(sessions[2:], rows[2:], strict=True)
        ):
            base_prediction = base_model.predict(base_x)
            augmented_prediction = augmented_model.predict(augmented_x)
            diagnostics.append(
                {
                    "date": session.date,
                    "base": model_metrics(y, base_prediction, constant),
                    "base_plus_curvature": model_metrics(y, augmented_prediction, constant),
                    "incremental_skill": (
                        model_metrics(y, augmented_prediction, constant)[
                            "mae_skill_vs_development_median"
                        ]
                        - model_metrics(y, base_prediction, constant)[
                            "mae_skill_vs_development_median"
                        ]
                    ),
                    "paired_block_ci95": paired_skill_ci(
                        y,
                        base_prediction,
                        augmented_prediction,
                        block=SURFACE_BLOCK,
                        seed=2000 + index + horizon,
                        constant=constant,
                    ),
                }
            )
        output[f"{horizon * 5}s"] = {
            "base_alpha_selected_on_2026-08-21": base_alpha,
            "augmented_alpha_selected_on_2026-08-21": augmented_alpha,
            "diagnostics": diagnostics,
        }
    return output


def _option_lead_model_rows(
    session: SurfaceSession, horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    embargo = 1
    ends = valid_surface_ends(session, horizon + embargo)
    c = {name: index for index, name in enumerate(session.columns)}
    v = session.values
    log_mid = v[:, c["futures_log_mid"]]
    seconds = ((session.timestamps[ends] // NS) % 86_400).astype(np.float64)
    angle = 2.0 * np.pi * seconds / 86_400.0
    base = np.column_stack(
        (
            v[ends, c["futures_return_5s"]],
            log_mid[ends] - log_mid[ends - 6],
            log_mid[ends] - log_mid[ends - 12],
            v[ends, c["futures_realized_volatility_30s"]],
            v[ends, c["futures_relative_spread"]],
            v[ends, c["futures_microprice_dislocation"]],
            v[ends, c["futures_depth_imbalance"]],
            v[ends, c["futures_log_trade_intensity_10s"]],
            np.sin(angle),
            np.cos(angle),
        )
    )
    call = v[:, c["atm__option_mid_to_future__near__CE"]]
    put = v[:, c["atm__option_mid_to_future__near__PE"]]
    option_forward = (call[ends] - call[ends - 6]) - (put[ends] - put[ends - 6])
    augmented = np.column_stack((base, option_forward))
    start = ends + embargo
    future = start + horizon
    target = log_mid[future] - log_mid[start]
    strike = v[:, c["atm__strike__near"]]
    stable = (strike[ends - 6] == strike[ends]) & (strike[ends] == strike[future])
    return base, augmented, np.where(stable, target, np.nan)


def audit_option_lead_increment(sessions: list[SurfaceSession]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in (1, 2):
        rows = [_option_lead_model_rows(session, horizon) for session in sessions]
        base_alpha = _choose_alpha(rows[0][0], rows[0][2], rows[1][0], rows[1][2])
        augmented_alpha = _choose_alpha(rows[0][1], rows[0][2], rows[1][1], rows[1][2])
        base_dev = np.vstack((rows[0][0], rows[1][0]))
        augmented_dev = np.vstack((rows[0][1], rows[1][1]))
        target_dev = np.concatenate((rows[0][2], rows[1][2]))
        base_model = PreparedRidge(base_alpha).fit(base_dev, target_dev)
        augmented_model = PreparedRidge(augmented_alpha).fit(augmented_dev, target_dev)
        constant = float(np.nanmedian(target_dev))
        diagnostics = []
        for index, (session, (base, augmented, target)) in enumerate(
            zip(sessions[2:], rows[2:], strict=True)
        ):
            base_prediction = base_model.predict(base)
            augmented_prediction = augmented_model.predict(augmented)
            base_metrics = model_metrics(target, base_prediction, constant)
            augmented_metrics = model_metrics(target, augmented_prediction, constant)
            diagnostics.append(
                {
                    "date": session.date,
                    "base_futures_state": base_metrics,
                    "base_plus_option_forward": augmented_metrics,
                    "incremental_skill": (
                        augmented_metrics["mae_skill_vs_development_median"]
                        - base_metrics["mae_skill_vs_development_median"]
                    ),
                    "paired_block_ci95": paired_skill_ci(
                        target,
                        base_prediction,
                        augmented_prediction,
                        block=SURFACE_BLOCK,
                        seed=9000 + index + horizon,
                        constant=constant,
                    ),
                }
            )
        output[f"{horizon * 5}s"] = {
            "target_start_embargo_seconds": 5,
            "base_alpha": base_alpha,
            "augmented_alpha": augmented_alpha,
            "diagnostics": diagnostics,
        }
    return output


def _magnitude_rows(
    session: SurfaceSession,
    embargo: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    horizon = 60
    ends = valid_surface_ends(session, horizon + embargo)
    c = {name: index for index, name in enumerate(session.columns)}
    futures_names = [
        "futures_relative_spread",
        "futures_microprice_dislocation",
        "futures_depth_imbalance",
        "futures_log_trade_intensity_10s",
        "futures_realized_volatility_30s",
        "futures_return_5s",
    ]
    option_names = [
        name
        for name in session.columns
        if (
            name.startswith("surface__")
            or name.startswith("option_relative_spread__")
            or name.startswith("option_depth_imbalance__")
            or name.startswith("option_return_5s__")
            or name in {
                "atm_near_straddle_to_future",
                "atm_near_call_put_skew",
                "atm_far_straddle_to_future",
                "atm_far_call_put_skew",
            }
        )
        and "quote_count" not in name
    ]

    def context(names: list[str]) -> np.ndarray:
        indices = [c[name] for name in names]
        current = session.values[ends][:, indices]
        lag_30s = current - session.values[ends - 6][:, indices]
        lag_60s = current - session.values[ends - 12][:, indices]
        return np.column_stack((current, lag_30s, lag_60s))

    seconds = ((session.timestamps[ends] // NS) % 86_400).astype(np.float64)
    angle = 2.0 * np.pi * seconds / 86_400.0
    base = np.column_stack((context(futures_names), np.sin(angle), np.cos(angle)))
    augmented = np.column_stack((base, context(option_names)))
    start = ends + embargo
    future = start + horizon
    returns = session.values[:, c["futures_return_5s"]]
    realized = np.asarray(
        [
            np.sqrt(float(np.square(returns[index + 1 : index + horizon + 1]).sum()))
            for index in start
        ]
    )
    straddle = session.values[:, c["atm_near_straddle_to_future"]]
    stable_strike = (
        session.values[start, c["atm__strike__near"]]
        == session.values[future, c["atm__strike__near"]]
    )
    straddle_change = np.abs(straddle[future] - straddle[start]) * 10_000.0
    targets = {
        "realized_futures_volatility": realized,
        "absolute_straddle_change_bps": np.where(stable_strike, straddle_change, np.nan),
    }
    return base, augmented, targets


class PreparedHGB:
    def __init__(self) -> None:
        self.center: np.ndarray | None = None
        self.low: np.ndarray | None = None
        self.high: np.ndarray | None = None
        self.model = HistGradientBoostingRegressor(
            max_iter=150,
            learning_rate=0.04,
            max_leaf_nodes=15,
            l2_regularization=3.0,
            random_state=42,
        )

    def _transform(self, values: np.ndarray) -> np.ndarray:
        assert self.center is not None and self.low is not None and self.high is not None
        filled = np.where(np.isfinite(values), values, self.center)
        return np.clip(filled, self.low, self.high)

    def fit(self, x: np.ndarray, y: np.ndarray) -> PreparedHGB:
        finite_y = np.isfinite(y)
        x = x[finite_y]
        y = y[finite_y]
        self.center = np.nanmedian(x, axis=0)
        filled = np.where(np.isfinite(x), x, self.center)
        self.low = np.nanquantile(filled, 0.005, axis=0)
        self.high = np.nanquantile(filled, 0.995, axis=0)
        self.model.fit(np.clip(filled, self.low, self.high), y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.model.predict(self._transform(x))


def audit_surface_magnitude_increment(sessions: list[SurfaceSession]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for embargo in (0, 1):
        rows = [_magnitude_rows(session, embargo) for session in sessions]
        for target_name in ("realized_futures_volatility", "absolute_straddle_change_bps"):
            base_dev = np.vstack((rows[0][0], rows[1][0]))
            augmented_dev = np.vstack((rows[0][1], rows[1][1]))
            target_dev = np.concatenate((rows[0][2][target_name], rows[1][2][target_name]))
            base_model = PreparedHGB().fit(base_dev, target_dev)
            augmented_model = PreparedHGB().fit(augmented_dev, target_dev)
            constant = float(np.nanmedian(target_dev))
            diagnostics = []
            for index, (session, (base, augmented, targets_)) in enumerate(
                zip(sessions[2:], rows[2:], strict=True)
            ):
                target = targets_[target_name]
                base_prediction = base_model.predict(base)
                augmented_prediction = augmented_model.predict(augmented)
                base_metrics = model_metrics(target, base_prediction, constant)
                augmented_metrics = model_metrics(target, augmented_prediction, constant)
                diagnostics.append(
                    {
                        "date": session.date,
                        "base_futures_state": base_metrics,
                        "base_plus_option_surface": augmented_metrics,
                        "incremental_skill": (
                            augmented_metrics["mae_skill_vs_development_median"]
                            - base_metrics["mae_skill_vs_development_median"]
                        ),
                        "paired_block_ci95": paired_skill_ci(
                            target,
                            base_prediction,
                            augmented_prediction,
                            block=SURFACE_BLOCK,
                            seed=8000 + index + embargo,
                            constant=constant,
                        ),
                    }
                )
            output[f"{target_name}__embargo_{embargo * 5}s"] = {
                "horizon_seconds": 300,
                "target_start_embargo_seconds": embargo * 5,
                "development_dates": [sessions[0].date, sessions[1].date],
                "diagnostics": diagnostics,
            }
    return output


def load_future_grid(path: Path, date: str) -> dict[str, np.ndarray]:
    payload = np.load(path, allow_pickle=False)
    timestamps = payload["timestamps"].astype(np.int64)
    second = timestamps // NS
    unique, reverse = np.unique(second[::-1], return_index=True)
    indices = len(second) - 1 - reverse
    order = np.argsort(unique)
    unique = unique[order]
    indices = indices[order]
    full = np.arange(unique[0], unique[-1] + 1, dtype=np.int64)
    position = np.searchsorted(unique, full, side="right") - 1
    valid = (position >= 0) & ((full - unique[np.maximum(position, 0)]) <= 2)
    selected = indices[np.maximum(position, 0)]
    bid = payload["bid"][selected].astype(np.float64)
    ask = payload["ask"][selected].astype(np.float64)
    bid_quantity = payload["bid_quantity"][selected].astype(np.float64)
    ask_quantity = payload["ask_quantity"][selected].astype(np.float64)
    cumulative_volume = payload["cumulative_volume"][selected].astype(np.float64)
    valid &= np.isfinite(bid) & np.isfinite(ask) & (ask > bid)
    valid &= (bid_quantity + ask_quantity) > 0
    mid = (bid + ask) / 2.0
    imbalance = (bid_quantity - ask_quantity) / (bid_quantity + ask_quantity)
    spread_bps = (ask - bid) / mid * 10_000.0
    volume_delta = np.maximum(np.diff(cumulative_volume, prepend=cumulative_volume[0]), 0.0)
    return {
        "date": np.asarray([date]),
        "timestamps": full,
        "valid": valid,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "imbalance": imbalance,
        "spread_bps": spread_bps,
        "volume_delta": volume_delta,
    }


def future_feature_target(
    grid: dict[str, np.ndarray], horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mid = grid["mid"]
    # One-second embargo: signal at t, markout begins at t+1.
    starts = np.arange(30, len(mid) - horizon - 1)
    valid = grid["valid"]
    eligible = valid[starts] & valid[starts + 1] & valid[starts + 1 + horizon]
    starts = starts[eligible]
    trailing_return = np.log(mid[starts] / mid[starts - 5])
    trailing_vol = np.asarray(
        [np.sqrt(np.square(np.diff(np.log(mid[index - 30 : index + 1]))).sum()) for index in starts]
    )
    volume = np.asarray(
        [np.log1p(np.nansum(grid["volume_delta"][index - 10 : index + 1])) for index in starts]
    )
    seconds = grid["timestamps"][starts] % 86_400
    angle = 2.0 * np.pi * seconds / 86_400.0
    x = np.column_stack(
        (
            trailing_return,
            trailing_vol,
            grid["spread_bps"][starts],
            volume,
            np.sin(angle),
            np.cos(angle),
        )
    )
    augmented = np.column_stack((x, grid["imbalance"][starts]))
    target = np.log(mid[starts + 1 + horizon] / mid[starts + 1])
    return starts, x, augmented, target


def audit_future_volatility_features(grids: list[dict[str, np.ndarray]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for horizon in (5, 10, 30):
        rows: list[dict[str, Any]] = []
        for index, grid in enumerate(grids):
            starts, base, _, _ = future_feature_target(grid, horizon)
            mid = grid["mid"]
            target = np.asarray(
                [
                    np.sqrt(
                        np.square(
                            np.diff(np.log(mid[start + 1 : start + horizon + 2]))
                        ).sum()
                    )
                    for start in starts
                ]
            )
            for signal_name, feature_index in (
                ("trailing_30s_volatility", 1),
                ("trailing_10s_volume_intensity", 3),
            ):
                rho, count = rank_correlation(base[:, feature_index], target)
                rows.append(
                    {
                        "signal": signal_name,
                        "date": str(grid["date"][0]),
                        "samples": count,
                        "spearman_rho": rho,
                        "block_ci95": moving_block_ci(
                            base[:, feature_index],
                            target,
                            block=FUTURES_BLOCK,
                            seed=5000 + index + horizon + feature_index,
                        ),
                    }
                )
        for signal_name in ("trailing_30s_volatility", "trailing_10s_volume_intensity"):
            selected = [row for row in rows if row["signal"] == signal_name]
            correlations = [row["spearman_rho"] for row in selected]
            output.append(
                {
                    "signal": signal_name,
                    "target": "forward_realized_mid_volatility",
                    "horizon_seconds": horizon,
                    "sessions": selected,
                    "same_sign_all_sessions": bool(
                        all(np.sign(value) == np.sign(correlations[0]) for value in correlations)
                    ),
                    "minimum_absolute_rho": float(min(abs(value) for value in correlations)),
                }
            )
    return output


def audit_volume_increment(grids: list[dict[str, np.ndarray]]) -> dict[str, Any]:
    """Measure volume's volatility value after trailing volatility and clock controls."""
    horizon = 30
    prepared = []
    for grid in grids:
        starts, features, _, _ = future_feature_target(grid, horizon)
        mid = grid["mid"]
        target = np.asarray(
            [
                np.sqrt(
                    np.square(np.diff(np.log(mid[start + 1 : start + horizon + 2]))).sum()
                )
                for start in starts
            ]
        )
        base = features[:, [1, 2, 4, 5]]
        augmented = features[:, [1, 2, 4, 5, 3]]
        prepared.append((base, augmented, target))
    alpha = 100.0
    base_model = PreparedRidge(alpha).fit(prepared[0][0], prepared[0][2])
    augmented_model = PreparedRidge(alpha).fit(prepared[0][1], prepared[0][2])
    constant = float(np.median(prepared[0][2]))
    sessions = []
    for index, (grid, (base, augmented, target)) in enumerate(
        zip(grids[1:], prepared[1:], strict=True)
    ):
        base_prediction = base_model.predict(base)
        augmented_prediction = augmented_model.predict(augmented)
        base_metrics = model_metrics(target, base_prediction, constant)
        augmented_metrics = model_metrics(target, augmented_prediction, constant)
        sessions.append(
            {
                "date": str(grid["date"][0]),
                "base": base_metrics,
                "base_plus_volume": augmented_metrics,
                "incremental_skill": (
                    augmented_metrics["mae_skill_vs_development_median"]
                    - base_metrics["mae_skill_vs_development_median"]
                ),
                "paired_block_ci95": paired_skill_ci(
                    target,
                    base_prediction,
                    augmented_prediction,
                    block=FUTURES_BLOCK,
                    seed=7000 + index,
                    constant=constant,
                ),
            }
        )
    return {
        "target": "30s_forward_realized_mid_volatility",
        "fit_date": str(grids[0]["date"][0]),
        "ridge_alpha": alpha,
        "base_features": ["trailing_30s_volatility", "spread", "clock_sin", "clock_cos"],
        "added_feature": "trailing_10s_volume_intensity",
        "sessions": sessions,
    }


def taker_diagnostic(
    grid: dict[str, np.ndarray],
    starts: np.ndarray,
    predictions: np.ndarray,
    horizon: int,
    threshold: float,
    reserve_bps: float = 0.5,
) -> dict[str, Any]:
    selected = np.flatnonzero(np.abs(predictions) >= threshold)
    trades: list[float] = []
    last_exit = -1
    for location in selected:
        signal_index = int(starts[location])
        entry = signal_index + 1
        exit_ = entry + horizon
        if entry <= last_exit:
            continue
        side = 1 if predictions[location] > 0 else -1
        entry_price = grid["ask"][entry] if side > 0 else grid["bid"][entry]
        exit_price = grid["bid"][exit_] if side > 0 else grid["ask"][exit_]
        trades.append(float(side * (exit_price / entry_price - 1.0) * 10_000.0))
        last_exit = exit_
    values = np.asarray(trades)
    if len(values) == 0:
        return {"trades": 0}
    return {
        "trades": len(values),
        "gross_bps_per_trade": float(values.mean()),
        "net_bps_per_trade_after_0.5bp_reserve": float(values.mean() - reserve_bps),
        "gross_win_rate": float(np.mean(values > 0)),
    }


def audit_future_microstructure(grids: list[dict[str, np.ndarray]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in (1, 5, 10, 30):
        rows = [future_feature_target(grid, horizon) for grid in grids]
        alpha = _choose_alpha(rows[0][2], rows[0][3], rows[1][2], rows[1][3])
        model = PreparedRidge(alpha).fit(rows[0][2], rows[0][3])
        discovery_prediction = model.predict(rows[0][2])
        threshold = float(np.quantile(np.abs(discovery_prediction), 0.9))
        sessions = []
        for index, (grid, (starts, _base_x, augmented_x, target)) in enumerate(
            zip(grids, rows, strict=True)
        ):
            prediction = model.predict(augmented_x)
            rho, count = rank_correlation(augmented_x[:, -1], target)
            upper = target[augmented_x[:, -1] >= np.quantile(augmented_x[:, -1], 0.9)]
            lower = target[augmented_x[:, -1] <= np.quantile(augmented_x[:, -1], 0.1)]
            sessions.append(
                {
                    "date": str(grid["date"][0]),
                    "samples": count,
                    "imbalance_spearman_rho": rho,
                    "block_ci95": moving_block_ci(
                        augmented_x[:, -1],
                        target,
                        block=FUTURES_BLOCK,
                        seed=3000 + index + horizon,
                    ),
                    "top_minus_bottom_decile_future_mid_bps": float(
                        (np.mean(upper) - np.mean(lower)) * 10_000.0
                    ),
                    "model": model_metrics(target, prediction, float(np.median(rows[0][3]))),
                    "taker_diagnostic": taker_diagnostic(
                        grid, starts, prediction, horizon, threshold
                    ),
                }
            )
        output[f"{horizon}s"] = {
            "alpha_selected_on_2026-08-27": alpha,
            "prediction_threshold_90pct_fitted_on_2026-08-26": threshold,
            "sessions": sessions,
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", nargs=4, type=Path, required=True)
    parser.add_argument("--future", nargs=3, type=Path, required=True)
    parser.add_argument("--future-dates", nargs=3, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    surface_sessions = [load_surface(path) for path in args.surface]
    future_grids = [
        load_future_grid(path, date)
        for path, date in zip(args.future, args.future_dates, strict=True)
    ]
    payload = {
        "status": "retrospective_reuse_audit_complete",
        "claim_boundary": (
            "Forecast/state evidence only unless a separately reported bid-ask taker diagnostic "
            "is positive. All sessions have been seen in prior research; results are not "
            "prospective."
        ),
        "surface_protocol": {
            "dates": [session.date for session in surface_sessions],
            "univariate": "fixed definitions, every session reported, 60-second moving-block CI",
            "incremental": (
                "19 Aug train, 21 Aug ridge-alpha selection, refit 19+21, unchanged diagnostics "
                "on 26 and 27 Aug"
            ),
        },
        "surface_univariate": audit_surface_univariate(surface_sessions),
        "surface_embargo_checks": audit_surface_embargo(surface_sessions),
        "option_forward_lead": audit_option_forward_lead(surface_sessions),
        "option_forward_increment": audit_option_lead_increment(surface_sessions),
        "curvature_increment": audit_curvature_increment(surface_sessions),
        "surface_magnitude_increment": audit_surface_magnitude_increment(surface_sessions),
        "futures_protocol": {
            "dates": args.future_dates,
            "sampling": "one-second last book, maximum two-second carry, one-second target embargo",
            "model": "26 Aug fit, alpha selected on 27 Aug, 28 Aug unchanged final diagnostic",
            "execution": "actual bid/ask entry and exit plus 0.5bp reserve; non-overlapping trades",
        },
        "futures_microstructure": audit_future_microstructure(future_grids),
        "futures_volatility_features": audit_future_volatility_features(future_grids),
        "futures_volume_increment": audit_volume_increment(future_grids),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": payload["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
