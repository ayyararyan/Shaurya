"""Cost-aware, chronological alpha screen for the 2026-08-26 NIFTY tape.

The final `sample_role == "test"` segment is evaluated only when a candidate
survives discovery selection and Holm-corrected validation.
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
FEATURES = (
    "futures_return_5s_option_signed",
    "futures_return_10s_option_signed",
    "futures_return_30s_option_signed",
    "futures_depth_option_signed",
    "futures_microprice_option_signed",
    "option_depth_imbalance",
    "option_microprice_dislocation",
    "option_return_5s",
    "lead_lag_5s",
    "lead_lag_10s",
)


@dataclass(frozen=True)
class Candidate:
    feature: str
    quantile: float
    direction: int
    expiry: str
    moneyness: float
    horizon_seconds: int

    @property
    def name(self) -> str:
        side = "follow" if self.direction == 1 else "fade"
        money = int(round(self.moneyness * 10_000))
        return (
            f"{self.feature}__q{int(self.quantile * 100)}__{side}__"
            f"{self.expiry}__m{money}bp__h{self.horizon_seconds}"
        )


def _future_return(frame: pd.DataFrame, seconds: int) -> pd.Series:
    states = (
        frame[["timestamp_ns", "futures_log_mid"]]
        .drop_duplicates("timestamp_ns")
        .sort_values("timestamp_ns")
    )
    past = states.rename(
        columns={"timestamp_ns": "past_timestamp_ns", "futures_log_mid": "past_log_mid"}
    )
    joined = states.assign(past_timestamp_ns=states["timestamp_ns"] - seconds * NS).merge(
        past, on="past_timestamp_ns", how="left"
    )
    values = (
        joined.set_index("timestamp_ns")["futures_log_mid"]
        - joined.set_index("timestamp_ns")["past_log_mid"]
    )
    return frame["timestamp_ns"].map(values)


def prepare_panel(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    parts = frame["instrument_id"].str.split(":")
    frame["expiry_date"] = parts.str[4]
    frame["strike"] = pd.to_numeric(parts.str[5])
    frame["option_kind"] = parts.str[6]
    expiries = sorted(frame["expiry_date"].unique())
    if len(expiries) != 2:
        raise ValueError(f"expected exactly two expiries, got {expiries}")
    frame["expiry_bucket"] = frame["expiry_date"].map({expiries[0]: "near", expiries[1]: "far"})
    frame["option_mid"] = np.exp(frame["option_log_mid"])
    frame["future_mid"] = np.exp(frame["futures_log_mid"])
    frame["moneyness"] = (frame["strike"] / frame["future_mid"] - 1.0).abs()
    frame["delta_sign"] = np.where(frame["option_kind"].eq("CE"), 1.0, -1.0)

    for seconds in (5, 10, 30):
        frame[f"futures_return_{seconds}s"] = _future_return(frame, seconds)
    frame["futures_return_5s_option_signed"] = frame["futures_return_5s"] * frame["delta_sign"]
    frame["futures_return_10s_option_signed"] = frame["futures_return_10s"] * frame["delta_sign"]
    frame["futures_return_30s_option_signed"] = frame["futures_return_30s"] * frame["delta_sign"]
    frame["futures_depth_option_signed"] = frame["futures_depth_imbalance"] * frame["delta_sign"]
    frame["futures_microprice_option_signed"] = (
        frame["futures_microprice_dislocation"] * frame["delta_sign"]
    )
    frame["lead_lag_5s"] = frame["futures_return_5s_option_signed"] - frame["option_return_5s"]
    frame["lead_lag_10s"] = frame["futures_return_10s_option_signed"] - frame["option_return_5s"]

    future_quotes = frame[["instrument_id", "timestamp_ns", "option_mid", "option_relative_spread"]]
    for seconds in (5, 30):
        quotes = future_quotes.rename(
            columns={
                "timestamp_ns": "exit_timestamp_ns",
                "option_mid": f"exit_mid_{seconds}s",
                "option_relative_spread": f"exit_relative_spread_{seconds}s",
            }
        )
        frame["exit_timestamp_ns"] = frame["timestamp_ns"] + seconds * NS
        frame = frame.merge(quotes, on=["instrument_id", "exit_timestamp_ns"], how="left")
        exit_mid = frame[f"exit_mid_{seconds}s"]
        exit_half = exit_mid * frame[f"exit_relative_spread_{seconds}s"] / 2.0
        entry_half = frame["option_mid"] * frame["option_relative_spread"] / 2.0
        frame[f"gross_long_bps_{seconds}s"] = (
            (exit_mid - frame["option_mid"]) / frame["option_mid"] * 10_000.0
        )
        frame[f"gross_short_bps_{seconds}s"] = -frame[f"gross_long_bps_{seconds}s"]
        frame[f"net_long_bps_{seconds}s"] = (
            ((exit_mid - exit_half) - (frame["option_mid"] + entry_half))
            / frame["option_mid"]
            * 10_000.0
        )
        frame[f"net_short_bps_{seconds}s"] = (
            ((frame["option_mid"] - entry_half) - (exit_mid + exit_half))
            / frame["option_mid"]
            * 10_000.0
        )
        frame = frame.drop(columns="exit_timestamp_ns")
    return frame


def candidates() -> list[Candidate]:
    return [
        Candidate(feature, quantile, direction, expiry, moneyness, horizon)
        for feature in FEATURES
        for quantile in (0.50, 0.75, 0.90)
        for direction in (-1, 1)
        for expiry in ("near", "far")
        for moneyness in (0.005, 0.010)
        for horizon in (5, 30)
    ]


def _eligible(frame: pd.DataFrame, candidate: Candidate) -> pd.DataFrame:
    eligible = frame[
        frame["eligible_buffer_30s"]
        & frame["expiry_bucket"].eq(candidate.expiry)
        & frame["moneyness"].le(candidate.moneyness)
        & frame[candidate.feature].notna()
        & frame[f"net_long_bps_{candidate.horizon_seconds}s"].notna()
    ]
    if candidate.horizon_seconds == 30:
        seconds = eligible["timestamp_ns"].floordiv(NS)
        eligible = eligible[seconds.mod(30).eq(0)]
    return eligible


def threshold_for(discovery: pd.DataFrame, candidate: Candidate) -> float:
    eligible = _eligible(discovery, candidate)
    if eligible.empty:
        return math.inf
    return float(eligible[candidate.feature].abs().quantile(candidate.quantile))


def trades_for(frame: pd.DataFrame, candidate: Candidate, threshold: float) -> pd.DataFrame:
    eligible = _eligible(frame, candidate)
    eligible = eligible[eligible[candidate.feature].abs().ge(threshold)].copy()
    if eligible.empty:
        return eligible
    # One executable choice per timestamp: prefer the tightest quoted option.
    chosen = eligible.loc[
        eligible.groupby("timestamp_ns")["option_relative_spread"].idxmin()
    ].copy()
    raw_position = np.sign(chosen[candidate.feature].to_numpy()) * candidate.direction
    chosen["position"] = raw_position.astype(int)
    horizon = candidate.horizon_seconds
    chosen["gross_bps"] = np.where(
        chosen["position"].eq(1),
        chosen[f"gross_long_bps_{horizon}s"],
        chosen[f"gross_short_bps_{horizon}s"],
    )
    chosen["net_bps"] = np.where(
        chosen["position"].eq(1),
        chosen[f"net_long_bps_{horizon}s"],
        chosen[f"net_short_bps_{horizon}s"],
    )
    return chosen.sort_values("timestamp_ns")


def evaluate(frame: pd.DataFrame, candidate: Candidate, threshold: float) -> dict[str, Any]:
    trades = trades_for(frame, candidate, threshold)
    if trades.empty:
        return {"trades": 0, "gross_mean_bps": None, "net_mean_bps": None, "p_value": 1.0}
    minute = trades["timestamp_ns"].floordiv(60 * NS)
    block_pnl = trades.groupby(minute)["net_bps"].sum()
    if len(block_pnl) < 2 or float(block_pnl.std(ddof=1)) == 0.0:
        p_value = 1.0
        block_se = None
    else:
        statistic = float(block_pnl.mean() / (block_pnl.std(ddof=1) / math.sqrt(len(block_pnl))))
        p_value = float(stats.t.sf(statistic, df=len(block_pnl) - 1))
        block_se = float(block_pnl.std(ddof=1) / math.sqrt(len(block_pnl)))
    return {
        "trades": int(len(trades)),
        "minutes": int(len(block_pnl)),
        "gross_mean_bps": float(trades["gross_bps"].mean()),
        "net_mean_bps": float(trades["net_bps"].mean()),
        "net_total_bps": float(trades["net_bps"].sum()),
        "win_rate": float(trades["net_bps"].gt(0).mean()),
        "p_value": p_value,
        "minute_mean_bps": float(block_pnl.mean()),
        "minute_standard_error_bps": block_se,
        "max_trade_bps": float(trades["net_bps"].max()),
        "min_trade_bps": float(trades["net_bps"].min()),
    }


def holm_passes(rows: list[dict[str, Any]], alpha: float = 0.05) -> set[str]:
    ordered = sorted(rows, key=lambda item: item["validation"]["p_value"])
    passed: set[str] = set()
    total = len(ordered)
    for index, row in enumerate(ordered):
        cutoff = alpha / (total - index)
        if row["validation"]["p_value"] <= cutoff:
            passed.add(row["name"])
        else:
            break
    return passed


def run(panel_path: Path) -> dict[str, Any]:
    frame = prepare_panel(panel_path)
    train = frame[frame["sample_role"].eq("train")].copy()
    train_times = np.sort(train["timestamp_ns"].unique())
    cut = int(len(train_times) * 0.60)
    discovery_end = int(train_times[cut - 1])
    validation_start = discovery_end + 30 * NS
    discovery = train[train["timestamp_ns"].le(discovery_end)]
    validation = train[train["timestamp_ns"].ge(validation_start)]

    discovery_rows: list[dict[str, Any]] = []
    thresholds: dict[str, float] = {}
    specs = candidates()
    for candidate in specs:
        threshold = threshold_for(discovery, candidate)
        thresholds[candidate.name] = threshold
        metrics = evaluate(discovery, candidate, threshold)
        if metrics["trades"] >= 30 and metrics["net_mean_bps"] is not None:
            discovery_rows.append(
                {"name": candidate.name, "candidate": candidate, "discovery": metrics}
            )
    discovery_rows.sort(
        key=lambda item: (item["discovery"]["net_mean_bps"], item["discovery"]["trades"]),
        reverse=True,
    )
    shortlist = discovery_rows[:20]
    validation_rows: list[dict[str, Any]] = []
    for row in shortlist:
        candidate = row["candidate"]
        validation_metrics = evaluate(validation, candidate, thresholds[candidate.name])
        validation_rows.append(
            {
                **row,
                "threshold": thresholds[candidate.name],
                "validation": validation_metrics,
            }
        )
    passes = holm_passes(validation_rows)
    survivors = [
        row
        for row in validation_rows
        if row["name"] in passes
        and row["validation"]["trades"] >= 30
        and row["validation"]["net_mean_bps"] is not None
        and row["validation"]["net_mean_bps"] > 0
    ]
    survivors.sort(key=lambda item: item["validation"]["net_mean_bps"], reverse=True)

    selected: dict[str, Any] | None = None
    final_inspected = False
    if survivors:
        winner = survivors[0]
        final_frame = frame[frame["sample_role"].eq("test")]
        selected = {
            "name": winner["name"],
            "candidate": asdict(winner["candidate"]),
            "threshold": winner["threshold"],
            "discovery": winner["discovery"],
            "validation": winner["validation"],
            "final": evaluate(final_frame, winner["candidate"], winner["threshold"]),
        }
        final_inspected = True

    serializable_shortlist = []
    for row in validation_rows:
        serializable_shortlist.append(
            {
                "name": row["name"],
                "candidate": asdict(row["candidate"]),
                "threshold": row["threshold"],
                "discovery": row["discovery"],
                "validation": row["validation"],
                "holm_pass": row["name"] in passes,
            }
        )
    return {
        "protocol": {
            "candidate_count": len(specs),
            "discovery_shortlist_count": len(shortlist),
            "validation_alpha": 0.05,
            "multiple_testing": "Holm correction across the 20 discovery-shortlisted candidates",
            "cost_model": "observed entry ask/bid and exact-horizon exit bid/ask",
            "position_limit": (
                "one option per timestamp; 30-second strategies sampled non-overlapping"
            ),
            "discovery_end_ns": discovery_end,
            "validation_start_ns": validation_start,
            "final_role": "sample_role=test",
        },
        "verdict": "candidate" if selected else "cash",
        "final_inspected": final_inspected,
        "selected": selected,
        "validation_survivor_count": len(survivors),
        "shortlist": serializable_shortlist,
    }


def write_memo(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real-tape cost-aware alpha screen — 2026-08-26",
        "",
        f"Verdict: **{result['verdict'].upper()}**",
        "",
        f"Tested {result['protocol']['candidate_count']} fixed candidate variants.",
        (
            "Only the top 20 discovery candidates entered chronological validation, "
            "with Holm correction."
        ),
        "Execution uses observed bid/ask at both entry and the exact-horizon exit.",
        "",
    ]
    if result["selected"] is None:
        lines.extend(
            [
                "No strategy passed cost-aware, multiple-testing-corrected validation.",
                "The final held-out segment was deliberately not inspected.",
            ]
        )
    else:
        selected = result["selected"]
        lines.extend(
            [
                f"Selected: `{selected['name']}`",
                f"Validation net mean: {selected['validation']['net_mean_bps']:.4f} bps/trade.",
                f"Final net mean: {selected['final']['net_mean_bps']:.4f} bps/trade.",
                f"Final trades: {selected['final']['trades']}.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("panel", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run(args.panel)
    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    write_memo(result, args.output_dir / "MEMO.md")
    print(json.dumps({key: result[key] for key in ("verdict", "final_inspected", "selected")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
