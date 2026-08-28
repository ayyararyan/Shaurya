"""Recent-data replications of selected 2025-2026 intraday-alpha papers.

Index results are costed NIFTY-return proxies.  Option results are predictive diagnostics only:
the archive contains rolling ATM-relative buckets rather than fixed, executable contracts.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict
from io import TextIOWrapper
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from shaurya.research.intraday_alpha_tournament import (
    MODEL_FEATURES,
    PRIMARY_ROUND_TRIP_COST_BPS,
    build_tournament_panel,
    daily_pnl,
    strategy_metric,
)
from shaurya.research.intraday_volatility import _local_naive_datetime, load_clean_index

INDEX_DISCOVERY_START = pd.Timestamp("2025-09-01")
INDEX_DISCOVERY_END = pd.Timestamp("2026-06-30")
INDEX_VALIDATION_END = pd.Timestamp("2026-08-14")
INDEX_FINAL_START = pd.Timestamp("2026-08-17")
OPTION_DISCOVERY_START = pd.Timestamp("2025-09-01")
OPTION_DISCOVERY_END = pd.Timestamp("2026-03-31")
OPTION_VALIDATION_END = pd.Timestamp("2026-05-07")
OPTION_FINAL_START = pd.Timestamp("2026-05-08")
OPTION_OFFSETS = (-2, -1, 0, 1, 2)
OPTION_NAME = re.compile(r"__(ATM(?:[+-]\d+)?)__(CALL|PUT)__1m\.csv$")


def _ridge() -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=20.0)),
        ]
    )


def _correlation_summary(frame: pd.DataFrame, predictor: str, target: str) -> dict[str, Any]:
    clean = frame[["date", predictor, target]].dropna()
    correlation = float(clean[predictor].corr(clean[target])) if len(clean) > 1 else 0.0
    daily = clean.assign(product=clean[predictor] * clean[target]).groupby("date")["product"].mean()
    t_statistic = float(stats.ttest_1samp(daily, 0.0).statistic) if len(daily) > 1 else 0.0
    return {
        "observations": len(clean),
        "days": int(clean["date"].nunique()),
        "correlation": correlation,
        "spearman": float(clean[predictor].corr(clean[target], method="spearman")),
        "daily_product_t_statistic": t_statistic,
    }


def build_phase_panel(index_zip: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build causal one-minute phase observations; target is the current open-to-close return."""
    index, audit = load_clean_index(index_zip)
    recent = index[index["date"] >= INDEX_DISCOVERY_START].copy()
    recent["phase"] = recent["minute"] % 15
    recent["target_bps"] = np.log(recent["close"] / recent["open"]) * 10_000.0
    recent["bar_return_bps"] = recent.groupby("date")["close"].transform(
        lambda values: np.log(values).diff().mul(10_000.0)
    )
    for lag in range(1, 13):
        recent[f"phase_lag_{lag}"] = recent.groupby(["date", "phase"])["target_bps"].shift(lag)
    recent["prior_5m_bps"] = (
        recent.groupby("date")["close"]
        .transform(lambda values: np.log(values).diff(5).mul(10_000.0))
        .shift(1)
    )
    recent["prior_rv_15_bps"] = recent.groupby("date")["bar_return_bps"].transform(
        lambda values: values.shift(1).pow(2).rolling(15, min_periods=10).sum().pow(0.5)
    )
    recent["date"] = recent["datetime"].dt.normalize()
    audit = {
        **audit,
        "phase_rows": len(recent),
        "phase_sessions": int(recent["date"].nunique()),
        "first_phase_row": recent["datetime"].min().isoformat(),
        "last_phase_row": recent["datetime"].max().isoformat(),
    }
    return recent.reset_index(drop=True), audit


def _index_splits(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "discovery": frame[frame["date"].between(INDEX_DISCOVERY_START, INDEX_DISCOVERY_END)],
        "validation": frame[
            frame["date"].between(INDEX_DISCOVERY_END + pd.Timedelta(days=1), INDEX_VALIDATION_END)
        ],
        "final_week": frame[frame["date"] >= INDEX_FINAL_START],
    }


