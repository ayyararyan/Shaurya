#!/usr/bin/env python3
"""Falsification and execution-stress audit for rolling-252 NSGVC."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import ttest_1samp
from sklearn.linear_model import LinearRegression


FEATURES = [
    "lag1_logrv", "lag5_logrv", "lag22_logrv", "log_iv_int", "logT",
    "open5_logvar", "open5_range", "abs_open5_ret", "prev_ret",
]
PRIMARY_LOOKBACK = 252
PRIMARY_Q = 0.70
PRIMARY_RR_QUANTILE = 0.60
PRIMARY_COST = 6.0


def load_panel(path: Path) -> pd.DataFrame:
    p = pd.read_csv(path, parse_dates=["date", "expiry"]).sort_values("date")
    return p.dropna(subset=["log_fwd_int", "iv", *FEATURES]).copy()


def distribution(x: np.ndarray) -> dict[str, float | int | None]:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "total": 0.0}
    test = ttest_1samp(x, 0.0, alternative="greater") if len(x) > 1 else None
    rng = np.random.default_rng(20260902 + len(x))
    iid = rng.choice(x, size=(50_000, len(x)), replace=True).mean(axis=1)
    block = 4
    starts = rng.integers(0, len(x), size=(50_000, math.ceil(len(x) / block)))
    offsets = np.arange(block)
    indices = (starts[:, :, None] + offsets[None, None, :]) % len(x)
    moving = x[indices.reshape(50_000, -1)[:, :len(x)]].mean(axis=1)
    return {
        "n": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
        "win_rate": float((x > 0).mean()), "total": float(x.sum()),
        "p_one_sided": float(test.pvalue) if test is not None else None,
        "iid_ci_lo": float(np.quantile(iid, .025)), "iid_ci_hi": float(np.quantile(iid, .975)),
        "block4_ci_lo": float(np.quantile(moving, .025)), "block4_ci_hi": float(np.quantile(moving, .975)),
        "worst": float(x.min()), "best": float(x.max()),
    }


def simple_distribution(x: np.ndarray) -> dict[str, float | int | None]:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "total": 0.0}
    return {
        "n": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
        "win_rate": float((x > 0).mean()), "total": float(x.sum()),
    }


def model_and_cutoff(train: pd.DataFrame, q_max: float, rr_quantile: float) -> tuple[LinearRegression, float]:
    model = LinearRegression().fit(train[["log_iv_int", "logT"]], train.log_fwd_int)
    pred = np.exp(model.predict(train[["log_iv_int", "logT"]])) / train.iv_int_var
    x = train.assign(pred_ratio_wf=pred)
    first_q = x[x.pred_ratio_wf <= q_max].sort_values(["expiry", "date"]).groupby("expiry", as_index=False).first()
    if len(first_q) < 8:
        raise ValueError("insufficient q-gated calibration expiries")
    return model, float(first_q.rr_400.quantile(rr_quantile))


def walk_signals(
    panel: pd.DataFrame,
    lookback: int | None,
    q_max: float,
    rr_quantile: float,
    gate_mode: str = "both",
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    expiries = sorted(pd.Timestamp(x) for x in panel.expiry.unique() if pd.Timestamp(x) >= pd.Timestamp("2024-01-01"))
    for expiry in expiries:
        score = panel[panel.expiry == expiry].copy()
        if score.empty:
            continue
        first_date = score.date.min()
        train = panel[(panel.date < first_date) & (panel.expiry < first_date)]
        if lookback is not None:
            train = train.tail(lookback)
        if len(train) < 150:
            continue
        try:
            model, cutoff = model_and_cutoff(train, q_max, rr_quantile)
        except ValueError:
            continue
        score["pred_ratio_wf"] = np.exp(model.predict(score[["log_iv_int", "logT"]])) / score.iv_int_var
        q_pass = score.pred_ratio_wf <= q_max
        rr_pass = score.rr_400 <= cutoff
        mask = {"none": np.ones(len(score), dtype=bool), "q_only": q_pass, "rr_only": rr_pass, "both": q_pass & rr_pass}[gate_mode]
        chosen = score[mask].sort_values("date").head(1).copy()
        if chosen.empty:
            continue
        q33, q67 = train.iv.quantile([1 / 3, 2 / 3])
        chosen["iv_regime"] = "low" if chosen.iv.iloc[0] <= q33 else ("high" if chosen.iv.iloc[0] > q67 else "middle")
        chosen["horizon_sessions_round"] = int(round(float(chosen.h_trading_days.iloc[0])))
        chosen["rr_cutoff_wf"] = cutoff
        chosen["train_n"] = len(train)
        chosen["gate_mode"] = gate_mode
        rows.append(chosen)
    return pd.concat(rows, ignore_index=True).sort_values("date") if rows else pd.DataFrame()


def build_execution_ledgers(panel: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    snapshots = snapshots.copy()
    snapshots["date"] = pd.to_datetime(snapshots.date)
    variants = [("0920_open", "09:20", "open"), ("0920_close", "09:20", "close"), ("0921_open", "09:21", "open")]
    rows: list[dict[str, object]] = []
    for name, clock, field in variants:
        snap = snapshots[snapshots.time == clock]
        pivot = snap.pivot_table(index="date", columns=["side", "offset"], values=field, aggfunc="last")
        for r in panel.itertuples():
            if r.date not in pivot.index:
                continue
            prices = pivot.loc[r.date]
            for width in [400, 500]:
                offset = width // 50
                needed = [("CALL", 0), ("PUT", 0), ("CALL", offset), ("PUT", -offset)]
                if not all(key in prices.index and np.isfinite(prices[key]) for key in needed):
                    continue
                credit = float(prices[("CALL", 0)] + prices[("PUT", 0)] - prices[("CALL", offset)] - prices[("PUT", -offset)])
                terminal = float(r.expiry_spot)
                strike = float(r.K)
                payoff = min(abs(terminal - strike), width)
                rows.append({
                    "date": r.date, "expiry": r.expiry, "year": int(r.year), "execution": name,
                    "width": width, "credit": credit, "payoff": payoff, "pnl": credit - payoff,
                    "maxloss": width - credit,
                })
    return pd.DataFrame(rows)


def attach(signals: pd.DataFrame, ledger: pd.DataFrame, execution: str, width: int = 500) -> pd.DataFrame:
    trade = ledger[(ledger.execution == execution) & (ledger.width == width)]
    return signals.merge(trade, on=["date", "expiry", "year"], how="left", suffixes=("", "_trade"))


def grouped_breakdown(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(column):
        rows.append({column: key, **distribution((group.pnl - PRIMARY_COST).to_numpy(float))})
    return pd.DataFrame(rows)


def capital_path(signals: pd.DataFrame, ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float | int]]:
    equity = 100_000.0
    peak = equity
    max_drawdown = 0.0
    rows: list[dict[str, object]] = []
    available = ledger[ledger.execution == "0920_open"].set_index(["date", "expiry", "width"])
    for signal in signals.sort_values("date").itertuples():
        cap = 0.20 * equity
        selected = None
        for width in [500, 400]:
            key = (signal.date, signal.expiry, width)
            if key not in available.index:
                continue
            trade = available.loc[key]
            if float(trade.maxloss) * 65 <= cap:
                selected = (width, trade)
                break
        before = equity
        if selected is None:
            rows.append({"date": signal.date, "expiry": signal.expiry, "action": "skip_risk", "equity_before": before, "equity_after": equity})
            continue
        width, trade = selected
        net_rupees = (float(trade.pnl) - PRIMARY_COST) * 65
        equity += net_rupees
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)
        rows.append({
            "date": signal.date, "expiry": signal.expiry, "action": "trade", "width": width,
            "risk_rupees": float(trade.maxloss) * 65, "net_rupees": net_rupees,
            "equity_before": before, "equity_after": equity,
        })
    path = pd.DataFrame(rows)
    traded = path[path.action == "trade"]
    width_counts = {str(int(k)): int(v) for k, v in traded.width.value_counts().items()} if len(traded) else {}
    return path, {
        "starting_equity": 100_000.0, "ending_equity": equity,
        "net_profit": equity - 100_000.0, "trades": int((path.action == "trade").sum()),
        "skipped_for_risk": int((path.action == "skip_risk").sum()), "width_counts": width_counts,
        "max_drawdown_fraction": max_drawdown,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--reference-trades", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    panel = load_panel(args.panel)
    snapshots = pd.read_csv(args.snapshots, dtype={"time": str})
    reference = pd.read_csv(args.reference_trades, parse_dates=["date", "expiry"])
    ledger = build_execution_ledgers(panel, snapshots)

    # Verify that the independently reconstructed 09:20-open economics match the audited ledger.
    check = ledger[ledger.execution == "0920_open"].merge(reference, on=["date", "expiry", "year", "width"], suffixes=("_new", "_ref"))
    reconstruction_max_diff = float(np.max(np.abs(check.pnl_new - check.pnl_ref)))
    if reconstruction_max_diff > 1e-10:
        raise AssertionError(f"09:20-open reconstruction differs: {reconstruction_max_diff}")

    primary_signals = walk_signals(panel, PRIMARY_LOOKBACK, PRIMARY_Q, PRIMARY_RR_QUANTILE, "both")
    primary = attach(primary_signals, ledger, "0920_open")
    primary_net = (primary.pnl - PRIMARY_COST).to_numpy(float)

    execution_rows = []
    for execution in ["0920_open", "0920_close", "0921_open"]:
        joined = attach(primary_signals, ledger, execution)
        for cost in [6.0, 10.0, 15.0, 20.0]:
            execution_rows.append({"execution": execution, "cost_points": cost, **distribution((joined.pnl - cost).to_numpy(float))})
    execution_stress = pd.DataFrame(execution_rows)

    concentration_rows = []
    concentration_base = primary[["date"]].assign(net_points=primary_net)
    for remove in [0, 1, 3, 5]:
        removed = concentration_base.nlargest(remove, "net_points").index if remove else []
        retained = concentration_base.drop(index=removed).sort_values("date").net_points.to_numpy(float)
        concentration_rows.append({"removed_best_trades": remove, **distribution(retained)})
    concentration = pd.DataFrame(concentration_rows)

    gate_ledgers = []
    gate_rows = []
    for mode in ["none", "q_only", "rr_only", "both"]:
        signals = walk_signals(panel, PRIMARY_LOOKBACK, PRIMARY_Q, PRIMARY_RR_QUANTILE, mode)
        joined = attach(signals, ledger, "0920_open")
        gate_ledgers.append(joined)
        gate_rows.append({"gate_mode": mode, **distribution((joined.pnl - PRIMARY_COST).to_numpy(float))})
    gate_attribution = pd.DataFrame(gate_rows)

    grid_rows = []
    for lookback in [200, 252, 300, 378, 504]:
        for q_max in [.65, .675, .70, .725, .75]:
            for rr_quantile in [.50, .55, .60, .65, .70]:
                signals = walk_signals(panel, lookback, q_max, rr_quantile, "both")
                joined = attach(signals, ledger, "0920_open")
                grid_rows.append({
                    "lookback": lookback, "q_max": q_max, "rr_quantile": rr_quantile,
                    **simple_distribution((joined.pnl - PRIMARY_COST).to_numpy(float)),
                })
    neighborhood = pd.DataFrame(grid_rows)

    by_year = grouped_breakdown(primary, "year")
    by_iv = grouped_breakdown(primary, "iv_regime")
    by_horizon = grouped_breakdown(primary, "horizon_sessions_round")
    cap_path, cap_summary = capital_path(primary_signals, ledger)
    primary_stats = distribution(primary_net)
    close10 = execution_stress[(execution_stress.execution == "0920_close") & (execution_stress.cost_points == 10)].iloc[0]
    next10 = execution_stress[(execution_stress.execution == "0921_open") & (execution_stress.cost_points == 10)].iloc[0]
    remove5 = concentration[concentration.removed_best_trades == 5].iloc[0]
    eligible_grid = neighborhood[neighborhood.n >= 20]
    positive_grid_share = float((eligible_grid["mean"] > 0).mean())
    criteria = {
        "09:20_close_positive_at_cost10": bool(close10["mean"] > 0),
        "09:21_open_positive_at_cost10": bool(next10["mean"] > 0),
        "positive_after_removing_best5": bool(remove5["mean"] > 0),
        "at_least_60pct_neighborhood_positive": bool(positive_grid_share >= .60),
        "block_bootstrap_lower_bound_positive": bool(primary_stats["block4_ci_lo"] > 0),
        "positive_mean_each_year": bool((by_year["mean"] > 0).all()),
        "capital_path_profitable": bool(cap_summary["ending_equity"] > cap_summary["starting_equity"]),
    }
    summary = {
        "definitions": {"lookback": 252, "q_max": .70, "rr_quantile": .60, "width": 500, "base_cost": 6},
        "execution_reconstruction_max_abs_pnl_diff": reconstruction_max_diff,
        "primary": primary_stats,
        "parameter_neighborhood": {
            "variants": int(len(neighborhood)), "eligible_variants_n_ge_20": int(len(eligible_grid)),
            "share_positive": positive_grid_share, "median_mean_points": float(eligible_grid["mean"].median()),
            "worst_mean_points": float(eligible_grid["mean"].min()), "best_mean_points": float(eligible_grid["mean"].max()),
            "primary_mean_percentile": float((eligible_grid["mean"] <= primary_stats["mean"]).mean()),
        },
        "capital_path": cap_summary,
        "criteria": criteria,
        "passed_all_criteria": bool(all(criteria.values())),
    }

    ledger.to_csv(args.out / "execution_variant_ledger.csv", index=False)
    primary.to_csv(args.out / "primary_signal_ledger.csv", index=False)
    execution_stress.to_csv(args.out / "execution_and_cost_stress.csv", index=False)
    concentration.to_csv(args.out / "top_trade_concentration.csv", index=False)
    gate_attribution.to_csv(args.out / "gate_attribution.csv", index=False)
    pd.concat(gate_ledgers, ignore_index=True).to_csv(args.out / "gate_attribution_ledger.csv", index=False)
    neighborhood.to_csv(args.out / "parameter_neighborhood.csv", index=False)
    by_year.to_csv(args.out / "regime_by_year.csv", index=False)
    by_iv.to_csv(args.out / "regime_by_iv.csv", index=False)
    by_horizon.to_csv(args.out / "regime_by_horizon.csv", index=False)
    cap_path.to_csv(args.out / "capital_path.csv", index=False)
    (args.out / "falsification_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
