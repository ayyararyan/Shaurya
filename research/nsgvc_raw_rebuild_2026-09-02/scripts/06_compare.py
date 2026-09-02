#!/usr/bin/env python3
"""Compare a clean NSGVC raw rebuild with the frozen reproducible package."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


WORK = Path(os.environ["NSGVC_WORK"])
SMILE = Path(os.environ["NSGVC_SMILE"])
PACKAGE = Path(os.environ["NSGVC_PACKAGE"])
OUT = Path(os.environ["NSGVC_AUDIT_OUT"])
OUT.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def max_abs(left: pd.Series, right: pd.Series) -> float | None:
    a = pd.to_numeric(left, errors="coerce").to_numpy(float)
    b = pd.to_numeric(right, errors="coerce").to_numpy(float)
    finite = np.isfinite(a) & np.isfinite(b)
    if not finite.any():
        return None
    return float(np.max(np.abs(a[finite] - b[finite])))


def keyed_comparison(
    rebuilt: pd.DataFrame,
    reference: pd.DataFrame,
    keys: list[str],
    fields: list[str],
) -> dict[str, object]:
    l = rebuilt.copy()
    r = reference.copy()
    for key in keys:
        if "date" in key or key == "expiry":
            l[key] = pd.to_datetime(l[key]).dt.strftime("%Y-%m-%d")
            r[key] = pd.to_datetime(r[key]).dt.strftime("%Y-%m-%d")
    merged = l.merge(r, on=keys, how="outer", suffixes=("_rebuilt", "_reference"), indicator=True)
    common = merged[merged["_merge"] == "both"]
    diffs: dict[str, float | None] = {}
    for field in fields:
        lc = f"{field}_rebuilt"
        rc = f"{field}_reference"
        if lc in common and rc in common:
            diffs[field] = max_abs(common[lc], common[rc])
    return {
        "rebuilt_rows": int(len(l)),
        "reference_rows": int(len(r)),
        "common_rows": int(len(common)),
        "rebuilt_only_rows": int((merged["_merge"] == "left_only").sum()),
        "reference_only_rows": int((merged["_merge"] == "right_only").sum()),
        "max_abs_differences": diffs,
    }


spot_zip = Path(os.environ["NSGVC_SPOT_ZIP"])
option_zip = Path(os.environ["NSGVC_OPTION_ZIP"])
rebuilt_smile = pd.read_csv(SMILE / "smile_daily_panel.csv", parse_dates=["date", "expiry"])
reference_smile = pd.read_csv(PACKAGE / "data/derived/smile_daily_panel.csv", parse_dates=["date", "expiry"])
rebuilt_trades = pd.read_csv(WORK / "ironfly_trades_corrected.csv", parse_dates=["date", "expiry"])
reference_trades = pd.read_csv(PACKAGE / "data/derived/ironfly_trades_corrected.csv", parse_dates=["date", "expiry"])
reference_final = pd.read_csv(PACKAGE / "results/final_trade_ledger_500w_cost6.csv", parse_dates=["date", "expiry"])

features = [
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
d = rebuilt_smile.dropna(subset=["log_fwd_int", "iv", *features]).copy()
dev = d[d.year <= 2024]
train = d[d.year <= 2025]
mdev = LinearRegression().fit(dev[["log_iv_int", "logT"]], dev.log_fwd_int)
mfin = LinearRegression().fit(train[["log_iv_int", "logT"]], train.log_fwd_int)
d["pred_int_frozen"] = np.where(
    d.year <= 2025,
    np.exp(mdev.predict(d[["log_iv_int", "logT"]])),
    np.exp(mfin.predict(d[["log_iv_int", "logT"]])),
)
d["pred_ratio_frozen"] = d.pred_int_frozen / d.iv_int_var

devq = (
    d[(d.year <= 2024) & (d.pred_ratio_frozen <= 0.70)]
    .sort_values(["expiry", "date"])
    .groupby("expiry", as_index=False)
    .first()
)
rr_cutoff = float(devq.rr_400.quantile(0.60))
eligible = (
    d[(d.pred_ratio_frozen <= 0.70) & (d.rr_400 <= rr_cutoff)]
    .sort_values(["expiry", "date"])
    .groupby("expiry", as_index=False)
    .first()[["date", "expiry", "year", "rr_400", "pred_ratio_frozen"]]
)
final = eligible.merge(
    rebuilt_trades[rebuilt_trades.width == 500],
    on=["date", "expiry", "year"],
    how="left",
    suffixes=("", "_trade"),
)
final["netpts_cost6"] = final.pnl - 6.0
final.to_csv(OUT / "raw_rebuild_final_trade_ledger.csv", index=False)

smile_comparison = keyed_comparison(
    rebuilt_smile,
    reference_smile,
    ["date"],
    [
        "expiry",
        "iv",
        "forward",
        "fwd_int_var",
        "iv_int_var",
        "pred_int",
        "pred_ratio",
        "rr_400",
        "bf_400",
        "rr_500",
        "bf_500",
    ],
)
trade_comparison = keyed_comparison(
    rebuilt_trades,
    reference_trades,
    ["date", "expiry", "width"],
    ["credit", "payoff", "pnl", "maxloss", "pred_int", "pred_ratio"],
)
final_comparison = keyed_comparison(
    final,
    reference_final,
    ["date", "expiry"],
    ["rr_400", "pnl", "credit", "maxloss", "netpts_cost6"],
)

# Isolate whether any disagreement is caused solely by rows present only in the
# consolidated archive. Refit and gate after restricting to the package's date
# universe; this is a diagnostic, not deletion of raw observations.
reference_dates = set(reference_smile.date.dt.normalize())
rebuilt_only_dates = sorted(set(rebuilt_smile.date.dt.normalize()) - reference_dates)
common_d = d[d.date.dt.normalize().isin(reference_dates)].copy()
common_dev = common_d[common_d.year <= 2024]
common_train = common_d[common_d.year <= 2025]
common_mdev = LinearRegression().fit(common_dev[["log_iv_int", "logT"]], common_dev.log_fwd_int)
common_mfin = LinearRegression().fit(common_train[["log_iv_int", "logT"]], common_train.log_fwd_int)
common_d["pred_int_common"] = np.where(
    common_d.year <= 2025,
    np.exp(common_mdev.predict(common_d[["log_iv_int", "logT"]])),
    np.exp(common_mfin.predict(common_d[["log_iv_int", "logT"]])),
)
common_d["pred_ratio_common"] = common_d.pred_int_common / common_d.iv_int_var
common_devq = (
    common_d[(common_d.year <= 2024) & (common_d.pred_ratio_common <= 0.70)]
    .sort_values(["expiry", "date"])
    .groupby("expiry", as_index=False)
    .first()
)
common_rr_cutoff = float(common_devq.rr_400.quantile(0.60))
common_eligible = (
    common_d[(common_d.pred_ratio_common <= 0.70) & (common_d.rr_400 <= common_rr_cutoff)]
    .sort_values(["expiry", "date"])
    .groupby("expiry", as_index=False)
    .first()[["date", "expiry", "year", "rr_400", "pred_ratio_common"]]
)
common_final = common_eligible.merge(
    rebuilt_trades[rebuilt_trades.width == 500],
    on=["date", "expiry", "year"],
    how="left",
)
common_final["netpts_cost6"] = common_final.pnl - 6.0
common_final.to_csv(OUT / "common_date_final_trade_ledger.csv", index=False)
common_final_comparison = keyed_comparison(
    common_final,
    reference_final,
    ["date", "expiry"],
    ["rr_400", "pnl", "credit", "maxloss", "netpts_cost6"],
)

summary = {
    "inputs": {
        "spot_zip": str(spot_zip),
        "spot_zip_sha256": sha256(spot_zip),
        "option_zip": str(option_zip),
        "option_zip_sha256": sha256(option_zip),
    },
    "raw_extraction": {
        "spot_rows": int(len(pd.read_csv(WORK / "spot_2022_2026.csv"))),
        "option_0920_rows": int(len(pd.read_csv(WORK / "option_0920_entries_2023_2026.csv"))),
    },
    "frozen_model": {
        "development_rows": int(len(dev)),
        "final_train_rows": int(len(train)),
        "final_intercept": float(mfin.intercept_),
        "final_coefficients": [float(x) for x in mfin.coef_],
        "max_abs_existing_vs_frozen_pred_ratio": max_abs(d.pred_ratio, d.pred_ratio_frozen),
        "rr400_cutoff": rr_cutoff,
        "rr400_vol_points": rr_cutoff * 100.0,
    },
    "smile_panel_comparison": smile_comparison,
    "ironfly_trade_comparison": trade_comparison,
    "final_ledger_comparison": final_comparison,
    "consolidated_archive_date_diagnostic": {
        "rebuilt_only_dates": [x.strftime("%Y-%m-%d") for x in rebuilt_only_dates],
        "common_date_final_train_rows": int(len(common_train)),
        "common_date_final_intercept": float(common_mfin.intercept_),
        "common_date_final_coefficients": [float(x) for x in common_mfin.coef_],
        "common_date_rr400_cutoff": common_rr_cutoff,
        "common_date_rr400_vol_points": common_rr_cutoff * 100.0,
        "common_date_final_ledger_comparison": common_final_comparison,
        "common_date_total_inr_at_lot65": float((common_final.netpts_cost6 * 65.0).sum()),
    },
    "final_results_cost6": {
        "trades": int(len(final)),
        "mean_net_option_points": float(final.netpts_cost6.mean()),
        "median_net_option_points": float(final.netpts_cost6.median()),
        "win_rate": float((final.netpts_cost6 > 0).mean()),
        "total_inr_at_lot65": float((final.netpts_cost6 * 65.0).sum()),
    },
}
(OUT / "raw_rebuild_audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

md = f"""# NSGVC Independent Raw Rebuild Audit

This run rebuilt the NSGVC research chain from the consolidated NIFTY spot and option ZIPs, while preserving the package's frozen model and gate definitions.

- Rebuilt spot rows: {summary['raw_extraction']['spot_rows']:,}
- Rebuilt 09:20 option rows: {summary['raw_extraction']['option_0920_rows']:,}
- Frozen final-model training rows: {summary['frozen_model']['final_train_rows']:,}
- Rebuilt RR400 cutoff: {rr_cutoff:.15f} ({rr_cutoff * 100:.6f} vol points)
- Final trades: {len(final)}
- Mean net P&L at 6 points cost: {final.netpts_cost6.mean():.6f} option points
- Win rate: {(final.netpts_cost6 > 0).mean():.6%}
- Total at the package's normalized 65-unit lot: INR {(final.netpts_cost6 * 65).sum():,.6f}

Exact keyed comparisons are recorded in `raw_rebuild_audit.json`. A zero unmatched-row count and numerical differences near floating-point precision establish agreement with the frozen package.
"""
(OUT / "RAW_REBUILD_AUDIT.md").write_text(md, encoding="utf-8")
print(json.dumps(summary, indent=2))
