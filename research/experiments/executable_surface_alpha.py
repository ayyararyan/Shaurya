"""Cost-aware executable tests for ATM-IV and term-structure signals.

This intentionally tests a small, fixed family.  A signal is observed at t,
entry occurs at the next five-second state, and exits use the observed ATM
straddle bid/ask.  Trades are retained only when the same fixed ATM contract
strike is present at entry and exit.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

NS = 1_000_000_000
STEP_SECONDS = 5
ENTRY_DELAY_SECONDS = 5
MIN_TRADES = 20


@dataclass(frozen=True)
class Candidate:
    name: str
    instrument: str
    signal: str
    direction: int
    hold_seconds: int


def candidate_specs() -> list[Candidate]:
    specs: list[Candidate] = []
    for hold in (30, 60, 300):
        specs.extend(
            [
                Candidate(f"near_iv_delta30_revert_h{hold}", "near", "near_iv_delta30", -1, hold),
                Candidate(f"near_iv_z300_revert_h{hold}", "near", "near_iv_z300", -1, hold),
                Candidate(
                    f"term_iv_delta30_revert_h{hold}",
                    "calendar",
                    "term_iv_delta30",
                    -1,
                    hold,
                ),
                Candidate(f"term_iv_z300_revert_h{hold}", "calendar", "term_iv_z300", -1, hold),
            ]
        )
    return specs


def load_session(path: Path) -> pd.DataFrame:
    payload = np.load(path, allow_pickle=False)
    frame = pd.DataFrame(payload["values"], columns=payload["columns"].tolist())
    frame.insert(0, "timestamp_ns", payload["timestamps"].astype(np.int64))
    frame["trading_date"] = str(payload["trading_date"].tolist()[0])
    frame["future"] = np.exp(frame["futures_log_mid"])
    for bucket in ("near", "far"):
        frame[f"{bucket}_bid"] = (
            frame[f"atm__straddle_bid_to_future__{bucket}"] * frame["future"]
        )
        frame[f"{bucket}_ask"] = (
            frame[f"atm__straddle_ask_to_future__{bucket}"] * frame["future"]
        )
        frame[f"{bucket}_strike"] = frame[f"atm__strike__{bucket}"]
        frame[f"{bucket}_iv"] = frame[f"surface__atm_iv__{bucket}"]

    frame["term_iv"] = frame["near_iv"] - frame["far_iv"]
    frame["near_iv_delta30"] = frame["near_iv"] - frame["near_iv"].shift(6)
    frame["term_iv_delta30"] = frame["term_iv"] - frame["term_iv"].shift(6)
    for column, output in (("near_iv", "near_iv_z300"), ("term_iv", "term_iv_z300")):
        history = frame[column].shift(1).rolling(60, min_periods=30)
        scale = history.std().replace(0.0, np.nan)
        frame[output] = (frame[column] - history.mean()) / scale
    return frame


def fit_threshold(frame: pd.DataFrame, signal: str) -> float:
    values = frame[signal].abs().replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return math.inf
    return float(values.quantile(0.75))


def _fixed_contract_valid(frame: pd.DataFrame, entry: int, exit_: int, instrument: str) -> bool:
    buckets = ("near",) if instrument == "near" else ("near", "far")
    for bucket in buckets:
        entry_strike = frame.at[entry, f"{bucket}_strike"]
        exit_strike = frame.at[exit_, f"{bucket}_strike"]
        if not np.isfinite(entry_strike) or entry_strike != exit_strike:
            return False
    return True


def _pnl_points(frame: pd.DataFrame, entry: int, exit_: int, instrument: str, side: int) -> float:
    if instrument == "near":
        if side > 0:
            return float(frame.at[exit_, "near_bid"] - frame.at[entry, "near_ask"])
        return float(frame.at[entry, "near_bid"] - frame.at[exit_, "near_ask"])
    if side > 0:  # long near, short far
        return float(
            -frame.at[entry, "near_ask"]
            + frame.at[entry, "far_bid"]
            + frame.at[exit_, "near_bid"]
            - frame.at[exit_, "far_ask"]
        )
    return float(
        frame.at[entry, "near_bid"]
        - frame.at[entry, "far_ask"]
        - frame.at[exit_, "near_ask"]
        + frame.at[exit_, "far_bid"]
    )


def trades_for(frame: pd.DataFrame, candidate: Candidate, threshold: float) -> pd.DataFrame:
    delay_steps = ENTRY_DELAY_SECONDS // STEP_SECONDS
    hold_steps = candidate.hold_seconds // STEP_SECONDS
    rows: list[dict[str, Any]] = []
    next_free = 0
    for decision in range(len(frame)):
        signal = float(frame.at[decision, candidate.signal])
        if decision < next_free or not np.isfinite(signal) or abs(signal) < threshold:
            continue
        entry = decision + delay_steps
        exit_ = entry + hold_steps
        if exit_ >= len(frame):
            break
        expected_entry = int(frame.at[decision, "timestamp_ns"]) + ENTRY_DELAY_SECONDS * NS
        expected_exit = expected_entry + candidate.hold_seconds * NS
        if int(frame.at[entry, "timestamp_ns"]) != expected_entry:
            continue
        if int(frame.at[exit_, "timestamp_ns"]) != expected_exit:
            continue
        if not _fixed_contract_valid(frame, entry, exit_, candidate.instrument):
            continue
        quote_columns = ["near_bid", "near_ask"]
        if candidate.instrument == "calendar":
            quote_columns.extend(["far_bid", "far_ask"])
        if not np.isfinite(frame.loc[[entry, exit_], quote_columns].to_numpy()).all():
            continue
        side = int(np.sign(signal) * candidate.direction)
        pnl = _pnl_points(frame, entry, exit_, candidate.instrument, side)
        entry_scale = float(frame.at[entry, "near_ask"] + frame.at[entry, "near_bid"]) / 2.0
        rows.append(
            {
                "trading_date": frame.at[entry, "trading_date"],
                "decision_timestamp_ns": int(frame.at[decision, "timestamp_ns"]),
                "entry_timestamp_ns": int(frame.at[entry, "timestamp_ns"]),
                "exit_timestamp_ns": int(frame.at[exit_, "timestamp_ns"]),
                "side": side,
                "signal": signal,
                "pnl_points": pnl,
                "pnl_bps_of_near_premium": pnl / entry_scale * 10_000.0,
            }
        )
        next_free = exit_ + 1
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, surcharge_points: float = 0.0) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0, "mean_points": None, "total_points": 0.0, "p_value": 1.0}
    net = trades["pnl_points"] - surcharge_points
    if len(net) < 2 or float(net.std(ddof=1)) == 0.0:
        p_value = 1.0
    else:
        p_value = float(stats.ttest_1samp(net, 0.0, alternative="greater").pvalue)
    return {
        "trades": int(len(net)),
        "mean_points": float(net.mean()),
        "median_points": float(net.median()),
        "total_points": float(net.sum()),
        "win_rate": float(net.gt(0.0).mean()),
        "standard_error_points": (
            float(net.std(ddof=1) / math.sqrt(len(net))) if len(net) > 1 else None
        ),
        "p_value": p_value,
    }


def holm_passes(rows: list[dict[str, Any]], alpha: float = 0.05) -> set[str]:
    ordered = sorted(rows, key=lambda row: row["validation"]["p_value"])
    passed: set[str] = set()
    for index, row in enumerate(ordered):
        if row["validation"]["p_value"] <= alpha / (len(ordered) - index):
            passed.add(str(row["candidate"]["name"]))
        else:
            break
    return passed


def run(paths: list[Path], output: Path) -> dict[str, Any]:
    sessions = {frame["trading_date"].iloc[0]: frame for frame in map(load_session, paths)}
    required = {"2026-08-19", "2026-08-21", "2026-08-26", "2026-08-27"}
    if set(sessions) != required:
        raise ValueError(f"expected sessions {sorted(required)}, got {sorted(sessions)}")
    discovery = sessions["2026-08-19"]
    validation = sessions["2026-08-21"]
    rows: list[dict[str, Any]] = []
    for candidate in candidate_specs():
        threshold = fit_threshold(discovery, candidate.signal)
        discovery_trades = trades_for(discovery, candidate, threshold)
        validation_trades = trades_for(validation, candidate, threshold)
        row = {
            "candidate": asdict(candidate),
            "threshold": threshold,
            "discovery": summarize(discovery_trades, 1.0),
            "validation": summarize(validation_trades, 1.0),
            "diagnostics": {},
        }
        for date in ("2026-08-26", "2026-08-27"):
            trades = trades_for(sessions[date], candidate, threshold)
            row["diagnostics"][date] = {
                str(cost): summarize(trades, cost) for cost in (0.0, 0.5, 1.0, 2.0)
            }
        rows.append(row)
    eligible = [row for row in rows if row["validation"]["trades"] >= MIN_TRADES]
    passes = holm_passes(eligible)
    survivors = [
        row for row in eligible
        if row["candidate"]["name"] in passes and row["validation"]["mean_points"] > 0.0
    ]
    for row in rows:
        row["holm_validation_pass"] = row["candidate"]["name"] in passes
    result = {
        "protocol": {
            "discovery": "2026-08-19",
            "validation": "2026-08-21",
            "diagnostics": ["2026-08-26", "2026-08-27"],
            "candidate_count": len(rows),
            "entry_delay_seconds": ENTRY_DELAY_SECONDS,
            "fixed_contract_required": True,
            "execution": "observed ATM straddle bid/ask at entry and exit",
            "selection_surcharge_points": 1.0,
            "cost_ladder_surcharge_points": [0.0, 0.5, 1.0, 2.0],
            "multiple_testing": "one-sided trade t-tests with Holm correction",
        },
        "verdict": "candidate" if survivors else "cash",
        "survivors": [row["candidate"]["name"] for row in survivors],
        "rows": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    flat: list[dict[str, Any]] = []
    for row in rows:
        flat.append(
            {
                "candidate": row["candidate"]["name"],
                "validation_trades": row["validation"]["trades"],
                "validation_mean_points_after_1pt": row["validation"]["mean_points"],
                "validation_p_value": row["validation"]["p_value"],
                "holm_pass": row["holm_validation_pass"],
                "aug26_mean_after_1pt": row["diagnostics"]["2026-08-26"]["1.0"]["mean_points"],
                "aug27_mean_after_1pt": row["diagnostics"]["2026-08-27"]["1.0"]["mean_points"],
            }
        )
    pd.DataFrame(flat).sort_values(
        "validation_mean_points_after_1pt", ascending=False, na_position="last"
    ).to_csv(output / "summary.csv", index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sessions", nargs=4, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.sessions, args.output)
    print(json.dumps({"verdict": result["verdict"], "survivors": result["survivors"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
