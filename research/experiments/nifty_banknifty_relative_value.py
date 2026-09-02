"""Cost-aware NIFTY/BANKNIFTY futures relative-value screen.

Each trade is a static notional hedge: long one NIFTY notional and short a
rolling-beta BANKNIFTY notional, or the reverse. Signals and hedge ratios use
only prior one-second returns. January selects from a small fixed grid; February
is evaluated unchanged using futures bid/ask on both legs.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy import stats

NS = 1_000_000_000
HEDGE_WINDOWS = (300, 900)
SIGNAL_WINDOWS = (30, 60, 300)
ENTRY_ZS = (1.5, 2.0)
HOLDS = (30, 60, 300)
EXTRA_COST_BPS = (0.0, 0.5, 1.0, 2.0)
MIN_JANUARY_TRADES = 30


@dataclass(frozen=True)
class Candidate:
    hedge_window: int
    signal_window: int
    entry_z: float
    hold_seconds: int

    @property
    def name(self) -> str:
        return (
            f"rv_hw{self.hedge_window}_sw{self.signal_window}_"
            f"z{int(self.entry_z * 10)}_h{self.hold_seconds}"
        )


def candidates() -> list[Candidate]:
    return [
        Candidate(hedge, signal, z, hold)
        for hedge in HEDGE_WINDOWS
        for signal in SIGNAL_WINDOWS
        for z in ENTRY_ZS
        for hold in HOLDS
    ]


def _last_thursday(year: int, month: int) -> date:
    day = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    while day.weekday() != 3:
        day -= pd.Timedelta(days=1)
    return cast(date, day.date())


def _future_contract(path: Path, underlying: str) -> tuple[date, Path] | None:
    match = re.fullmatch(
        rf"{underlying}(\d{{2}})([A-Z]{{3}})FUT_\d{{4}}_\d{{2}}_\d{{2}}\.parquet",
        path.name,
    )
    if match is None:
        return None
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    return _last_thursday(2000 + int(match.group(1)), months[match.group(2)]), path


def _nearest_future(day_dir: Path, underlying: str) -> Path:
    session = date.fromisoformat(day_dir.name.replace("_", "-"))
    available = [
        item
        for path in day_dir.glob(f"{underlying}*FUT*.parquet")
        if (item := _future_contract(path, underlying)) is not None and item[0] >= session
    ]
    if not available:
        raise ValueError(f"no {underlying} future in {day_dir}")
    return min(available, key=lambda item: item[0])[1]


def _quote_grid(path: Path, session: date) -> pd.DataFrame:
    raw = pd.read_parquet(path, columns=["timestamp", "bp1", "sp1"])
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw["bid"] = pd.to_numeric(raw["bp1"], errors="coerce")
    raw["ask"] = pd.to_numeric(raw["sp1"], errors="coerce")
    raw = raw.sort_values("timestamp")
    raw[["bid", "ask"]] = raw[["bid", "ask"]].ffill()
    raw = raw.dropna(subset=["timestamp"]).set_index("timestamp")
    raw = raw.loc[~raw.index.duplicated(keep="last")]
    grid = pd.date_range(f"{session} 09:16:00", f"{session} 15:29:00", freq="1s")
    result = raw[["bid", "ask"]].resample("1s").last().reindex(grid).ffill()
    result["mid"] = (result["bid"] + result["ask"]) / 2.0
    result.loc[(result["bid"] <= 0.0) | (result["ask"] < result["bid"]), :] = np.nan
    return result


def load_session(day_dir: Path) -> pd.DataFrame:
    session = date.fromisoformat(day_dir.name.replace("_", "-"))
    nifty_path = _nearest_future(day_dir, "NIFTY")
    bank_path = _nearest_future(day_dir, "BANKNIFTY")
    nifty = _quote_grid(nifty_path, session).add_prefix("nifty_")
    bank = _quote_grid(bank_path, session).add_prefix("bank_")
    frame = nifty.join(bank)
    frame["session"] = session.isoformat()
    return frame


def prepare(frame: pd.DataFrame, candidate: Candidate) -> pd.DataFrame:
    result = frame.copy()
    ret_n = np.log(result["nifty_mid"]).diff()
    ret_b = np.log(result["bank_mid"]).diff()
    beta = ret_n.rolling(candidate.hedge_window, min_periods=candidate.hedge_window // 2).cov(ret_b)
    beta = beta / ret_b.rolling(
        candidate.hedge_window, min_periods=candidate.hedge_window // 2
    ).var()
    beta = beta.shift(1).clip(0.0, 3.0)
    relative = np.log(result["nifty_mid"]).diff(candidate.signal_window) - beta * np.log(
        result["bank_mid"]
    ).diff(candidate.signal_window)
    history = relative.shift(1).rolling(
        candidate.hedge_window, min_periods=candidate.hedge_window // 2
    )
    result["beta"] = beta
    result["zscore"] = (relative - history.mean()) / history.std().replace(0.0, np.nan)
    return result


def _leg_entry(side: int, bid: float, ask: float) -> float:
    return ask if side > 0 else bid


def _leg_exit(side: int, bid: float, ask: float) -> float:
    return bid if side > 0 else ask


def trades_for(frame: pd.DataFrame, candidate: Candidate) -> pd.DataFrame:
    prepared = prepare(frame, candidate)
    trades: list[dict[str, Any]] = []
    index = 0
    while index + 1 + candidate.hold_seconds < len(prepared):
        zscore = float(prepared["zscore"].iloc[index])
        beta = float(prepared["beta"].iloc[index])
        if not np.isfinite(zscore) or not np.isfinite(beta) or abs(zscore) < candidate.entry_z:
            index += 1
            continue
        entry, exit_ = index + 1, index + 1 + candidate.hold_seconds
        if prepared.index[entry] != prepared.index[index] + pd.Timedelta(seconds=1):
            index += 1
            continue
        if prepared.index[exit_] != prepared.index[entry] + pd.Timedelta(
            seconds=candidate.hold_seconds
        ):
            index += 1
            continue
        # Positive z means NIFTY outperformed its hedge; fade it.
        nifty_side = -int(np.sign(zscore))
        bank_side = -nifty_side
        entry_nifty = _leg_entry(
            nifty_side,
            float(prepared["nifty_bid"].iloc[entry]),
            float(prepared["nifty_ask"].iloc[entry]),
        )
        entry_bank = _leg_entry(
            bank_side,
            float(prepared["bank_bid"].iloc[entry]),
            float(prepared["bank_ask"].iloc[entry]),
        )
        exit_nifty = _leg_exit(
            nifty_side,
            float(prepared["nifty_bid"].iloc[exit_]),
            float(prepared["nifty_ask"].iloc[exit_]),
        )
        exit_bank = _leg_exit(
            bank_side,
            float(prepared["bank_bid"].iloc[exit_]),
            float(prepared["bank_ask"].iloc[exit_]),
        )
        prices = [entry_nifty, entry_bank, exit_nifty, exit_bank]
        if not np.isfinite(prices).all() or min(prices) <= 0.0:
            index += 1
            continue
        nifty_pnl = nifty_side * (exit_nifty - entry_nifty) / entry_nifty * 10_000.0
        bank_pnl = beta * bank_side * (exit_bank - entry_bank) / entry_bank * 10_000.0
        trades.append(
            {
                "session": prepared["session"].iloc[entry],
                "entry_time": prepared.index[entry].isoformat(),
                "exit_time": prepared.index[exit_].isoformat(),
                "zscore": zscore,
                "beta": beta,
                "nifty_side": nifty_side,
                "nifty_pnl_bps": nifty_pnl,
                "bank_pnl_bps": bank_pnl,
                "gross_pnl_bps": nifty_pnl + bank_pnl,
            }
        )
        index = exit_ + 1
    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, cost: float = 1.0) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0, "total_bps": 0.0}
    net = trades["gross_pnl_bps"] - cost
    daily = trades.assign(net=net).groupby("session")["net"].sum()
    return {
        "trades": len(trades),
        "days": int(trades["session"].nunique()),
        "gross_mean_bps": float(trades["gross_pnl_bps"].mean()),
        "gross_total_bps": float(trades["gross_pnl_bps"].sum()),
        "net_mean_bps": float(net.mean()),
        "total_bps": float(net.sum()),
        "win_rate": float((net > 0.0).mean()),
        "positive_days": int((daily > 0.0).sum()),
        "daily_wilcoxon_p": (
            float(stats.wilcoxon(daily, alternative="greater").pvalue)
            if len(daily) >= 5 and np.any(daily != 0.0)
            else 1.0
        ),
    }


def evaluate(
    frames: list[pd.DataFrame], candidate: Candidate
) -> tuple[pd.DataFrame, dict[str, Any]]:
    trades = pd.concat([trades_for(frame, candidate) for frame in frames], ignore_index=True)
    return trades, summarize(trades, 1.0)


def load_available_sessions(root: Path) -> tuple[list[pd.DataFrame], list[str]]:
    sessions: list[pd.DataFrame] = []
    skipped: list[str] = []
    for day in sorted(root.glob("2026_??_??")):
        try:
            sessions.append(load_session(day))
        except ValueError as error:
            if "future in" not in str(error):
                raise
            skipped.append(day.name)
    return sessions, skipped


def run(january_root: Path, february_root: Path, output: Path) -> dict[str, Any]:
    january, january_skipped = load_available_sessions(january_root)
    february, february_skipped = load_available_sessions(february_root)
    rows: list[dict[str, Any]] = []
    for candidate in candidates():
        _, metrics = evaluate(january, candidate)
        rows.append({"candidate": asdict(candidate), "name": candidate.name, "january": metrics})
    eligible = [row for row in rows if row["january"]["trades"] >= MIN_JANUARY_TRADES]
    selected = max(eligible, key=lambda row: row["january"]["total_bps"])
    selected_candidate = Candidate(**selected["candidate"])
    feb_trades, _ = evaluate(february, selected_candidate)
    result = {
        "protocol": {
            "selection": "January only, 36 fixed relative-value candidates",
            "evaluation": "February unchanged",
            "entry_delay_seconds": 1,
            "execution": "both futures legs cross bid/ask at entry and exit",
            "extra_cost_ladder_bps": list(EXTRA_COST_BPS),
            "notional_hedge": "one NIFTY notional against rolling-beta BANKNIFTY notional",
            "usable_sessions": {
                "january": len(january),
                "february": len(february),
                "january_skipped": january_skipped,
                "february_skipped": february_skipped,
            },
        },
        "candidates": rows,
        "selected": selected,
        "february_cost_ladder": {str(cost): summarize(feb_trades, cost) for cost in EXTRA_COST_BPS},
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    feb_trades.to_csv(output / "february_trades.csv", index=False)
    print(json.dumps({"selected": selected, "february": result["february_cost_ladder"]}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--january-root", type=Path, required=True)
    parser.add_argument("--february-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.january_root, args.february_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
