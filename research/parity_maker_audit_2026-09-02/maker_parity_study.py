#!/usr/bin/env python3
"""Queue-aware passive-entry study for the frozen far-parity futures lead."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


NS = 1_000_000_000
STEP_NS = 5 * NS
HORIZON = 6
THRESHOLD = 5.887791725829495e-05
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0, 1_000.0)
BASELINE = (
    ("futures_return_5s", "level"),
    ("futures_log_mid", "delta_30s"),
    ("futures_log_mid", "delta_60s"),
    ("futures_relative_spread", "level"),
    ("futures_microprice_dislocation", "level"),
    ("futures_depth_imbalance", "level"),
    ("futures_realized_volatility_30s", "level"),
)
LAGS = {"level": 0, "delta_30s": 6, "delta_60s": 12}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Session:
    timestamps: np.ndarray
    values: np.ndarray
    columns: tuple[str, ...]
    date: str


@dataclass(frozen=True)
class FutureTape:
    timestamps: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    bid_quantity: np.ndarray
    ask_quantity: np.ndarray
    last_price: np.ndarray
    cumulative_volume: np.ndarray


def load_session(path: Path) -> Session:
    loaded = np.load(path, allow_pickle=False)
    return Session(
        timestamps=loaded["timestamps"].astype(np.int64),
        values=loaded["values"].astype(np.float64),
        columns=tuple(str(x) for x in loaded["columns"].tolist()),
        date=str(loaded["trading_date"].tolist()[0]),
    )


def load_tape(path: Path) -> FutureTape:
    x = np.load(path, allow_pickle=False)
    return FutureTape(
        timestamps=x["timestamps"].astype(np.int64), bid=x["bid"], ask=x["ask"],
        bid_quantity=x["bid_quantity"], ask_quantity=x["ask_quantity"],
        last_price=x["last_price"], cumulative_volume=x["cumulative_volume"],
    )


def valid_ends(session: Session) -> np.ndarray:
    valid = []
    for end in range(11, len(session.timestamps) - HORIZON):
        window = session.timestamps[end - 11:end + HORIZON + 1]
        if np.all(np.diff(window) == STEP_NS):
            valid.append(end)
    return np.asarray(valid, dtype=np.int64)


def feature(session: Session, ends: np.ndarray, name: str, transform: str) -> np.ndarray:
    column = session.columns.index(name)
    current = session.values[ends, column]
    lag = LAGS[transform]
    return current if lag == 0 else current - session.values[ends - lag, column]


def raw_features(session: Session, ends: np.ndarray) -> np.ndarray:
    columns = [feature(session, ends, name, transform) for name, transform in BASELINE]
    columns.append(feature(session, ends, "surface__parity_residual_rms_to_forward__far", "delta_60s"))
    day_ns = 86_400 * NS
    phase = 2.0 * np.pi * (session.timestamps[ends] % day_ns) / day_ns
    columns.extend((np.sin(phase), np.cos(phase)))
    return np.column_stack(columns)


def target(session: Session, ends: np.ndarray) -> np.ndarray:
    column = session.columns.index("futures_log_mid")
    return session.values[ends + HORIZON, column] - session.values[ends, column]


def prepare(train: np.ndarray, others: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray]]:
    center = np.nanmedian(train, axis=0)
    center = np.where(np.isfinite(center), center, 0.0)
    filled = np.where(np.isfinite(train), train, center)
    scale = np.nanstd(filled, axis=0, ddof=1)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
    return (
        np.clip((filled - center) / scale, -10, 10),
        [np.clip((np.where(np.isfinite(x), x, center) - center) / scale, -10, 10) for x in others],
    )


def predictions(sessions: list[Session]) -> tuple[list[np.ndarray], list[np.ndarray], float]:
    ends = [valid_ends(x) for x in sessions]
    ys = [target(x, e) for x, e in zip(sessions, ends, strict=True)]
    xs = [raw_features(x, e) for x, e in zip(sessions, ends, strict=True)]
    masks = [np.isfinite(y) for y in ys]
    xs = [x[m] for x, m in zip(xs, masks, strict=True)]
    ys = [y[m] for y, m in zip(ys, masks, strict=True)]
    times = [s.timestamps[e][m] for s, e, m in zip(sessions, ends, masks, strict=True)]
    train, other = prepare(xs[0], xs[1:])
    alpha = min(ALPHAS, key=lambda a: np.mean(np.abs(ys[1] - Ridge(alpha=a).fit(train, ys[0]).predict(other[0]))))
    model = Ridge(alpha=alpha).fit(train, ys[0])
    return [model.predict(other[0]), model.predict(other[1])], [times[1], times[2]], alpha


def signal_indices(prediction: np.ndarray) -> np.ndarray:
    selected = []
    index = 0
    while index < len(prediction):
        if abs(prediction[index]) >= THRESHOLD:
            selected.append(index)
            index += HORIZON
        else:
            index += 1
    return np.asarray(selected, dtype=np.int64)


def quote_at(tape: FutureTape, when: int) -> int | None:
    index = int(np.searchsorted(tape.timestamps, when, side="right") - 1)
    if index < 0 or when - int(tape.timestamps[index]) > 2 * NS:
        return None
    return index


def midpoint_at(tape: FutureTape, when: int) -> float | None:
    index = quote_at(tape, when)
    return None if index is None else float((tape.bid[index] + tape.ask[index]) / 2)


def simulate_one(
    tape: FutureTape,
    signal_ns: int,
    direction: int,
    latency_ms: int,
    ttl_seconds: int,
    queue_fraction: float,
) -> dict[str, object]:
    arrival = signal_ns + latency_ms * 1_000_000
    quote_index = quote_at(tape, arrival)
    if quote_index is None:
        return {"status": "stale_or_missing_entry_quote"}
    order_price = float(tape.bid[quote_index] if direction > 0 else tape.ask[quote_index])
    shown = float(tape.bid_quantity[quote_index] if direction > 0 else tape.ask_quantity[quote_index])
    queue_remaining = queue_fraction * shown + 65.0
    deadline = min(signal_ns + ttl_seconds * NS, signal_ns + 30 * NS)
    end = int(np.searchsorted(tape.timestamps, deadline, side="right"))
    fill_index = None
    previous_volume = float(tape.cumulative_volume[quote_index])
    for index in range(quote_index + 1, end):
        through = tape.ask[index] <= order_price + 1e-6 if direction > 0 else tape.bid[index] >= order_price - 1e-6
        current_volume = float(tape.cumulative_volume[index])
        volume_delta = max(0.0, current_volume - previous_volume) if np.isfinite(current_volume) and np.isfinite(previous_volume) else 0.0
        previous_volume = current_volume if np.isfinite(current_volume) else previous_volume
        traded_here = (
            np.isfinite(tape.last_price[index])
            and ((tape.last_price[index] <= order_price + .026) if direction > 0 else (tape.last_price[index] >= order_price - .026))
        )
        if through:
            fill_index = index
            break
        if traded_here and volume_delta > 0:
            if queue_fraction == 0.0:
                fill_index = index
                break
            queue_remaining -= volume_delta
            if queue_remaining <= 0:
                fill_index = index
                break
    if fill_index is None:
        return {"status": "unfilled", "entry_quote_age_ms": (arrival - int(tape.timestamps[quote_index])) / 1e6, "queue_ahead_units": queue_fraction * shown}
    exit_ns = signal_ns + 30 * NS
    exit_index = quote_at(tape, exit_ns)
    if exit_index is None:
        return {"status": "missing_exit_quote"}
    exit_price = float(tape.bid[exit_index] if direction > 0 else tape.ask[exit_index])
    gross_bps = direction * math.log(exit_price / order_price) * 10_000.0
    fill_mid = float((tape.bid[fill_index] + tape.ask[fill_index]) / 2)
    result: dict[str, object] = {
        "status": "filled", "entry_price": order_price, "exit_price": exit_price,
        "gross_bps": gross_bps, "fill_delay_ms": (int(tape.timestamps[fill_index]) - signal_ns) / 1e6,
        "entry_quote_age_ms": (arrival - int(tape.timestamps[quote_index])) / 1e6,
        "queue_ahead_units": queue_fraction * shown,
    }
    for seconds in (1, 5):
        future_mid = midpoint_at(tape, int(tape.timestamps[fill_index]) + seconds * NS)
        result[f"adverse_mid_move_{seconds}s_bps"] = (
            direction * math.log(future_mid / fill_mid) * 10_000.0 if future_mid is not None else np.nan
        )
        result[f"mark_from_fill_{seconds}s_bps"] = (
            direction * math.log(future_mid / order_price) * 10_000.0 if future_mid is not None else np.nan
        )
    return result


def summaries(trades: pd.DataFrame, signal_counts: dict[str, int]) -> pd.DataFrame:
    rows = []
    grouping = ["session", "latency_ms", "ttl_seconds", "queue_model", "fee_bps"]
    for keys, group in trades.groupby(grouping):
        session, latency, ttl, queue_model, fee = keys
        filled = group[group.status == "filled"]
        net = filled.gross_bps - fee
        count = signal_counts[str(session)]
        rows.append({
            "session": session, "latency_ms": latency, "ttl_seconds": ttl,
            "queue_model": queue_model, "fee_bps": fee, "signals": count,
            "fills": len(filled), "fill_rate": len(filled) / count if count else np.nan,
            "mean_net_bps_per_fill": net.mean() if len(net) else np.nan,
            "mean_net_bps_per_signal": net.sum() / count if count else np.nan,
            "total_net_bps": net.sum(), "win_rate_fills": (net > 0).mean() if len(net) else np.nan,
            "mean_adverse_1s_bps": filled.adverse_mid_move_1s_bps.mean() if len(filled) else np.nan,
            "mean_adverse_5s_bps": filled.adverse_mid_move_5s_bps.mean() if len(filled) else np.nan,
        })
    return pd.DataFrame(rows)


def pooled_summaries(trades: pd.DataFrame, total_signals: int) -> pd.DataFrame:
    rows = []
    grouping = ["latency_ms", "ttl_seconds", "queue_model", "fee_bps"]
    for keys, group in trades.groupby(grouping):
        latency, ttl, queue_model, fee = keys
        filled = group[group.status == "filled"]
        net = filled.gross_bps - fee
        rows.append({
            "latency_ms": latency, "ttl_seconds": ttl, "queue_model": queue_model,
            "fee_bps": fee, "signals": total_signals, "fills": len(filled),
            "fill_rate": len(filled) / total_signals, "mean_net_bps_per_fill": net.mean(),
            "mean_net_bps_per_signal": net.sum() / total_signals,
            "total_net_bps": net.sum(), "win_rate_fills": (net > 0).mean(),
            "break_even_fee_bps_per_fill": filled.gross_bps.mean(),
        })
    return pd.DataFrame(rows)


def opportunity_bootstrap(group: pd.DataFrame) -> dict[str, float]:
    values = np.where(group.status == "filled", group.gross_bps - group.fee_bps, 0.0)
    rng = np.random.default_rng(20260902)
    means = rng.choice(values, size=(50_000, len(values)), replace=True).mean(axis=1)
    return {
        "mean_bps_per_signal": float(values.mean()),
        "ci_lo": float(np.quantile(means, .025)),
        "ci_hi": float(np.quantile(means, .975)),
        "probability_mean_positive": float((means > 0).mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", nargs=3, type=Path, required=True)
    parser.add_argument("--future-tapes", nargs=2, type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sessions = [load_session(x) for x in args.sessions]
    tapes = [load_tape(x) for x in args.future_tapes]
    prediction_sets, timestamp_sets, alpha = predictions(sessions)
    if not math.isclose(float(np.quantile(np.abs(prediction_sets[0]), .95)), THRESHOLD, rel_tol=0, abs_tol=1e-15):
        raise AssertionError("frozen validation threshold was not reproduced")

    raw_rows = []
    signal_counts: dict[str, int] = {}
    queue_models = {"touch": 0.0, "half_displayed": 0.5, "full_displayed": 1.0}
    for session, tape, prediction, timestamps in zip(sessions[1:], tapes, prediction_sets, timestamp_sets, strict=True):
        chosen = signal_indices(prediction)
        signal_counts[session.date] = len(chosen)
        for latency in (0, 250, 1_000):
            for ttl in (1, 5):
                for queue_name, queue_fraction in queue_models.items():
                    for index in chosen:
                        base = {
                            "session": session.date, "signal_ns": int(timestamps[index]),
                            "prediction": float(prediction[index]), "direction": int(np.sign(prediction[index])),
                            "latency_ms": latency, "ttl_seconds": ttl, "queue_model": queue_name,
                        }
                        outcome = simulate_one(tape, int(timestamps[index]), int(np.sign(prediction[index])), latency, ttl, queue_fraction)
                        for fee in (0.0, 0.2, 0.5, 1.0):
                            raw_rows.append({**base, **outcome, "fee_bps": fee})
    trades = pd.DataFrame(raw_rows)
    summary = summaries(trades, signal_counts)
    pooled = pooled_summaries(trades, sum(signal_counts.values()))
    headline = summary[(summary.latency_ms == 250) & (summary.ttl_seconds == 5) & (summary.queue_model == "full_displayed") & (summary.fee_bps == .5)]
    touch = summary[(summary.latency_ms == 250) & (summary.ttl_seconds == 5) & (summary.queue_model == "touch") & (summary.fee_bps == .5)]
    pooled_headline = pooled[(pooled.latency_ms == 250) & (pooled.ttl_seconds == 5) & (pooled.queue_model == "full_displayed") & (pooled.fee_bps == .5)]
    pooled_touch = pooled[(pooled.latency_ms == 250) & (pooled.ttl_seconds == 5) & (pooled.queue_model == "touch") & (pooled.fee_bps == .5)]
    headline_events = trades[(trades.latency_ms == 250) & (trades.ttl_seconds == 5) & (trades.queue_model == "full_displayed") & (trades.fee_bps == .5)]
    touch_events = trades[(trades.latency_ms == 250) & (trades.ttl_seconds == 5) & (trades.queue_model == "touch") & (trades.fee_bps == .5)]
    fee_half = summary[summary.fee_bps == .5]
    config_index = ["latency_ms", "ttl_seconds", "queue_model"]
    config_outcomes = fee_half.pivot_table(index=config_index, columns="session", values="total_net_bps")
    result = {
        "status": "passive_maker_research_complete",
        "inputs": {
            "surface_sessions": [{"path": str(x), "sha256": sha256(x)} for x in args.sessions],
            "reduced_future_tapes": [{"path": str(x), "sha256": sha256(x)} for x in args.future_tapes],
        },
        "model": "frozen baseline_plus_far_parity_delta_60s",
        "ridge_alpha_selected_on_validation": alpha,
        "prediction_threshold": THRESHOLD,
        "holding_seconds_from_signal": 30,
        "order_size_units": 65,
        "signal_counts": signal_counts,
        "headline_full_queue_250ms_ttl5_fee0.5bps": headline.to_dict(orient="records"),
        "optimistic_touch_250ms_ttl5_fee0.5bps": touch.to_dict(orient="records"),
        "pooled_headline": pooled_headline.to_dict(orient="records")[0],
        "pooled_optimistic_touch": pooled_touch.to_dict(orient="records")[0],
        "headline_opportunity_bootstrap": opportunity_bootstrap(headline_events),
        "touch_opportunity_bootstrap": opportunity_bootstrap(touch_events),
        "fee0.5_grid_robustness": {
            "configurations": int(len(config_outcomes)),
            "positive_on_both_sessions": int((config_outcomes > 0).all(axis=1).sum()),
            "positive_when_pooled": int((pooled[pooled.fee_bps == .5].total_net_bps > 0).sum()),
        },
        "limitations": [
            "Cumulative-volume changes are assigned to the recorded last price; aggressor-side data are not native.",
            "Displayed queue depletion counts executions only and ignores cancellations, making the full-queue model conservative.",
            "A fill caused by the market moving through the limit is assumed at the limit price.",
            "Exit is a marketable order at the recorded best quote 30 seconds after the original signal.",
            "Fees are a sensitivity ladder, not a reconstructed broker bill.",
        ],
    }
    trades.to_csv(args.out / "maker_trade_events.csv", index=False)
    summary.to_csv(args.out / "maker_summary_grid.csv", index=False)
    pooled.to_csv(args.out / "maker_pooled_grid.csv", index=False)
    (args.out / "maker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
