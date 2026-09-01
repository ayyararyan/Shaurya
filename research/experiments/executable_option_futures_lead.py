"""Executable January-selection / February-evaluation of the option lead."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

try:
    from experiments.subminute_option_futures_lead import build_session
except ModuleNotFoundError:  # Direct script execution places experiments/ on sys.path.
    from subminute_option_futures_lead import build_session

SOURCE_SECONDS = 10
TARGET_SECONDS = 5
ENTRY_DELAY_SECONDS = 1
QUANTILES = (0.0, 0.5, 0.75, 0.9)
COSTS_BPS = (0.0, 1.0, 2.0, 6.0)


def trade_returns(
    frame: pd.DataFrame,
    signal_name: str,
    threshold: float,
    residual_beta: float,
) -> np.ndarray:
    option_return = np.log(frame["implied_forward"]).diff(SOURCE_SECONDS)
    future_past = np.log(frame["future_mid"]).diff(SOURCE_SECONDS)
    signal = option_return
    if signal_name == "option_residual":
        signal = option_return - residual_beta * future_past
    rows: list[float] = []
    index = 0
    while index + ENTRY_DELAY_SECONDS + TARGET_SECONDS < len(frame):
        value = float(signal.iloc[index])
        if not np.isfinite(value) or abs(value) < threshold or value == 0.0:
            index += 1
            continue
        entry = index + ENTRY_DELAY_SECONDS
        exit_ = entry + TARGET_SECONDS
        side = int(np.sign(value))
        if side > 0:
            entry_price = float(frame["future_ask"].iloc[entry])
            exit_price = float(frame["future_bid"].iloc[exit_])
            pnl = exit_price - entry_price
        else:
            entry_price = float(frame["future_bid"].iloc[entry])
            exit_price = float(frame["future_ask"].iloc[exit_])
            pnl = entry_price - exit_price
        if all(np.isfinite([entry_price, exit_price, pnl])) and entry_price > 0.0:
            rows.append(pnl / entry_price * 10_000.0)
            index = exit_ + 1
        else:
            index += 1
    return np.asarray(rows, dtype=np.float64)


def summary(values: np.ndarray) -> dict[str, Any]:
    if len(values) == 0:
        return {"trades": 0}
    result: dict[str, Any] = {
        "trades": int(len(values)),
        "gross_mean_bps": float(values.mean()),
        "gross_total_bps": float(values.sum()),
        "gross_win_rate": float(np.mean(values > 0.0)),
    }
    for cost in COSTS_BPS:
        net = values - cost
        p_value = (
            float(stats.ttest_1samp(net, 0.0, alternative="greater").pvalue)
            if len(net) > 1 and float(net.std(ddof=1)) > 0.0
            else 1.0
        )
        result[f"net_mean_bps_at_{cost:g}"] = float(net.mean())
        result[f"net_total_bps_at_{cost:g}"] = float(net.sum())
        result[f"p_value_at_{cost:g}"] = p_value
    return result


def load_month(root: Path) -> tuple[list[pd.DataFrame], list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    metadata: list[dict[str, Any]] = []
    for day in sorted(root.glob("2026_??_??")):
        frame, details = build_session(day)
        frames.append(frame)
        metadata.append(details)
        print(json.dumps({"session": details["session"], "status": "loaded"}), flush=True)
    return frames, metadata


def fit_residual_beta(frames: list[pd.DataFrame]) -> float:
    option_values: list[np.ndarray] = []
    future_values: list[np.ndarray] = []
    for frame in frames:
        option = np.log(frame["implied_forward"]).diff(SOURCE_SECONDS)
        future = np.log(frame["future_mid"]).diff(SOURCE_SECONDS)
        valid = option.notna() & future.notna()
        option_values.append(option[valid].to_numpy())
        future_values.append(future[valid].to_numpy())
    option_all = np.concatenate(option_values)
    future_all = np.concatenate(future_values)
    denominator = float(np.dot(future_all, future_all))
    return float(np.dot(future_all, option_all) / denominator) if denominator > 0.0 else 0.0


def threshold_for(
    frames: list[pd.DataFrame], signal_name: str, quantile: float, beta: float
) -> float:
    values: list[np.ndarray] = []
    for frame in frames:
        option = np.log(frame["implied_forward"]).diff(SOURCE_SECONDS)
        future = np.log(frame["future_mid"]).diff(SOURCE_SECONDS)
        signal = option if signal_name == "option_raw" else option - beta * future
        values.append(signal.abs().dropna().to_numpy())
    return float(np.quantile(np.concatenate(values), quantile))


def combined_returns(
    frames: list[pd.DataFrame], signal_name: str, threshold: float, beta: float
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    arrays: list[np.ndarray] = []
    by_day: list[dict[str, Any]] = []
    for frame in frames:
        values = trade_returns(frame, signal_name, threshold, beta)
        arrays.append(values)
        day = str(frame.index[0].date())
        by_day.append({"session": day, **summary(values)})
    return np.concatenate(arrays) if arrays else np.asarray([]), by_day


def run(january_root: Path, february_root: Path, output: Path) -> dict[str, Any]:
    january, january_inventory = load_month(january_root)
    february, february_inventory = load_month(february_root)
    beta = fit_residual_beta(january)
    candidates: list[dict[str, Any]] = []
    for signal_name in ("option_raw", "option_residual"):
        for quantile in QUANTILES:
            threshold = threshold_for(january, signal_name, quantile, beta)
            values, by_day = combined_returns(january, signal_name, threshold, beta)
            candidates.append(
                {
                    "signal": signal_name,
                    "quantile": quantile,
                    "threshold": threshold,
                    "january": summary(values),
                    "january_by_day": by_day,
                }
            )
    eligible = [row for row in candidates if row["january"]["trades"] >= 100]
    selected = max(eligible, key=lambda row: row["january"]["net_mean_bps_at_1"])
    february_values, february_by_day = combined_returns(
        february, selected["signal"], selected["threshold"], beta
    )
    result = {
        "protocol": {
            "selection": "January only",
            "evaluation": "February unchanged",
            "source_seconds": SOURCE_SECONDS,
            "entry_delay_seconds": ENTRY_DELAY_SECONDS,
            "holding_seconds": TARGET_SECONDS,
            "execution": "futures ask/bid crossing at entry and bid/ask crossing at exit",
            "cost_ladder_bps_beyond_observed_spread": list(COSTS_BPS),
            "threshold_quantiles": list(QUANTILES),
        },
        "residual_beta_fit_january": beta,
        "selected": {key: selected[key] for key in ("signal", "quantile", "threshold", "january")},
        "february": summary(february_values),
        "february_by_day": february_by_day,
        "candidates": candidates,
        "inventory": {"january": january_inventory, "february": february_inventory},
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    pd.DataFrame(february_by_day).to_csv(output / "february_by_day.csv", index=False)
    print(json.dumps({"selected": result["selected"], "february": result["february"]}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("january_root", type=Path)
    parser.add_argument("february_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.january_root, args.february_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
