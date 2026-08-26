#!/usr/bin/env python3
"""Non-price-path features (volume, open interest, true intraminute OHLC) and the outcome
targets they are tested against, for the Gate-B gap-fill population.

New module.  It does not modify, and is not imported by, any pre-existing script.

Design commitments that the report depends on
---------------------------------------------
**Every feature is computed from bars timestamped at or before its stated decision minute.**
Two decision families are built and they are never mixed:

*   ``entry`` -- decision minute = the gap-fill minute itself.  Features see only
    ``[09:15, entry]``.  This family can only ever produce an **entry filter**: take the
    trade or stand aside.
*   ``persist:W`` for W in {15, 30, 45, 60} -- decision minute = entry + W.  Features see
    ``[09:15, entry+W]``, with the flow features measured on the post-entry sub-window
    ``[entry, entry+W]``.  This family can only ever produce a **stay-in / cut rule** on a
    position that is already open.

**Strike identity.**  Everything at "the entry strike" is looked up by the ABSOLUTE strike
value fixed at the fill minute, exactly as ``gate_b_common.py`` does.  The archive's
``rel_strike`` label rolls intraday and is never used.

**The endogeneity that cannot be designed away.**  Volume and open interest AT a given strike
depend on where spot went, because a strike attracts flow partly because spot came to it.
For the ``persist`` family this is first-order: a feature measured on ``[entry, entry+W]``
is contaminated by the spot path over that same window, and the spot path over that window
is mechanically related to the spot path afterwards through nothing more than continuity.
Features are therefore graded, and the grade travels with every number in the report:

*   ``exogenous``   -- fixed before the session's intraday path exists (09:15 open-interest
    snapshots, and ratios of them).  Nothing about the intraday path can have caused these.
*   ``pre-entry``   -- uses only bars up to the fill minute.  Path-dependent only through the
    pre-entry path, which is the gate's own definition, so it is a legitimate entry filter.
*   ``endogenous``  -- uses post-entry bars.  Reported as an ASSOCIATION, never as a
    predictor, and never used to claim a causal or forecasting relationship.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SESSION_OPEN = "09:15"
SESSION_END = "15:29"

PERSIST_WINDOWS = (15, 30, 45, 60)
MIN_REMAINING_MINUTES = 30          # a target needs at least this much session left

# feature name -> (grade, human description)
FEATURE_GRADE: dict[str, tuple[str, str]] = {
    # --- A. trend / choppiness on TRUE intraminute OHLC -----------------------------
    "chop_call":       ("pre-entry/endogenous", "Choppiness Index, entry-strike CALL true OHLC"),
    "adx_call":        ("pre-entry/endogenous", "ADX(7), entry-strike CALL true OHLC"),
    "dmi_call":        ("pre-entry/endogenous", "+DI - -DI, entry-strike CALL true OHLC"),
    "chop_spotproxy":  ("pre-entry/endogenous", "Choppiness Index, spot close-only proxy"),
    "adx_spotproxy":   ("pre-entry/endogenous", "ADX(7), spot close-only proxy"),
    # --- B. volume ------------------------------------------------------------------
    "vol_level":       ("pre-entry/endogenous", "log total volume, entry-strike CALL, window"),
    "vol_rel":         ("pre-entry/endogenous", "window volume/min ÷ same contract's own earlier volume/min"),
    "vol_trend":       ("pre-entry/endogenous", "OLS slope of per-minute log volume across the window"),
    "vol_conc":        ("pre-entry/endogenous", "Herfindahl of per-minute volume within the window"),
    "vol_share":       ("pre-entry/endogenous", "entry-strike CALL volume ÷ whole CALL chain volume, window"),
    "chain_vol":       ("pre-entry/endogenous", "log total CALL+PUT chain volume in the window"),
    # --- C. open interest -----------------------------------------------------------
    "oi_open":         ("exogenous", "entry-strike CALL open interest at 09:15"),
    "oi_level":        ("pre-entry/endogenous", "log entry-strike CALL open interest at the decision minute"),
    "oi_chg_open":     ("pre-entry/endogenous", "entry-strike CALL OI change since 09:15, %"),
    "oi_trend":        ("pre-entry/endogenous", "OLS slope of entry-strike CALL OI across the window, %/min"),
    # --- D. put vs call at matched strikes -------------------------------------------
    "pcr_oi_open":     ("exogenous", "PUT/CALL open interest at the entry strike, 09:15"),
    "pcr_oi":          ("pre-entry/endogenous", "PUT/CALL open interest at the entry strike, decision minute"),
    "pcr_vol":         ("pre-entry/endogenous", "PUT/CALL volume at the entry strike over the window"),
    "pcr_oi_chain":    ("pre-entry/endogenous", "PUT/CALL open interest, whole chain, decision minute"),
    "pcr_vol_chain":   ("pre-entry/endogenous", "PUT/CALL volume, whole chain, over the window"),
}

TREND_FEATURES = ("chop_call", "adx_call", "dmi_call", "chop_spotproxy", "adx_spotproxy")
VOLUME_FEATURES = ("vol_level", "vol_rel", "vol_trend", "vol_conc", "vol_share", "chain_vol")
OI_FEATURES = ("oi_open", "oi_level", "oi_chg_open", "oi_trend")
PCR_FEATURES = ("pcr_oi_open", "pcr_oi", "pcr_vol", "pcr_oi_chain", "pcr_vol_chain")
ALL_FEATURES = TREND_FEATURES + VOLUME_FEATURES + OI_FEATURES + PCR_FEATURES

TARGETS = ("r2_rest", "eff_rest", "dir_rest", "pnl_rest")
TARGET_LABEL = {
    "r2_rest":  "straight-line R² of spot, decision minute -> 15:29 (trendiness)",
    "eff_rest": "signed directional efficiency of spot, decision minute -> 15:29",
    "dir_rest": "spot return, decision minute -> 15:29, %",
    "pnl_rest": "real strike-tracked CALL return, decision minute -> 15:29, %",
}


# ----------------------------------------------------------------------------- indicators
def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Wilder true range.  ``tr[0]`` is the bar's own range (no prior close exists)."""
    tr = np.empty(len(high))
    tr[0] = high[0] - low[0]
    if len(high) > 1:
        pc = close[:-1]
        tr[1:] = np.maximum.reduce([high[1:] - low[1:],
                                    np.abs(high[1:] - pc),
                                    np.abs(low[1:] - pc)])
    return tr