def run_quarter_hour_scan(panel: pd.DataFrame) -> dict[str, Any]:
    features = [f"phase_lag_{lag}" for lag in range(1, 13)] + [
        "prior_5m_bps",
        "prior_rv_15_bps",
    ]
    phase_results: dict[str, Any] = {}
    for phase in range(15):
        phase_frame = panel[panel["phase"] == phase].dropna(subset=["phase_lag_1"])
        splits = _index_splits(phase_frame)
        model = _ridge().fit(splits["discovery"][features], splits["discovery"]["target_bps"])
        result: dict[str, Any] = {}
        for name, split in splits.items():
            prediction = np.asarray(model.predict(split[features]), dtype=float)
            evaluated = split[["date", "target_bps"]].copy()
            evaluated["prediction"] = prediction
            evaluated["position"] = np.sign(prediction)
            gross = (
                evaluated.assign(pnl_bps=evaluated["position"] * evaluated["target_bps"])
                .groupby("date")["pnl_bps"]
                .sum()
            )
            # Each phase observation is a separate one-minute position followed by 14 flat
            # minutes, so every active prediction pays a complete round trip.
            costed = gross - evaluated.groupby("date")["position"].apply(
                lambda values: float(values.abs().sum()) * PRIMARY_ROUND_TRIP_COST_BPS
            )
            result[name] = {
                "observations": len(split),
                "days": int(split["date"].nunique()),
                "prediction_correlation": float(
                    evaluated["prediction"].corr(evaluated["target_bps"])
                ),
                "gross_mean_bps_per_day": float(gross.mean()),
                "net_6bps_mean_bps_per_day": float(costed.mean()),
            }
        phase_results[str(phase)] = result
    actual = phase_results["0"]
    validation_placebos = [
        phase_results[str(phase)]["validation"]["prediction_correlation"] for phase in range(1, 15)
    ]
    return {
        "definition": (
            "clock minute modulo 15; phase 0 is :00/:15/:30/:45 and phases 1-14 "
            "are shifted-clock placebos"
        ),
        "features": features,
        "phases": phase_results,
        "summary": {
            "phase_0_validation_correlation": actual["validation"]["prediction_correlation"],
            "phase_0_final_correlation": actual["final_week"]["prediction_correlation"],
            "phase_0_validation_gross_bps_per_day": actual["validation"]["gross_mean_bps_per_day"],
            "phase_0_final_gross_bps_per_day": actual["final_week"]["gross_mean_bps_per_day"],
            "phase_0_validation_net_6bps_per_day": actual["validation"][
                "net_6bps_mean_bps_per_day"
            ],
            "placebo_validation_correlation_median": float(np.median(validation_placebos)),
            "phase_0_validation_percentile_among_phases": float(
                stats.percentileofscore(
                    validation_placebos, actual["validation"]["prediction_correlation"]
                )
            ),
            "phase_0_final_net_6bps_per_day": actual["final_week"]["net_6bps_mean_bps_per_day"],
        },
    }


