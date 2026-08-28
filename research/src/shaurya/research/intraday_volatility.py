"""Causal intraday NIFTY move/volatility research utilities.

This module deliberately stops at forecast evaluation.  The source option archive contains
rolling ATM-relative OHLCV, not fixed contracts, quotes, IV, OI, or executable spreads, so it is
not sufficient for an honest option-P&L backtest.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats
from sklearn.base import RegressorMixin
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

REGULAR_OPEN_MINUTE = 9 * 60 + 15
REGULAR_CLOSE_MINUTE = 15 * 60 + 29
EXPECTED_REGULAR_BARS = REGULAR_CLOSE_MINUTE - REGULAR_OPEN_MINUTE + 1
TUESDAY_EXPIRY_START = pd.Timestamp("2025-09-01")
DEFAULT_HORIZONS = (15, 30, 60)
RANDOM_SEED = 20260826
FloatArray = npt.NDArray[np.float64]

_OPTION_NAME = re.compile(r"__ATM__(CALL|PUT)__1m\.csv$")


@dataclass(frozen=True)
class DataAudit:
    raw_index_rows: int
    duplicate_index_timestamps: int
    invalid_index_rows: int
    rejected_sessions: int
    accepted_sessions: int
    clean_index_rows: int
    raw_atm_option_rows: int
    duplicate_atm_option_rows: int
    negative_atm_volume_rows: int
    matched_rows: int
    sample_rows: int
    first_sample: str
    last_sample: str


@dataclass(frozen=True)
class Metric:
    n: int
    days: int
    mae: float
    rmse: float
    spearman: float
    r2_vs_seasonal: float
    mae_skill_vs_seasonal: float
    top_quintile_lift: float
    top_quintile_precision: float


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float
    lower_95: float
    upper_95: float
    samples: int


def _csv_entries(archive: zipfile.ZipFile, predicate: Any) -> list[zipfile.ZipInfo]:
    return sorted(
        (entry for entry in archive.infolist() if predicate(entry.filename)),
        key=lambda entry: entry.filename,
    )


def _read_zip_csvs(path: Path, entries: Sequence[zipfile.ZipInfo]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(path) as archive:
        for entry in entries:
            with archive.open(entry) as raw, TextIOWrapper(raw, encoding="utf-8") as text:
                frames.append(pd.read_csv(text))
    if not frames:
        raise ValueError(f"no matching CSV files found in {path}")
    return pd.concat(frames, ignore_index=True)


def _local_naive_datetime(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    return parsed.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)


def load_clean_index(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Load regular, complete weekday sessions and reject pathological source sessions."""
    with zipfile.ZipFile(path) as archive:
        entries = _csv_entries(
            archive,
            lambda name: name.endswith("__NIFTY__1m.csv") and "/monthly/" in name,
        )
    frame = _read_zip_csvs(path, entries)
    raw_rows = len(frame)
    frame["datetime"] = _local_naive_datetime(frame["datetime"])
    frame = frame.dropna(subset=["datetime"])
    duplicate_rows = int(frame.duplicated("datetime", keep="last").sum())
    frame = frame.drop_duplicates("datetime", keep="last")

    price_columns = ["open", "high", "low", "close"]
    for column in price_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    tolerance = 1e-7
    valid = (
        frame[price_columns].notna().all(axis=1)
        & (frame[price_columns] > 0).all(axis=1)
        & (frame["high"] + tolerance >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] - tolerance <= frame[["open", "close", "high"]].min(axis=1))
    )
    invalid_rows = int((~valid).sum())
    frame = frame[valid].copy()
    frame["minute"] = frame["datetime"].dt.hour * 60 + frame["datetime"].dt.minute
    frame = frame[
        frame["minute"].between(REGULAR_OPEN_MINUTE, REGULAR_CLOSE_MINUTE)
        & (frame["datetime"].dt.dayofweek < 5)
    ].copy()
    frame["date"] = frame["datetime"].dt.normalize()
    frame["bar_log_range"] = np.log(frame["high"] / frame["low"])

    session = frame.groupby("date", sort=True).agg(
        rows=("datetime", "size"),
        unique_minutes=("minute", "nunique"),
        first_minute=("minute", "min"),
        last_minute=("minute", "max"),
        max_bar_log_range=("bar_log_range", "max"),
    )
    accepted = session[
        (session["rows"] == EXPECTED_REGULAR_BARS)
        & (session["unique_minutes"] == EXPECTED_REGULAR_BARS)
        & (session["first_minute"] == REGULAR_OPEN_MINUTE)
        & (session["last_minute"] == REGULAR_CLOSE_MINUTE)
        & (session["max_bar_log_range"] <= np.log(1.04))
    ].index
    clean = frame[frame["date"].isin(accepted)].copy()
    clean = clean.sort_values("datetime").reset_index(drop=True)
    audit = {
        "raw_index_rows": raw_rows,
        "duplicate_index_timestamps": duplicate_rows,
        "invalid_index_rows": invalid_rows,
        "rejected_sessions": int(len(session) - len(accepted)),
        "accepted_sessions": int(len(accepted)),
        "clean_index_rows": int(len(clean)),
    }
    return clean, audit


