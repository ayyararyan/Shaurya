"""Conservative passive-futures test of the frozen option-implied lead.

An order is posted one second after the signal at the then-current futures
bid (predicted rise) or ask (predicted fall).  A fill is credited only if the
opposite quote strictly trades through the limit while the order is alive.
The exit crosses the spread after a fixed holding period.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

try:
    from experiments.subminute_option_futures_lead import build_session
except ModuleNotFoundError:  # Direct execution places experiments/ on sys.path.
    from subminute_option_futures_lead import build_session

SOURCE_SECONDS = 10
PLACEMENT_DELAY_SECONDS = 1
TTL_SECONDS = (1, 2, 3, 5)
HOLD_SECONDS = (5, 10, 30)
COSTS_BPS = (0.0, 0.25, 0.5, 1.0)
MIN_DISCOVERY_FILLS = 100


@dataclass(frozen=True)
class Candidate:
    ttl_seconds: int
    hold_seconds: int

    @property
    def name(self) -> str:
        return f"strict_quote_through_ttl{self.ttl_seconds}_hold{self.hold_seconds}"


def candidates() -> list[Candidate]:
    return [Candidate(ttl, hold) for ttl in TTL_SECONDS for hold in HOLD_SECONDS]


def _signal(frame: pd.DataFrame, beta: float) -> pd.Series:
    option_return = np.log(frame["implied_forward"]).diff(SOURCE_SECONDS)
    future_return = np.log(frame["future_mid"]).diff(SOURCE_SECONDS)
    return option_return - beta * future_return


def simulate_session(
    frame: pd.DataFrame,
    candidate: Candidate,
    threshold: float,
    beta: float,
) -> tuple[pd.DataFrame, int]:
    signal = _signal(frame, beta)
    fills: list[dict[str, Any]] = []
    orders = 0
    index = SOURCE_SECONDS
    last_index = len(frame) - 1
    while index + PLACEMENT_DELAY_SECONDS < last_index:
        value = float(signal.iloc[index])
        if not np.isfinite(value) or value == 0.0 or abs(value) < threshold:
            index += 1
            continue
        placement = index + PLACEMENT_DELAY_SECONDS
        side = int(np.sign(value))
        limit = float(
            frame["future_bid"].iloc[placement]
            if side > 0
            else frame["future_ask"].iloc[placement]
        )
        if not np.isfinite(limit) or limit <= 0.0:
            index += 1
            continue
        orders += 1
        final_fill_index = min(placement + candidate.ttl_seconds, last_index)
        fill_index: int | None = None
        for probe in range(placement + 1, final_fill_index + 1):
            crossed = (
                float(frame["future_ask"].iloc[probe]) < limit
                if side > 0
                else float(frame["future_bid"].iloc[probe]) > limit
            )
            if crossed:
                fill_index = probe
                break
        if fill_index is None:
            index = final_fill_index + 1
            continue
        exit_index = fill_index + candidate.hold_seconds
        if exit_index > last_index:
            break
        exit_price = float(
            frame["future_bid"].iloc[exit_index]
            if side > 0
            else frame["future_ask"].iloc[exit_index]
        )
        if np.isfinite(exit_price) and exit_price > 0.0:
            pnl = (exit_price - limit) * side / limit * 10_000.0
            fills.append(
                {
                    "side": side,
                    "signal": value,
                    "limit": limit,
                    "placement_index": placement,
                    "fill_index": fill_index,
                    "fill_wait_seconds": fill_index - placement,
                    "exit_index": exit_index,
                    "gross_pnl_bps": pnl,
                }
            )
        index = exit_index + 1
    return pd.DataFrame(fills), orders


def summarize(fills: pd.DataFrame, orders: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "orders": orders,
        "fills": int(len(fills)),
        "fill_rate": float(len(fills) / orders) if orders else 0.0,
    }
    if fills.empty:
        return result
    gross = fills["gross_pnl_bps"].to_numpy(dtype=np.float64)
    result.update(
        {
            "gross_mean_bps_per_fill": float(gross.mean()),
            "gross_total_bps": float(gross.sum()),
            "gross_bps_per_order": float(gross.sum() / orders),
            "gross_win_rate": float(np.mean(gross > 0.0)),
            "median_fill_wait_seconds": float(fills["fill_wait_seconds"].median()),
        }
    )
    for cost in COSTS_BPS:
        net = gross - cost
        result[f"net_mean_bps_per_fill_at_{cost:g}"] = float(net.mean())
        result[f"net_total_bps_at_{cost:g}"] = float(net.sum())
        result[f"net_bps_per_order_at_{cost:g}"] = float(net.sum() / orders)
    return result


def evaluate_month(
    frames: list[pd.DataFrame], candidate: Candidate, threshold: float, beta: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    all_fills: list[pd.DataFrame] = []
    total_orders = 0
    by_day: list[dict[str, Any]] = []
    for frame in frames:
        fills, orders = simulate_session(frame, candidate, threshold, beta)
        all_fills.append(fills)
        total_orders += orders
        by_day.append(
            {
                "session": str(frame.index[0].date()),
                **summarize(fills, orders),
            }
        )
    combined = pd.concat(all_fills, ignore_index=True) if all_fills else pd.DataFrame()
    aggregate = summarize(combined, total_orders)
    daily_net = np.asarray(
        [float(row.get("net_total_bps_at_0.5", 0.0)) for row in by_day], dtype=np.float64
    )
    aggregate["positive_days_at_0.5bp"] = int(np.sum(daily_net > 0.0))
    aggregate["days"] = len(by_day)
    aggregate["daily_wilcoxon_p_at_0.5bp"] = (
        float(stats.wilcoxon(daily_net, alternative="greater").pvalue)
        if len(daily_net) >= 5 and np.any(daily_net != 0.0)
        else 1.0
    )
    return aggregate, by_day


def load_month(root: Path) -> tuple[list[pd.DataFrame], list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    inventory: list[dict[str, Any]] = []
    for day in sorted(root.glob("2026_??_??")):
        frame, metadata = build_session(day)
        frames.append(frame)
        inventory.append(metadata)
        print(json.dumps({"session": metadata["session"], "status": "loaded"}), flush=True)
    return frames, inventory


def run(january_root: Path, february_root: Path, frozen_path: Path, output: Path) -> dict[str, Any]:
    frozen = json.loads(frozen_path.read_text())
    if frozen["selected"]["signal"] != "option_residual":
        raise ValueError("frozen signal is not option_residual")
    threshold = float(frozen["selected"]["threshold"])
    beta = float(frozen["residual_beta_fit_january"])
    january, january_inventory = load_month(january_root)
    february, february_inventory = load_month(february_root)
    discovery_rows: list[dict[str, Any]] = []
    for candidate in candidates():
        metrics, by_day = evaluate_month(january, candidate, threshold, beta)
        discovery_rows.append(
            {
                "candidate": asdict(candidate),
                "name": candidate.name,
                "metrics": metrics,
                "by_day": by_day,
            }
        )
    eligible = [row for row in discovery_rows if row["metrics"]["fills"] >= MIN_DISCOVERY_FILLS]
    selected = max(eligible, key=lambda row: row["metrics"]["net_bps_per_order_at_0.5"])
    selected_candidate = Candidate(**selected["candidate"])
    evaluation, evaluation_by_day = evaluate_month(
        february, selected_candidate, threshold, beta
    )
    result = {
        "protocol": {
            "frozen_signal": str(frozen_path),
            "signal": "option_residual",
            "source_seconds": SOURCE_SECONDS,
            "placement_delay_seconds": PLACEMENT_DELAY_SECONDS,
            "fill_rule": "strict opposite-quote through limit",
            "exit_rule": "cross spread after fixed hold",
            "selection": "maximize January net bps per order after 0.5bp per fill",
            "evaluation": "February unchanged",
            "costs_bps_beyond_observed_quotes": list(COSTS_BPS),
            "candidate_count": len(discovery_rows),
        },
        "threshold": threshold,
        "residual_beta": beta,
        "selected": {key: selected[key] for key in ("candidate", "name", "metrics")},
        "february": evaluation,
        "february_by_day": evaluation_by_day,
        "discovery_candidates": discovery_rows,
        "inventory": {"january": january_inventory, "february": february_inventory},
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    pd.DataFrame(evaluation_by_day).to_csv(output / "february_by_day.csv", index=False)
    print(json.dumps({"selected": result["selected"], "february": result["february"]}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("january_root", type=Path)
    parser.add_argument("february_root", type=Path)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.january_root, args.february_root, args.frozen, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