def choppiness_index(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     n: int = 14) -> float:
    """E.W. Dreiss Choppiness Index over the LAST ``n`` bars.

    CHOP = 100 · log10( Σ TR / (max High − min Low) ) / log10(n).
    ~100 = maximal chop (path walked far, went nowhere); ~0 = one clean directional move.
    """
    if len(high) < max(n, 8):
        n = len(high)
    if n < 8:
        return np.nan
    h, l, c = high[-n:], low[-n:], close[-n:]
    # TR needs the bar before the window to be honest about the first gap.
    idx0 = len(high) - n
    if idx0 >= 1:
        tr = true_range(np.concatenate([[high[idx0 - 1]], h]),
                        np.concatenate([[low[idx0 - 1]], l]),
                        np.concatenate([[close[idx0 - 1]], c]))[1:]
    else:
        tr = true_range(h, l, c)
    rng = float(h.max() - l.min())
    s = float(tr.sum())
    if rng <= 0 or s <= 0:
        return np.nan
    return float(100.0 * np.log10(s / rng) / np.log10(n))


def wilder_smooth(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's recursive smoothing, seeded on the first ``n`` observations."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    acc = float(x[:n].sum())
    out[n - 1] = acc
    for i in range(n, len(x)):
        acc = acc - acc / n + float(x[i])
        out[i] = acc
    return out


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        n: int = 7) -> tuple[float, float]:
    """Wilder ADX and the raw directional spread (+DI − −DI), both at the last bar.

    ADX needs 2n bars to have a smoothed DX at all; NaN is returned below that.
    """
    m = len(high)
    if m < 2 * n + 1:
        return np.nan, np.nan
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)[1:]
    atr = wilder_smooth(tr, n)
    sp = wilder_smooth(plus_dm, n)
    sm = wilder_smooth(minus_dm, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100.0 * sp / atr
        mdi = 100.0 * sm / atr
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = dx[np.isfinite(dx)]
    if len(dx) < n:
        return np.nan, np.nan
    a = wilder_smooth(dx, n)[-1] / n
    spread = float(pdi[-1] - mdi[-1]) if np.isfinite(pdi[-1]) and np.isfinite(mdi[-1]) else np.nan
    return float(a), spread


def ols_slope(y: np.ndarray) -> float:
    n = len(y)
    if n < 5:
        return np.nan
    x = np.arange(n, dtype=float)
    xm, ym = x.mean(), y.mean()
    den = float(((x - xm) ** 2).sum())
    if den <= 0:
        return np.nan
    return float(((x - xm) * (y - ym)).sum() / den)


def straight_line_r2(y: np.ndarray) -> float:
    """R² of an OLS fit of ``y`` on its own index -- how close to a straight line the path is."""
    n = len(y)
    if n < MIN_REMAINING_MINUTES:
        return np.nan
    x = np.arange(n, dtype=float)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0:
        return np.nan
    b = ols_slope(y)
    if not np.isfinite(b):
        return np.nan
    a = float(y.mean() - b * x.mean())
    resid = y - (a + b * x)
    return float(1.0 - float((resid ** 2).sum()) / ss_tot)


def directional_efficiency(y: np.ndarray) -> float:
    if len(y) < MIN_REMAINING_MINUTES:
        return np.nan
    path = float(np.abs(np.diff(y)).sum())
    if path <= 0:
        return np.nan
    return float((y[-1] - y[0]) / path)


# --------------------------------------------------------------------------- panel build
def _series_for(day: pd.DataFrame, side: str, strike: float) -> pd.DataFrame:
    s = day[(day["side"] == side) & (day["strike"] == strike)]
    return s.sort_values("minutes")


def _win(frame: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    return frame[(frame["minutes"] >= lo) & (frame["minutes"] <= hi)]


def build_panel(paths: list[dict], quotes: pd.DataFrame) -> pd.DataFrame:
    """One row per (fire, decision point) with every feature and every target."""
    by_date = {d: g for d, g in quotes.groupby("date", sort=False)}
    open_min = int(SESSION_OPEN[:2]) * 60 + int(SESSION_OPEN[3:])
    rows: list[dict] = []

    for p in paths:
        day = by_date.get(p["date"])
        if day is None:
            continue
        K = float(p["K"])
        call = _series_for(day, "CALL", K)
        put = _series_for(day, "PUT", K)
        chain_c = day[day["side"] == "CALL"]
        chain_p = day[day["side"] == "PUT"]

        entry_min = int(p["entry_minute"])
        spots = np.asarray(p["spots"], dtype=float)
        real = np.asarray(p["real_prices"], dtype=float)
        elapsed = np.asarray(p["elapsed"], dtype=int)

        # OI at the session open for the entry strike -- the one fully exogenous quantity.
        c_open = call[call["minutes"] <= open_min]
        pu_open = put[put["minutes"] <= open_min]
        oi_open_c = float(c_open["oi"].iloc[-1]) if len(c_open) else np.nan
        oi_open_p = float(pu_open["oi"].iloc[-1]) if len(pu_open) else np.nan

        decisions: list[tuple[str, int, int, int]] = [("entry", 0, entry_min, open_min)]
        for W in PERSIST_WINDOWS:
            idx = np.flatnonzero(elapsed <= W)
            if len(idx) == 0:
                continue
            di = int(idx[-1])
            decisions.append((f"persist:{W}", di, entry_min + int(elapsed[di]), entry_min))

        for name, di, dmin, flow_lo in decisions:
            rest_spot = spots[di:]
            n_rest = len(rest_spot)
            if n_rest < MIN_REMAINING_MINUTES:
                continue

            row: dict = {
                "date": p["date"], "decision": name, "decision_minute": dmin,
                "entry_clock": p["entry_clock"], "entry_minute": entry_min,
                "vix_rose": int(p["vix_rose"]), "iv_bucket": str(p["iv_bucket"]),
                "is_gate_b": int(p["is_gate_b"]), "K": K,
                "minutes_remaining": int(n_rest - 1),
                "held_minutes_if_persist": int(elapsed[di]),
            }

            # ---------------- targets ----------------
            row["r2_rest"] = straight_line_r2(rest_spot)
            row["eff_rest"] = directional_efficiency(rest_spot)
            row["dir_rest"] = float((rest_spot[-1] / rest_spot[0] - 1.0) * 100.0)
            px0 = real[di]
            fin = np.flatnonzero(np.isfinite(real[di:]))
            row["pnl_rest"] = (
                float((real[di:][fin[-1]] / px0 - 1.0) * 100.0)
                if np.isfinite(px0) and px0 > 0 and len(fin) else np.nan
            )
            # entry -> decision minute, needed to price a "cut here" branch of a persist rule
            row["pnl_todate"] = (
                float((px0 / real[0] - 1.0) * 100.0)
                if np.isfinite(px0) and np.isfinite(real[0]) and real[0] > 0 else np.nan
            )
            row["pnl_full"] = (
                float((real[np.flatnonzero(np.isfinite(real))[-1]] / real[0] - 1.0) * 100.0)
                if np.isfinite(real[0]) and real[0] > 0 else np.nan
            )
            row["spot_todate"] = float((spots[di] / spots[0] - 1.0) * 100.0)

            # ---------------- A. trend / chop on TRUE OHLC ----------------
            cw = _win(call, open_min, dmin)
            if len(cw) >= 8:
                h = cw["high"].to_numpy(dtype=float)
                l = cw["low"].to_numpy(dtype=float)
                c = cw["close"].to_numpy(dtype=float)
                row["chop_call"] = choppiness_index(h, l, c, n=14)
                a, sp = adx(h, l, c, n=7)
                row["adx_call"] = a
                row["dmi_call"] = sp
            else:
                row["chop_call"] = row["adx_call"] = row["dmi_call"] = np.nan

            # spot close-only proxy: high = low = close, i.e. what earlier work used
            sw = spots[: di + 1] if name == "entry" else None
            if name == "entry":
                # pre-entry spot is not in ``spots`` (which starts at entry); rebuild from
                # the CALL frame's own spot column, which is the same one-minute snapshot.
                sp_frame = _win(call, open_min, dmin)["spot"].to_numpy(dtype=float)
            else:
                sp_frame = np.concatenate([
                    _win(call, open_min, entry_min)["spot"].to_numpy(dtype=float)[:-1],
                    spots[: di + 1],
                ])
            if len(sp_frame) >= 8:
                row["chop_spotproxy"] = choppiness_index(sp_frame, sp_frame, sp_frame, n=14)
                a2, _ = adx(sp_frame, sp_frame, sp_frame, n=7)
                row["adx_spotproxy"] = a2
            else:
                row["chop_spotproxy"] = row["adx_spotproxy"] = np.nan

            # ---------------- B. volume ----------------
            fw = _win(call, flow_lo, dmin)          # flow window
            pw = _win(put, flow_lo, dmin)
            prior = _win(call, open_min, max(flow_lo - 1, open_min))
            v = fw["volume"].to_numpy(dtype=float)
            nmin = max(len(v), 1)
            tot_v = float(v.sum())
            row["vol_level"] = float(np.log1p(tot_v))
            prior_v = prior["volume"].to_numpy(dtype=float)
            if name == "entry":
                # own-norm for an entry filter: last 15 minutes against everything before it
                recent = _win(call, max(dmin - 14, open_min), dmin)["volume"].to_numpy(float)
                base = _win(call, open_min, max(dmin - 15, open_min))["volume"].to_numpy(float)
                row["vol_rel"] = (
                    float(recent.mean() / base.mean())
                    if len(recent) and len(base) and base.mean() > 0 else np.nan
                )
            else:
                row["vol_rel"] = (
                    float((tot_v / nmin) / prior_v.mean())
                    if len(prior_v) and prior_v.mean() > 0 else np.nan
                )
            row["vol_trend"] = ols_slope(np.log1p(v)) if len(v) >= 5 else np.nan
            row["vol_conc"] = float(((v / tot_v) ** 2).sum()) if tot_v > 0 else np.nan
            chain_w = _win(chain_c, flow_lo, dmin)
            chain_tot = float(chain_w["volume"].sum())
            row["vol_share"] = float(tot_v / chain_tot) if chain_tot > 0 else np.nan
            chain_pw = _win(chain_p, flow_lo, dmin)
            both = chain_tot + float(chain_pw["volume"].sum())
            row["chain_vol"] = float(np.log1p(both))

            # ---------------- C. open interest ----------------
            row["oi_open"] = float(np.log1p(oi_open_c)) if np.isfinite(oi_open_c) else np.nan
            cd = _win(call, open_min, dmin)
            oi_now = float(cd["oi"].iloc[-1]) if len(cd) else np.nan
            row["oi_level"] = float(np.log1p(oi_now)) if np.isfinite(oi_now) else np.nan
            row["oi_chg_open"] = (
                float((oi_now / oi_open_c - 1.0) * 100.0)
                if np.isfinite(oi_now) and np.isfinite(oi_open_c) and oi_open_c > 0 else np.nan
            )
            oi_w = fw["oi"].to_numpy(dtype=float)
            row["oi_trend"] = (
                float(ols_slope(oi_w) / oi_w.mean() * 100.0)
                if len(oi_w) >= 5 and oi_w.mean() > 0 else np.nan
            )

            # ---------------- D. put vs call at matched strikes ----------------
            row["pcr_oi_open"] = (
                float(oi_open_p / oi_open_c)
                if np.isfinite(oi_open_p) and np.isfinite(oi_open_c) and oi_open_c > 0 else np.nan
            )
            pd_ = _win(put, open_min, dmin)
            oi_now_p = float(pd_["oi"].iloc[-1]) if len(pd_) else np.nan
            row["pcr_oi"] = (
                float(oi_now_p / oi_now)
                if np.isfinite(oi_now_p) and np.isfinite(oi_now) and oi_now > 0 else np.nan
            )
            pv = float(pw["volume"].sum())
            row["pcr_vol"] = float(pv / tot_v) if tot_v > 0 else np.nan
            ci = _win(chain_c, open_min, dmin)
            pi = _win(chain_p, open_min, dmin)
            ci_oi = ci.sort_values("minutes").groupby("strike")["oi"].last().sum()
            pi_oi = pi.sort_values("minutes").groupby("strike")["oi"].last().sum()
            row["pcr_oi_chain"] = float(pi_oi / ci_oi) if ci_oi > 0 else np.nan
            cvol = float(chain_w["volume"].sum())
            row["pcr_vol_chain"] = (
                float(float(chain_pw["volume"].sum()) / cvol) if cvol > 0 else np.nan
            )

            rows.append(row)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    import gate_b_flow_common as gfc
    import gate_b_full_paths as gbf

    paths = gbf.load_full_paths()
    quotes = gfc.load_flow_quotes()
    panel = build_panel(paths, quotes)
    panel.to_csv("gate_b_flow_panel.csv", index=False)
    print(f"panel rows: {len(panel)}  fires: {panel['date'].nunique()}")
    print(panel.groupby("decision").size())
    cov = panel[panel["vix_rose"] == 1].groupby("decision")[list(ALL_FEATURES)].apply(
        lambda g: g.notna().mean() * 100.0)
    print("\nfeature coverage %, fires only:")
    print(cov.round(1).to_string())
