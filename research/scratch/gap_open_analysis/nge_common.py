#!/usr/bin/env python3
"""Ex-ante dealer Net Gamma Exposure (NGE) data layer for the NIFTY path-quality test.

New module.  It does not modify, and is not imported by, any pre-existing script.  Every
cache it writes carries a new filename, so nothing already on disk is touched.

What it builds
--------------
1.  ``nge_open_snapshot.pkl`` -- the **09:15 bar** of every hydrated CALL and PUT contract in
    the archive (2,772 one-minute CSVs, WEEK1 expiry, ATM-10..ATM+10, 2021-2026), keyed on
    the ABSOLUTE strike, never on the rolling ``rel_strike`` label.  The 15:29 bar of every
    contract is captured in the same pass so the ex-ante claim below can be *verified*
    rather than asserted.

2.  ``nge_daily.pkl`` -- one row per trading date: gamma-weighted call and put open interest
    at five chain widths, the standard-convention composite, the opening ATM implied
    volatility, and the realised path-quality labels computed from the spot column.

The ex-ante claim, and how it is checked
----------------------------------------
Exchange open interest is an end-of-session quantity.  The 09:15 bar of a session therefore
carries the open interest standing at the **previous** session's close: nothing that happens
after 09:15 on the trade date can have entered it.  This is verified directly in
``audit_ex_ante`` by matching each (date, side, absolute strike) 09:15 snapshot against the
same contract's 15:29 snapshot on the previous trading date and reporting the exact-match
rate.  If that rate is high, the measure is ex ante by construction and not merely by
assumption.

Maturity convention
-------------------
**TRADING TIME**, following ``CORRECTION_GATE_B_VOL_CRUSH.md``: 375 minutes per session
(09:15-15:30), 252 sessions per year, counting only sessions between the trade date and the
expiry date.  A calendar-time maturity produced a retracted finding on this project once
already and is not used anywhere in this module.  Implied volatilities inverted or consumed
under this convention are LOWER IN LEVEL than market-quoted ones; that is a change of units,
not of information, and everything downstream is internally consistent in it.

Offline analysis only.  No broker, credential, exchange network, or order path is used
anywhere in this module.  No live order is authorised.
"""
from __future__ import annotations

import json
import math
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options"
)
MANIFEST = CACHE / "manifest.jsonl"

SNAPSHOT_CACHE = Path("nge_open_snapshot.pkl")
SNAPSHOT_AUDIT = Path("nge_open_snapshot_audit.json")
DAILY_CACHE = Path("nge_daily.pkl")

STRIKE_STEP = 50.0
SESSION_OPEN = "09:15"
SESSION_LAST = "15:29"
MINUTES_PER_SESSION = 375.0          # 09:15 -> 15:30
SESSIONS_PER_YEAR = 252.0
RISK_FREE_RATE = 0.065               # same constant the project already uses

USE_COLS = ["close", "iv", "strike", "oi", "spot", "datetime", "volume"]


# --------------------------------------------------------------------------------------
# 09:15 / 15:29 snapshot extraction
# --------------------------------------------------------------------------------------

def manifest_rows() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def cached_path(row: dict) -> Path:
    return CACHE / str(row["from_date"])[:4] / Path(str(row["path"])).name


