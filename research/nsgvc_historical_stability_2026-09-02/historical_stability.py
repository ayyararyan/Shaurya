#!/usr/bin/env python3
"""Leakage-safe historical stability tests for frozen NSGVC v1.0."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import ttest_1samp
from sklearn.linear_model import LinearRegression


COMPLETE_CASE_FEATURES = [
    "lag1_logrv",
    "lag5_logrv",
    "lag22_logrv",
    "log_iv_int",
    "logT",
    "open5_logvar",
    "open5_range",
    "abs_open5_ret",
    "prev_ret",
]
Q_MAX = 0.70
RR_QUANTILE = 0.60
COST = 6.0
WIDTH = 500


def load_panel(path: Path) -> pd.DataFrame:
    panel = pd.read_csv(path, parse_dates=["date", "expiry"]).sort_values("date")
    return panel.dropna(subset=["log_fwd_int", "iv", *COMPLETE_CASE_FEATURES]).copy()


def fit_predict(train: pd.DataFrame, score: pd.DataFrame) -> tuple[np.ndarray, LinearRegression]:
    model = LinearRegression().fit(train[["log_iv_int", "logT"]], train.log_fwd_int)
    pred_int = np.exp(model.predict(score[["log_iv_int", "logT"]]))
    return pred_int / score.iv_int_var.to_numpy(float), model


def calibrate(train: pd.DataFrame) -> tuple[LinearRegression, float]:
    pred_ratio, model = fit_predict(train, train)
    calibration = train.assign(pred_ratio_wf=pred_ratio)
    first_q = (
        calibration[calibration.pred_ratio_wf <= Q_MAX]
        .sort_values(["expiry", "date"])
        .groupby("expiry", as_index=False)
        .first()
    )
    if len(first_q) < 8:
        raise ValueError("insufficient q-gated expiries for RR calibration")
    return model, float(first_q.rr_400.quantile(RR_QUANTILE))


def score_with_model(score: pd.DataFrame, model: LinearRegression, rr_cutoff: float) -> pd.DataFrame:
    x = score.copy()
    pred_int = np.exp(model.predict(x[["log_iv_int", "logT"]]))
    x["pred_ratio_wf"] = pred_int / x.iv_int_var
    x["rr_cutoff"] = rr_cutoff
    return x[(x.pred_ratio_wf <= Q_MAX) & (x.rr_400 <= rr_cutoff)]


def first_per_expiry(score: pd.DataFrame, model: LinearRegression, rr_cutoff: float) -> pd.DataFrame:
    return (
        score_with_model(score, model, rr_cutoff)
        .sort_values(["expiry", "date"])
        .groupby("expiry", as_index=False)
        .first()
        .sort_values("date")
    )


def attach_pnl(signals: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "expiry", "year", "width", "credit", "payoff", "pnl", "maxloss"]
    out = signals.merge(trades.loc[trades.width == WIDTH, cols], on=["date", "expiry", "year"], how="left")
    out["net_points"] = out.pnl - COST
    return out


def summarize(frame: pd.DataFrame) -> dict[str, float | int | None]:
    x = frame.net_points.dropna().to_numpy(float)
    if len(x) == 0:
        return {"n": 0, "mean_net": None, "median_net": None, "win_rate": None, "total_net": 0.0, "p_one_sided": None, "bootstrap_ci_lo": None, "bootstrap_ci_hi": None}
    test = ttest_1samp(x, 0.0, alternative="greater") if len(x) > 1 else None
    rng = np.random.default_rng(20260902 + len(x))
    bootstrap_means = rng.choice(x, size=(50_000, len(x)), replace=True).mean(axis=1)
    return {
        "n": int(len(x)),
        "mean_net": float(np.mean(x)),
        "median_net": float(np.median(x)),
        "win_rate": float(np.mean(x > 0)),
        "total_net": float(np.sum(x)),
        "p_one_sided": float(test.pvalue) if test is not None and np.isfinite(test.pvalue) else None,
        "bootstrap_ci_lo": float(np.quantile(bootstrap_means, 0.025)),
        "bootstrap_ci_hi": float(np.quantile(bootstrap_means, 0.975)),
        "worst_trade": float(np.min(x)),
        "best_trade": float(np.max(x)),
    }


def training_start_matrix(panel: pd.DataFrame, extended: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    starts = pd.to_datetime([
        "2023-01-02",
        "2023-01-23",
        "2023-02-01",
        "2023-03-01",
        "2023-04-01",
        "2023-07-01",
        "2023-10-01",
        "2024-01-01",
    ])
    rows: list[dict[str, object]] = []
    for start in starts:
        source = extended if start < pd.Timestamp("2023-01-23") else panel
        dev = source[(source.date >= start) & (source.date <= pd.Timestamp("2024-12-31"))]
        if len(dev) < 200:
            continue
        _, rr = calibrate(dev)
        for split, end, refit_end in [
            ("validation_2025", pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")),
            ("partial_2026", pd.Timestamp("2026-05-14"), pd.Timestamp("2025-12-31")),
        ]:
            score_start = pd.Timestamp("2025-01-01") if split == "validation_2025" else pd.Timestamp("2026-01-01")
            train = source[(source.date >= start) & (source.date <= refit_end)]
            model, _ = calibrate(train)
            score = panel[(panel.date >= score_start) & (panel.date <= end)]
            result = attach_pnl(first_per_expiry(score, model, rr), trades)
            rows.append({
                "training_start": start.strftime("%Y-%m-%d"),
                "split": split,
                "train_n": len(train),
                "rr_cutoff": rr,
                "intercept": float(model.intercept_),
                "coef_log_iv_int": float(model.coef_[0]),
                "coef_logT": float(model.coef_[1]),
                **summarize(result),
            })
    return pd.DataFrame(rows)


def quarterly_matrix(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, object]] = []
    ledgers: list[pd.DataFrame] = []
    periods = pd.period_range("2024Q1", "2026Q2", freq="Q")
    for period in periods:
        start = period.start_time.normalize()
        end = min(period.end_time.normalize(), pd.Timestamp("2026-05-14"))
        if end < start:
            continue
        train = panel[(panel.date < start) & (panel.expiry < start)]
        if len(train) < 150:
            continue
        try:
            model, rr = calibrate(train)
        except ValueError:
            continue
        score = panel[(panel.date >= start) & (panel.date <= end)]
        result = attach_pnl(first_per_expiry(score, model, rr), trades)
        result["test_period"] = str(period)
        ledgers.append(result)
        summary_rows.append({
            "test_period": str(period),
            "test_start": start.strftime("%Y-%m-%d"),
            "test_end": end.strftime("%Y-%m-%d"),
            "train_n": len(train),
            "rr_cutoff": rr,
            **summarize(result),
        })
    return pd.DataFrame(summary_rows), pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()


def expiry_walk_forward(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    ledgers: list[pd.DataFrame] = []
    expiries = sorted(x for x in panel.expiry.unique() if pd.Timestamp(x) >= pd.Timestamp("2024-01-01"))
    for mode in ["expanding", "rolling_252"]:
        for expiry_value in expiries:
            expiry = pd.Timestamp(expiry_value)
            score = panel[panel.expiry == expiry]
            if score.empty:
                continue
            first_date = score.date.min()
            train = panel[(panel.date < first_date) & (panel.expiry < first_date)]
            if mode == "rolling_252":
                train = train.tail(252)
            if len(train) < 150:
                continue
            try:
                model, rr = calibrate(train)
            except ValueError:
                continue
            signal = first_per_expiry(score, model, rr)
            if signal.empty:
                continue
            result = attach_pnl(signal, trades)
            result["walk_mode"] = mode
            result["train_n"] = len(train)
            result["rr_cutoff"] = rr
            ledgers.append(result)
    return pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()


def cost_ladder(frame: pd.DataFrame, grouping: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(grouping):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        base = dict(zip(grouping, key_tuple, strict=True))
        for cost in [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]:
            x = group.pnl.dropna().to_numpy(float) - cost
            rows.append({
                **base,
                "cost_points": cost,
                "n": len(x),
                "mean_net": float(np.mean(x)) if len(x) else None,
                "total_net": float(np.sum(x)),
                "win_rate": float(np.mean(x > 0)) if len(x) else None,
            })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--extended-panel", type=Path, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    panel = load_panel(args.panel)
    extended = load_panel(args.extended_panel)
    trades = pd.read_csv(args.trades, parse_dates=["date", "expiry"])
    start_matrix = training_start_matrix(panel, extended, trades)
    quarter_summary, quarter_ledger = quarterly_matrix(panel, trades)
    walk_ledger = expiry_walk_forward(panel, trades)
    walk_summary = []
    if not walk_ledger.empty:
        for (mode, year), group in walk_ledger.groupby(["walk_mode", "year"]):
            walk_summary.append({"walk_mode": mode, "year": int(year), **summarize(group)})
        for mode, group in walk_ledger.groupby("walk_mode"):
            walk_summary.append({"walk_mode": mode, "year": "all", **summarize(group)})
    walk_summary_df = pd.DataFrame(walk_summary)
    walk_costs = cost_ladder(walk_ledger, ["walk_mode"]) if not walk_ledger.empty else pd.DataFrame()

    start_matrix.to_csv(args.out / "training_start_sensitivity.csv", index=False)
    quarter_summary.to_csv(args.out / "quarterly_expanding_summary.csv", index=False)
    quarter_ledger.to_csv(args.out / "quarterly_expanding_ledger.csv", index=False)
    walk_ledger.to_csv(args.out / "expiry_walk_forward_ledger.csv", index=False)
    walk_summary_df.to_csv(args.out / "expiry_walk_forward_summary.csv", index=False)
    walk_costs.to_csv(args.out / "expiry_walk_forward_cost_ladder.csv", index=False)

    original = start_matrix[start_matrix.training_start == "2023-01-23"]
    start_positive = start_matrix.assign(positive=lambda x: x.mean_net > 0).groupby("split").positive.mean()
    quarter_positive = float((quarter_summary.mean_net > 0).mean()) if len(quarter_summary) else math.nan
    traded_quarters = quarter_summary[quarter_summary.n > 0]
    aggregates = {
        "fixed_definitions": {"q_max": Q_MAX, "rr_quantile": RR_QUANTILE, "width": WIDTH, "cost_points": COST},
        "training_start_variants": int(start_matrix.training_start.nunique()),
        "share_positive_by_split_across_starts": {str(k): float(v) for k, v in start_positive.items()},
        "original_start_results": original.to_dict(orient="records"),
        "quarterly_blocks": int(len(quarter_summary)),
        "share_positive_quarters": quarter_positive,
        "share_positive_traded_quarters": float((traded_quarters.mean_net > 0).mean()) if len(traded_quarters) else math.nan,
        "quarterly_total_net_points": float(quarter_ledger.net_points.sum()) if len(quarter_ledger) else 0.0,
        "quarterly_aggregate": summarize(quarter_ledger),
        "walk_forward": walk_summary_df.to_dict(orient="records"),
    }
    (args.out / "stability_summary.json").write_text(json.dumps(aggregates, indent=2), encoding="utf-8")
    print(json.dumps(aggregates, indent=2))


if __name__ == "__main__":
    main()
