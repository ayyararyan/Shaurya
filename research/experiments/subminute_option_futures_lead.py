"""Session-level test of whether NIFTY option-implied forwards lead futures.

For each session, choose the nearest-expiry CE/PE pair at the strike nearest the
first valid futures quote after 09:16.  The fixed-contract option-implied forward
is K + call_mid - put_mid.  We compare its trailing return with a strictly future
futures return over 1/2/5/10/30 seconds, including one- and two-second embargoes.
Inference is across sessions, not overlapping rows.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

HORIZONS = (1, 2, 5, 10, 30)
EMBARGOES = (0, 1, 2)
MARKET_START = "09:16:00"
MARKET_END = "15:29:00"
MONTHS = {name: number for number, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    1,
)}


@dataclass(frozen=True)
class Contract:
    path: Path
    expiry: date
    strike: int | None
    kind: str


def _last_thursday(year: int, month: int) -> date:
    day = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    while day.weekday() != 3:
        day -= pd.Timedelta(days=1)
    return day.date()


def parse_contract(path: Path) -> Contract | None:
    symbol = path.name.split("_20", 1)[0]
    future = re.fullmatch(r"NIFTY(\d{2})([A-Z]{3})FUT", symbol)
    if future:
        year, month = 2000 + int(future.group(1)), MONTHS[future.group(2)]
        return Contract(path, _last_thursday(year, month), None, "FUT")
    monthly = re.fullmatch(r"NIFTY(\d{2})([A-Z]{3})(\d+)(CE|PE)", symbol)
    if monthly:
        year, month = 2000 + int(monthly.group(1)), MONTHS[monthly.group(2)]
        return Contract(
            path, _last_thursday(year, month), int(monthly.group(3)), monthly.group(4)
        )
    weekly = re.fullmatch(r"NIFTY(\d{2})([1-9OND])(\d{2})(\d+)(CE|PE)", symbol)
    if weekly:
        month_code = weekly.group(2)
        month = int(month_code) if month_code.isdigit() else {"O": 10, "N": 11, "D": 12}[month_code]
        return Contract(
            path,
            date(2000 + int(weekly.group(1)), month, int(weekly.group(3))),
            int(weekly.group(4)),
            weekly.group(5),
        )
    return None


def _quote_grid(path: Path, session: date) -> pd.DataFrame:
    raw = pd.read_parquet(path, columns=["timestamp", "bp1", "sp1"])
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw["bid"] = pd.to_numeric(raw["bp1"], errors="coerce")
    raw["ask"] = pd.to_numeric(raw["sp1"], errors="coerce")
    raw = raw.sort_values("timestamp")
    raw[["bid", "ask"]] = raw[["bid", "ask"]].ffill()
    raw = raw.dropna(subset=["timestamp"]).set_index("timestamp")
    raw = raw.loc[~raw.index.duplicated(keep="last")]
    start = pd.Timestamp(f"{session} {MARKET_START}")
    end = pd.Timestamp(f"{session} {MARKET_END}")
    grid = pd.date_range(start, end, freq="1s")
    quote = raw[["bid", "ask"]].resample("1s").last().reindex(grid).ffill()
    quote["mid"] = (quote["bid"] + quote["ask"]) / 2.0
    quote.loc[(quote["bid"] <= 0) | (quote["ask"] < quote["bid"]), "mid"] = np.nan
    return quote


def select_contracts(day_dir: Path) -> tuple[Contract, Contract, Contract]:
    session = date.fromisoformat(day_dir.name.replace("_", "-"))
    contracts = [
        item
        for path in day_dir.glob("NIFTY*_*.parquet")
        if (item := parse_contract(path))
    ]
    futures = sorted(
        (item for item in contracts if item.kind == "FUT" and item.expiry >= session),
        key=lambda item: item.expiry,
    )
    if not futures:
        raise ValueError(f"no NIFTY future in {day_dir}")
    future = futures[0]
    future_grid = _quote_grid(future.path, session)
    valid = future_grid["mid"].dropna()
    if valid.empty:
        raise ValueError(f"no valid future quotes in {future.path}")
    reference = float(valid.iloc[0])
    options = [item for item in contracts if item.kind in {"CE", "PE"} and item.expiry >= session]
    expiries = sorted({item.expiry for item in options})
    for expiry in expiries:
        calls = {
            item.strike: item
            for item in options
            if item.expiry == expiry and item.kind == "CE"
        }
        puts = {
            item.strike: item
            for item in options
            if item.expiry == expiry and item.kind == "PE"
        }
        common = sorted(set(calls) & set(puts))
        if common:
            strike = min(common, key=lambda value: abs(float(value) - reference))
            return future, calls[strike], puts[strike]
    raise ValueError(f"no paired option contracts in {day_dir}")


def build_session(day_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    session = date.fromisoformat(day_dir.name.replace("_", "-"))
    future, call, put = select_contracts(day_dir)
    futures = _quote_grid(future.path, session).add_prefix("future_")
    calls = _quote_grid(call.path, session).add_prefix("call_")
    puts = _quote_grid(put.path, session).add_prefix("put_")
    frame = futures.join(calls).join(puts)
    frame["implied_forward"] = float(call.strike) + frame["call_mid"] - frame["put_mid"]
    frame.loc[frame["implied_forward"] <= 0, "implied_forward"] = np.nan
    return frame, {
        "session": session.isoformat(),
        "future": future.path.name,
        "call": call.path.name,
        "put": put.path.name,
        "strike": call.strike,
        "expiry": call.expiry.isoformat(),
        "rows": len(frame),
    }


def session_statistics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    log_option = np.log(frame["implied_forward"])
    log_future = np.log(frame["future_mid"])
    rows: list[dict[str, Any]] = []
    for source in HORIZONS:
        option_past = log_option - log_option.shift(source)
        future_past = log_future - log_future.shift(source)
        for target in HORIZONS:
            for embargo in EMBARGOES:
                future_next = log_future.shift(-(embargo + target)) - log_future.shift(-embargo)
                option_next = log_option.shift(-(embargo + target)) - log_option.shift(-embargo)
                for name, predictor, response in (
                    ("options_to_futures", option_past, future_next),
                    ("futures_to_options", future_past, option_next),
                    ("futures_autocorrelation", future_past, future_next),
                ):
                    valid = predictor.notna() & response.notna()
                    count = int(valid.sum())
                    rho = (
                        float(stats.spearmanr(predictor[valid], response[valid]).statistic)
                        if count >= 30
                        else np.nan
                    )
                    rows.append(
                        {
                            "direction": name,
                            "source_seconds": source,
                            "target_seconds": target,
                            "embargo_seconds": embargo,
                            "observations": count,
                            "spearman": rho,
                        }
                    )
    return rows


def aggregate(per_session: pd.DataFrame) -> pd.DataFrame:
    keys = ["direction", "source_seconds", "target_seconds", "embargo_seconds"]
    rows: list[dict[str, Any]] = []
    for values, group in per_session.groupby(keys, sort=True):
        rho = group["spearman"].dropna()
        p_value = (
            float(stats.wilcoxon(rho, alternative="greater").pvalue)
            if len(rho) >= 5
            else 1.0
        )
        rows.append(
            {
                **dict(zip(keys, values, strict=True)),
                "sessions": int(len(rho)),
                "median_session_spearman": float(rho.median()) if len(rho) else None,
                "mean_session_spearman": float(rho.mean()) if len(rho) else None,
                "positive_session_share": float(rho.gt(0).mean()) if len(rho) else None,
                "session_wilcoxon_p": p_value,
            }
        )
    result = pd.DataFrame(rows)
    result["holm_pass"] = False
    option_rows = result["direction"].eq("options_to_futures") & result["embargo_seconds"].gt(0)
    ordered = result.loc[option_rows].sort_values("session_wilcoxon_p").index.tolist()
    for rank, index in enumerate(ordered):
        cutoff = 0.05 / (len(ordered) - rank)
        if result.at[index, "session_wilcoxon_p"] <= cutoff:
            result.at[index, "holm_pass"] = True
        else:
            break
    return result


def run(roots: list[Path], output: Path) -> dict[str, Any]:
    day_dirs = sorted(day for root in roots for day in root.glob("2026_??_??") if day.is_dir())
    session_rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for day_dir in day_dirs:
        try:
            frame, metadata = build_session(day_dir)
            inventory.append(metadata)
            stats_rows = session_statistics(frame)
            for row in stats_rows:
                row["session"] = metadata["session"]
            session_rows.extend(stats_rows)
            print(json.dumps({"session": metadata["session"], "status": "complete"}), flush=True)
        except Exception as exc:
            failures.append({"session": day_dir.name, "error": str(exc)})
            print(
                json.dumps({"session": day_dir.name, "status": "failed", "error": str(exc)}),
                flush=True,
            )
    per_session = pd.DataFrame(session_rows)
    summary = aggregate(per_session)
    output.mkdir(parents=True, exist_ok=True)
    per_session.to_csv(output / "per_session.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    payload = {
        "protocol": {
            "hypothesis": "fixed ATM option-implied-forward returns lead NIFTY futures returns",
            "source_horizons_seconds": list(HORIZONS),
            "target_horizons_seconds": list(HORIZONS),
            "embargoes_seconds": list(EMBARGOES),
            "inference": (
                "Wilcoxon signed-rank across sessions; "
                "Holm across embargoed option-lead pairs"
            ),
            "controls": ["reverse futures-to-options", "futures autocorrelation"],
        },
        "sessions_completed": len(inventory),
        "failures": failures,
        "inventory": inventory,
        "holm_passes": summary.loc[summary["holm_pass"]].to_dict(orient="records"),
    }
    (output / "results.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.roots, args.output)
    print(
        json.dumps(
            {
                "sessions": result["sessions_completed"],
                "holm_passes": len(result["holm_passes"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
