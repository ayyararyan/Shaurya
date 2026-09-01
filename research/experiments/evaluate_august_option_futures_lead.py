"""Apply the January-selected option lead unchanged to August state tapes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from experiments.executable_option_futures_lead import summary
except ModuleNotFoundError:  # Direct script execution places experiments/ on sys.path.
    from executable_option_futures_lead import summary

STEP_SECONDS = 5
SOURCE_STEPS = 2
ENTRY_DELAY_STEPS = 1
HOLD_STEPS = 1


def load_state(path: Path) -> pd.DataFrame:
    payload = np.load(path, allow_pickle=False)
    frame = pd.DataFrame(payload["values"], columns=payload["columns"].tolist())
    frame["timestamp_ns"] = payload["timestamps"].astype(np.int64)
    frame["future_mid"] = np.exp(frame["futures_log_mid"])
    half_spread = frame["futures_relative_spread"] / 2.0
    frame["future_bid"] = frame["future_mid"] * (1.0 - half_spread)
    frame["future_ask"] = frame["future_mid"] * (1.0 + half_spread)
    frame["implied_forward"] = (
        frame["atm__strike__near"]
        + frame["future_mid"] * frame["atm_near_call_put_skew"]
    )
    frame["trading_date"] = str(payload["trading_date"].tolist()[0])
    return frame


def returns_for(frame: pd.DataFrame, threshold: float, beta: float) -> np.ndarray:
    option_return = np.log(frame["implied_forward"]).diff(SOURCE_STEPS)
    future_return = np.log(frame["future_mid"]).diff(SOURCE_STEPS)
    signal = option_return - beta * future_return
    rows: list[float] = []
    index = SOURCE_STEPS
    final_offset = ENTRY_DELAY_STEPS + HOLD_STEPS
    while index + final_offset < len(frame):
        value = float(signal.iloc[index])
        entry = index + ENTRY_DELAY_STEPS
        exit_ = entry + HOLD_STEPS
        expected = (
            int(frame["timestamp_ns"].iloc[index])
            + final_offset * STEP_SECONDS * 1_000_000_000
        )
        strikes = frame["atm__strike__near"].iloc[index - SOURCE_STEPS : exit_ + 1]
        fixed_strike = strikes.notna().all() and strikes.nunique() == 1
        if (
            not np.isfinite(value)
            or abs(value) < threshold
            or value == 0.0
            or int(frame["timestamp_ns"].iloc[exit_]) != expected
            or not fixed_strike
        ):
            index += 1
            continue
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


def run(prior: Path, sessions: list[Path], output: Path) -> dict[str, Any]:
    frozen = json.loads(prior.read_text())
    threshold = float(frozen["selected"]["threshold"])
    beta = float(frozen["residual_beta_fit_january"])
    by_day: list[dict[str, Any]] = []
    all_values: list[np.ndarray] = []
    for path in sessions:
        frame = load_state(path)
        values = returns_for(frame, threshold, beta)
        all_values.append(values)
        by_day.append({"session": frame["trading_date"].iloc[0], **summary(values)})
    combined = np.concatenate(all_values)
    result = {
        "protocol": {
            "frozen_from": str(prior),
            "signal": frozen["selected"]["signal"],
            "threshold": threshold,
            "residual_beta": beta,
            "source_seconds": SOURCE_STEPS * STEP_SECONDS,
            "entry_delay_seconds": ENTRY_DELAY_STEPS * STEP_SECONDS,
            "holding_seconds": HOLD_STEPS * STEP_SECONDS,
            "fixed_atm_strike_required": True,
            "execution": "reconstructed futures bid/ask from recorded midpoint and spread",
        },
        "combined": summary(combined),
        "by_day": by_day,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, nargs=4, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.prior, args.sessions, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