def load_atm_options(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Load only rolling-ATM CALL and PUT files; volume is activity, never signed flow."""
    with zipfile.ZipFile(path) as archive:
        entries = _csv_entries(archive, lambda name: _OPTION_NAME.search(name) is not None)
    frames: list[pd.DataFrame] = []
    raw_rows = 0
    with zipfile.ZipFile(path) as archive:
        for entry in entries:
            match = _OPTION_NAME.search(entry.filename)
            if match is None:  # pragma: no cover - protected by entry predicate
                continue
            with archive.open(entry) as raw, TextIOWrapper(raw, encoding="utf-8") as text:
                frame = pd.read_csv(text, usecols=["datetime", "close", "volume"])
            raw_rows += len(frame)
            frame["side"] = match.group(1)
            frames.append(frame)
    if not frames:
        raise ValueError(f"no rolling-ATM CALL/PUT files found in {path}")
    options = pd.concat(frames, ignore_index=True)
    options["datetime"] = _local_naive_datetime(options["datetime"])
    options["close"] = pd.to_numeric(options["close"], errors="coerce")
    options["volume"] = pd.to_numeric(options["volume"], errors="coerce")
    negative_volume = int((options["volume"] < 0).sum())
    options.loc[options["volume"] < 0, "volume"] = np.nan
    options = options.dropna(subset=["datetime", "close"])
    options = options[options["close"] > 0]
    duplicate_rows = int(options.duplicated(["datetime", "side"], keep="last").sum())
    options = options.drop_duplicates(["datetime", "side"], keep="last")
    wide = options.pivot(index="datetime", columns="side", values=["close", "volume"])
    wide.columns = [f"atm_{side.lower()}_{field}" for field, side in wide.columns]
    wide = wide.reset_index()
    expected = [
        "atm_call_close",
        "atm_put_close",
        "atm_call_volume",
        "atm_put_volume",
    ]
    for column in expected:
        if column not in wide:
            wide[column] = np.nan
    return wide[["datetime", *expected]], {
        "raw_atm_option_rows": raw_rows,
        "duplicate_atm_option_rows": duplicate_rows,
        "negative_atm_volume_rows": negative_volume,
    }


def _forward_sum(values: FloatArray, horizon: int) -> FloatArray:
    result = np.full(len(values), np.nan)
    if len(values) <= horizon:
        return result
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    indices = np.arange(len(values) - horizon)
    result[indices] = cumulative[indices + horizon + 1] - cumulative[indices + 1]
    return result


def _add_session_features(group: pd.DataFrame, horizons: Iterable[int]) -> pd.DataFrame:
    group = group.sort_values("minute").copy()
    close = group["close"].to_numpy(float)
    log_close = np.log(close)
    returns = np.empty(len(group))
    returns[0] = np.nan
    returns[1:] = np.diff(log_close)
    group["ret_1"] = returns
    return_series = pd.Series(returns, index=group.index)
    squared = np.nan_to_num(returns, nan=0.0) ** 2
    parkinson = (np.log(group["high"] / group["low"]) ** 2) / (4.0 * np.log(2.0))

    for window in (5, 15, 30, 60):
        group[f"ret_{window}"] = np.log(group["close"] / group["close"].shift(window))
        group[f"rv_{window}"] = np.sqrt(
            return_series.rolling(window, min_periods=max(2, window // 3)).apply(
                lambda x: float(np.nansum(x**2)), raw=True
            )
        )
        group[f"pkv_{window}"] = np.sqrt(
            parkinson.rolling(window, min_periods=max(2, window // 3)).sum()
        )

    for horizon in horizons:
        future_close = np.full(len(group), np.nan)
        future_close[:-horizon] = close[horizon:]
        group[f"abs_move_{horizon}"] = np.abs(np.log(future_close / close)) * 10_000.0
        group[f"realized_vol_{horizon}"] = np.sqrt(_forward_sum(squared, horizon)) * 10_000.0
    return group


def build_panel(
    index_zip: Path,
    options_zip: Path,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    sample_every_minutes: int = 5,
) -> tuple[pd.DataFrame, DataAudit]:
    index, index_audit = load_clean_index(index_zip)
    options, option_audit = load_atm_options(options_zip)
    panel = index.merge(options, on="datetime", how="inner", validate="one_to_one")
    matched_rows = len(panel)
    panel = panel.sort_values(["date", "minute"]).reset_index(drop=True)

    daily = panel.groupby("date", sort=True).agg(
        day_open=("open", "first"),
        day_close=("close", "last"),
    )
    daily["previous_close"] = daily["day_close"].shift(1)
    daily["overnight_gap"] = np.log(daily["day_open"] / daily["previous_close"])
    panel = panel.merge(daily[["overnight_gap"]], left_on="date", right_index=True, how="left")
    panel = (
        panel.groupby("date", group_keys=False, sort=True)
        .apply(_add_session_features, horizons=horizons, include_groups=False)
        .reset_index(drop=True)
    )
    # ``include_groups=False`` prevents pandas from feeding the key into the feature function.
    # Restore the canonical session key from the timestamp afterwards.
    panel["date"] = panel["datetime"].dt.normalize()

    elapsed = panel["minute"] - REGULAR_OPEN_MINUTE
    panel["elapsed_fraction"] = elapsed / (EXPECTED_REGULAR_BARS - 1)
    panel["time_sin"] = np.sin(2 * np.pi * panel["elapsed_fraction"])
    panel["time_cos"] = np.cos(2 * np.pi * panel["elapsed_fraction"])
    panel["day_of_week"] = panel["date"].dt.dayofweek
    for weekday in range(5):
        panel[f"dow_{weekday}"] = (panel["day_of_week"] == weekday).astype(float)
    panel["tuesday_expiry_regime"] = (panel["date"] >= TUESDAY_EXPIRY_START).astype(float)
    panel["scheduled_expiry_day"] = np.where(
        panel["tuesday_expiry_regime"] == 1,
        panel["day_of_week"] == 1,
        panel["day_of_week"] == 3,
    ).astype(float)
    session_open = panel.groupby("date")["open"].transform("first")
    panel["session_return"] = np.log(panel["close"] / session_open)

    straddle = panel["atm_call_close"] + panel["atm_put_close"]
    total_volume = panel["atm_call_volume"] + panel["atm_put_volume"]
    panel["straddle_bps"] = straddle / panel["close"] * 10_000.0
    panel["premium_skew"] = (panel["atm_put_close"] - panel["atm_call_close"]) / straddle
    panel["volume_imbalance"] = (
        (panel["atm_put_volume"] - panel["atm_call_volume"]) / total_volume.replace(0, np.nan)
    )
    panel["log_total_volume"] = np.log1p(total_volume.clip(lower=0))
    panel["zero_option_volume"] = (total_volume == 0).astype(float)

    max_horizon = max(horizons)
    sample = panel[
        (elapsed % sample_every_minutes == 0)
        & (elapsed >= sample_every_minutes)
        & (panel["minute"] <= REGULAR_CLOSE_MINUTE - max_horizon)
    ].copy()
    target_columns = [
        f"{target}_{horizon}"
        for target in ("abs_move", "realized_vol")
        for horizon in horizons
    ]
    sample = sample.dropna(subset=target_columns).sort_values("datetime").reset_index(drop=True)
    audit = DataAudit(
        **index_audit,
        **option_audit,
        matched_rows=matched_rows,
        sample_rows=len(sample),
        first_sample=sample["datetime"].min().isoformat(),
        last_sample=sample["datetime"].max().isoformat(),
    )
    return sample, audit


INDEX_FEATURES = [
    "ret_1",
    "ret_5",
    "ret_15",
    "ret_30",
    "ret_60",
    "rv_5",
    "rv_15",
    "rv_30",
    "rv_60",
    "pkv_5",
    "pkv_15",
    "pkv_30",
    "pkv_60",
    "session_return",
    "overnight_gap",
    "elapsed_fraction",
    "time_sin",
    "time_cos",
    "dow_0",
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "tuesday_expiry_regime",
    "scheduled_expiry_day",
]
OPTION_FEATURES = [
    "straddle_bps",
    "premium_skew",
    "volume_imbalance",
    "log_total_volume",
    "zero_option_volume",
]


class SeasonalMeanRegressor:
    """Training-only mean target by five-minute clock bucket."""

    def __init__(self) -> None:
        self.global_mean = float("nan")
        self.by_minute: dict[int, float] = {}

    def fit(self, frame: pd.DataFrame, target: str) -> SeasonalMeanRegressor:
        self.global_mean = float(frame[target].mean())
        self.by_minute = frame.groupby("minute")[target].mean().to_dict()
        return self

    def predict(self, frame: pd.DataFrame) -> FloatArray:
        values = frame["minute"].map(self.by_minute).fillna(self.global_mean).to_numpy(float)
        return cast(FloatArray, values)


def _target_transformer(model: RegressorMixin) -> TransformedTargetRegressor:
    return TransformedTargetRegressor(
        regressor=model,
        func=np.log1p,
        inverse_func=np.expm1,
        check_inverse=False,
    )


def model_factories(seed: int = RANDOM_SEED) -> dict[str, tuple[list[str], RegressorMixin]]:
    ridge = lambda: _target_transformer(  # noqa: E731
        Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=10.0)),
            ]
        )
    )
    histogram = lambda: _target_transformer(  # noqa: E731
        Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        learning_rate=0.06,
                        max_iter=140,
                        max_leaf_nodes=15,
                        min_samples_leaf=80,
                        l2_regularization=2.0,
                        random_state=seed,
                    ),
                ),
            ]
        )
    )
    return {
        "ridge_index": (INDEX_FEATURES, ridge()),
        "ridge_index_options": (INDEX_FEATURES + OPTION_FEATURES, ridge()),
        "hist_index": (INDEX_FEATURES, histogram()),
        "hist_index_options": (INDEX_FEATURES + OPTION_FEATURES, histogram()),
    }


def calculate_metric(
    actual: FloatArray,
    prediction: FloatArray,
    seasonal: FloatArray,
    dates: pd.Series,
) -> Metric:
    actual = np.asarray(actual, dtype=float)
    prediction = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    seasonal = np.asarray(seasonal, dtype=float)
    residual = actual - prediction
    seasonal_residual = actual - seasonal
    seasonal_sse = float(np.sum(seasonal_residual**2))
    seasonal_mae = float(np.mean(np.abs(seasonal_residual)))
    threshold_prediction = np.quantile(prediction, 0.8)
    threshold_actual = np.quantile(actual, 0.8)
    selected = prediction >= threshold_prediction
    rank = stats.spearmanr(actual, prediction).statistic
    return Metric(
        n=len(actual),
        days=int(pd.Series(dates).nunique()),
        mae=float(np.mean(np.abs(residual))),
        rmse=float(np.sqrt(np.mean(residual**2))),
        spearman=float(rank) if np.isfinite(rank) else float("nan"),
        r2_vs_seasonal=(
            1.0 - float(np.sum(residual**2)) / seasonal_sse if seasonal_sse > 0 else float("nan")
        ),
        mae_skill_vs_seasonal=(
            1.0 - float(np.mean(np.abs(residual))) / seasonal_mae
            if seasonal_mae > 0
            else float("nan")
        ),
        top_quintile_lift=float(actual[selected].mean() / actual.mean()),
        top_quintile_precision=float((actual[selected] >= threshold_actual).mean()),
    )


def daily_block_bootstrap_skill(
    actual: FloatArray,
    prediction: FloatArray,
    seasonal: FloatArray,
    dates: pd.Series,
    *,
    samples: int = 1_000,
    seed: int = RANDOM_SEED,
) -> BootstrapInterval:
    table = pd.DataFrame(
        {
            "date": pd.Series(dates).reset_index(drop=True),
            "model_error": np.abs(np.asarray(actual) - np.asarray(prediction)),
            "seasonal_error": np.abs(np.asarray(actual) - np.asarray(seasonal)),
        }
    )
    daily = table.groupby("date", sort=False)[["model_error", "seasonal_error"]].sum()
    counts = table.groupby("date", sort=False).size().to_numpy(float)
    model_error = daily["model_error"].to_numpy(float)
    seasonal_error = daily["seasonal_error"].to_numpy(float)
    rng = np.random.default_rng(seed)
    draws = np.empty(samples)
    for draw in range(samples):
        indices = rng.integers(0, len(daily), size=len(daily))
        model_mae = model_error[indices].sum() / counts[indices].sum()
        seasonal_mae = seasonal_error[indices].sum() / counts[indices].sum()
        draws[draw] = 1.0 - model_mae / seasonal_mae
    estimate = 1.0 - model_error.sum() / seasonal_error.sum()
    return BootstrapInterval(
        estimate=float(estimate),
        lower_95=float(np.quantile(draws, 0.025)),
        upper_95=float(np.quantile(draws, 0.975)),
        samples=samples,
    )


def _split(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    year = frame["date"].dt.year
    if name == "development":
        return frame[year <= 2023]
    if name == "selection":
        return frame[year == 2024]
    if name == "holdout_2025":
        return frame[year == 2025]
    if name == "current_2026":
        return frame[year == 2026]
    if name == "tuesday_regime":
        return frame[frame["date"] >= TUESDAY_EXPIRY_START]
    raise ValueError(f"unknown split: {name}")


def _fit_predict(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    target: str,
    features: list[str],
    model: RegressorMixin,
) -> FloatArray:
    model.fit(train[features], train[target].to_numpy(float))
    prediction = np.maximum(np.asarray(model.predict(evaluation[features]), dtype=float), 0.0)
    return cast(FloatArray, prediction)


def run_experiment(
    panel: pd.DataFrame,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    bootstrap_samples: int = 1_000,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    development = _split(panel, "development")
    selection = _split(panel, "selection")
    if development.empty or selection.empty:
        raise ValueError(
            "the experiment requires development data through 2023 and 2024 selection data"
        )

    result: dict[str, Any] = {
        "protocol": {
            "development": "2021-2023",
            "model_selection": "2024 only",
            "frozen_evaluation": ["2025", "2026 through archive end"],
            "regime_break": "Tuesday-expiry regime begins 2025-09-01",
            "sampling_minutes": 5,
            "bootstrap_unit": "trading session",
            "bootstrap_samples": bootstrap_samples,
            "seed": seed,
            "execution_claim": False,
        },
        "tasks": {},
    }

    for target_family in ("abs_move", "realized_vol"):
        for horizon in horizons:
            target = f"{target_family}_{horizon}"
            task_key = f"{target_family}_{horizon}m"
            seasonal_dev = SeasonalMeanRegressor().fit(development, target)
            seasonal_selection = seasonal_dev.predict(selection)
            candidates: dict[str, Any] = {}
            for name, (features, model) in model_factories(seed).items():
                prediction = _fit_predict(development, selection, target, features, model)
                candidates[name] = asdict(
                    calculate_metric(
                        selection[target].to_numpy(float),
                        prediction,
                        seasonal_selection,
                        selection["date"],
                    )
                )
            winner = max(
                candidates,
                key=lambda name: (
                    candidates[name]["mae_skill_vs_seasonal"],
                    candidates[name]["spearman"],
                ),
            )

            train_frozen = pd.concat([development, selection], ignore_index=True)
            frozen_seasonal = SeasonalMeanRegressor().fit(train_frozen, target)
            winner_features, winner_model = model_factories(seed)[winner]
            winner_model.fit(train_frozen[winner_features], train_frozen[target].to_numpy(float))
            evaluations: dict[str, Any] = {}
            for split_name in ("holdout_2025", "current_2026", "tuesday_regime"):
                evaluation = _split(panel, split_name)
                if evaluation.empty:
                    continue
                prediction = np.maximum(
                    np.asarray(winner_model.predict(evaluation[winner_features]), dtype=float),
                    0.0,
                )
                seasonal_prediction = frozen_seasonal.predict(evaluation)
                metric = calculate_metric(
                    evaluation[target].to_numpy(float),
                    prediction,
                    seasonal_prediction,
                    evaluation["date"],
                )
                interval = daily_block_bootstrap_skill(
                    evaluation[target].to_numpy(float),
                    prediction,
                    seasonal_prediction,
                    evaluation["date"],
                    samples=bootstrap_samples,
                    seed=(
                        seed
                        + horizon
                        + len(split_name)
                        + (0 if target_family == "abs_move" else 1_000)
                    ),
                )
                evaluations[split_name] = {
                    "metric": asdict(metric),
                    "mae_skill_daily_bootstrap": asdict(interval),
                    "date_start": evaluation["date"].min().date().isoformat(),
                    "date_end": evaluation["date"].max().date().isoformat(),
                }

            # Matched ridge comparison estimates whether the five option-activity fields add value.
            ridge_increment: dict[str, Any] = {}
            for split_name in ("selection", "holdout_2025", "current_2026", "tuesday_regime"):
                evaluation = selection if split_name == "selection" else _split(panel, split_name)
                train = development if split_name == "selection" else train_frozen
                if evaluation.empty:
                    continue
                paired: dict[str, float] = {}
                for name in ("ridge_index", "ridge_index_options"):
                    features, model = model_factories(seed)[name]
                    prediction = _fit_predict(train, evaluation, target, features, model)
                    paired[name] = float(
                        np.mean(np.abs(evaluation[target].to_numpy(float) - prediction))
                    )
                ridge_increment[split_name] = {
                    "index_mae": paired["ridge_index"],
                    "index_options_mae": paired["ridge_index_options"],
                    "option_mae_increment": (
                        1.0 - paired["ridge_index_options"] / paired["ridge_index"]
                    ),
                }

            histogram_increment: dict[str, Any] = {
                "selection": {
                    "index_mae": candidates["hist_index"]["mae"],
                    "index_options_mae": candidates["hist_index_options"]["mae"],
                    "option_mae_increment": (
                        1.0
                        - candidates["hist_index_options"]["mae"]
                        / candidates["hist_index"]["mae"]
                    ),
                }
            }
            histogram_models: dict[str, tuple[list[str], RegressorMixin]] = {}
            for name in ("hist_index", "hist_index_options"):
                features, model = model_factories(seed)[name]
                model.fit(train_frozen[features], train_frozen[target].to_numpy(float))
                histogram_models[name] = (features, model)
            for split_name in ("holdout_2025", "current_2026", "tuesday_regime"):
                evaluation = _split(panel, split_name)
                if evaluation.empty:
                    continue
                paired_mae: dict[str, float] = {}
                for name, (features, model) in histogram_models.items():
                    prediction = np.maximum(
                        np.asarray(model.predict(evaluation[features]), dtype=float), 0.0
                    )
                    paired_mae[name] = float(
                        np.mean(np.abs(evaluation[target].to_numpy(float) - prediction))
                    )
                histogram_increment[split_name] = {
                    "index_mae": paired_mae["hist_index"],
                    "index_options_mae": paired_mae["hist_index_options"],
                    "option_mae_increment": (
                        1.0
                        - paired_mae["hist_index_options"] / paired_mae["hist_index"]
                    ),
                }

            holdout = evaluations.get("holdout_2025", {})
            current = evaluations.get("current_2026", {})
            holdout_lower = (
                holdout.get("mae_skill_daily_bootstrap", {}).get("lower_95", float("nan"))
            )
            current_skill = current.get("metric", {}).get("mae_skill_vs_seasonal", float("nan"))
            current_lower = (
                current.get("mae_skill_daily_bootstrap", {}).get("lower_95", float("nan"))
            )
            result["tasks"][task_key] = {
                "target": target,
                "selection_candidates": candidates,
                "selected_model": winner,
                "evaluations": evaluations,
                "option_feature_increment": {
                    "ridge": ridge_increment,
                    "histogram": histogram_increment,
                },
                "gate": {
                    "holdout_skill_ci_above_zero": bool(holdout_lower > 0),
                    "current_skill_ci_above_zero": bool(current_lower > 0),
                    "current_point_skill_above_zero": bool(current_skill > 0),
                    "passed": bool(holdout_lower > 0 and current_lower > 0),
                },
            }
    passed = [name for name, task in result["tasks"].items() if task["gate"]["passed"]]
    option_positive_current = [
        name
        for name, task in result["tasks"].items()
        if task["option_feature_increment"]["histogram"]["current_2026"][
            "option_mae_increment"
        ]
        > 0
    ]
    result["summary"] = {
        "tasks_tested": len(result["tasks"]),
        "tasks_passing_gate": len(passed),
        "passing_tasks": passed,
        "option_tasks_improved_in_2026": len(option_positive_current),
        "option_feature_verdict": (
            "rolling-ATM option fields were not stable incremental predictors"
            if len(option_positive_current) < len(result["tasks"])
            else "rolling-ATM option fields improved every current task"
        ),
        "prospective_recommendation": "freeze an index-only model for prospective validation",
        "overall_verdict": (
            "incremental forecast signal found"
            if passed
            else "no model cleared the predeclared retrospective stability gate"
        ),
    }
    return result
