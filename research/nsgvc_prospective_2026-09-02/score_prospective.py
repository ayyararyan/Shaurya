#!/usr/bin/env python3
"""Apply the frozen NSGVC gates to genuinely post-freeze daily panel rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = {"date", "expiry", "log_iv_int", "logT", "iv_int_var", "rr_400"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trades", type=Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    panel = pd.read_csv(args.panel, parse_dates=["date", "expiry"])
    missing = sorted(REQUIRED - set(panel.columns))
    if missing:
        raise ValueError(f"panel lacks required columns: {missing}")

    start = pd.Timestamp(config["prospective_start_date"])
    excluded = {pd.Timestamp(x) for x in config["invalid_or_excluded_dates"]}
    candidate = panel[(panel.date >= start) & (~panel.date.isin(excluded))].copy()
    candidate = candidate.dropna(subset=list(REQUIRED - {"date", "expiry"}))

    model = config["model"]
    candidate["pred_int_frozen"] = np.exp(
        model["intercept"]
        + model["coef_log_iv_int"] * candidate.log_iv_int
        + model["coef_logT"] * candidate.logT
    )
    candidate["pred_ratio_frozen"] = candidate.pred_int_frozen / candidate.iv_int_var
    gates = config["gates"]
    candidate["q_gate"] = candidate.pred_ratio_frozen <= gates["pred_ratio_max"]
    candidate["rr_gate"] = candidate.rr_400 <= gates["rr400_max_decimal"]
    candidate["both_gates"] = candidate.q_gate & candidate.rr_gate

    signals = (
        candidate[candidate.both_gates]
        .sort_values(["expiry", "date"])
        .groupby("expiry", as_index=False)
        .first()
        .sort_values("date")
    )

    result: dict[str, object] = {
        "strategy_version": config["version"],
        "prospective_start_date": config["prospective_start_date"],
        "config_sha256": sha256(args.config),
        "panel_sha256": sha256(args.panel),
        "eligible_input_rows": int(len(candidate)),
        "signal_count": int(len(signals)),
        "signal_dates": signals.date.dt.strftime("%Y-%m-%d").tolist(),
        "status": "signals_scored" if len(candidate) else "awaiting_post_freeze_data"
    }

    if args.trades is not None:
        trades = pd.read_csv(args.trades, parse_dates=["date", "expiry"])
        needed = {"date", "expiry", "width", "pnl", "maxloss", "credit"}
        absent = sorted(needed - set(trades.columns))
        if absent:
            raise ValueError(f"trades file lacks required columns: {absent}")
        joined = signals[["date", "expiry", "pred_ratio_frozen", "rr_400"]].merge(
            trades[trades.width.isin([400, 500])], on=["date", "expiry"], how="left"
        )
        joined["net_points_cost6"] = joined.pnl - config["structure"]["completed_structure_cost_points"]
        joined.to_csv(args.out.with_suffix(".matured_trades.csv"), index=False)
        matured = joined.dropna(subset=["pnl"])
        result["matured_structure_rows"] = int(len(matured))
        result["matured_expiries"] = int(matured.expiry.nunique())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    candidate.to_csv(args.out.with_suffix(".daily_scores.csv"), index=False)
    signals.to_csv(args.out.with_suffix(".signals.csv"), index=False)
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