def run_volatility_gated_scan(index_zip: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    panel, audit = build_tournament_panel(index_zip)
    panel = panel[panel["date"] >= INDEX_DISCOVERY_START].copy()
    panel["future_rv_5_bps"] = (
        panel.groupby("date")["ret_1"].transform(
            lambda values: (
                values.shift(-1).pow(2).rolling(5, min_periods=5).sum().shift(-4).pow(0.5)
            )
        )
        * 10_000.0
    )
    discovery = panel[panel["date"] <= INDEX_DISCOVERY_END].dropna(subset=["future_rv_5_bps"])
    validation = panel[
        panel["date"].between(INDEX_DISCOVERY_END + pd.Timedelta(days=1), INDEX_VALIDATION_END)
    ].dropna(subset=["future_rv_5_bps"])
    final = panel[panel["date"] >= INDEX_FINAL_START].dropna(subset=["future_rv_5_bps"])
    return_model = _ridge().fit(discovery[MODEL_FEATURES], discovery["forward_return_bps"])
    vol_model = _ridge().fit(discovery[MODEL_FEATURES], discovery["future_rv_5_bps"])
    discovery_return = np.asarray(return_model.predict(discovery[MODEL_FEATURES]), dtype=float)
    discovery_vol = np.asarray(vol_model.predict(discovery[MODEL_FEATURES]), dtype=float)
    vol_low, vol_high = np.quantile(discovery_vol, [1 / 3, 2 / 3])

    candidates: dict[str, tuple[float, str]] = {}
    for participation in (0.10, 0.25, 0.50, 1.00):
        threshold = float(np.quantile(np.abs(discovery_return), 1.0 - participation))
        for gate in ("all", "low", "high"):
            candidates[f"{gate}_vol_p{participation:g}"] = (threshold, gate)

    splits = {"validation": validation, "final_week": final}
    results: dict[str, Any] = {}
    for candidate, (threshold, gate) in candidates.items():
        result: dict[str, Any] = {}
        for split_name, split in splits.items():
            predicted_return = np.asarray(return_model.predict(split[MODEL_FEATURES]), dtype=float)
            predicted_vol = np.asarray(vol_model.predict(split[MODEL_FEATURES]), dtype=float)
            active = np.abs(predicted_return) >= threshold
            if gate == "low":
                active &= predicted_vol <= vol_low
            elif gate == "high":
                active &= predicted_vol >= vol_high
            position = np.where(active, np.sign(predicted_return), 0.0)
            metric = strategy_metric(daily_pnl(split, position, PRIMARY_ROUND_TRIP_COST_BPS))
            result[split_name] = asdict(metric)
        results[candidate] = result
    best_active = max(results, key=lambda name: results[name]["validation"]["mean_daily_bps"])
    results["cash"] = {
        "validation": asdict(
            strategy_metric(daily_pnl(validation, np.zeros(len(validation)), 6.0))
        ),
        "final_week": asdict(strategy_metric(daily_pnl(final, np.zeros(len(final)), 6.0))),
    }
    selected = max(results, key=lambda name: results[name]["validation"]["mean_daily_bps"])
    ungated = max(
        (name for name in results if name.startswith("all_")),
        key=lambda name: results[name]["validation"]["mean_daily_bps"],
    )
    return {
        "protocol": {
            "discovery": "2025-09-01 through 2026-06-30",
            "validation": "2026-07-01 through 2026-08-14",
            "final_week": "2026-08-17 through 2026-08-21",
            "cost_bps_round_trip": PRIMARY_ROUND_TRIP_COST_BPS,
            "volatility_gates": "discovery predicted-volatility terciles",
        },
        "candidates": results,
        "summary": {
            "selected_on_validation": selected,
            "selected_final": results[selected]["final_week"],
            "best_active_on_validation": best_active,
            "best_active_final": results[best_active]["final_week"],
            "best_ungated_on_validation": ungated,
            "ungated_final": results[ungated]["final_week"],
        },
    }, audit


def _offset(label: str) -> int:
    return 0 if label == "ATM" else int(label.removeprefix("ATM"))


def load_recent_option_grid(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    raw_rows = 0
    with zipfile.ZipFile(path) as archive:
        entries = []
        for entry in archive.infolist():
            match = OPTION_NAME.search(entry.filename)
            if (
                match is None
                or "/data/2025/" not in entry.filename
                and "/data/2026/" not in entry.filename
            ):
                continue
            if _offset(match.group(1)) in OPTION_OFFSETS:
                entries.append((entry, match.group(1), match.group(2)))
        for entry, label, side in entries:
            with archive.open(entry) as raw, TextIOWrapper(raw, encoding="utf-8") as text:
                frame = pd.read_csv(text, usecols=["datetime", "close", "volume"])
            raw_rows += len(frame)
            frame["offset"] = _offset(label)
            frame["side"] = side
            frames.append(frame)
    options = pd.concat(frames, ignore_index=True)
    options["datetime"] = _local_naive_datetime(options["datetime"])
    options["close"] = pd.to_numeric(options["close"], errors="coerce")
    options["volume"] = pd.to_numeric(options["volume"], errors="coerce")
    options = options.dropna(subset=["datetime", "close"])
    options = options[(options["close"] > 0) & (options["datetime"] >= OPTION_DISCOVERY_START)]
    duplicate_rows = int(options.duplicated(["datetime", "offset", "side"], keep="last").sum())
    options = options.drop_duplicates(["datetime", "offset", "side"], keep="last")
    close = options.pivot(index="datetime", columns=["offset", "side"], values="close")
    volume = options.pivot(index="datetime", columns=["offset", "side"], values="volume")
    grid = pd.DataFrame(index=close.index)
    for offset in OPTION_OFFSETS:
        grid[f"straddle_{offset}"] = close[(offset, "CALL")] + close[(offset, "PUT")]
        grid[f"volume_{offset}"] = volume[(offset, "CALL")].clip(lower=0) + volume[
            (offset, "PUT")
        ].clip(lower=0)
    grid = grid.reset_index().sort_values("datetime")
    grid["date"] = grid["datetime"].dt.normalize()
    grid["minute"] = grid["datetime"].dt.hour * 60 + grid["datetime"].dt.minute
    return grid, {
        "raw_selected_option_rows": raw_rows,
        "duplicate_selected_option_rows": duplicate_rows,
        "grid_rows": len(grid),
        "grid_sessions": int(grid["date"].nunique()),
        "first_grid_row": grid["datetime"].min().isoformat(),
        "last_grid_row": grid["datetime"].max().isoformat(),
    }


def quadratic_atm_residual(values: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    """ATM richness relative to a quadratic fitted to the four neighbouring buckets."""
    offsets = np.asarray(OPTION_OFFSETS, dtype=float)
    mask = offsets != 0
    coefficients = np.polyfit(offsets[mask], values[mask], deg=2)
    return float(values[2] - np.polyval(coefficients, 0.0))


def build_option_diagnostics(grid: pd.DataFrame) -> pd.DataFrame:
    sampled = grid[(grid["minute"] - 9 * 60) % 30 == 0].copy()
    grouped = sampled.groupby("date", group_keys=False)
    sampled["atm_shock_30m"] = grouped["straddle_0"].transform(lambda values: np.log(values).diff())
    sampled["atm_forward_30m"] = grouped["straddle_0"].transform(
        lambda values: np.log(values).shift(-1) - np.log(values)
    )
    sampled["volume"] = sampled["volume_0"]
    sampled["volume_abnormal"] = sampled["volume"] / sampled.groupby(
        sampled["datetime"].dt.strftime("%H:%M")
    )["volume"].transform("median").replace(0, np.nan)
    straddles = sampled[[f"straddle_{offset}" for offset in OPTION_OFFSETS]].to_numpy(float)
    sampled["atm_richness"] = np.asarray(
        [
            quadratic_atm_residual(row) / row[2] if np.isfinite(row).all() else np.nan
            for row in straddles
        ]
    )
    atm_forward = grouped["straddle_0"].transform(
        lambda values: np.log(values).shift(-1) - np.log(values)
    )
    wing_forward = 0.5 * (
        grouped["straddle_-1"].transform(lambda values: np.log(values).shift(-1) - np.log(values))
        + grouped["straddle_1"].transform(lambda values: np.log(values).shift(-1) - np.log(values))
    )
    sampled["atm_relative_forward_30m"] = atm_forward - wing_forward
    return sampled.reset_index(drop=True)


def _option_splits(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "discovery": frame[frame["date"].between(OPTION_DISCOVERY_START, OPTION_DISCOVERY_END)],
        "validation": frame[
            frame["date"].between(
                OPTION_DISCOVERY_END + pd.Timedelta(days=1), OPTION_VALIDATION_END
            )
        ],
        "final_week": frame[frame["date"] >= OPTION_FINAL_START],
    }


def run_option_scans(frame: pd.DataFrame) -> dict[str, Any]:
    splits = _option_splits(frame)
    volume_cutoff = float(splits["discovery"]["volume_abnormal"].quantile(0.75))
    reversal: dict[str, Any] = {}
    curvature: dict[str, Any] = {}
    for name, split in splits.items():
        robust_reversal = split[
            split["atm_shock_30m"].abs().le(0.10) & split["atm_forward_30m"].abs().le(0.10)
        ]
        robust_curvature = split[
            split["atm_richness"].abs().le(0.10) & split["atm_relative_forward_30m"].abs().le(0.10)
        ]
        reversal[name] = {
            "raw": _correlation_summary(split, "atm_shock_30m", "atm_forward_30m"),
            "robust": _correlation_summary(robust_reversal, "atm_shock_30m", "atm_forward_30m"),
            "high_volume": _correlation_summary(
                robust_reversal[robust_reversal["volume_abnormal"] >= volume_cutoff],
                "atm_shock_30m",
                "atm_forward_30m",
            ),
        }
        curvature[name] = {
            "raw": _correlation_summary(split, "atm_richness", "atm_relative_forward_30m"),
            "robust": _correlation_summary(
                robust_curvature, "atm_richness", "atm_relative_forward_30m"
            ),
        }
    return {
        "warning": (
            "diagnostics only: rolling ATM buckets are not fixed contracts and "
            "quotes/IV/OI are absent"
        ),
        "half_hour_reversal": {
            "hypothesis": "negative shock/forward correlation, stronger after abnormal volume",
            "robust_filter": "absolute prior and forward rolling-bucket returns <= 10%",
            "discovery_high_volume_cutoff": volume_cutoff,
            "splits": reversal,
        },
        "smile_curvature": {
            "hypothesis": "negative ATM-richness/ATM-relative-forward correlation",
            "definition": "ATM residual from quadratic fit to rolling offsets -2,-1,+1,+2",
            "robust_filter": "absolute richness and relative forward return <= 10%",
            "splits": curvature,
        },
    }


def run_paper_alpha_scan(index_zip: Path, options_zip: Path) -> dict[str, Any]:
    phase_panel, phase_audit = build_phase_panel(index_zip)
    gated, gated_audit = run_volatility_gated_scan(index_zip)
    grid, option_audit = load_recent_option_grid(options_zip)
    diagnostics = build_option_diagnostics(grid)
    return {
        "protocol": {
            "index_final_holdout": "2026-08-17 through 2026-08-21",
            "option_final_holdout": "2026-05-08 through 2026-05-14",
            "selection_rule": (
                "all thresholds/models fixed using discovery and validation before final week"
            ),
        },
        "data_audit": {"phase": phase_audit, "gated": gated_audit, "options": option_audit},
        "quarter_hour": run_quarter_hour_scan(phase_panel),
        "volatility_gated_direction": gated,
        "options": run_option_scans(diagnostics),
    }
