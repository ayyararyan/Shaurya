#!/usr/bin/env python3
"""Verify the frozen coefficients against the package's archived predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    p = pd.read_csv(args.panel)
    p = p[p.year >= 2026].copy()
    m = cfg["model"]
    pred_int = np.exp(m["intercept"] + m["coef_log_iv_int"] * p.log_iv_int + m["coef_logT"] * p.logT)
    pred_ratio = pred_int / p.iv_int_var
    finite = np.isfinite(pred_ratio) & np.isfinite(p.pred_ratio)
    maximum = float(np.max(np.abs(pred_ratio[finite] - p.loc[finite, "pred_ratio"])))
    result = {
        "compared_rows": int(finite.sum()),
        "max_abs_pred_ratio_difference": maximum,
        "pass_at_1e_12": maximum <= 1e-12,
    }
    if not result["pass_at_1e_12"]:
        raise AssertionError(result)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