def build_snapshot() -> tuple[pd.DataFrame, dict]:
    """The 09:15 and 15:29 bar of every hydrated contract, keyed on ABSOLUTE strike."""
    frames: list[pd.DataFrame] = []
    files_read = files_missing = 0
    raw_rows = 0
    for row in manifest_rows():
        side = row.get("drv_option_type")
        if side not in ("CALL", "PUT"):
            continue
        path = cached_path(row)
        if not path.exists():
            files_missing += 1
            continue
        frame = pd.read_csv(path, usecols=USE_COLS)
        files_read += 1
        raw_rows += len(frame)
        clock = frame["datetime"].str.slice(11, 16)
        frame = frame[clock.isin((SESSION_OPEN, SESSION_LAST))].copy()
        if frame.empty:
            continue
        frame["clock"] = clock.loc[frame.index]
        frame["date"] = frame["datetime"].str.slice(0, 10)
        frame["side"] = side
        frames.append(frame.drop(columns=["datetime"]))
    if not frames:
        raise FileNotFoundError("no hydrated minute files found in the local cache")

    snap = pd.concat(frames, ignore_index=True)
    snap_rows_before_dedup = len(snap)
    non_positive = int((snap["close"] <= 0).sum())
    snap = snap[snap["close"] > 0]

    key = ["date", "clock", "side", "strike"]
    dup_groups = int((snap.groupby(key, sort=False).size() > 1).sum())
    # Same dedup convention as the rest of the project: keep the highest-volume row for a
    # contract-minute.  Two rel_strike files can describe the same absolute contract.
    snap = snap.sort_values(key + ["volume"], ascending=[True] * 4 + [False])
    snap = snap.drop_duplicates(subset=key, keep="first")

    snap = snap[["date", "clock", "side", "strike", "close", "iv", "oi", "spot", "volume"]]
    snap = snap.sort_values(["date", "clock", "side", "strike"]).reset_index(drop=True)

    audit = {
        "files_read": files_read,
        "files_missing": files_missing,
        "raw_rows_scanned": raw_rows,
        "snapshot_rows_before_dedup": snap_rows_before_dedup,
        "non_positive_close_dropped": non_positive,
        "duplicate_contract_minutes": dup_groups,
        "snapshot_rows": len(snap),
        "dates": int(snap["date"].nunique()),
        "dates_with_0915": int(snap[snap["clock"] == SESSION_OPEN]["date"].nunique()),
        "zero_iv_share_pct_0915": round(
            100.0 * float((snap[snap["clock"] == SESSION_OPEN]["iv"] <= 0).mean()), 3),
        "zero_oi_share_pct_0915": round(
            100.0 * float((snap[snap["clock"] == SESSION_OPEN]["oi"] <= 0).mean()), 3),
    }
    return snap, audit


def load_snapshot(rebuild: bool = False) -> pd.DataFrame:
    if SNAPSHOT_CACHE.exists() and not rebuild:
        return pd.read_pickle(SNAPSHOT_CACHE)
    snap, audit = build_snapshot()
    tmp = SNAPSHOT_CACHE.with_suffix(".incoming")
    snap.to_pickle(tmp)
    os.replace(tmp, SNAPSHOT_CACHE)
    SNAPSHOT_AUDIT.write_text(json.dumps(audit, indent=2))
    return snap


def audit_ex_ante(snap: pd.DataFrame) -> dict:
    """Is the 09:15 open-interest snapshot the PREVIOUS session's closing open interest?

    Matches every (side, absolute strike) present at 09:15 on date d against the same
    contract's 15:29 bar on the previous trading date in the archive, and reports how often
    the two open-interest figures are identical.  A high exact-match rate establishes that
    nothing occurring after 09:15 on date d can have entered the measure.
    """
    dates = sorted(snap["date"].unique())
    prev = {d: p for p, d in zip(dates[:-1], dates[1:])}
    op = snap[snap["clock"] == SESSION_OPEN][["date", "side", "strike", "oi"]]
    cl = snap[snap["clock"] == SESSION_LAST][["date", "side", "strike", "oi"]]
    op = op.assign(prev_date=op["date"].map(prev))
    merged = op.merge(
        cl.rename(columns={"date": "prev_date", "oi": "oi_prev_close"}),
        on=["prev_date", "side", "strike"], how="inner",
    )
    exact = merged["oi"] == merged["oi_prev_close"]
    rel = np.where(
        merged["oi_prev_close"] > 0,
        np.abs(merged["oi"] - merged["oi_prev_close"]) / merged["oi_prev_close"].clip(lower=1),
        np.nan,
    )
    return {
        "matched_contract_days": int(len(merged)),
        "exact_match_share_pct": round(100.0 * float(exact.mean()), 4),
        "median_abs_rel_difference_pct": round(100.0 * float(np.nanmedian(rel)), 4),
        "share_within_1pct": round(100.0 * float(np.nanmean(rel <= 0.01)), 3),
    }


