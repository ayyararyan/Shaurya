#!/usr/bin/env python3
"""Purged overnight-aware RV forecasting horse race for NIFTY nearest-weekly options.

Research only.  The headline target is forward *integrated* realized variance from the
forecast origin to WEEK1 expiry, including every overnight close-to-open jump in the holding
window.  The script intentionally does not alter Shaurya's production NSGVC coefficients.

Run from research/scratch/gap_open_analysis, where the historical archive helpers and caches
already live.  Default origin is the 10:00 one-minute bar close (known after that bar closes).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import nge_common as nc
from analyze_still_water_spot import load_spot

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
except Exception:  # pragma: no cover - optional exploratory contender
    HistGradientBoostingRegressor = None

SEED = 20260910
RATE = nc.RISK_FREE_RATE
SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
MIN_TRAIN = 252
RIDGE_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
EPS = 1e-12

# The local archive only carries WEEK1 ATM +/- 10 strikes. Production can exclude a much wider
# ATM band because it has a fuller chain; historical backfill cannot. V2 therefore fits a
# constrained single-slice eSSVI proxy to OTM quotes including the near-ATM region and reports the
# policy explicitly. No future prices enter the fit.
HISTORICAL_ESSVI_POLICY = "single_week1_slice_otm_include_near_atm_due_to_archive_width"


@dataclass(frozen=True)
class LinearModel:
    beta: np.ndarray
    mu: np.ndarray
    sd: np.ndarray

    def predict(self, x: np.ndarray) -> np.ndarray:
        z = (x - self.mu) / self.sd
        a = np.column_stack([np.ones(len(z)), z])
        return a @ self.beta


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_price(*, is_call: bool, forward: float, strike: float, T: float, sigma: float) -> float:
    if min(forward, strike, T, sigma) <= 0:
        return float("nan")
    srt = sigma * math.sqrt(T)
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * T) / srt
    d2 = d1 - srt
    disc = math.exp(-RATE * T)
    if is_call:
        return disc * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return disc * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def invert_black76(*, is_call: bool, price: float, forward: float, strike: float, T: float) -> float:
    if min(price, forward, strike, T) <= 0:
        return float("nan")
    disc = math.exp(-RATE * T)
    intrinsic = disc * max((forward - strike) if is_call else (strike - forward), 0.0)
    upper = disc * (forward if is_call else strike)
    if not (intrinsic + 1e-9 < price < upper - 1e-9):
        return float("nan")
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        val = black76_price(is_call=is_call, forward=forward, strike=strike, T=T, sigma=mid)
        if val < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _next_expiry(date: str, expiries: list[str]) -> str | None:
    i = int(np.searchsorted(expiries, date, side="left"))
    return expiries[i] if i < len(expiries) else None


def _expiry_timestamp(expiry: str) -> pd.Timestamp:
    return pd.Timestamp(f"{expiry} 15:30:00", tz="Asia/Kolkata")


def _origin_timestamp(date: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{date} {clock}:00", tz="Asia/Kolkata")


def load_option_snapshot(clock: str, rebuild: bool = False) -> pd.DataFrame:
    tag = clock.replace(":", "")
    cache = Path(f"rv_forecast_v2_option_snapshot_{tag}.pkl")
    if cache.exists() and not rebuild:
        return pd.read_pickle(cache)

    use_cols = ["close", "iv", "strike", "oi", "spot", "datetime", "volume"]
    frames: list[pd.DataFrame] = []
    for row in nc.manifest_rows():
        side = row.get("drv_option_type")
        if side not in ("CALL", "PUT"):
            continue
        path = nc.cached_path(row)
        if not path.exists():
            continue
        frame = pd.read_csv(path, usecols=use_cols)
        m = frame["datetime"].str.slice(11, 16).eq(clock)
        if not m.any():
            continue
        frame = frame.loc[m].copy()
        frame["date"] = frame["datetime"].str.slice(0, 10)
        frame["side"] = side
        frames.append(frame.drop(columns=["datetime"]))
    if not frames:
        raise FileNotFoundError(f"no option bars found at {clock}")

    snap = pd.concat(frames, ignore_index=True)
    snap = snap[(snap["close"] > 0) & np.isfinite(snap["close"])]
    key = ["date", "side", "strike"]
    snap = snap.sort_values(key + ["volume"], ascending=[True, True, True, False])
    snap = snap.drop_duplicates(key, keep="first").sort_values(key).reset_index(drop=True)
    tmp = cache.with_suffix(".incoming")
    snap.to_pickle(tmp)
    os.replace(tmp, cache)
    return snap


def parity_forward(day: pd.DataFrame, T: float) -> float:
    calls = day[day["side"] == "CALL"][["strike", "close"]].rename(columns={"close": "c"})
    puts = day[day["side"] == "PUT"][["strike", "close"]].rename(columns={"close": "p"})
    pair = calls.merge(puts, on="strike", how="inner")
    if pair.empty:
        return float(day["spot"].median() * math.exp(RATE * T))
    candidates = pair["strike"].to_numpy(float) + math.exp(RATE * T) * (
        pair["c"].to_numpy(float) - pair["p"].to_numpy(float)
    )
    spot = float(day["spot"].median())
    ok = np.isfinite(candidates) & (candidates > 0.95 * spot) & (candidates < 1.05 * spot)
    if ok.sum() < 3:
        return spot * math.exp(RATE * T)
    return float(np.median(candidates[ok]))


def essvi_w(k: np.ndarray | float, theta: float, rho: float, psi: float) -> np.ndarray:
    x = np.asarray(k, dtype=float)
    core = np.sqrt(((psi * x) + (rho * theta)) ** 2 + theta**2 * (1.0 - rho**2))
    return 0.5 * (theta + rho * psi * x + core)


def fit_essvi_slice(day: pd.DataFrame, *, expiry: str, clock: str) -> dict[str, float] | None:
    origin = _origin_timestamp(str(day["date"].iloc[0]), clock)
    exp_ts = _expiry_timestamp(expiry)
    T = (exp_ts - origin).total_seconds() / SECONDS_PER_YEAR
    if T <= 0:
        return None
    F = parity_forward(day, T)
    spot = float(day["spot"].median())

    obs: list[tuple[float, float, float]] = []
    for strike, g in day.groupby("strike"):
        K = float(strike)
        if K < F:
            q = g[g["side"] == "PUT"]
            is_call = False
        else:
            q = g[g["side"] == "CALL"]
            is_call = True
        if q.empty:
            continue
        row = q.iloc[0]
        iv = float(row["iv"]) / 100.0 if float(row["iv"]) > 1.0 else float(row["iv"])
        if not (0.02 <= iv <= 2.0):
            iv = invert_black76(
                is_call=is_call, price=float(row["close"]), forward=F, strike=K, T=T
            )
        if not np.isfinite(iv) or iv <= 0:
            continue
        k = math.log(K / F)
        total_var = iv * iv * T
        weight = 1.0 / (1.0 + (abs(k) / 0.02) ** 2)
        obs.append((k, total_var, weight))
    if len(obs) < 7:
        return None

    ks = np.asarray([x[0] for x in obs])
    ws = np.asarray([x[1] for x in obs])
    wt = np.asarray([x[2] for x in obs])
    wt = wt / wt.sum()
    atm_idx = int(np.argmin(np.abs(ks)))
    theta0 = max(float(ws[atm_idx]), 1e-6)
    x0 = np.array([theta0, -0.25, min(0.12, math.sqrt(2.0 * theta0))])

    def objective(x: np.ndarray) -> float:
        theta, rho, psi = map(float, x)
        residual = essvi_w(ks, theta, rho, psi) - ws
        return float(np.sum(wt * residual * residual))

    def constraints(x: np.ndarray) -> np.ndarray:
        theta, rho, psi = map(float, x)
        return np.asarray(
            [4.0 - psi * (1.0 + abs(rho)), 4.0 * theta - psi * psi * (1.0 + abs(rho))]
        )

    res = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=((1e-8, 5.0), (-0.999, 0.999), (1e-8, 4.0)),
        constraints=({"type": "ineq", "fun": constraints},),
        options={"maxiter": 1000, "ftol": 1e-14, "disp": False},
    )
    if not bool(res.success) or float(np.min(constraints(np.asarray(res.x)))) < -1e-7:
        return None
    theta, rho, psi = map(float, res.x)

    def iv_at_strike(K: float) -> float:
        k = math.log(K / F)
        w = float(essvi_w(k, theta, rho, psi))
        return math.sqrt(max(w, EPS) / T)

    atm_iv = math.sqrt(theta / T)
    out: dict[str, float] = {
        "surface_T": T,
        "surface_forward": F,
        "surface_forward_basis": F / spot - 1.0,
        "essvi_theta": theta,
        "essvi_rho": rho,
        "essvi_psi": psi,
        "essvi_phi": psi / theta,
        "essvi_atm_iv": atm_iv,
        "essvi_skew_w0": 0.5 * rho * psi,
        "essvi_fit_rmse": math.sqrt(max(float(res.fun), 0.0)),
        "essvi_quote_count": float(len(obs)),
    }
    atm_strike = 50.0 * math.floor((F / 50.0) + 0.5)
    for width in (100.0, 200.0, 400.0):
        left = iv_at_strike(atm_strike - width)
        right = iv_at_strike(atm_strike + width)
        out[f"essvi_rr{int(width)}"] = left - right
        out[f"essvi_bf{int(width)}"] = 0.5 * (left + right) - atm_iv
        out[f"essvi_left{int(width)}"] = left
        out[f"essvi_right{int(width)}"] = right
    return out


def build_surface_features(snap: pd.DataFrame, clock: str) -> pd.DataFrame:
    expiries = nc._expiry_dates()
    rows: list[dict[str, float | str]] = []
    for date, day in snap.groupby("date", sort=True):
        expiry = _next_expiry(str(date), expiries)
        if expiry is None:
            continue
        fit = fit_essvi_slice(day, expiry=expiry, clock=clock)
        if fit is None:
            continue
        rows.append({"date": str(date), "expiry": expiry, **fit})
    return pd.DataFrame(rows)


def daily_realized_features(spot: pd.DataFrame) -> pd.DataFrame:
    x = spot.copy()
    x = x[(x["clock"] >= nc.SESSION_OPEN) & (x["clock"] <= nc.SESSION_LAST)]
    x = x.drop_duplicates(["date", "clock"]).sort_values(["date", "clock"])
    rows: list[dict[str, float | str]] = []
    prev_close: float | None = None
    for date, g in x.groupby("date", sort=True):
        px = g["spot"].to_numpy(float)
        if len(px) < 200:
            continue
        r = np.diff(np.log(px))
        rv = float(np.sum(r * r))
        up = float(np.sum((r[r > 0]) ** 2))
        down = float(np.sum((r[r < 0]) ** 2))
        bipower = float((math.pi / 2.0) * np.sum(np.abs(r[1:]) * np.abs(r[:-1]))) if len(r) > 1 else 0.0
        jump = max(rv - bipower, 0.0)
        quarticity = float((len(r) / 3.0) * np.sum(r**4)) if len(r) else 0.0
        open_px, close_px = float(px[0]), float(px[-1])
        on_ret = math.log(open_px / prev_close) if prev_close and prev_close > 0 else np.nan
        rows.append(
            {
                "date": str(date),
                "intra_var": rv,
                "up_semivar": up,
                "down_semivar": down,
                "bipower_var": bipower,
                "jump_var": jump,
                "quarticity": quarticity,
                "max_abs_1m": float(np.max(np.abs(r))) if len(r) else np.nan,
                "overnight_ret": on_ret,
                "overnight_var": on_ret * on_ret if np.isfinite(on_ret) else np.nan,
                "open_spot": open_px,
                "close_spot": close_px,
            }
        )
        prev_close = close_px
    return pd.DataFrame(rows)


def origin_intraday_features(spot: pd.DataFrame, clock: str) -> pd.DataFrame:
    """Features realized from the session open through the forecast-origin bar only."""
    x = spot.copy()
    x = x[(x["clock"] >= nc.SESSION_OPEN) & (x["clock"] <= clock)]
    x = x.drop_duplicates(["date", "clock"]).sort_values(["date", "clock"])
    rows: list[dict[str, float | str]] = []
    for date, g in x.groupby("date", sort=True):
        px = g["spot"].to_numpy(float)
        if len(px) < 2:
            continue
        r = np.diff(np.log(px))
        rv = float(np.sum(r * r))
        bipower = float((math.pi / 2.0) * np.sum(np.abs(r[1:]) * np.abs(r[:-1]))) if len(r) > 1 else 0.0
        rows.append(
            {
                "date": str(date),
                "origin_intra_var": rv,
                "origin_up_semivar": float(np.sum((r[r > 0]) ** 2)),
                "origin_down_semivar": float(np.sum((r[r < 0]) ** 2)),
                "origin_jump_var": max(rv - bipower, 0.0),
                "origin_abs_return": abs(float(math.log(px[-1] / px[0]))),
                "origin_signed_return": float(math.log(px[-1] / px[0])),
                "origin_max_abs_1m": float(np.max(np.abs(r))),
            }
        )
    return pd.DataFrame(rows)


def trailing_sum_prior(values: np.ndarray, i: int, w: int) -> float:
    if i < w:
        return np.nan
    return float(np.nansum(values[i - w : i]))


def add_lagged_realized_features(panel: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.sort_values("date").reset_index(drop=True)
    pos = {str(v): i for i, v in enumerate(d["date"])}
    arrays = {c: d[c].to_numpy(float) for c in [
        "intra_var", "up_semivar", "down_semivar", "bipower_var", "jump_var",
        "quarticity", "overnight_var", "overnight_ret", "max_abs_1m",
    ]}
    rows: list[dict[str, float | str]] = []
    for date in panel["date"]:
        i = pos.get(str(date))
        if i is None:
            continue
        rec: dict[str, float | str] = {"date": str(date)}
        for w in (1, 5, 22, 66):
            rec[f"intra_var_{w}"] = trailing_sum_prior(arrays["intra_var"], i, w) / w
            rec[f"on_var_{w}"] = trailing_sum_prior(arrays["overnight_var"], i, w) / w
            rec[f"up_var_{w}"] = trailing_sum_prior(arrays["up_semivar"], i, w) / w
            rec[f"down_var_{w}"] = trailing_sum_prior(arrays["down_semivar"], i, w) / w
            rec[f"jump_var_{w}"] = trailing_sum_prior(arrays["jump_var"], i, w) / w
            rec[f"bipower_var_{w}"] = trailing_sum_prior(arrays["bipower_var"], i, w) / w
        if i >= 1:
            rec["last_overnight_ret"] = float(arrays["overnight_ret"][i - 1])
            rec["last_overnight_var"] = float(arrays["overnight_var"][i - 1])
            rec["last_max_abs_1m"] = float(arrays["max_abs_1m"][i - 1])
            rec["last_quarticity"] = float(arrays["quarticity"][i - 1])
        rows.append(rec)
    return panel.merge(pd.DataFrame(rows), on="date", how="left")


def build_targets(spot: pd.DataFrame, panel_dates: pd.DataFrame, clock: str) -> pd.DataFrame:
    x = spot.copy()
    x = x[(x["clock"] >= nc.SESSION_OPEN) & (x["clock"] <= nc.SESSION_LAST)]
    x = x.drop_duplicates(["date", "clock"]).sort_values(["date", "clock"])
    sessions = sorted(x["date"].astype(str).unique().tolist())
    by_date = {str(d): g.sort_values("clock") for d, g in x.groupby("date", sort=False)}
    expiries = nc._expiry_dates()
    rows: list[dict[str, float | str]] = []

    for date in panel_dates["date"].astype(str):
        expiry = _next_expiry(date, expiries)
        if expiry is None or date not in by_date or expiry not in by_date:
            continue
        i = int(np.searchsorted(sessions, date))
        j = int(np.searchsorted(sessions, expiry))
        if i >= len(sessions) or j >= len(sessions) or sessions[i] != date or sessions[j] != expiry:
            continue

        intra = 0.0
        night = 0.0
        valid = True
        prev_close = None
        for p in range(i, j + 1):
            d = sessions[p]
            g = by_date[d]
            if p == i:
                g = g[g["clock"] >= clock]
            px = g["spot"].to_numpy(float)
            if len(px) < 2:
                valid = False
                break
            if p > i and prev_close is not None:
                open_px = float(px[0])
                night += math.log(open_px / prev_close) ** 2
            rr = np.diff(np.log(px))
            intra += float(np.sum(rr * rr))
            prev_close = float(px[-1])
        if not valid:
            continue
        origin = _origin_timestamp(date, clock)
        T = (_expiry_timestamp(expiry) - origin).total_seconds() / SECONDS_PER_YEAR
        rows.append(
            {
                "date": date,
                "expiry": expiry,
                "target_intra_var": intra,
                "target_overnight_var": night,
                "target_total_var": intra + night,
                "target_nights": float(max(j - i, 0)),
                "surface_T_target": T,
            }
        )
    return pd.DataFrame(rows)


def add_current_gap(panel: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    x = daily[["date", "overnight_ret", "overnight_var"]].copy()
    x = x.rename(columns={"overnight_ret": "current_gap_ret", "overnight_var": "current_gap_var"})
    return panel.merge(x, on="date", how="left")


def add_vix(panel: pd.DataFrame) -> pd.DataFrame:
    path = Path("k2_expiry_vix_rose_panel.csv")
    if not path.exists():
        return panel
    v = pd.read_csv(path)
    v["date"] = pd.to_datetime(v["date"]).dt.strftime("%Y-%m-%d")
    for c in ("vix_open", "vix_prior_session_close"):
        if c in v:
            v[c] = pd.to_numeric(v[c], errors="coerce")
    keep = [c for c in ["date", "vix_open", "vix_prior_session_close"] if c in v]
    v = v[keep].drop_duplicates("date")
    if "vix_open" in v and "vix_prior_session_close" in v:
        v["vix_gap"] = v["vix_open"] - v["vix_prior_session_close"]
    return panel.merge(v, on="date", how="left")


def add_optional_exogenous(panel: pd.DataFrame, path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return panel
    ex = pd.read_csv(path)
    if "date" not in ex:
        raise ValueError("exogenous CSV must contain date")
    ex["date"] = pd.to_datetime(ex["date"]).dt.strftime("%Y-%m-%d")
    bad = [c for c in ex.columns if c != "date" and not c.startswith("exo_")]
    if bad:
        raise ValueError(f"exogenous feature columns must start with exo_: {bad}")
    return panel.merge(ex.drop_duplicates("date"), on="date", how="left")


def build_panel(clock: str, rebuild: bool, exogenous: Path | None) -> pd.DataFrame:
    tag = clock.replace(":", "")
    cache = Path(f"rv_forecast_v2_panel_{tag}.pkl")
    if cache.exists() and not rebuild:
        return pd.read_pickle(cache)

    snap = load_option_snapshot(clock, rebuild=rebuild)
    surface = build_surface_features(snap, clock)
    spot, _ = load_spot()
    daily = daily_realized_features(spot)
    origin_features = origin_intraday_features(spot, clock)
    targets = build_targets(spot, surface[["date"]], clock)
    panel = surface.merge(targets, on=["date", "expiry"], how="inner", suffixes=("", "_target"))
    panel = add_lagged_realized_features(panel, daily)
    panel = add_current_gap(panel, daily)
    panel = panel.merge(origin_features, on="date", how="left")
    panel = add_vix(panel)
    panel = add_optional_exogenous(panel, exogenous)
    panel["year"] = panel["date"].str.slice(0, 4).astype(int)
    panel["dow"] = pd.to_datetime(panel["date"]).dt.dayofweek.astype(float)
    panel["n_sess"] = panel["target_nights"] + 1.0
    panel["log_T"] = np.log(panel["surface_T"].clip(lower=EPS))
    panel["log_iv_int"] = np.log(panel["essvi_theta"].clip(lower=EPS))
    panel = panel.sort_values("date").reset_index(drop=True)
    tmp = cache.with_suffix(".incoming")
    panel.to_pickle(tmp)
    os.replace(tmp, cache)
    return panel


def _standardize_fit(x: np.ndarray, y: np.ndarray, alpha: float = 0.0) -> LinearModel:
    mu = np.nanmean(x, axis=0)
    sd = np.nanstd(x, axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    z = (x - mu) / sd
    a = np.column_stack([np.ones(len(z)), z])
    pen = np.eye(a.shape[1]) * alpha
    pen[0, 0] = 0.0
    beta = np.linalg.solve(a.T @ a + pen, a.T @ y)
    return LinearModel(beta=beta, mu=mu, sd=sd)


def qlike(y: np.ndarray, yhat: np.ndarray) -> float:
    y = np.clip(np.asarray(y, float), EPS, None)
    yhat = np.clip(np.asarray(yhat, float), EPS, None)
    ratio = y / yhat
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def purged_train(panel: pd.DataFrame, origin_date: str) -> pd.DataFrame:
    return panel[(panel["date"] < origin_date) & (panel["expiry"] < origin_date)]


def choose_ridge_alpha(tr: pd.DataFrame, features: list[str], target: str) -> float:
    d = tr.dropna(subset=features + [target]).sort_values("date").reset_index(drop=True)
    if len(d) < 2 * MIN_TRAIN:
        return 10.0
    dates = d["date"].tolist()
    cut_idx = sorted(set(int(len(d) * f) for f in (0.55, 0.70, 0.85)))
    scores = {a: [] for a in RIDGE_ALPHAS}
    for ci in cut_idx:
        if ci < MIN_TRAIN or ci >= len(d) - 10:
            continue
        start = dates[ci]
        stop_i = min(ci + max(20, len(d) // 10), len(d))
        stop = dates[stop_i - 1]
        fit = d[(d["date"] < start) & (d["expiry"] < start)]
        val = d[(d["date"] >= start) & (d["date"] <= stop)]
        fit = fit.dropna(subset=features + [target])
        val = val.dropna(subset=features + [target])
        if len(fit) < MIN_TRAIN or len(val) < 10:
            continue
        xtr = fit[features].to_numpy(float)
        ytr = np.log(np.clip(fit[target].to_numpy(float), EPS, None))
        xva = val[features].to_numpy(float)
        yva = val[target].to_numpy(float)
        for alpha in RIDGE_ALPHAS:
            m = _standardize_fit(xtr, ytr, alpha=alpha)
            pred = np.exp(m.predict(xva))
            scores[alpha].append(qlike(yva, pred))
    valid = {a: float(np.mean(v)) for a, v in scores.items() if v}
    return min(valid, key=valid.get) if valid else 10.0


BASE = ["log_iv_int", "log_T"]
HAR_TOTAL = BASE + [
    "intra_var_1", "intra_var_5", "intra_var_22", "on_var_1", "on_var_5", "on_var_22"
]
SURFACE = [
    "essvi_rho", "essvi_psi", "essvi_phi", "essvi_skew_w0",
    "essvi_rr100", "essvi_rr200", "essvi_rr400",
    "essvi_bf100", "essvi_bf200", "essvi_bf400",
    "surface_forward_basis", "essvi_fit_rmse",
]
RICH = [
    "up_var_5", "down_var_5", "up_var_22", "down_var_22",
    "jump_var_5", "jump_var_22", "bipower_var_5", "bipower_var_22",
    "last_quarticity", "last_max_abs_1m", "current_gap_ret", "current_gap_var",
    "origin_intra_var", "origin_up_semivar", "origin_down_semivar", "origin_jump_var",
    "origin_abs_return", "origin_signed_return", "origin_max_abs_1m", "dow", "n_sess",
]
OPTIONAL = ["vix_open", "vix_prior_session_close", "vix_gap"]

DAY_FEATURES = [
    "log_iv_int", "log_T", "intra_var_1", "intra_var_5", "intra_var_22", "intra_var_66",
    "up_var_5", "down_var_5", "up_var_22", "down_var_22",
    "jump_var_5", "bipower_var_22", "last_quarticity", "last_max_abs_1m",
    "current_gap_ret", "current_gap_var", "origin_intra_var", "origin_up_semivar",
    "origin_down_semivar", "origin_jump_var", "origin_abs_return", "origin_signed_return",
    "origin_max_abs_1m", "n_sess", "dow",
] + SURFACE

NIGHT_FEATURES = [
    "log_iv_int", "log_T", "on_var_1", "on_var_5", "on_var_22", "on_var_66",
    "last_overnight_ret", "last_overnight_var", "current_gap_ret", "current_gap_var",
    "origin_intra_var", "origin_abs_return", "origin_signed_return", "origin_jump_var",
    "jump_var_5", "down_var_5", "n_sess", "dow",
] + SURFACE


def available_features(panel: pd.DataFrame, requested: list[str]) -> list[str]:
    return [c for c in requested if c in panel.columns and panel[c].notna().sum() >= MIN_TRAIN]


def direct_log_forecast(
    tr: pd.DataFrame,
    row: pd.DataFrame,
    features: list[str],
    target: str,
    *,
    ridge: bool,
) -> float:
    d = tr.dropna(subset=features + [target])
    if len(d) < MIN_TRAIN or row[features].isna().to_numpy().any():
        return np.nan
    alpha = choose_ridge_alpha(d, features, target) if ridge else 0.0
    model = _standardize_fit(
        d[features].to_numpy(float),
        np.log(np.clip(d[target].to_numpy(float), EPS, None)),
        alpha=alpha,
    )
    return float(np.exp(model.predict(row[features].to_numpy(float))[0]))


def decomposed_forecast(
    tr: pd.DataFrame, row: pd.DataFrame, *, ridge: bool
) -> tuple[float, float, float]:
    extras = OPTIONAL + [c for c in tr.columns if c.startswith("exo_")]
    day_features = available_features(tr, DAY_FEATURES + extras)
    night_features = available_features(tr, NIGHT_FEATURES + extras)
    d = tr.copy()
    d["day_rate"] = d["target_intra_var"] / d["n_sess"].clip(lower=1.0)
    n = d["target_nights"]
    d["night_rate"] = np.where(n > 0, d["target_overnight_var"] / n, np.nan)

    day_hat_rate = direct_log_forecast(d, row, day_features, "day_rate", ridge=ridge)
    day_hat = day_hat_rate * float(row["n_sess"].iloc[0]) if np.isfinite(day_hat_rate) else np.nan
    nights = float(row["target_nights"].iloc[0])
    if nights <= 0:
        night_hat = 0.0
    else:
        night_hat_rate = direct_log_forecast(d, row, night_features, "night_rate", ridge=ridge)
        night_hat = night_hat_rate * nights if np.isfinite(night_hat_rate) else np.nan
    total = day_hat + night_hat if np.isfinite(day_hat) and np.isfinite(night_hat) else np.nan
    return total, day_hat, night_hat


def hgb_forecast(tr: pd.DataFrame, row: pd.DataFrame, features: list[str], target: str) -> float:
    if HistGradientBoostingRegressor is None:
        return np.nan
    d = tr.dropna(subset=features + [target])
    if len(d) < 400 or row[features].isna().to_numpy().any():
        return np.nan
    x = d[features].to_numpy(float)
    y = np.log(np.clip(d[target].to_numpy(float), EPS, None))
    m = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.04,
        max_iter=200,
        max_leaf_nodes=7,
        min_samples_leaf=30,
        l2_regularization=3.0,
        random_state=SEED,
    )
    m.fit(x, y)
    return float(np.exp(m.predict(row[features].to_numpy(float))[0]))


def walk_forward(panel: pd.DataFrame, fast: bool) -> pd.DataFrame:
    p = panel.sort_values("date").reset_index(drop=True)
    har = available_features(p, HAR_TOTAL)
    har_surface = available_features(p, HAR_TOTAL + SURFACE)
    exog = [c for c in p.columns if c.startswith("exo_")]
    rich = available_features(p, HAR_TOTAL + SURFACE + RICH + OPTIONAL + exog)
    rows: list[dict[str, float | str]] = []

    for _, r in p.iterrows():
        date = str(r["date"])
        tr = purged_train(p, date)
        if len(tr) < MIN_TRAIN:
            continue
        row = r.to_frame().T
        rec: dict[str, float | str] = {
            "date": date,
            "expiry": str(r["expiry"]),
            "truth_total_var": float(r["target_total_var"]),
            "truth_intra_var": float(r["target_intra_var"]),
            "truth_overnight_var": float(r["target_overnight_var"]),
            "theta": float(r["essvi_theta"]),
            "T": float(r["surface_T"]),
            "n_sess": float(r["n_sess"]),
            "nights": float(r["target_nights"]),
            "train_n": float(len(tr)),
        }
        rate = tr["target_total_var"] / tr["surface_T"].clip(lower=EPS)
        rec["mean_rate"] = float(rate.mean() * float(r["surface_T"]))
        rec["iv_identity"] = float(r["essvi_theta"])
        rec["iv_only"] = direct_log_forecast(tr, row, BASE, "target_total_var", ridge=False)
        rec["har"] = direct_log_forecast(tr, row, har, "target_total_var", ridge=False)
        rec["har_surface"] = direct_log_forecast(tr, row, har_surface, "target_total_var", ridge=False)
        rec["har_surface_ridge"] = direct_log_forecast(tr, row, rich, "target_total_var", ridge=True)
        d0, d0_day, d0_night = decomposed_forecast(tr, row, ridge=False)
        d1, d1_day, d1_night = decomposed_forecast(tr, row, ridge=True)
        rec["decomp_har_surface"] = d0
        rec["decomp_har_surface_ridge"] = d1
        rec["component_intra_decomp_har_surface"] = d0_day
        rec["component_overnight_decomp_har_surface"] = d0_night
        rec["component_intra_decomp_har_surface_ridge"] = d1_day
        rec["component_overnight_decomp_har_surface_ridge"] = d1_night
        if not fast:
            rec["hgb_surface_rich"] = hgb_forecast(tr, row, rich, "target_total_var")
        rows.append(rec)
    return pd.DataFrame(rows)


def oos_r2(y: np.ndarray, yhat: np.ndarray, bench: np.ndarray) -> float:
    sse = float(np.sum((y - yhat) ** 2))
    sst = float(np.sum((y - bench) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def evaluate_forecasts(fc: pd.DataFrame) -> dict[str, object]:
    model_cols = [
        c
        for c in fc.columns
        if not c.startswith("component_")
        and c
        not in {
            "date",
            "expiry",
            "truth_total_var",
            "truth_intra_var",
            "truth_overnight_var",
            "theta",
            "T",
            "n_sess",
            "nights",
            "train_n",
        }
    ]
    out: dict[str, object] = {
        "n": int(len(fc)),
        "models": {},
        "components": {},
        "by_year": {},
        "by_horizon": {},
    }

    def one(sub: pd.DataFrame, model: str) -> dict[str, float]:
        d = sub.dropna(subset=[model, "truth_total_var", "mean_rate"])
        yy = d["truth_total_var"].to_numpy(float)
        pp = d[model].to_numpy(float)
        bb = d["mean_rate"].to_numpy(float)
        if len(d) < 10:
            return {}
        rv_true = np.sqrt(yy / d["T"].to_numpy(float)) * 100.0
        rv_pred = np.sqrt(np.clip(pp, EPS, None) / d["T"].to_numpy(float)) * 100.0
        return {
            "n": float(len(d)),
            "qlike": qlike(yy, pp),
            "mse_var": float(np.mean((yy - pp) ** 2)),
            "oos_r2_vs_mean_rate": oos_r2(yy, pp, bb),
            "rmse_rv_vol_points": float(np.sqrt(np.mean((rv_true - rv_pred) ** 2))),
            "corr_var": float(np.corrcoef(yy, pp)[0, 1]) if np.std(pp) > 0 else np.nan,
            "mean_q": float(np.mean(pp / d["theta"].to_numpy(float))),
        }

    for model in model_cols:
        out["models"][model] = one(fc, model)

    for model in ("decomp_har_surface", "decomp_har_surface_ridge"):
        day_col = f"component_intra_{model}"
        night_col = f"component_overnight_{model}"
        if day_col not in fc or night_col not in fc:
            continue
        day = fc.dropna(subset=[day_col, "truth_intra_var"])
        night = fc[(fc["nights"] > 0)].dropna(subset=[night_col, "truth_overnight_var"])
        out["components"][model] = {
            "intraday_n": int(len(day)),
            "intraday_qlike": qlike(
                day["truth_intra_var"].to_numpy(float), day[day_col].to_numpy(float)
            )
            if len(day)
            else np.nan,
            "intraday_corr": float(np.corrcoef(day["truth_intra_var"], day[day_col])[0, 1])
            if len(day) > 2 and day[day_col].std() > 0
            else np.nan,
            "overnight_n": int(len(night)),
            "overnight_qlike": qlike(
                night["truth_overnight_var"].to_numpy(float), night[night_col].to_numpy(float)
            )
            if len(night)
            else np.nan,
            "overnight_corr": float(
                np.corrcoef(night["truth_overnight_var"], night[night_col])[0, 1]
            )
            if len(night) > 2 and night[night_col].std() > 0
            else np.nan,
            "overnight_mse": float(
                np.mean((night["truth_overnight_var"] - night[night_col]) ** 2)
            )
            if len(night)
            else np.nan,
        }
    for year, sub in fc.groupby(fc["date"].str.slice(0, 4)):
        out["by_year"][str(year)] = {m: one(sub, m) for m in model_cols}
    for n_sess, sub in fc.groupby("n_sess"):
        out["by_horizon"][str(int(n_sess))] = {m: one(sub, m) for m in model_cols}
    return out


def write_markdown(results: dict[str, object], path: Path) -> None:
    models = results["models"]
    ranked = sorted(
        ((k, v) for k, v in models.items() if isinstance(v, dict) and v),
        key=lambda kv: kv[1].get("qlike", np.inf),
    )
    lines = [
        "# RV forecast V2 horse race results",
        "",
        "Headline target: forward integrated realized variance **including overnight gaps**.",
        f"Historical eSSVI policy: `{HISTORICAL_ESSVI_POLICY}`.",
        "",
        "| rank | model | n | QLIKE | OOS R2 vs mean-rate | RV RMSE (vol pts) | corr(var) |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for rank, (name, v) in enumerate(ranked, 1):
        lines.append(
            f"| {rank} | {name} | {int(v['n'])} | {v['qlike']:.6f} | "
            f"{v['oos_r2_vs_mean_rate']:+.3f} | {v['rmse_rv_vol_points']:.3f} | "
            f"{v['corr_var']:+.3f} |"
        )
    lines += [
        "",
        "Selection rule: primary = lowest OOS QLIKE; secondary = OOS R2 and RV RMSE. "
        "No production coefficient changes are made by this script.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clock", default="10:00")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--fast", action="store_true", help="skip the nonlinear HGB contender")
    ap.add_argument("--exogenous", type=Path, default=None)
    args = ap.parse_args()

    panel = build_panel(args.clock, args.rebuild, args.exogenous)
    fc = walk_forward(panel, args.fast)
    results = evaluate_forecasts(fc)
    results["spec"] = {
        "seed": SEED,
        "clock": args.clock,
        "min_train": MIN_TRAIN,
        "purge": "train expiry strictly before forecast date; same rule inside ridge CV",
        "target": "integrated realized variance from origin to WEEK1 expiry including overnight gaps",
        "surface_policy": HISTORICAL_ESSVI_POLICY,
        "primary_loss": "QLIKE",
    }
    tag = args.clock.replace(":", "")
    fc.to_csv(f"rv_forecast_v2_oos_{tag}.csv", index=False)
    Path(f"rv_forecast_v2_results_{tag}.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    write_markdown(results, Path(f"RV_FORECAST_V2_RESULTS_{tag}.md"))
    print(Path(f"RV_FORECAST_V2_RESULTS_{tag}.md").read_text())


if __name__ == "__main__":
    main()
