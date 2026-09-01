"""Delta-hedged NIFTY straddle carry using a pre-2026 volatility model.

The historical model is fit only on observations before 2026.  January is
used to select among 18 fixed horizon/edge/hedge-cadence candidates; February is
evaluated with the selected rule. Options and futures cross the recorded bid/ask,
entry is delayed one second, the option pair remains fixed for the trade, and
the futures hedge is rebalanced once per minute.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

try:
    from experiments.subminute_option_futures_lead import build_session
except ModuleNotFoundError:  # Direct execution places experiments/ on sys.path.
    from subminute_option_futures_lead import build_session

from shaurya.research.intraday_volatility import INDEX_FEATURES, build_panel, model_factories

TRADING_MINUTES_PER_YEAR = 252 * 375
ENTRY_DELAY_SECONDS = 1
HEDGE_INTERVAL_SECONDS = (60, 300, 900)
EXTRA_COST_POINTS = (0.0, 0.5, 1.0, 2.0)
MIN_JANUARY_TRADES = 10


@dataclass(frozen=True)
class Candidate:
    horizon_minutes: int
    edge_vol_points: float
    hedge_interval_seconds: int

    @property
    def name(self) -> str:
        return (
            f"carry_h{self.horizon_minutes}_edge{int(self.edge_vol_points * 100):02d}"
            f"_hedge{self.hedge_interval_seconds}"
        )


def candidates() -> list[Candidate]:
    return [
        Candidate(horizon, edge, hedge)
        for horizon in (30, 60)
        for edge in (0.0, 0.02, 0.04)
        for hedge in HEDGE_INTERVAL_SECONDS
    ]


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_straddle(forward: float, strike: float, t_years: float, sigma: float) -> float:
    if min(forward, strike, t_years, sigma) <= 0.0:
        return math.nan
    root_t = math.sqrt(t_years)
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t_years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    call = forward * _normal_cdf(d1) - strike * _normal_cdf(d2)
    put = strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1)
    return call + put


def implied_straddle_vol(
    price: float, forward: float, strike: float, t_years: float
) -> float:
    intrinsic = abs(forward - strike)
    if not all(np.isfinite([price, forward, strike, t_years])) or price <= intrinsic:
        return math.nan
    low, high = 1e-4, 5.0
    if black_straddle(forward, strike, t_years, high) < price:
        return math.nan
    for _ in range(80):
        middle = (low + high) / 2.0
        if black_straddle(forward, strike, t_years, middle) < price:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def straddle_delta(forward: float, strike: float, t_years: float, sigma: float) -> float:
    if min(forward, strike, t_years, sigma) <= 0.0:
        return math.nan
    d1 = (
        math.log(forward / strike) + 0.5 * sigma * sigma * t_years
    ) / (sigma * math.sqrt(t_years))
    return 2.0 * _normal_cdf(d1) - 1.0


def futures_trade_cashflow(quantity: float, bid: float, ask: float) -> float:
    """Cashflow for changing futures position by quantity at adverse touch."""
    if not all(np.isfinite([quantity, bid, ask])) or bid <= 0.0 or ask < bid:
        return math.nan
    return -quantity * (ask if quantity > 0.0 else bid)


def _years_to_expiry(timestamp: pd.Timestamp, expiry: date) -> float:
    expiry_time = pd.Timestamp(f"{expiry.isoformat()} 15:30:00")
    return max(float((expiry_time - timestamp).total_seconds()), 0.0) / (365.25 * 86_400.0)


def _forward(frame: pd.DataFrame, index: int, strike: float) -> float:
    return float(strike + frame["call_mid"].iloc[index] - frame["put_mid"].iloc[index])


def _trade_signal(
    predicted_sigma: float,
    bid_iv: float,
    ask_iv: float,
    edge: float,
) -> int:
    if predicted_sigma > ask_iv + edge:
        return 1
    if predicted_sigma < bid_iv - edge:
        return -1
    return 0


def simulate_trade(
    frame: pd.DataFrame,
    decision_index: int,
    expiry: date,
    strike: float,
    predicted_sigma: float,
    candidate: Candidate,
) -> dict[str, Any] | None:
    entry = decision_index + ENTRY_DELAY_SECONDS
    exit_ = entry + candidate.horizon_minutes * 60
    if exit_ >= len(frame):
        return None
    timestamps = frame.index
    if timestamps[entry] != timestamps[decision_index] + pd.Timedelta(seconds=1):
        return None
    if timestamps[exit_] != timestamps[entry] + pd.Timedelta(minutes=candidate.horizon_minutes):
        return None
    entry_values = frame.iloc[entry]
    required = [
        "call_bid", "call_ask", "put_bid", "put_ask", "future_bid", "future_ask"
    ]
    if not np.isfinite(entry_values[required].to_numpy(dtype=float)).all():
        return None
    forward = _forward(frame, entry, strike)
    if not np.isfinite(forward) or abs(strike / forward - 1.0) > 0.01:
        return None
    t_years = _years_to_expiry(timestamps[entry], expiry)
    if t_years < 1.0 / 365.25:
        return None
    bid_price = float(entry_values["call_bid"] + entry_values["put_bid"])
    ask_price = float(entry_values["call_ask"] + entry_values["put_ask"])
    bid_iv = implied_straddle_vol(bid_price, forward, strike, t_years)
    ask_iv = implied_straddle_vol(ask_price, forward, strike, t_years)
    if not all(np.isfinite([bid_iv, ask_iv])):
        return None
    side = _trade_signal(predicted_sigma, bid_iv, ask_iv, candidate.edge_vol_points)
    if side == 0:
        return None

    entry_option = ask_price if side > 0 else bid_price
    futures_position = 0.0
    hedge_cashflow = 0.0
    hedge_trades = 0
    for hedge_index in range(entry, exit_, candidate.hedge_interval_seconds):
        row = frame.iloc[hedge_index]
        current_forward = _forward(frame, hedge_index, strike)
        current_t = _years_to_expiry(timestamps[hedge_index], expiry)
        current_mid = float(row["call_mid"] + row["put_mid"])
        sigma = implied_straddle_vol(current_mid, current_forward, strike, current_t)
        delta = straddle_delta(current_forward, strike, current_t, sigma)
        if not np.isfinite(delta):
            continue
        desired = -side * delta
        change = desired - futures_position
        cashflow = futures_trade_cashflow(
            change, float(row["future_bid"]), float(row["future_ask"])
        )
        if not np.isfinite(cashflow):
            continue
        hedge_cashflow += cashflow
        futures_position = desired
        hedge_trades += int(abs(change) > 1e-12)

    exit_row = frame.iloc[exit_]
    if not np.isfinite(exit_row[required].to_numpy(dtype=float)).all():
        return None
    exit_option = (
        float(exit_row["call_bid"] + exit_row["put_bid"])
        if side > 0
        else float(exit_row["call_ask"] + exit_row["put_ask"])
    )
    option_pnl = side * (exit_option - entry_option)
    close_cashflow = futures_trade_cashflow(
        -futures_position,
        float(exit_row["future_bid"]),
        float(exit_row["future_ask"]),
    )
    if not np.isfinite(close_cashflow):
        return None
    hedge_cashflow += close_cashflow
    gross = option_pnl + hedge_cashflow
    return {
        "entry_time": timestamps[entry].isoformat(),
        "exit_time": timestamps[exit_].isoformat(),
        "side": side,
        "predicted_sigma": predicted_sigma,
        "bid_iv": bid_iv,
        "ask_iv": ask_iv,
        "option_pnl_points": option_pnl,
        "hedge_pnl_points": hedge_cashflow,
        "gross_pnl_points": gross,
        "hedge_trades": hedge_trades,
    }


def fit_predictions(
    index_zip: Path, options_zip: Path
) -> tuple[dict[int, pd.Series], dict[str, Any]]:
    panel, audit = build_panel(index_zip, options_zip, horizons=(30, 60))
    training = panel[panel["date"] < pd.Timestamp("2026-01-01")].copy()
    evaluation = panel[
        panel["date"].between(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-28"))
    ].copy()
    predictions: dict[int, pd.Series] = {}
    for horizon in (30, 60):
        features, model = model_factories()["hist_index"]
        model.fit(training[features], training[f"realized_vol_{horizon}"])
        predicted_bps = np.maximum(model.predict(evaluation[features]), 0.0)
        annualized = predicted_bps / 10_000.0 * math.sqrt(
            TRADING_MINUTES_PER_YEAR / horizon
        )
        predictions[horizon] = pd.Series(annualized, index=evaluation["datetime"])
    metadata = {
        "training_start": training["datetime"].min().isoformat(),
        "training_end": training["datetime"].max().isoformat(),
        "evaluation_start": evaluation["datetime"].min().isoformat(),
        "evaluation_end": evaluation["datetime"].max().isoformat(),
        "training_rows": len(training),
        "evaluation_rows": len(evaluation),
        "features": INDEX_FEATURES,
        "audit": asdict(audit),
    }
    return predictions, metadata


def run_session(
    day_dir: Path,
    prediction: pd.Series,
    candidate: Candidate,
) -> list[dict[str, Any]]:
    frame, metadata = build_session(day_dir)
    expiry = date.fromisoformat(metadata["expiry"])
    strike = float(metadata["strike"])
    trades: list[dict[str, Any]] = []
    next_free = 0
    index_lookup = pd.Series(np.arange(len(frame)), index=frame.index)
    for timestamp, predicted_sigma in prediction.items():
        if timestamp.date().isoformat() != metadata["session"] or timestamp not in index_lookup:
            continue
        decision = int(index_lookup.loc[timestamp])
        if decision < next_free:
            continue
        trade = simulate_trade(
            frame, decision, expiry, strike, float(predicted_sigma), candidate
        )
        if trade is not None:
            trade["session"] = metadata["session"]
            trades.append(trade)
            next_free = decision + ENTRY_DELAY_SECONDS + candidate.horizon_minutes * 60 + 1
    return trades


def summarize(trades: pd.DataFrame, extra_cost: float = 1.0) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0, "total_points": 0.0}
    net = trades["gross_pnl_points"] - extra_cost
    daily = trades.assign(net=net).groupby("session")["net"].sum()
    return {
        "trades": len(trades),
        "days": int(trades["session"].nunique()),
        "long_trades": int((trades["side"] > 0).sum()),
        "short_trades": int((trades["side"] < 0).sum()),
        "gross_mean_points": float(trades["gross_pnl_points"].mean()),
        "gross_total_points": float(trades["gross_pnl_points"].sum()),
        "net_mean_points": float(net.mean()),
        "total_points": float(net.sum()),
        "win_rate": float((net > 0.0).mean()),
        "positive_days": int((daily > 0.0).sum()),
        "daily_wilcoxon_p": (
            float(stats.wilcoxon(daily, alternative="greater").pvalue)
            if len(daily) >= 5 and np.any(daily != 0.0)
            else 1.0
        ),
    }


def run(
    index_zip: Path,
    options_zip: Path,
    january_root: Path,
    february_root: Path,
    output: Path,
) -> dict[str, Any]:
    predictions, model_metadata = fit_predictions(index_zip, options_zip)
    january_days = sorted(january_root.glob("2026_??_??"))
    february_days = sorted(february_root.glob("2026_??_??"))
    rows: list[dict[str, Any]] = []
    for candidate in candidates():
        trades = [
            trade
            for day in january_days
            for trade in run_session(day, predictions[candidate.horizon_minutes], candidate)
        ]
        frame = pd.DataFrame(trades)
        rows.append(
            {
                "candidate": asdict(candidate),
                "name": candidate.name,
                "january": summarize(frame, 1.0),
            }
        )
        print(json.dumps({"candidate": candidate.name, "january": rows[-1]["january"]}), flush=True)
    eligible = [row for row in rows if row["january"]["trades"] >= MIN_JANUARY_TRADES]
    if not eligible:
        raise ValueError("no candidate produced enough January trades")
    selected = max(eligible, key=lambda row: row["january"]["total_points"])
    selected_candidate = Candidate(**selected["candidate"])
    february_trades = [
        trade
        for day in february_days
        for trade in run_session(
            day, predictions[selected_candidate.horizon_minutes], selected_candidate
        )
    ]
    february_frame = pd.DataFrame(february_trades)
    cost_ladder = {
        str(cost): summarize(february_frame, cost) for cost in EXTRA_COST_POINTS
    }
    result = {
        "protocol": {
            "model_training": "all accepted samples before 2026-01-01",
            "selection": "18 fixed horizon/edge/hedge-cadence candidates on January 2026",
            "evaluation": "selected rule unchanged on February 2026",
            "entry_delay_seconds": ENTRY_DELAY_SECONDS,
            "hedge_interval_seconds": list(HEDGE_INTERVAL_SECONDS),
            "execution": "option and futures bid/ask crossing",
            "fixed_daily_option_pair": True,
            "extra_cost_points": list(EXTRA_COST_POINTS),
        },
        "model": model_metadata,
        "candidates": rows,
        "selected": selected,
        "february_cost_ladder": cost_ladder,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    february_frame.to_csv(output / "february_trades.csv", index=False)
    print(json.dumps({"selected": selected, "february": cost_ladder}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--options-zip", type=Path, required=True)
    parser.add_argument("--january-root", type=Path, required=True)
    parser.add_argument("--february-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.index_zip, args.options_zip, args.january_root, args.february_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