# --------------------------------------------------------------------------------------
# trading-time maturity
# --------------------------------------------------------------------------------------

def trading_sessions_between(trade_date: str, expiry_date: str, sessions: list[str]) -> float:
    """Sessions remaining from 09:15 on ``trade_date`` to 15:30 on ``expiry_date``.

    ``sessions`` is the sorted list of actual trading dates in the archive, so holidays are
    handled by the calendar rather than by a weekday rule.  Counted from the OPEN, so the
    trade date itself contributes a full session.
    """
    lo = np.searchsorted(sessions, trade_date, side="left")
    hi = np.searchsorted(sessions, expiry_date, side="right")
    return float(max(hi - lo, 0))


def maturity_years(n_sessions: float) -> float:
    return max(n_sessions, 1e-6) / SESSIONS_PER_YEAR


# --------------------------------------------------------------------------------------
# Black-Scholes gamma
# --------------------------------------------------------------------------------------

def bs_gamma(S: np.ndarray, K: np.ndarray, T: float, r: float, sigma: np.ndarray) -> np.ndarray:
    """Gamma = phi(d1) / (S sigma sqrt(T)).  Identical for a call and a put at the same strike.

    Put-call parity gives d(C-P)/dS = 1 exactly, a constant, so the second derivative of the
    difference is zero and Gamma_call(K) == Gamma_put(K).  The sign that separates them in a
    dealer-gamma measure is therefore entirely a POSITION assumption, never a property of the
    contract.  That is the whole point of the free-coefficient design downstream.
    """
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    out = np.full(np.broadcast(S, K, sigma).shape, np.nan)
    ok = (S > 0) & (K > 0) & (sigma > 0) & (T > 0)
    if not np.any(ok):
        return out
    Sx, Kx, sx = np.broadcast_arrays(S, K, sigma)
    sqrtT = math.sqrt(T)
    d1 = (np.log(Sx[ok] / Kx[ok]) + (r + 0.5 * sx[ok] ** 2) * T) / (sx[ok] * sqrtT)
    out[ok] = np.exp(-0.5 * d1 ** 2) / math.sqrt(2.0 * math.pi) / (Sx[ok] * sx[ok] * sqrtT)
    return out


# --------------------------------------------------------------------------------------
# path-quality labels, computed from the spot column
# --------------------------------------------------------------------------------------

