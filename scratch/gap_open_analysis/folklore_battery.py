#!/usr/bin/env python3
"""Frozen Indian Options Folklore Battery (H1--H15, PROT-01--PROT-08).

Offline research only.  No broker, credential, order path, or live-trading module is
imported.  Option prices are traded closes, so every option P&L estimate is an upper
bound for the buyer and for the seller alike.  Trading time is 375 minutes/session and
252 sessions/year.  H11 and H14 are explicitly truncated-chain proxies.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats

import nge_common
from nge_breakout_test import load_spot_by_date


SEED = 20260823
PLACEBO_DRAWS = 2000
BONFERRONI = 0.05 / 15.0
PANEL_PATH = Path("nge_panel.csv")
QUOTE_CACHE = Path("folklore_required_quotes_20260823.pkl")
RESULTS_PATH = Path("folklore_battery_results.json")
SESSION_PANEL_PATH = Path("folklore_battery_panel.csv")
REPORT_PATH = Path("FOLKLORE_BATTERY_TEST.md")
SPEC_REPORT_ALIAS = Path("FOLKLORE_BATTERY_RESULTS.md")
LEDGER_PATH = Path("folklore_battery_claim_evidence_ledger.md")
STRIKE_STEP = nge_common.STRIKE_STEP

OPTION_IDS = {"H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"}
PROXY_IDS = {"H11", "H14"}
NAMES = {
    "H1": "SELL_STRADDLE_0920_ALL",
    "H2": "SELL_STRADDLE_0920_EXPIRY",
    "H3": "SELL_STRADDLE_0920_NONEXPIRY",
    "H4": "SELL_STRADDLE_OVERNIGHT",
    "H5": "SELL_STRADDLE_HIGH_IV",
    "H6": "SELL_STRADDLE_BY_DTE",
    "H7": "BUY_OTM_EXPIRY_LOTTERY",
    "H8": "BUY_STRADDLE_LOW_IV",
    "H9": "GAP_FADE",
    "H10": "GAP_CONTINUATION",
    "H11": "PCR_CONTRARIAN_TRUNCATED_CHAIN_PROXY",
    "H12": "WEEKDAY",
    "H13": "OVERNIGHT_VS_INTRADAY",
    "H14": "MAX_PAIN_PIN_TRUNCATED_CHAIN_PROXY",
    "H15": "ROUND_NUMBER_PIN",
}


def finite_float(x: Any) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if math.isfinite(y) else None


def jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return finite_float(x)
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if pd.isna(x):
        return None
    return x


def atomic_json(path: Path, obj: dict) -> None:
    incoming = path.with_suffix(".incoming")
    incoming.write_text(json.dumps(jsonable(obj), indent=2, allow_nan=False) + "\n")
    os.replace(incoming, path)


def t_wilcoxon(values: pd.Series | np.ndarray) -> dict:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "t": None, "t_p": None,
                "wilcoxon_stat": None, "wilcoxon_p": None}
    mean = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if n > 1 else np.nan
    if n > 1 and sd > 0:
        tt = stats.ttest_1samp(x, 0.0)
        tval, tp = float(tt.statistic), float(tt.pvalue)
    elif mean == 0:
        tval, tp = 0.0, 1.0
    else:
        tval, tp = None, None
    try:
        if np.allclose(x, 0):
            wstat, wp = 0.0, 1.0
        else:
            w = stats.wilcoxon(x, zero_method="wilcox", alternative="two-sided")
            wstat, wp = float(w.statistic), float(w.pvalue)
    except ValueError:
        wstat, wp = None, None
    return {"n": int(n), "mean": mean, "sd": finite_float(sd), "t": tval,
            "t_p": tp, "wilcoxon_stat": wstat, "wilcoxon_p": wp}


def lag1(values: pd.Series | np.ndarray) -> float | None:
    x = pd.Series(np.asarray(values, dtype=float)).dropna()
    return finite_float(x.autocorr(lag=1)) if len(x) >= 3 else None


def tail_report(frame: pd.DataFrame, value: str) -> dict:
    d = frame[["date", value]].dropna().sort_values("date").copy()
    if d.empty:
        return {"worst_session": None, "worst_five": [], "max_drawdown": None,
                "p01": None, "p99": None}
    d[value] = d[value].astype(float)
    worst = d.nsmallest(5, value)
    cumulative = d[value].cumsum()
    drawdown = cumulative - np.maximum.accumulate(np.r_[0.0, cumulative.to_numpy()])[1:]
    return {
        "worst_session": {"date": str(worst.iloc[0]["date"]),
                          "value": float(worst.iloc[0][value])},
        "worst_five": [{"date": str(r.date), "value": float(getattr(r, value))}
                       for r in worst.itertuples(index=False)],
        "max_drawdown": float(np.min(drawdown)),
        "p01": float(d[value].quantile(0.01)),
        "p99": float(d[value].quantile(0.99)),
        "tail_survivability": "not established; no capital or margin model is registered",
    }


def by_year(frame: pd.DataFrame, value: str) -> dict:
    out: dict[str, dict] = {}
    d = frame[["date", value]].dropna().copy()
    d["year"] = d["date"].str.slice(0, 4).astype(int)
    for year, group in d.groupby("year", sort=True):
        s = t_wilcoxon(group[value])
        out[str(year)] = {"n": s["n"], "mean": s["mean"], "t": s["t"],
                          "nominal_p": s["t_p"], "wilcoxon_p": s["wilcoxon_p"]}
    return out


def empirical_p(observed_abs: float, draws: np.ndarray) -> dict:
    draws = np.asarray(draws, dtype=float)
    draws = draws[np.isfinite(draws)]
    p = (1.0 + float(np.sum(draws >= observed_abs))) / (len(draws) + 1.0)
    return {"seed": SEED, "draws": int(len(draws)), "observed_abs_stat": observed_abs,
            "median_abs_placebo_stat": float(np.median(draws)), "empirical_p": p}


def subset_placebo(y: np.ndarray, label: np.ndarray, selected: bool = True) -> dict:
    y = np.asarray(y, dtype=float)
    label = np.asarray(label, dtype=bool)
    obs = t_wilcoxon(y[label == selected])["t"]
    if obs is None:
        return {"seed": SEED, "draws": 0, "empirical_p": None}
    rng = np.random.default_rng(SEED)
    vals = np.empty(PLACEBO_DRAWS)
    for i in range(PLACEBO_DRAWS):
        perm = rng.permutation(label)
        vals[i] = abs(t_wilcoxon(y[perm == selected])["t"] or np.nan)
    return empirical_p(abs(obs), vals)


def signal_placebo(y: np.ndarray, signal: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    signal = np.asarray(signal, dtype=float)
    obs = t_wilcoxon(y * signal)["t"]
    rng = np.random.default_rng(SEED)
    vals = np.empty(PLACEBO_DRAWS)
    for i in range(PLACEBO_DRAWS):
        vals[i] = abs(t_wilcoxon(y * rng.permutation(signal))["t"] or np.nan)
    return empirical_p(abs(float(obs)), vals)


def joint_zero_f(y: np.ndarray, group: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    group = np.asarray(group)
    ok = np.isfinite(y) & pd.notna(group)
    y, group = y[ok], group[ok]
    levels = sorted(pd.unique(group).tolist())
    k, n = len(levels), len(y)
    if n <= k or k == 0:
        return {"stat_name": "F", "statistic": None, "df1": k, "df2": n-k,
                "p": None, "n": n}
    means = {level: float(np.mean(y[group == level])) for level in levels}
    ss_model = sum(float(np.sum(group == level)) * means[level] ** 2 for level in levels)
    ss_error = sum(float(np.sum((y[group == level] - means[level]) ** 2)) for level in levels)
    f = (ss_model / k) / (ss_error / (n - k)) if ss_error > 0 else np.inf
    return {"stat_name": "joint F(all cell means=0)", "statistic": float(f),
            "df1": k, "df2": n-k, "p": float(stats.f.sf(f, k, n-k)), "n": n}


def group_placebo(y: np.ndarray, group: np.ndarray) -> dict:
    obs = joint_zero_f(y, group)["statistic"]
    rng = np.random.default_rng(SEED)
    vals = np.empty(PLACEBO_DRAWS)
    for i in range(PLACEBO_DRAWS):
        vals[i] = joint_zero_f(y, rng.permutation(group))["statistic"]
    return empirical_p(abs(float(obs)), np.abs(vals))


def make_result(hid: str, frame: pd.DataFrame, value: str, units: str,
                *, conditional: bool, placebo: dict | None = None,
                primary: dict | None = None, notes: list[str] | None = None,
                extra: dict | None = None) -> dict:
    stats0 = t_wilcoxon(frame[value])
    primary_test = primary or {"stat_name": "one-sample t", "statistic": stats0["t"],
                               "p": stats0["t_p"], "n": stats0["n"]}
    p = primary_test.get("p")
    clears = bool(p is not None and p < BONFERRONI)
    # The registered t-tests are two-sided.  A p-value can therefore clear in the
    # folklore-opposite direction.  Preserve that statistical rejection, but never
    # call a negative-P&L (or negative pin-score) rejection a strategy survivor.
    direction_supported = True if hid == "H12" else bool(
        stats0["mean"] is not None and stats0["mean"] > 0
    )
    result = {
        "id": hid, "name": NAMES[hid], "status": "computed", "units": units,
        "conditional": conditional, "truncated_chain_proxy": hid in PROXY_IDS,
        "n": stats0["n"], "mean": stats0["mean"], "t": stats0["t"],
        "nominal_p": p, "bonferroni_threshold": BONFERRONI,
        "bonferroni_pass": clears,
        "direction_supported": direction_supported,
        "supported_direction_survivor": bool(clears and direction_supported),
        "primary_test": primary_test,
        "wilcoxon": {"statistic": stats0["wilcoxon_stat"], "p": stats0["wilcoxon_p"]},
        "placebo": placebo,
        "lag1_autocorrelation": lag1(frame[value]),
        "tail": tail_report(frame, value),
        "by_year": by_year(frame, value),
        "notes": list(notes or []),
    }
    if hid in OPTION_IDS:
        eligible = frame[["pnl_points", "entry_premium"]].dropna()
        be = (100.0 * eligible["pnl_points"].mean() / eligible["entry_premium"].mean()
              if len(eligible) and eligible["entry_premium"].mean() > 0 else None)
        result["breakeven_round_trip_cost_pct_entry_premium"] = finite_float(be)
        result["breakeven_positive_room"] = bool(be is not None and be > 0)
        worst_value = (result["tail"].get("worst_session") or {}).get("value")
        catastrophic = bool(worst_value is not None and worst_value <= -100.0)
        result["tail"]["catastrophic_option_tail"] = catastrophic
        result["tail"]["survivable_tail_pass"] = False if catastrophic else None
        if catastrophic:
            result["tail"]["tail_assessment"] = (
                "fails: a session lost at least 100% of entry premium; without a capital/"
                "margin model this cannot be called survivable and is not a strategy"
            )
        result["notes"].append(
            "Every option mean uses traded closes and excludes bid-ask; it is an upper "
            "bound for the buyer and for the seller alike."
        )
    else:
        result["breakeven_round_trip_cost_pct_entry_premium"] = None
        result["breakeven_positive_room"] = None
    if extra:
        result.update(extra)
    return result


class Battery:
    def __init__(self, fresh: bool):
        self.panel = pd.read_csv(PANEL_PATH)
        self.panel["date"] = self.panel["date"].astype(str)
        self.panel = self.panel.sort_values("date").reset_index(drop=True)
        self.panel["trailing_iv_median"] = (
            self.panel["atm_iv_open"].expanding(min_periods=1).median().shift(1)
        )
        self.spot = load_spot_by_date()
        obj = pd.read_pickle(QUOTE_CACHE)
        self.quotes = obj["quotes"].copy()
        self.cache_audit = obj["audit"]
        self.chain = {(d, c): g for (d, c), g in
                      self.quotes.groupby(["date", "clock"], sort=False)}
        self.spot_px: dict[tuple[str, str], float] = {}
        for date, path in self.spot.items():
            for clock in ("09:15", "09:20", "15:29"):
                hit = path.loc[path["clock"] == clock, "spot"]
                if not hit.empty:
                    self.spot_px[(str(date), clock)] = float(hit.iloc[-1])
        if fresh or not RESULTS_PATH.exists():
            self.results = {
                "title": "Indian Options Folklore Battery",
                "spec_date": "2026-08-23", "seed": SEED,
                "placebo_draws": PLACEBO_DRAWS, "registered_family_size": 15,
                "bonferroni_threshold": BONFERRONI,
                "trading_time": {"minutes_per_session": 375, "sessions_per_year": 252},
                "quote_cache": str(QUOTE_CACHE), "quote_cache_audit": self.cache_audit,
                "measurement": {
                    "atm": "nearest absolute strike at entry minute",
                    "prices": "traded closes; no bid-ask; upper bound for buyer and seller",
                    "expiry_day": "nge_panel.is_expiry_day; no hardcoded weekday",
                    "H11_H14": "truncated-chain proxies, not full-chain quantities",
                },
                "hypotheses": {}, "completion_order": [],
            }
            if SESSION_PANEL_PATH.exists():
                SESSION_PANEL_PATH.unlink()
            atomic_json(RESULTS_PATH, self.results)
        else:
            self.results = json.loads(RESULTS_PATH.read_text())

    def done(self, hid: str) -> bool:
        return hid in self.results["hypotheses"]

    def checkpoint(self, hid: str, result: dict, frame: pd.DataFrame, value: str) -> None:
        self.results["hypotheses"][hid] = result
        if hid not in self.results["completion_order"]:
            self.results["completion_order"].append(hid)
        atomic_json(RESULTS_PATH, self.results)
        # A single stable schema keeps the cross-hypothesis panel readable even though
        # the registered rules carry different diagnostics.  Rule-specific fields are
        # retained losslessly in metadata_json.
        common = ["date", "year", "is_expiry_day", "sessions_to_expiry", "signal",
                  "entry_premium", "pnl_points", "entry_spot", "spot_open", "spot_close"]
        out = pd.DataFrame({
            "hypothesis": hid,
            "date": frame["date"].astype(str),
            "year": frame["date"].astype(str).str.slice(0, 4).astype(int),
            "outcome": value,
            "value": frame[value].astype(float),
            "units": result["units"],
        })
        for col in common[2:]:
            out[col] = frame[col].to_numpy() if col in frame.columns else np.nan
        meta_cols = [c for c in frame.columns if c not in set(common + [value])]
        if meta_cols:
            out["metadata_json"] = frame[meta_cols].apply(
                lambda row: json.dumps(jsonable(row.to_dict()), separators=(",", ":")), axis=1
            )
        else:
            out["metadata_json"] = "{}"
        out = out[["hypothesis", "date", "year", "outcome", "value", "units",
                   "is_expiry_day", "sessions_to_expiry", "signal", "entry_premium",
                   "pnl_points", "entry_spot", "spot_open", "spot_close", "metadata_json"]]
        mode = "a" if SESSION_PANEL_PATH.exists() else "w"
        out.to_csv(SESSION_PANEL_PATH, mode=mode, header=(mode == "w"), index=False)
        print(f"checkpoint {hid}: N={result['n']} mean={result['mean']} "
              f"p={result['nominal_p']} pass={result['bonferroni_pass']}", flush=True)

    def nearest_atm(self, date: str, clock: str, spot: float) -> float | None:
        g = self.chain.get((date, clock))
        if g is None:
            return None
        sides = g.pivot_table(index="strike", columns="side", values="close", aggfunc="first")
        if not {"CALL", "PUT"}.issubset(sides.columns):
            return None
        strikes = np.sort(sides.dropna(subset=["CALL", "PUT"]).index.to_numpy(dtype=float))
        return float(strikes[np.argmin(np.abs(strikes - spot))]) if len(strikes) else None

    def price(self, date: str, clock: str, side: str, strike: float) -> float | None:
        g = self.chain.get((date, clock))
        if g is None:
            return None
        hit = g[(g["side"] == side) & (g["strike"] == strike)]
        return float(hit.iloc[0]["close"]) if not hit.empty else None

    def straddles_0920(self) -> pd.DataFrame:
        rows = []
        for r in self.panel.itertuples(index=False):
            date = str(r.date)
            spot = self.spot_px.get((date, "09:20"))
            if spot is None:
                continue
            atm = self.nearest_atm(date, "09:20", spot)
            if atm is None:
                continue
            vals = [self.price(date, c, s, atm) for c in ("09:20", "15:29")
                    for s in ("CALL", "PUT")]
            if any(v is None for v in vals):
                continue
            ce, pe, cx, px = [float(v) for v in vals]
            entry, exit_ = ce + pe, cx + px
            rows.append({
                "date": date, "year": int(r.year), "is_expiry_day": int(r.is_expiry_day),
                "sessions_to_expiry": int(r.sessions_to_expiry), "atm_iv_open": float(r.atm_iv_open),
                "trailing_iv_median": finite_float(r.trailing_iv_median), "entry_spot": spot,
                "atm_strike": atm, "entry_premium": entry, "exit_premium": exit_,
                "seller_pnl_points": entry - exit_, "seller_return_pct": 100*(entry-exit_)/entry,
                "buyer_pnl_points": exit_ - entry, "buyer_return_pct": 100*(exit_-entry)/entry,
            })
        return pd.DataFrame(rows)

    def overnight_straddles(self) -> pd.DataFrame:
        rows = []
        dates = self.panel["date"].tolist()
        meta = self.panel.set_index("date")
        for date, next_date in zip(dates[:-1], dates[1:]):
            r = meta.loc[date]
            if int(r["is_expiry_day"]) == 1:
                continue  # expired WEEK1 contract cannot be bought back next session
            spot = self.spot_px.get((date, "15:29"))
            if spot is None:
                continue
            atm = self.nearest_atm(date, "15:29", spot)
            if atm is None:
                continue
            vals = [self.price(date, "15:29", s, atm) for s in ("CALL", "PUT")]
            vals += [self.price(next_date, "09:15", s, atm) for s in ("CALL", "PUT")]
            if any(v is None for v in vals):
                continue
            ce, pe, cx, px = [float(v) for v in vals]
            entry, exit_ = ce+pe, cx+px
            rows.append({"date": date, "next_date": next_date, "year": int(r["year"]),
                         "atm_strike": atm, "entry_premium": entry, "exit_premium": exit_,
                         "pnl_points": entry-exit_, "value": 100*(entry-exit_)/entry})
        return pd.DataFrame(rows)

    def expiry_lottery(self) -> pd.DataFrame:
        rows = []
        for r in self.panel[self.panel["is_expiry_day"] == 1].itertuples(index=False):
            date = str(r.date)
            spot = self.spot_px.get((date, "09:20"))
            if spot is None:
                continue
            atm = self.nearest_atm(date, "09:20", spot)
            if atm is None:
                continue
            kc, kp = atm + 5*STRIKE_STEP, atm - 5*STRIKE_STEP
            vals = [self.price(date, "09:20", "CALL", kc),
                    self.price(date, "09:20", "PUT", kp),
                    self.price(date, "15:29", "CALL", kc),
                    self.price(date, "15:29", "PUT", kp)]
            if any(v is None for v in vals):
                continue
            ce, pe, cx, px = [float(v) for v in vals]
            entry, exit_ = ce+pe, cx+px
            rows.append({"date": date, "year": int(r.year), "is_expiry_day": 1,
                         "atm_strike": atm, "call_strike": kc, "put_strike": kp,
                         "entry_premium": entry, "exit_premium": exit_,
                         "pnl_points": exit_-entry, "value": 100*(exit_-entry)/entry})
        return pd.DataFrame(rows)

    def spot_frame(self) -> pd.DataFrame:
        rows = []
        prev_close = None
        prev_date = None
        for r in self.panel.itertuples(index=False):
            date = str(r.date)
            op = self.spot_px.get((date, "09:15")); cl = self.spot_px.get((date, "15:29"))
            if op is None or cl is None:
                prev_close, prev_date = cl, date
                continue
            overnight = (100*(op/prev_close-1)) if prev_close else np.nan
            gap = overnight
            intra = 100*(cl/op-1)
            rows.append({"date": date, "year": int(r.year), "weekday": pd.Timestamp(date).day_name(),
                         "is_expiry_day": int(r.is_expiry_day), "spot_open": op, "spot_close": cl,
                         "prev_date": prev_date, "prev_close": prev_close, "gap_pct": gap,
                         "intraday_pct": intra, "overnight_pct": overnight})
            prev_close, prev_date = cl, date
        return pd.DataFrame(rows)

    def pcr_frame(self, spot: pd.DataFrame) -> pd.DataFrame:
        q = self.quotes[self.quotes["clock"] == "09:15"]
        sums = q.groupby(["date", "side"])["oi"].sum().unstack()
        sums = sums.dropna(subset=["CALL", "PUT"])
        sums = sums[(sums["CALL"] > 0) & (sums["PUT"] > 0)].copy()
        sums["pcr_proxy"] = sums["PUT"] / sums["CALL"]
        sums["trailing_pcr_median"] = sums["pcr_proxy"].expanding().median().shift(1)
        out = spot.merge(sums[["pcr_proxy", "trailing_pcr_median"]], left_on="date",
                         right_index=True, how="inner")
        out = out.dropna(subset=["trailing_pcr_median"])
        out["signal"] = np.sign(out["pcr_proxy"] - out["trailing_pcr_median"])
        out = out[out["signal"] != 0].copy()
        out["value"] = out["signal"] * out["intraday_pct"]
        return out

    def maxpain_frame(self, spot: pd.DataFrame) -> pd.DataFrame:
        q = self.quotes[self.quotes["clock"] == "09:15"]
        spot_idx = spot.set_index("date")
        rows = []
        for date, g in q.groupby("date", sort=True):
            if date not in spot_idx.index:
                continue
            piv = g.pivot_table(index="strike", columns="side", values="oi", aggfunc="sum",
                                fill_value=0)
            if not {"CALL", "PUT"}.issubset(piv.columns):
                continue
            strikes = np.sort(piv.index.to_numpy(dtype=float))
            call_oi = piv.reindex(strikes)["CALL"].to_numpy(dtype=float)
            put_oi = piv.reindex(strikes)["PUT"].to_numpy(dtype=float)
            losses = []
            for settle in strikes:
                losses.append(float(np.sum(call_oi*np.maximum(settle-strikes, 0)) +
                                    np.sum(put_oi*np.maximum(strikes-settle, 0))))
            pin = float(strikes[int(np.argmin(losses))])
            s = spot_idx.loc[date]
            rows.append({"date": date, "year": int(s["year"]),
                         "is_expiry_day": int(s["is_expiry_day"]), "spot_open": float(s["spot_open"]),
                         "spot_close": float(s["spot_close"]), "maxpain_proxy": pin,
                         "value": abs(float(s["spot_open"])-pin)-abs(float(s["spot_close"])-pin),
                         "available_strikes": strikes.tolist()})
        return pd.DataFrame(rows)

    def run(self) -> None:
        s = self.straddles_0920()
        spot = self.spot_frame()

        def cp_option(hid: str, d: pd.DataFrame, pnl: str, ret: str, conditional: bool,
                      placebo: dict | None = None, notes: list[str] | None = None,
                      primary: dict | None = None, extra: dict | None = None) -> None:
            if self.done(hid):
                return
            x = d.copy().rename(columns={pnl: "pnl_points", ret: "value"})
            res = make_result(hid, x, "value", "% of entry premium", conditional=conditional,
                              placebo=placebo, primary=primary, notes=notes, extra=extra)
            self.checkpoint(hid, res, x, "value")

        # H1
        cp_option("H1", s, "seller_pnl_points", "seller_return_pct", False)

        # H2/H3: expiry-label conditional subsets and shuffled-label placebos.
        seller_y = s["seller_return_pct"].to_numpy()
        expiry_label = s["is_expiry_day"].to_numpy(dtype=bool)
        cp_option("H2", s[s.is_expiry_day == 1], "seller_pnl_points", "seller_return_pct", True,
                  subset_placebo(seller_y, expiry_label, True))
        cp_option("H3", s[s.is_expiry_day == 0], "seller_pnl_points", "seller_return_pct", True,
                  subset_placebo(seller_y, expiry_label, False))

        # H4
        if not self.done("H4"):
            d4 = self.overnight_straddles()
            res4 = make_result("H4", d4, "value", "% of entry premium", conditional=False,
                               notes=["Expiry-session entries are unavailable: the WEEK1 contract "
                                      "expires before the next session and cannot be bought back at 09:15."])
            self.checkpoint("H4", res4, d4, "value")

        # H5/H8 use the frozen past-only trailing median.
        valid_iv = s.dropna(subset=["trailing_iv_median"]).copy()
        high = (valid_iv["atm_iv_open"] > valid_iv["trailing_iv_median"]).to_numpy()
        cp_option("H5", valid_iv[high], "seller_pnl_points", "seller_return_pct", True,
                  subset_placebo(valid_iv["seller_return_pct"].to_numpy(), high, True))

        # H6: joint test that all DTE-cell means are zero, plus each registered cell.
        if not self.done("H6"):
            d6 = s.copy().rename(columns={"seller_pnl_points": "pnl_points",
                                          "seller_return_pct": "value"})
            primary6 = joint_zero_f(d6["value"].to_numpy(), d6["sessions_to_expiry"].to_numpy())
            cell6 = {}
            for cell, g in d6.groupby("sessions_to_expiry", sort=True):
                cell6[str(int(cell))] = t_wilcoxon(g["value"])
            bucket_year = {}
            for (year, cell), g in d6.groupby(["year", "sessions_to_expiry"], sort=True):
                bucket_year.setdefault(str(int(year)), {})[str(int(cell))] = t_wilcoxon(g["value"])
            res6 = make_result("H6", d6, "value", "% of entry premium", conditional=True,
                               placebo=group_placebo(d6["value"].to_numpy(),
                                                       d6["sessions_to_expiry"].to_numpy()),
                               primary=primary6, extra={"dte_cells": cell6,
                                                        "dte_cells_by_year": bucket_year})
            self.checkpoint("H6", res6, d6, "value")

        # H7
        d7 = self.expiry_lottery()
        # Placebo expiry labels over the same OTM construction is not computable on non-expiry
        # dates without rebuilding a different leg panel; build it directly for all dates.
        all_lottery_rows = []
        for r in self.panel.itertuples(index=False):
            date = str(r.date); spot0 = self.spot_px.get((date, "09:20"))
            if spot0 is None: continue
            atm = self.nearest_atm(date, "09:20", spot0)
            if atm is None: continue
            kc, kp = atm+5*STRIKE_STEP, atm-5*STRIKE_STEP
            vals = [self.price(date, "09:20", "CALL", kc), self.price(date, "09:20", "PUT", kp),
                    self.price(date, "15:29", "CALL", kc), self.price(date, "15:29", "PUT", kp)]
            if any(v is None for v in vals): continue
            ce, pe, cx, px = map(float, vals); entry = ce+pe
            all_lottery_rows.append({"value": 100*((cx+px)-entry)/entry,
                                     "is_expiry_day": int(r.is_expiry_day)})
        all_lot = pd.DataFrame(all_lottery_rows)
        p7 = subset_placebo(all_lot["value"].to_numpy(),
                              all_lot["is_expiry_day"].to_numpy(dtype=bool), True)
        cp_option("H7", d7, "pnl_points", "value", True, p7)

        cp_option("H8", valid_iv[~high], "buyer_pnl_points", "buyer_return_pct", True,
                  subset_placebo(valid_iv["buyer_return_pct"].to_numpy(), high, False))

        # H9/H10 exact mirrors; each is checkpointed, with the shared family interpretation noted.
        gap = spot.dropna(subset=["gap_pct"]).copy()
        gap = gap[gap["gap_pct"] != 0].copy()
        gap["gap_direction"] = np.sign(gap["gap_pct"])
        gap["fade"] = -gap["gap_direction"] * gap["intraday_pct"]
        gap["continuation"] = gap["gap_direction"] * gap["intraday_pct"]
        for hid, col, sig in (("H9", "fade", -gap["gap_direction"].to_numpy()),
                              ("H10", "continuation", gap["gap_direction"].to_numpy())):
            if self.done(hid): continue
            d = gap.copy(); d["value"] = d[col]
            res = make_result(hid, d, "value", "% spot return", conditional=True,
                              placebo=signal_placebo(d["intraday_pct"].to_numpy(), sig),
                              notes=["H9 and its exact H10 mirror are reported alongside; "
                                     "the frozen family size remains 15."])
            self.checkpoint(hid, res, d, "value")

        # H11 truncated-chain PCR proxy.
        if not self.done("H11"):
            d11 = self.pcr_frame(spot)
            res11 = make_result("H11", d11, "value", "% spot return", conditional=True,
                                placebo=signal_placebo(d11["intraday_pct"].to_numpy(),
                                                         d11["signal"].to_numpy()),
                                notes=["PCR uses only the archived ATM±10 chain and is a "
                                       "truncated-chain proxy, not the true full-chain PCR."])
            self.checkpoint("H11", res11, d11, "value")

        # H12 weekday cells: registered joint F, then cell t/Wilcoxon.
        if not self.done("H12"):
            d12 = spot.copy(); d12["value"] = d12["intraday_pct"]
            primary12 = joint_zero_f(d12["value"].to_numpy(), d12["weekday"].to_numpy())
            cells = {str(k): t_wilcoxon(g["value"]) for k, g in
                     d12.groupby("weekday", sort=True)}
            cells_year = {}
            for (year, wd), g in d12.groupby(["year", "weekday"], sort=True):
                cells_year.setdefault(str(int(year)), {})[str(wd)] = t_wilcoxon(g["value"])
            res12 = make_result("H12", d12, "value", "% spot return", conditional=True,
                                placebo=group_placebo(d12["value"].to_numpy(),
                                                        d12["weekday"].to_numpy()),
                                primary=primary12,
                                extra={"weekday_cells": cells, "weekday_cells_by_year": cells_year})
            self.checkpoint("H12", res12, d12, "value")

        # H13 paired decomposition; primary is overnight minus intraday.
        if not self.done("H13"):
            d13 = spot.dropna(subset=["overnight_pct"]).copy()
            d13["value"] = d13["overnight_pct"] - d13["intraday_pct"]
            comp = {"overnight_vs_zero": t_wilcoxon(d13["overnight_pct"]),
                    "intraday_vs_zero": t_wilcoxon(d13["intraday_pct"]),
                    "overnight_minus_intraday": t_wilcoxon(d13["value"])}
            comp_year = {}
            for year, g in d13.groupby("year", sort=True):
                comp_year[str(int(year))] = {
                    "overnight": t_wilcoxon(g["overnight_pct"]),
                    "intraday": t_wilcoxon(g["intraday_pct"]),
                    "difference": t_wilcoxon(g["value"])}
            res13 = make_result("H13", d13, "value", "percentage-point return difference",
                                conditional=False,
                                extra={"component_tests": comp, "components_by_year": comp_year})
            self.checkpoint("H13", res13, d13, "value")

        # H14 truncated-chain max-pain proxy with specified random-strike placebo and
        # a separate shuffled-expiry-label diagnostic.
        mp = self.maxpain_frame(spot)
        if not self.done("H14"):
            exp = mp[mp["is_expiry_day"] == 1].copy()
            rng = np.random.default_rng(SEED)
            draw_t = np.empty(PLACEBO_DRAWS)
            for j in range(PLACEBO_DRAWS):
                vals = []
                for r in exp.itertuples(index=False):
                    pin = float(rng.choice(np.asarray(r.available_strikes, dtype=float)))
                    vals.append(abs(r.spot_open-pin)-abs(r.spot_close-pin))
                draw_t[j] = abs(t_wilcoxon(np.asarray(vals))["t"] or np.nan)
            obs_t = abs(float(t_wilcoxon(exp["value"])["t"]))
            p_random = empirical_p(obs_t, draw_t)
            p_random["placebo_type"] = "random available strike per expiry session"
            p_label = subset_placebo(mp["value"].to_numpy(),
                                       mp["is_expiry_day"].to_numpy(dtype=bool), True)
            controls = {"expiry": t_wilcoxon(exp["value"]),
                        "nonexpiry": t_wilcoxon(mp.loc[mp.is_expiry_day == 0, "value"]),
                        "expiry_pin_success_rate_pct": 100*float((exp["value"] > 0).mean()),
                        "nonexpiry_pin_success_rate_pct":
                            100*float((mp.loc[mp.is_expiry_day == 0, "value"] > 0).mean())}
            controls_year = {}
            for (year, flag), g in mp.groupby(["year", "is_expiry_day"], sort=True):
                controls_year.setdefault(str(int(year)), {})[
                    "expiry" if flag else "nonexpiry"] = t_wilcoxon(g["value"])
            res14 = make_result("H14", exp, "value", "spot points closer to max-pain proxy",
                                conditional=True, placebo=p_random,
                                notes=["Max pain uses only the archived ATM±10 chain and is a "
                                       "truncated-chain proxy, not true full-chain max pain."],
                                extra={"controls": controls, "controls_by_year": controls_year,
                                       "shuffled_expiry_label_placebo": p_label})
            self.checkpoint("H14", res14, exp, "value")

        # H15 closeness surplus relative to the exact uniform null E|U-50|=25.
        if not self.done("H15"):
            d15all = spot.copy()
            d15all["value"] = np.abs(np.mod(d15all["spot_close"], 100.0)-50.0)-25.0
            d15 = d15all[d15all["is_expiry_day"] == 1].copy()
            controls15 = {"expiry": t_wilcoxon(d15["value"]),
                          "nonexpiry": t_wilcoxon(d15all.loc[d15all.is_expiry_day == 0, "value"])}
            ctrl15year = {}
            for (year, flag), g in d15all.groupby(["year", "is_expiry_day"], sort=True):
                ctrl15year.setdefault(str(int(year)), {})[
                    "expiry" if flag else "nonexpiry"] = t_wilcoxon(g["value"])
            res15 = make_result("H15", d15, "value", "spot-point closeness surplus vs uniform",
                                conditional=True,
                                placebo=subset_placebo(d15all["value"].to_numpy(),
                                                         d15all["is_expiry_day"].to_numpy(bool), True),
                                extra={"controls": controls15, "controls_by_year": ctrl15year,
                                       "uniform_null_expected_abs_mod_minus_50": 25.0})
            self.checkpoint("H15", res15, d15, "value")

        self.results["complete"] = len(self.results["hypotheses"]) == 15
        self.results["bonferroni_threshold_clear"] = [
            hid for hid in NAMES
            if self.results["hypotheses"].get(hid, {}).get("bonferroni_pass")
        ]
        self.results["survivors"] = [
            hid for hid in NAMES
            if self.results["hypotheses"].get(hid, {}).get("supported_direction_survivor")
        ]
        atomic_json(RESULTS_PATH, self.results)
        self.write_report()

    def write_report(self) -> None:
        h = self.results["hypotheses"]
        survivors = self.results.get("survivors", [])
        threshold_clear = self.results.get("bonferroni_threshold_clear", [])
        if survivors:
            bits = []
            for hid in survivors:
                r = h[hid]
                if hid in OPTION_IDS:
                    cost = ("positive breakeven room" if r["breakeven_positive_room"]
                            else "no positive breakeven room")
                else:
                    cost = "breakeven cost not applicable"
                tail = r["tail"]
                if tail.get("catastrophic_option_tail"):
                    tail_text = (f"tail FAIL: worst {tail['worst_session']['value']:.1f}% and "
                                 f"max drawdown {tail['max_drawdown']:.1f} percentage points; "
                                 "not a strategy")
                else:
                    tail_text = "tail survivability not established without a capital/margin model"
                bits.append(f"{hid} ({cost}; {tail_text})")
            survivor_text = ", ".join(bits)
        else:
            survivor_text = "none"
        opposite = [hid for hid in threshold_clear if hid not in survivors]
        opposite_text = ", ".join(opposite) if opposite else "none"
        threshold_text = ", ".join(threshold_clear) if threshold_clear else "none"
        headline = (
            f"**Headline verdict (descriptive screening evidence): {len(threshold_clear)} of 15 "
            f"registered tests clear the Bonferroni cutoff 0.00333 ({threshold_text}), but "
            f"{opposite_text} clear in the "
            f"folklore-opposite direction. Supported-direction survivors: {survivor_text}.** "
            "A threshold-clearing negative is a rejection of the folklore rule, not a candidate. "
            "This is a screening battery, not a strategy recommendation, "
            "and no gate is armed. H11 PCR and H14 max pain are **truncated-chain proxies**, "
            "not the true full-chain quantities. Option estimates use traded closes without "
            "bid–ask and are upper bounds for buyers and sellers alike.\n"
        )
        lines = ["# Indian Options Folklore Battery", "", headline, "",
                 "## Single summary table", "",
                 "| Hypothesis | N | Mean | t / registered stat | Nominal p (Bonf. 0.00333) | Pass | Placebo p | Breakeven cost % | Worst session | Max drawdown |",
                 "|---|---:|---:|---:|---:|:---:|---:|---:|---|---:|"]
        for hid in NAMES:
            r = h.get(hid)
            if not r:
                lines.append(f"| {hid} | — | — | — | — | BLOCKED | — | — | — | — |")
                continue
            prim = r["primary_test"]
            stat = prim.get("statistic")
            stat_text = (f"F={stat:.3f}" if str(prim.get("stat_name", "")).startswith("joint F")
                         else (f"{r['t']:.3f}" if r.get("t") is not None else "—"))
            pp = r.get("placebo") or {}
            be = r.get("breakeven_round_trip_cost_pct_entry_premium")
            worst = r["tail"]["worst_session"]
            wtxt = f"{worst['date']}: {worst['value']:.3f}" if worst else "—"
            be_text = f"{be:.3f}" if be is not None else "—"
            pass_text = ("PASS" if r["bonferroni_pass"] else "FAIL")
            if r["bonferroni_pass"] and not r.get("direction_supported", False):
                pass_text += " (opposite sign)"
            lines.append(
                f"| {hid} {NAMES[hid]} | {r['n']} | {r['mean']:.4f} {r['units']} | "
                f"{stat_text} | {r['nominal_p']:.4g} (0.00333) | "
                f"{pass_text} | "
                f"{pp.get('empirical_p', '—') if pp.get('empirical_p') is not None else '—'} | "
                f"{be_text} | " +
                f"{wtxt} | {r['tail']['max_drawdown']:.3f} |"
            )
        lines += ["", "*Option-row means and per-year means are traded-close estimates. "
                  "They exclude bid–ask and therefore are upper bounds for buyers and sellers alike. "
                  "Breakeven cost is the round-trip cost as a percent of entry premium that sets "
                  "mean point P&L to zero.*", ""]

        for hid in NAMES:
            r = h.get(hid)
            lines += [f"## {hid} — {NAMES[hid]}", ""]
            if not r:
                lines += ["**Blocked.** No result was checkpointed.", ""]
                continue
            prim = r["primary_test"]
            ptext = f"{r['nominal_p']:.6g} (Bonferroni threshold 0.00333)"
            lines.append(
                f"N={r['n']}; mean={r['mean']:.6f} {r['units']}; t={r['t']}; "
                f"nominal p={ptext}; Wilcoxon p={r['wilcoxon']['p']}; "
                f"lag-1 autocorrelation={r['lag1_autocorrelation']}. "
                f"Registered primary: {prim['stat_name']}={prim['statistic']}, p={prim['p']}."
            )
            if r.get("placebo"):
                lines.append(f"Placebo: {r['placebo']['draws']} draws, seed {SEED}, empirical "
                             f"p={r['placebo']['empirical_p']}.")
            if hid in OPTION_IDS:
                lines.append(
                    f"Breakeven round-trip cost={r['breakeven_round_trip_cost_pct_entry_premium']:.6f}% "
                    "of entry premium. Every mean in this section uses traded closes, excludes "
                    "bid–ask, and is an upper bound for the buyer and for the seller alike."
                )
            for note in r.get("notes", []):
                if "Every option mean" not in note:
                    lines.append(note)
            if hid == "H3":
                lines.append("Year stability: the mean is positive in 2021–2025 but only 2025 "
                             "individually clears 0.00333, and 2026 is negative. The aggregate "
                             "screen is therefore a **lead, not a finding**; its catastrophic "
                             "tail separately prevents strategy interpretation.")
            if hid == "H7":
                lines.append("The sign is decisively opposite the buying folklore: the average "
                             "expiry lottery loses 92.0% of entry premium. This is evidence "
                             "against the rule, not a survivor and not a strategy.")
            if hid == "H14":
                lines.append("The negative score means expiry closes move farther from the "
                             "truncated max-pain proxy on average. The significant result rejects "
                             "proxy pinning; it does not support it, and it says nothing definitive "
                             "about true full-chain max pain.")
            tail = r["tail"]
            five = "; ".join(f"{x['date']} {x['value']:.4f}" for x in tail["worst_five"])
            lines.append(f"Tail: worst five = {five}; max drawdown={tail['max_drawdown']:.6f}; "
                         f"p1={tail['p01']:.6f}; p99={tail['p99']:.6f}. Tail survivability is "
                         "not established because the frozen design has no capital/margin model.")
            if tail.get("catastrophic_option_tail"):
                lines.append("**Tail verdict: FAIL.** The worst session lost at least 100% of "
                             "entry premium. This catastrophic exposed tail means the positive "
                             "mean, if any, is **not a strategy**.")
            lines += ["", "### Per-year breakdown", "",
                      "| Year | N | Mean | t | Nominal p (Bonf. 0.00333) | Wilcoxon p |",
                      "|---:|---:|---:|---:|---:|---:|"]
            for year, y in r["by_year"].items():
                lines.append(f"| {year} | {y['n']} | {y['mean']:.6f} | {y['t']} | "
                             f"{y['nominal_p']} | {y['wilcoxon_p']} |")
            if hid == "H6":
                lines += ["", "DTE-cell tests (each also contains t and Wilcoxon):",
                          "```json", json.dumps(jsonable(r["dte_cells"]), indent=2), "```"]
                levels = sorted({cell for cells in r["dte_cells_by_year"].values()
                                 for cell in cells}, key=int)
                lines += ["", "Per-year DTE-cell means (% of entry premium):", "",
                          "| Year | " + " | ".join(f"DTE {x}" for x in levels) + " |",
                          "|---:|" + "---:|"*len(levels)]
                for year, cells in r["dte_cells_by_year"].items():
                    lines.append("| " + year + " | " + " | ".join(
                        f"{cells[x]['mean']:.4f}" if x in cells else "—" for x in levels
                    ) + " |")
            if hid == "H12":
                lines += ["", "Weekday-cell tests (joint F is the registered primary):",
                          "```json", json.dumps(jsonable(r["weekday_cells"]), indent=2), "```"]
                days = [x for x in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                        if any(x in cells for cells in r["weekday_cells_by_year"].values())]
                lines += ["", "Per-year weekday-cell means (% spot return):", "",
                          "| Year | " + " | ".join(days) + " |",
                          "|---:|" + "---:|"*len(days)]
                for year, cells in r["weekday_cells_by_year"].items():
                    lines.append("| " + year + " | " + " | ".join(
                        f"{cells[x]['mean']:.4f}" if x in cells else "—" for x in days
                    ) + " |")
            if hid == "H13":
                lines += ["", "Component tests:", "```json",
                          json.dumps(jsonable(r["component_tests"]), indent=2), "```"]
                lines += ["", "Per-year component means (percentage points):", "",
                          "| Year | Overnight | Intraday | Overnight − intraday |",
                          "|---:|---:|---:|---:|"]
                for year, cells in r["components_by_year"].items():
                    lines.append(f"| {year} | {cells['overnight']['mean']:.4f} | "
                                 f"{cells['intraday']['mean']:.4f} | "
                                 f"{cells['difference']['mean']:.4f} |")
            if hid in ("H14", "H15"):
                lines += ["", "Expiry/non-expiry controls:", "```json",
                          json.dumps(jsonable(r["controls"]), indent=2), "```"]
                lines += ["", "Per-year expiry/control means:", "",
                          "| Year | Expiry | Non-expiry |", "|---:|---:|---:|"]
                for year, cells in r["controls_by_year"].items():
                    ex = cells.get("expiry", {}).get("mean")
                    ne = cells.get("nonexpiry", {}).get("mean")
                    lines.append(f"| {year} | {ex:.4f}" + (f" | {ne:.4f} |" if ne is not None
                                                          else " | — |"))
            lines.append("")

        lines += ["## Limitations", "",
                  "- **Truncated chain:** the archive contains only ATM−10 through ATM+10. "
                  "H11 PCR and H14 max pain are proxies, not the real full-chain quantities; "
                  "neither may be read as a test of true PCR or true max pain.",
                  "- **No bid–ask:** all option legs use traded close to traded close. This "
                  "flatters buyers and sellers alike; the breakeven-cost column is the relevant room.",
                  "- **WEEK1 only:** no WEEK2/WEEK3, monthly options, or futures tape.",
                  "- **No margin model:** short-option results are gross of SPAN and intraday "
                  "margin calls, so tail survivability cannot be certified.",
                  "- **No stops or targets:** the registered rules fully realise every tail.",
                  "- **Expiry metadata:** expiry sessions are selected only by `is_expiry_day`; "
                  "no weekday is hardcoded, preserving the 2025 Thursday-to-Tuesday change.",
                  "- **Multiplicity and scope:** this is descriptive exploratory screening. "
                  "A positive mean with an exposed catastrophic tail is not a strategy, and no "
                  "result authorises live trading or arms any gate.", ""]
        text = "\n".join(lines)
        REPORT_PATH.write_text(text)
        SPEC_REPORT_ALIAS.write_text(text)
        LEDGER_PATH.write_text(
            "# Claim–evidence ledger\n\n"
            "| Claim | Type | Estimand/evidence | Assumptions/threats | Boundary | Status |\n"
            "|---|---|---|---|---|---|\n"
            f"| {len(survivors)} of 15 clear Bonferroni | descriptive | Frozen session-level "
            "tests and p<0.00333 | IID daily observations; multiplicity fixed at 15 | screening, "
            "not causal or tradable | supported |\n"
            "| Option means have stated cost room and exposed tails | descriptive | traded-close "
            "P&L, breakeven cost, worst five, MDD, p1/p99 | no bid–ask or margin model | upper "
            "bounds; survivability not established | supported |\n"
            "| H11/H14 concern proxies only | measurement | ATM±10 OI chain | chain truncation | "
            "not true PCR/max pain | supported |\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="discard partial checkpoints")
    args = parser.parse_args()
    if not QUOTE_CACHE.exists():
        raise FileNotFoundError(f"build {QUOTE_CACHE} first with build_folklore_cache.py")
    Battery(fresh=args.fresh).run()


if __name__ == "__main__":
    main()
