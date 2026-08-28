"""Full-history causal option-surface signals for a NIFTY directional proxy.

The option archive contains rolling ATM-relative buckets rather than fixed contracts.  Option
features are therefore predictors only; P&L is computed exclusively from the matched NIFTY index
return as a futures-direction proxy with explicit round-trip costs.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import spearmanr

from shaurya.research.intraday_alpha_tournament import daily_pnl, strategy_metric
from shaurya.research.intraday_volatility import _local_naive_datetime, load_clean_index
from shaurya.research.parallel_alpha_tournament import holm_passes

FloatArray = npt.NDArray[np.float64]
OFFSETS = (-2, -1, 0, 1, 2)
COSTS_BPS = (0.0, 1.0, 2.0, 6.0)
PRIMARY_COST_BPS = 6.0
TRAINING_SESSIONS = 252
PARTICIPATION = 0.20
START_MONTH = pd.Period("2022-01", freq="M")
OPTION_NAME = re.compile(r"__(ATM(?:[+-]\d+)?)__(CALL|PUT)__1m\.csv$")


@dataclass(frozen=True)
class Calibration:
    month: str
    training_start: str
    training_end: str
    training_sessions: int
    thresholds: dict[str, float]


def _offset(label: str) -> int:
    return 0 if label == "ATM" else int(label.removeprefix("ATM"))


def load_full_option_grid(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load five rolling moneyness buckets across every year in the archive."""
    frames: list[pd.DataFrame] = []
    raw_rows = 0
    selected_files = 0
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            match = OPTION_NAME.search(entry.filename)
            if match is None or _offset(match.group(1)) not in OFFSETS:
                continue
            with archive.open(entry) as raw, TextIOWrapper(raw, encoding="utf-8") as text:
                frame = pd.read_csv(text, usecols=["datetime", "close", "volume"])
            frame["offset"] = _offset(match.group(1))
            frame["side"] = match.group(2)
            raw_rows += len(frame)
            selected_files += 1
            frames.append(frame)
    if not frames:
        raise ValueError("no matching option files")
    options = pd.concat(frames, ignore_index=True)
    options["datetime"] = _local_naive_datetime(options["datetime"])
    options["close"] = pd.to_numeric(options["close"], errors="coerce")
    options["volume"] = pd.to_numeric(options["volume"], errors="coerce").clip(lower=0)
    options = options.dropna(subset=["datetime", "close"])
    options = options[options["close"] > 0]
    duplicates = int(options.duplicated(["datetime", "offset", "side"], keep="last").sum())
    options = options.drop_duplicates(["datetime", "offset", "side"], keep="last")
    close = options.pivot(index="datetime", columns=["offset", "side"], values="close")
    volume = options.pivot(index="datetime", columns=["offset", "side"], values="volume")
    grid = pd.DataFrame(index=close.index)
    for offset in OFFSETS:
        for side in ("CALL", "PUT"):
            grid[f"close_{offset}_{side.lower()}"] = close[(offset, side)]
            grid[f"volume_{offset}_{side.lower()}"] = volume[(offset, side)]
    grid = grid.reset_index().sort_values("datetime")
    return grid, {
        "selected_files": selected_files,
        "raw_selected_rows": raw_rows,
        "duplicate_rows": duplicates,
        "grid_rows": len(grid),
        "first_grid_row": grid["datetime"].min().isoformat(),
        "last_grid_row": grid["datetime"].max().isoformat(),
    }


def _richness(row: FloatArray) -> float:
    mask = np.asarray(OFFSETS) != 0
    coefficients = np.polyfit(np.asarray(OFFSETS, dtype=float)[mask], row[mask], deg=2)
    return float((row[2] - np.polyval(coefficients, 0.0)) / row[2])