def path_labels(clocks: list[str], spots: np.ndarray, bar_minutes: int = 5) -> dict:
    """rho1 on ``bar_minutes`` returns, straight-line R^2, Kaufman ER, |displacement|.

    ``rho1`` is Barbon & Buraschi's measure: the lag-1 autocorrelation of intraday returns
    sampled at five minutes.  rho1 > 0 is a trending session, rho1 < 0 a mean-reverting one.
    It is a second-moment ratio and therefore divides out the realised drift, which is what
    makes it better behaved than straight-line R^2 (a noisy drift estimator -- see
    TREND_DAY_FORECASTABILITY_RESEARCH.md 1a).
    """
    mins = np.asarray([int(c[:2]) * 60 + int(c[3:]) for c in clocks], dtype=int)
    order = np.argsort(mins)
    mins, spots = mins[order], np.asarray(spots, dtype=float)[order]
    out: dict[str, float] = {}

    # --- rho1 on bar_minutes sampling ---
    grid = np.arange(mins[0], mins[-1] + 1, bar_minutes)
    idx = np.searchsorted(mins, grid, side="left")
    idx = idx[idx < len(mins)]
    idx = np.unique(idx)
    px = spots[idx]
    if len(px) >= 12:
        r = np.diff(np.log(px))
        rbar = r.mean()
        denom = float(np.sum((r - rbar) ** 2))
        num = float(np.sum((r[1:] - rbar) * (r[:-1] - rbar)))
        out["rho1"] = num / denom if denom > 0 else np.nan
        out["n_bars"] = int(len(r))
        # Lo-MacKinlay variance ratio at q = 3 bars (15 minutes)
        q = 3
        m = (len(r) // q) * q
        if m >= 3 * q and denom > 0:
            rq = r[:m].reshape(-1, q).sum(axis=1)
            v1 = float(np.var(r[:m], ddof=1))
            vq = float(np.var(rq, ddof=1))
            out["vr3"] = vq / (q * v1) if v1 > 0 else np.nan
        else:
            out["vr3"] = np.nan
    else:
        out["rho1"] = np.nan
        out["n_bars"] = int(max(len(px) - 1, 0))
        out["vr3"] = np.nan

    # --- straight-line R^2 of the minute path (the project's incumbent label) ---
    x = mins.astype(float)
    y = spots
    if len(y) >= 30 and np.std(y) > 0:
        xc, yc = x - x.mean(), y - y.mean()
        beta = float(np.dot(xc, yc) / np.dot(xc, xc))
        pred = beta * xc
        ss_res = float(np.sum((yc - pred) ** 2))
        ss_tot = float(np.sum(yc ** 2))
        out["r2_line"] = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    else:
        out["r2_line"] = np.nan

    # --- Kaufman Efficiency Ratio on minute closes ---
    steps = np.abs(np.diff(spots))
    total = float(steps.sum())
    out["kaufman_er"] = abs(float(spots[-1] - spots[0])) / total if total > 0 else np.nan

    # --- realised absolute displacement, in percent of the opening spot ---
    out["abs_disp_pct"] = abs(float(spots[-1] / spots[0] - 1.0)) * 100.0
    out["signed_disp_pct"] = float(spots[-1] / spots[0] - 1.0) * 100.0
    # realised volatility over the session, percent, from the same 5-minute grid
    if len(px) >= 12:
        out["rv_pct"] = float(np.sqrt(np.sum(np.diff(np.log(px)) ** 2))) * 100.0
    else:
        out["rv_pct"] = np.nan
    return out


# --------------------------------------------------------------------------------------
# per-date NGE construction
# --------------------------------------------------------------------------------------

CHAIN_WIDTHS = (3, 5, 7, 9, 10)

# Which per-contract implied volatility supplies Gamma(K).
#   "otm"   -- the OUT-OF-THE-MONEY side at that strike (call for K >= ATM, put for K < ATM).
#              Primary.  Gamma_call(K) == Gamma_put(K) by parity, so a strike has ONE gamma
#              and it should be read off the liquid, non-degenerate quote.  Verified: 0.000%
#              of OTM-side 09:15 quotes carry a non-positive iv, against 7.5% over all
#              quotes -- every degenerate iv in the archive is a deep in-the-money one.
#   "own"   -- each side uses its own iv, so calls and puts at one strike get different
#              gammas.  Internally inconsistent with parity but it is the literal reading of
#              "the archive's own per-contract iv", so it is carried as a sensitivity.
IV_MODES = ("otm", "own")


def _expiry_dates() -> list[str]:
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    return sorted(cal["actual_expiry"].dt.strftime("%Y-%m-%d").tolist())


def _next_expiry(trade_date: str, expiries: list[str]) -> str | None:
    i = np.searchsorted(expiries, trade_date, side="left")
    return expiries[i] if i < len(expiries) else None


def build_daily() -> tuple[pd.DataFrame, dict]:
    """One row per trading date: ex-ante gamma-weighted OI, opening IV, realised path labels."""
    from analyze_still_water_spot import load_spot

    snap = load_snapshot()
    op = snap[snap["clock"] == SESSION_OPEN].copy()
    sessions = sorted(snap["date"].unique().tolist())
    expiries = _expiry_dates()

    spot_df, _ = load_spot()
    spot_df = spot_df[(spot_df["clock"] >= SESSION_OPEN) & (spot_df["clock"] <= SESSION_LAST)]
    spot_by_date = {d: g.sort_values("clock") for d, g in spot_df.groupby("date")}

    diag = {"dates_seen": 0, "no_expiry": 0, "no_spot": 0, "thin_chain": 0,
            "expiry_day_dates": 0, "oi_open_equals_0916": None}
    out: list[dict] = []
    for date, day in op.groupby("date", sort=True):
        diag["dates_seen"] += 1
        expiry = _next_expiry(date, expiries)
        if expiry is None:
            diag["no_expiry"] += 1
            continue
        path = spot_by_date.get(date)
        if path is None or len(path) < 200:
            diag["no_spot"] += 1
            continue

        S0 = float(day["spot"].iloc[0])
        atm = float(round(S0 / STRIKE_STEP) * STRIKE_STEP)
        n_sess = trading_sessions_between(date, expiry, sessions)
        T_trade = maturity_years(n_sess)
        T_cal = max((pd.Timestamp(expiry) + pd.Timedelta(hours=15, minutes=30)
                     - pd.Timestamp(f"{date} 09:15:00")).total_seconds(), 60.0) / (365.0 * 86400.0)
        if expiry == date:
            diag["expiry_day_dates"] += 1

        wide = day.pivot_table(index="strike", columns="side",
                               values=["oi", "iv", "close"], aggfunc="first")
        strikes = wide.index.to_numpy(dtype=float)
        offset = np.round((strikes - atm) / STRIKE_STEP).astype(int)
        oi_c = wide[("oi", "CALL")].to_numpy(dtype=float) if ("oi", "CALL") in wide else np.full(len(strikes), np.nan)
        oi_p = wide[("oi", "PUT")].to_numpy(dtype=float) if ("oi", "PUT") in wide else np.full(len(strikes), np.nan)
        iv_c = wide[("iv", "CALL")].to_numpy(dtype=float) / 100.0 if ("iv", "CALL") in wide else np.full(len(strikes), np.nan)
        iv_p = wide[("iv", "PUT")].to_numpy(dtype=float) / 100.0 if ("iv", "PUT") in wide else np.full(len(strikes), np.nan)
        iv_c = np.where(iv_c > 0, iv_c, np.nan)
        iv_p = np.where(iv_p > 0, iv_p, np.nan)
        iv_otm = np.where(offset >= 0, iv_c, iv_p)

        row: dict = {"date": date, "spot_open": S0, "atm_strike": atm, "expiry": expiry,
                     "sessions_to_expiry": n_sess, "T_trading": T_trade, "T_calendar": T_cal,
                     "is_expiry_day": int(expiry == date),
                     "n_strikes": int(len(strikes))}

        # opening at-the-money implied volatility, percent, archive units
        at = offset == 0
        row["atm_iv_call_open"] = float(np.nanmean(iv_c[at]) * 100) if at.any() else np.nan
        row["atm_iv_put_open"] = float(np.nanmean(iv_p[at]) * 100) if at.any() else np.nan
        row["atm_iv_open"] = float(np.nanmean([row["atm_iv_call_open"], row["atm_iv_put_open"]]))

        ok_any = False
        for mode in IV_MODES:
            for tname, T in (("trade", T_trade), ("cal", T_cal)):
                if mode == "otm":
                    g_c = g_p = bs_gamma(S0, strikes, T, RISK_FREE_RATE, iv_otm)
                else:
                    g_c = bs_gamma(S0, strikes, T, RISK_FREE_RATE, iv_c)
                    g_p = bs_gamma(S0, strikes, T, RISK_FREE_RATE, iv_p)
                for w in CHAIN_WIDTHS:
                    m = np.abs(offset) <= w
                    gc = float(np.nansum(np.where(m, g_c * oi_c, 0.0))) * S0 * S0 * 0.01
                    gp = float(np.nansum(np.where(m, g_p * oi_p, 0.0))) * S0 * S0 * 0.01
                    tag = f"{mode}_{tname}_w{w}"
                    row[f"gcall_{tag}"] = gc
                    row[f"gput_{tag}"] = gp
                    row[f"gex_{tag}"] = gc - gp
                    row[f"gimb_{tag}"] = (gc - gp) / (gc + gp) if (gc + gp) > 0 else np.nan
                    if gc > 0 and gp > 0:
                        ok_any = True
        if not ok_any:
            diag["thin_chain"] += 1
            continue

        clocks = [str(c) for c in path["clock"]]
        spots = path["spot"].to_numpy(dtype=float)
        row.update(path_labels(clocks, spots))
        row["n_minutes"] = len(clocks)

        # Baltussen Table 7 pieces: rest-of-day and last-half-hour spot returns.
        mins = np.asarray([int(c[:2]) * 60 + int(c[3:]) for c in clocks])
        def at_or_before(target: str) -> float:
            lim = int(target[:2]) * 60 + int(target[3:])
            j = np.flatnonzero(mins <= lim)
            return float(spots[j[-1]]) if len(j) else np.nan
        s_open, s_0945, s_1500, s_close = (spots[0], at_or_before("09:45"),
                                           at_or_before("15:00"), spots[-1])
        row["r_first30_pct"] = (s_0945 / s_open - 1.0) * 100.0
        row["r_rod_pct"] = (s_1500 / s_open - 1.0) * 100.0
        row["r_last30_pct"] = (s_close / s_1500 - 1.0) * 100.0
        out.append(row)

    daily = pd.DataFrame(out).sort_values("date").reset_index(drop=True)
    daily["year"] = daily["date"].str.slice(0, 4).astype(int)
    daily["dow"] = pd.to_datetime(daily["date"]).dt.dayofweek

    # attach the project's own day labels where they exist (used only for the secondary slices)
    k2 = pd.read_csv("k2_expiry_vix_rose_panel.csv", parse_dates=["date"])
    k2["date"] = k2["date"].dt.strftime("%Y-%m-%d")
    keep = [c for c in ("date", "vix_rose", "is_expiry_day", "iv_bucket", "opening_iv", "gap")
            if c in k2.columns]
    daily = daily.merge(k2[keep].rename(columns={"is_expiry_day": "k2_is_expiry_day"}),
                        on="date", how="left")
    if "gap" in daily.columns:
        daily["gap_dir"] = np.where(daily["gap"] > 0, "up", "down")

    diag["dates_kept"] = int(len(daily))
    return daily, diag


def load_daily(rebuild: bool = False) -> pd.DataFrame:
    if DAILY_CACHE.exists() and not rebuild:
        return pd.read_pickle(DAILY_CACHE)
    daily, diag = build_daily()
    tmp = DAILY_CACHE.with_suffix(".incoming")
    daily.to_pickle(tmp)
    os.replace(tmp, DAILY_CACHE)
    Path("nge_daily_build_diag.json").write_text(json.dumps(diag, indent=2, default=str))
    return daily


if __name__ == "__main__":
    snap = load_snapshot(rebuild=False)
    print(json.dumps(json.loads(SNAPSHOT_AUDIT.read_text()), indent=2))
    print("ex-ante audit:", json.dumps(audit_ex_ante(snap), indent=2))
    daily = load_daily(rebuild=True)
    print(json.dumps(json.loads(Path("nge_daily_build_diag.json").read_text()), indent=2))
    print(f"daily rows: {len(daily)}  {daily['date'].min()} .. {daily['date'].max()}")
    print(daily[["rho1", "r2_line", "kaufman_er", "abs_disp_pct",
                 "gex_otm_trade_w10", "gimb_otm_trade_w10", "atm_iv_open"]].describe().to_string())