def build_historical_option_panel(
    index_zip: Path, options_zip: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    index, index_audit = load_clean_index(index_zip)
    grid, option_audit = load_full_option_grid(options_zip)
    grid["minute"] = grid["datetime"].dt.hour * 60 + grid["datetime"].dt.minute
    grid = grid[(grid["minute"] - 9 * 60) % 30 == 0].copy()
    panel = grid.merge(
        index[["datetime", "date", "close"]], on="datetime", how="inner", validate="one_to_one"
    ).sort_values("datetime")
    for offset in OFFSETS:
        panel[f"straddle_{offset}"] = panel[f"close_{offset}_call"] + panel[f"close_{offset}_put"]
    straddles = panel[[f"straddle_{offset}" for offset in OFFSETS]].to_numpy(float)
    panel["atm_richness"] = np.asarray(
        [_richness(row) if np.isfinite(row).all() else np.nan for row in straddles]
    )
    grouped = panel.groupby("date", sort=False)
    atm = panel["straddle_0"]
    panel["atm_shock_30m"] = grouped["straddle_0"].transform(lambda values: np.log(values).diff())
    panel["premium_skew"] = (panel["close_0_put"] - panel["close_0_call"]) / atm
    total_volume = panel["volume_0_put"] + panel["volume_0_call"]
    panel["volume_imbalance"] = (
        panel["volume_0_put"] - panel["volume_0_call"]
    ) / total_volume.replace(0, np.nan)
    panel["index_return_30m"] = grouped["close"].transform(lambda values: np.log(values).diff())
    panel["forward_return_bps"] = grouped["close"].transform(
        lambda values: (np.log(values.shift(-1)) - np.log(values)) * 10_000.0
    )
    panel["atm_forward_30m"] = grouped["straddle_0"].transform(
        lambda values: np.log(values.shift(-1)) - np.log(values)
    )
    atm_forward = panel["atm_forward_30m"]
    wing_forward = 0.5 * (
        grouped["straddle_-1"].transform(lambda values: np.log(values.shift(-1)) - np.log(values))
        + grouped["straddle_1"].transform(lambda values: np.log(values.shift(-1)) - np.log(values))
    )
    panel["atm_relative_forward_30m"] = atm_forward - wing_forward
    features = [
        "atm_shock_30m",
        "premium_skew",
        "volume_imbalance",
        "atm_richness",
        "index_return_30m",
    ]
    panel = panel.dropna(subset=[*features, "forward_return_bps"]).reset_index(drop=True)
    return panel, {
        "index": index_audit,
        "options": option_audit,
        "matched_decisions": len(panel),
        "matched_sessions": int(panel["date"].nunique()),
        "first_decision": panel["datetime"].min().isoformat(),
        "last_decision": panel["datetime"].max().isoformat(),
    }


SIGNALS = {
    "atm_shock": "atm_shock_30m",
    "premium_skew": "premium_skew",
    "volume_imbalance": "volume_imbalance",
    "atm_richness": "atm_richness",
    "index_momentum": "index_return_30m",
}


def rolling_positions(
    panel: pd.DataFrame,
) -> tuple[dict[str, FloatArray], list[Calibration]]:
    month = panel["date"].dt.to_period("M")
    candidates: dict[str, FloatArray] = {
        f"{direction}_{signal}": np.zeros(len(panel), dtype=float)
        for signal in SIGNALS
        for direction in ("positive", "negative")
    }
    calibrations: list[Calibration] = []
    for test_month in sorted(month[month >= START_MONTH].unique()):
        test_mask = (month == test_month).to_numpy()
        prior_dates = panel.loc[panel["date"] < test_month.start_time, "date"].drop_duplicates()
        selected_dates = prior_dates.tail(TRAINING_SESSIONS)
        if len(selected_dates) < 120:
            continue
        train = panel[panel["date"].isin(selected_dates)]
        thresholds = {
            signal: float(train[column].abs().quantile(1.0 - PARTICIPATION))
            for signal, column in SIGNALS.items()
        }
        for signal, column in SIGNALS.items():
            raw = panel.loc[test_mask, column].to_numpy(float)
            active = np.abs(raw) >= thresholds[signal]
            signed = np.where(active, np.sign(raw), 0.0)
            candidates[f"positive_{signal}"][test_mask] = signed
            candidates[f"negative_{signal}"][test_mask] = -signed
        calibrations.append(
            Calibration(
                month=str(test_month),
                training_start=selected_dates.min().date().isoformat(),
                training_end=selected_dates.max().date().isoformat(),
                training_sessions=len(selected_dates),
                thresholds=thresholds,
            )
        )
    return candidates, calibrations


def run_historical_option_alpha(panel: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    positions, calibrations = rolling_positions(panel)
    evaluated_months = {item.month for item in calibrations}
    mask = panel["date"].dt.to_period("M").astype(str).isin(evaluated_months).to_numpy()
    evaluation = panel.loc[mask]
    results: dict[str, Any] = {}
    monthly_rows: list[dict[str, Any]] = []
    p_values: dict[str, float] = {}
    for name, full_position in positions.items():
        costs: dict[str, Any] = {}
        daily_primary: pd.DataFrame | None = None
        for cost in COSTS_BPS:
            daily = daily_pnl(evaluation, full_position[mask], cost)
            costs[f"cost_{cost:g}bps"] = asdict(strategy_metric(daily))
            if cost == PRIMARY_COST_BPS:
                daily_primary = daily
            monthly = daily.assign(month=daily["date"].dt.to_period("M").astype(str))
            for test_month, group in monthly.groupby("month", sort=True):
                monthly_rows.append(
                    {
                        "candidate": name,
                        "month": test_month,
                        "cost_bps": cost,
                        "mean_daily_bps": float(group["pnl_bps"].mean()),
                        "total_bps": float(group["pnl_bps"].sum()),
                        "round_trips": float(group["turnover"].sum() / 2.0),
                    }
                )
        if daily_primary is None:
            raise RuntimeError("primary cost was not evaluated")
        yearly = daily_primary.assign(year=daily_primary["date"].dt.year).groupby("year")
        yearly_metrics = {
            str(year): asdict(strategy_metric(group.drop(columns="year"))) for year, group in yearly
        }
        candidate_months = [
            row
            for row in monthly_rows
            if row["candidate"] == name and row["cost_bps"] == PRIMARY_COST_BPS
        ]
        positive_month_rate = float(
            np.mean([row["mean_daily_bps"] > 0.0 for row in candidate_months])
        )
        results[name] = {
            "costs": costs,
            "yearly_at_6bps": yearly_metrics,
            "positive_month_rate_at_6bps": positive_month_rate,
        }
        p_values[name] = costs["cost_6bps"]["one_sided_p"]
    corrected = holm_passes(p_values)
    stable = sorted(
        name
        for name in corrected
        if results[name]["costs"]["cost_6bps"]["mean_daily_bps"] > 0.0
        and results[name]["positive_month_rate_at_6bps"] >= 0.55
        and sum(
            metric["mean_daily_bps"] > 0.0 for metric in results[name]["yearly_at_6bps"].values()
        )
        >= 4
    )
    diagnostics: list[dict[str, Any]] = []
    for year, frame in panel.groupby(panel["date"].dt.year, sort=True):
        for signal, target in (
            ("atm_shock_30m", "atm_forward_30m"),
            ("atm_richness", "atm_relative_forward_30m"),
            ("premium_skew", "forward_return_bps"),
            ("volume_imbalance", "forward_return_bps"),
        ):
            finite = frame[[signal, target]].dropna()
            rho = spearmanr(finite[signal], finite[target]).statistic
            diagnostics.append(
                {
                    "year": int(year),
                    "signal": signal,
                    "target": target,
                    "samples": len(finite),
                    "spearman": float(rho),
                }
            )
    payload = {
        "protocol": {
            "evaluation": "monthly pseudo-live from 2022 through archive end",
            "calibration": "trailing 252 sessions, minimum 120, before each test month",
            "participation": PARTICIPATION,
            "cost_ladder_round_trip_bps": COSTS_BPS,
            "primary_cost_bps": PRIMARY_COST_BPS,
            "multiple_testing": "Holm correction across ten fixed directional candidates",
            "warning": (
                "NIFTY index return is a futures proxy; rolling option buckets are predictors only"
            ),
        },
        "calibrations": [asdict(item) for item in calibrations],
        "candidates": results,
        "yearly_diagnostics": diagnostics,
        "summary": {
            "holm_passes": sorted(corrected),
            "stable_candidates": stable,
            "verdict": "historical candidate survives" if stable else "cash; no stable candidate",
        },
    }
    return payload, pd.DataFrame(monthly_rows)
