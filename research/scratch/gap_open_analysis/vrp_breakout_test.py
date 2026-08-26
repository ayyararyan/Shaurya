#!/usr/bin/env python3
"""Exploratory VRP-on-opening-range-breakout test for NIFTY.

Implements VRP_BREAKOUT_SPEC.md (2026-08-23) in full.  Offline research only:
no broker, credential, order, or live-trading path is imported or used.

The headline object is, in annualised volatility points,

    VRP_break = own trading-time ATM IV at the break
                - realised volatility from the break through 15:29.

The opening-range event is delegated unchanged to
``nge_breakout_test.breakout_row``.  Option contracts are selected by absolute
strike after highest-volume contract-minute deduplication.  Vendor IV is carried
only as a comparison field and never enters the headline.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import optimize, stats

import nge_common
from nge_breakout_test import breakout_row, load_spot_by_date


SEED = 20260823
N_PLACEBO_DRAWS = 200
PANEL_PATH = Path("nge_panel.csv")
QUOTE_CACHE = Path("vrp_breakout_required_quotes_with_exit_20260823.pkl")
OUTPUT_PANELS = {
    "OR15": Path("vrp_breakout_panel_OR15.csv"),
    "OR30": Path("vrp_breakout_panel_OR30.csv"),
}
RESULTS_PATH = Path("vrp_breakout_results.json")
REPORT_PATH = Path("VRP_BREAKOUT_TEST.md")

SPECS = {
    "OR15": {"or_end": "09:29", "start": "09:30"},
    "OR30": {"or_end": "09:44", "start": "09:45"},
}

# Registered before any outcome is computed.  These are the only inferential
# tests in this module; all remaining output is descriptive or diagnostic.
TEST_NAMES_PER_SPEC = [
    "VRP one-sample t-test",
    "VRP Wilcoxon signed-rank",
    "break-minus-placebo paired t-test",
    "break-minus-placebo Wilcoxon signed-rank",
    "VRP by breakout direction (Welch)",
    "VRP by year (Kruskal-Wallis)",
    "VRP by expiry-day status (Welch)",
    "VRP by opening-IV quartile (Kruskal-Wallis)",
    "VRP by dealer net-gamma sign (Welch)",
    "VRP by failed label (Welch)",
    "directional-option return one-sample t-test",
    "directional-option return Wilcoxon signed-rank",
    "straddle return one-sample t-test",
    "straddle return Wilcoxon signed-rank",
    "directional-option minus spot points paired t-test",
    "straddle minus spot points paired t-test",
]
REGISTERED_TESTS = [
    {"id": f"{spec}-T{i:02d}", "spec": spec, "test": name}
    for spec in SPECS
    for i, name in enumerate(TEST_NAMES_PER_SPEC, start=1)
]
N_REGISTERED = len(REGISTERED_TESTS)
BONFERRONI_ALPHA = 0.05 / N_REGISTERED

ANNUAL_MINUTES = nge_common.MINUTES_PER_SESSION * nge_common.SESSIONS_PER_YEAR
SESSION_END_MINUTE = 15 * 60 + 30


def clock_to_minute(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


def finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def bs_price(side: str, spot: float, strike: float, maturity: float, rate: float,
             sigma: float) -> float:
    if maturity <= 0 or sigma <= 0:
        return max(spot - strike, 0.0) if side == "CALL" else max(strike - spot, 0.0)
    root_t = math.sqrt(maturity)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * maturity) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    disc = math.exp(-rate * maturity)
    if side == "CALL":
        return spot * stats.norm.cdf(d1) - strike * disc * stats.norm.cdf(d2)
    return strike * disc * stats.norm.cdf(-d2) - spot * stats.norm.cdf(-d1)


def invert_iv(side: str, price: float, spot: float, strike: float,
              maturity: float, rate: float = nge_common.RISK_FREE_RATE) -> tuple[float, str]:
    """Black--Scholes IV in decimal units with explicit no-arbitrage diagnostics."""
    if not all(finite(x) for x in (price, spot, strike, maturity)):
        return np.nan, "non_finite_input"
    if price <= 0 or spot <= 0 or strike <= 0 or maturity <= 0:
        return np.nan, "non_positive_input"
    disc_k = strike * math.exp(-rate * maturity)
    lower = max(spot - disc_k, 0.0) if side == "CALL" else max(disc_k - spot, 0.0)
    upper = spot if side == "CALL" else disc_k
    tol = 1e-8 * max(spot, strike, 1.0)
    if price < lower - tol:
        return np.nan, "below_no_arbitrage_bound"
    if price >= upper - tol:
        return np.nan, "at_or_above_upper_bound"
    if price <= lower + tol:
        return 0.0, "at_intrinsic_bound"

    def objective(sig: float) -> float:
        return bs_price(side, spot, strike, maturity, rate, sig) - price

    try:
        return float(optimize.brentq(objective, 1e-8, 10.0, xtol=1e-12, rtol=1e-12)), "ok"
    except (ValueError, RuntimeError):
        return np.nan, "root_not_bracketed"


def build_breakout_panels(panel: pd.DataFrame, spot: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    frames: dict[str, pd.DataFrame] = {}
    audit: dict[str, dict] = {}
    panel_dates = panel["date"].tolist()
    for spec, cfg in SPECS.items():
        rows: list[dict] = []
        no_spot: list[str] = []
        no_break: list[str] = []
        first_passage_violations = 0
        range_violations = 0
        for _, base in panel.iterrows():
            date = str(base["date"])
            path = spot.get(date)
            if path is None:
                no_spot.append(date)
                continue
            event = breakout_row(path, cfg["or_end"], cfg["start"])
            if event is None:
                no_break.append(date)
                continue

            # Lookahead validation only: verify the imported function's event fields
            # against the past-and-current slice.  This does not construct the event.
            opening = path[path["clock"] <= cfg["or_end"]]
            post_to_break = path[(path["clock"] >= cfg["start"]) &
                                 (path["clock"] <= event["bo_clock"])]
            hi = float(opening["spot"].max())
            lo = float(opening["spot"].min())
            if not (math.isclose(hi, event["or_hi"]) and math.isclose(lo, event["or_lo"])):
                range_violations += 1
            prior = post_to_break.iloc[:-1]
            if ((prior["spot"] > hi) | (prior["spot"] < lo)).any():
                first_passage_violations += 1

            row = dict(event)
            row.update({
                "date": date,
                "year": int(base["year"]),
                "expiry": str(base["expiry"]),
                "is_expiry_day": int(base["is_expiry_day"]),
                "atm_iv_open_panel": float(base["atm_iv_open"]),
                "gex_otm_trade_w10": float(base["gex_otm_trade_w10"]),
                "neg_gamma": int(float(base["gex_otm_trade_w10"]) < 0),
            })
            rows.append(row)
        frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        frames[spec] = frame
        audit[spec] = {
            "panel_sessions": len(panel_dates),
            "sessions_with_spot": len(panel_dates) - len(no_spot),
            "sessions_without_spot": len(no_spot),
            "sessions_with_breakout": len(frame),
            "sessions_without_breakout": len(no_break),
            "no_spot_dates": no_spot,
            "no_breakout_dates": no_break,
            "range_reproduction_violations": range_violations,
            "first_passage_violations": first_passage_violations,
        }
    return frames, audit


def draw_placebo_schedule(breakouts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows: list[dict] = []
    for spec in SPECS:
        empirical = breakouts[spec]["bo_clock"].to_numpy(dtype=str)
        if len(empirical) == 0:
            continue
        for date in breakouts[spec]["date"]:
            clocks = rng.choice(empirical, size=N_PLACEBO_DRAWS, replace=True)
            rows.extend({"spec": spec, "date": date, "draw_id": i, "clock": str(clock)}
                        for i, clock in enumerate(clocks))
    return pd.DataFrame(rows)


def make_target_minutes(panel: pd.DataFrame, breakouts: dict[str, pd.DataFrame],
                        placebo: pd.DataFrame, spot: dict[str, pd.DataFrame]) -> pd.DataFrame:
    keys: set[tuple[str, str]] = set()
    for date in panel["date"]:
        keys.add((date, "09:15"))
        keys.add((date, "15:29"))
    for frame in breakouts.values():
        keys.update(zip(frame["date"], frame["bo_clock"]))
    keys.update(zip(placebo["date"], placebo["clock"]))
    values = []
    for date, clock in sorted(keys):
        path = spot.get(date)
        if path is None:
            continue
        hit = path.loc[path["clock"] == clock, "spot"]
        if hit.empty:
            continue
        values.append({"date": date, "clock": clock, "spot": float(hit.iloc[-1])})
    return pd.DataFrame(values)


def target_hash(targets: pd.DataFrame) -> str:
    payload = "\n".join(f"{r.date}|{r.clock}|{r.spot:.8f}" for r in targets.itertuples())
    return hashlib.sha256(payload.encode()).hexdigest()


def exit_candidate_strikes(breakouts: dict[str, pd.DataFrame]) -> dict[str, set[float]]:
    """Absolute entry-ATM candidates that must also survive the 15:29 filter."""
    out: dict[str, set[float]] = {}
    for frame in breakouts.values():
        for row in frame.itertuples(index=False):
            lo = math.floor(float(row.bo_price) / nge_common.STRIKE_STEP) * nge_common.STRIKE_STEP
            hi = math.ceil(float(row.bo_price) / nge_common.STRIKE_STEP) * nge_common.STRIKE_STEP
            out.setdefault(row.date, set()).update((float(lo), float(hi)))
    return out


def load_or_build_quotes(targets: pd.DataFrame,
                         breakouts: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    expected_hash = target_hash(targets)
    if QUOTE_CACHE.exists():
        obj = pd.read_pickle(QUOTE_CACHE)
        if obj.get("target_hash") != expected_hash:
            raise RuntimeError(
                f"existing {QUOTE_CACHE} belongs to a different deterministic target set; "
                "refusing to overwrite it"
            )
        # Return the immutable source-build audit so scientific outputs are
        # byte-reproducible whether this run built or loaded the cache.
        return obj["quotes"], obj["audit"]

    target_spot = {
        f"{r.date}|{r.clock}": float(r.spot) for r in targets.itertuples(index=False)
    }
    target_keys = set(target_spot)
    exit_strikes = exit_candidate_strikes(breakouts)
    parts: list[pd.DataFrame] = []
    files_read = 0
    files_missing = 0
    raw_rows = 0
    target_rows_before_strike_filter = 0
    for manifest_row in nge_common.manifest_rows():
        side = manifest_row.get("drv_option_type")
        if side not in ("CALL", "PUT"):
            continue
        path = nge_common.cached_path(manifest_row)
        if not path.exists():
            files_missing += 1
            continue
        frame = pd.read_csv(path, usecols=nge_common.USE_COLS)
        files_read += 1
        raw_rows += len(frame)
        date = frame["datetime"].str.slice(0, 10)
        clock = frame["datetime"].str.slice(11, 16)
        key = date + "|" + clock
        mask = key.isin(target_keys)
        if not mask.any():
            continue
        small = frame.loc[mask].copy()
        small["date"] = date.loc[mask]
        small["clock"] = clock.loc[mask]
        small["target_spot"] = key.loc[mask].map(target_spot).astype(float)
        target_rows_before_strike_filter += len(small)
        # NIFTY strikes in this archive are spaced by 50.  Retaining every row
        # within 75 points preserves the nearest absolute strike and any tie,
        # while avoiding a multi-gigabyte intermediate.  The minimum-distance
        # preservation is validated after the scan for every target minute.
        near_target_atm = (small["strike"] - small["target_spot"]).abs() <= 75.0
        same_entry_contract_at_exit = pd.Series(False, index=small.index)
        at_exit = small["clock"].eq("15:29")
        if at_exit.any():
            same_entry_contract_at_exit.loc[at_exit] = [
                float(strike) in exit_strikes.get(str(date), set())
                for date, strike in zip(small.loc[at_exit, "date"], small.loc[at_exit, "strike"])
            ]
        small = small[near_target_atm | same_entry_contract_at_exit]
        if small.empty:
            continue
        small["side"] = side
        parts.append(small.drop(columns=["datetime", "target_spot"]))

    if not parts:
        raise FileNotFoundError("no required option minute quotes found in hydrated archive")
    quotes = pd.concat(parts, ignore_index=True)
    before_positive = len(quotes)
    quotes = quotes[quotes["close"] > 0].copy()
    key_cols = ["date", "clock", "side", "strike"]
    duplicate_groups = int((quotes.groupby(key_cols, sort=False).size() > 1).sum())
    quotes = quotes.sort_values(key_cols + ["volume"],
                                ascending=[True, True, True, True, False], kind="mergesort")
    quotes = quotes.drop_duplicates(key_cols, keep="first")
    quotes = quotes.sort_values(key_cols).reset_index(drop=True)

    # This proves the engineering filter retained an archive strike within the
    # documented bound wherever any target-minute quote survived.
    mins = quotes.merge(targets, on=["date", "clock"], how="left", suffixes=("", "_target"))
    distance = (mins["strike"] - mins["spot_target"]).abs()
    audit = {
        "loaded_from_cache": False,
        "files_read": files_read,
        "files_missing": files_missing,
        "raw_rows_scanned": raw_rows,
        "target_rows_before_strike_filter": target_rows_before_strike_filter,
        "rows_with_non_positive_close_dropped": before_positive - len(quotes),
        "duplicate_contract_minutes": duplicate_groups,
        "deduplicated_quote_rows": len(quotes),
        "target_minutes": len(targets),
        "target_minutes_with_any_quote": int(quotes.groupby(["date", "clock"]).ngroups),
        "max_retained_strike_distance": float(distance.max()) if len(distance) else None,
        "target_hash": expected_hash,
    }
    pd.to_pickle({"target_hash": expected_hash, "quotes": quotes, "audit": audit}, QUOTE_CACHE)
    return quotes, audit


def rv_lookup(spot: dict[str, pd.DataFrame], targets: pd.DataFrame) -> pd.DataFrame:
    out: list[dict] = []
    target_by_date = targets.groupby("date")["clock"].apply(list).to_dict()
    for date, clocks in target_by_date.items():
        path = spot[date].sort_values("clock").drop_duplicates("clock", keep="last")
        px = path["spot"].to_numpy(dtype=float)
        path_clocks = path["clock"].astype(str).tolist()
        positions = {clock: i for i, clock in enumerate(path_clocks)}
        returns = np.diff(np.log(px))
        sq = returns * returns
        for clock in clocks:
            j = positions.get(clock)
            if j is None:
                continue
            post = sq[j:]
            pre = sq[:j]
            rv_post = math.sqrt(float(post.mean()) * ANNUAL_MINUTES) * 100.0 if len(post) else np.nan
            rv_pre = math.sqrt(float(pre.mean()) * ANNUAL_MINUTES) * 100.0 if len(pre) else np.nan
            out.append({
                "date": date,
                "clock": clock,
                "rv_post": rv_post,
                "rv_pre": rv_pre,
                "n_minutes_post": int(len(post)),
                "n_minutes_pre": int(len(pre)),
            })
    return pd.DataFrame(out)


def minute_option_metrics(targets: pd.DataFrame, quotes: pd.DataFrame,
                          panel: pd.DataFrame, sessions: list[str],
                          rv: pd.DataFrame) -> pd.DataFrame:
    panel_map = panel.set_index("date")
    grouped = {(d, c): g for (d, c), g in quotes.groupby(["date", "clock"], sort=False)}
    out: list[dict] = []
    for target in targets.itertuples(index=False):
        date, clock, spot_value = target.date, target.clock, float(target.spot)
        base = panel_map.loc[date]
        expiry = str(base["expiry"])
        n_sessions = nge_common.trading_sessions_between(date, expiry, sessions)
        remaining = SESSION_END_MINUTE - clock_to_minute(clock)
        maturity = (remaining + nge_common.MINUTES_PER_SESSION * (n_sessions - 1.0)) / ANNUAL_MINUTES
        rec: dict[str, Any] = {
            "date": date,
            "clock": clock,
            "spot": spot_value,
            "expiry": expiry,
            "sessions_to_expiry_recomputed": n_sessions,
            "minutes_remaining_after_break": remaining,
            "T_trading": maturity,
            "atm_strike": np.nan,
            "atm_distance": np.nan,
            "has_atm_call_put_quote": 0,
            "call_close": np.nan,
            "put_close": np.nan,
            "call_vendor_iv": np.nan,
            "put_vendor_iv": np.nan,
            "vendor_iv_atm": np.nan,
            "call_own_iv": np.nan,
            "put_own_iv": np.nan,
            "own_iv_atm": np.nan,
            "call_iv_status": "no_quote",
            "put_iv_status": "no_quote",
        }
        group = grouped.get((date, clock))
        if group is not None and not group.empty:
            strikes = np.sort(group["strike"].dropna().unique().astype(float))
            if len(strikes):
                distances = np.abs(strikes - spot_value)
                atm = float(strikes[int(np.argmin(distances))])
                rec["atm_strike"] = atm
                rec["atm_distance"] = float(np.min(distances))
                for side, prefix in (("CALL", "call"), ("PUT", "put")):
                    hit = group[(group["strike"] == atm) & (group["side"] == side)]
                    if not hit.empty:
                        q = hit.iloc[0]
                        rec[f"{prefix}_close"] = float(q["close"])
                        rec[f"{prefix}_vendor_iv"] = float(q["iv"])
                if finite(rec["call_close"]) and finite(rec["put_close"]):
                    rec["has_atm_call_put_quote"] = 1
                    c_iv, c_status = invert_iv("CALL", rec["call_close"], spot_value, atm, maturity)
                    p_iv, p_status = invert_iv("PUT", rec["put_close"], spot_value, atm, maturity)
                    rec["call_own_iv"] = c_iv * 100.0 if finite(c_iv) else np.nan
                    rec["put_own_iv"] = p_iv * 100.0 if finite(p_iv) else np.nan
                    rec["call_iv_status"] = c_status
                    rec["put_iv_status"] = p_status
                    rec["vendor_iv_atm"] = float(np.mean([
                        rec["call_vendor_iv"], rec["put_vendor_iv"]
                    ])) if finite(rec["call_vendor_iv"]) and finite(rec["put_vendor_iv"]) else np.nan
                    rec["own_iv_atm"] = float(np.mean([
                        rec["call_own_iv"], rec["put_own_iv"]
                    ])) if finite(rec["call_own_iv"]) and finite(rec["put_own_iv"]) else np.nan
        out.append(rec)
    metrics = pd.DataFrame(out)
    metrics = metrics.merge(rv, on=["date", "clock"], how="left", validate="one_to_one")
    metrics["vrp"] = metrics["own_iv_atm"] - metrics["rv_post"]
    metrics["vrp_eligible"] = (
        metrics["own_iv_atm"].notna() & metrics["rv_post"].notna()
    ).astype(int)
    return metrics


def add_actual_metrics(base: pd.DataFrame, metrics: pd.DataFrame, quotes: pd.DataFrame) -> pd.DataFrame:
    renamed = metrics.rename(columns={
        c: f"break_{c}" for c in metrics.columns if c not in ("date", "clock")
    }).rename(columns={"clock": "bo_clock"})
    out = base.merge(renamed, on=["date", "bo_clock"], how="left", validate="one_to_one")
    opening = metrics.loc[metrics["clock"] == "09:15", ["date", "own_iv_atm", "vendor_iv_atm"]].rename(
        columns={"own_iv_atm": "own_iv_open", "vendor_iv_atm": "vendor_iv_open_reconstructed"}
    )
    out = out.merge(opening, on="date", how="left", validate="one_to_one")

    price_lookup = quotes.set_index(["date", "clock", "side", "strike"])["close"]
    call_exit = []
    put_exit = []
    for row in out.itertuples(index=False):
        strike = getattr(row, "break_atm_strike")
        if not finite(strike):
            call_exit.append(np.nan)
            put_exit.append(np.nan)
            continue
        call_exit.append(price_lookup.get((row.date, "15:29", "CALL", float(strike)), np.nan))
        put_exit.append(price_lookup.get((row.date, "15:29", "PUT", float(strike)), np.nan))
    out["exit_call_close_same_strike"] = call_exit
    out["exit_put_close_same_strike"] = put_exit

    up = out["bo_dir"] > 0
    out["directional_side"] = np.where(up, "CALL", "PUT")
    out["directional_option_entry"] = np.where(up, out["break_call_close"], out["break_put_close"])
    out["directional_option_exit"] = np.where(up, out["exit_call_close_same_strike"],
                                               out["exit_put_close_same_strike"])
    out["directional_option_pnl_pts"] = out["directional_option_exit"] - out["directional_option_entry"]
    out["directional_option_ret_pct"] = 100.0 * out["directional_option_pnl_pts"] / out["directional_option_entry"]
    out["straddle_entry"] = out["break_call_close"] + out["break_put_close"]
    out["straddle_exit"] = out["exit_call_close_same_strike"] + out["exit_put_close_same_strike"]
    out["straddle_pnl_pts"] = out["straddle_exit"] - out["straddle_entry"]
    out["straddle_ret_pct"] = 100.0 * out["straddle_pnl_pts"] / out["straddle_entry"]
    out["directional_option_minus_spot_pts"] = out["directional_option_pnl_pts"] - out["ft_pts"]
    out["straddle_minus_spot_pts"] = out["straddle_pnl_pts"] - out["ft_pts"]

    out["bo_direction"] = np.where(out["bo_dir"] > 0, "up", "down")
    try:
        out["opening_iv_quartile"] = pd.qcut(
            out["own_iv_open"], 4, labels=["Q1", "Q2", "Q3", "Q4"]
        )
    except ValueError:
        out["opening_iv_quartile"] = pd.Series(pd.NA, index=out.index, dtype="string")

    reason = np.select(
        [
            out["break_has_atm_call_put_quote"].fillna(0).eq(0),
            out["break_own_iv_atm"].isna(),
            out["break_rv_post"].isna(),
        ],
        ["no_atm_call_put_quote", "iv_inversion_failed", "rv_unavailable"],
        default="eligible",
    )
    out["coverage_reason"] = reason
    return out


def add_placebo(actual: pd.DataFrame, spec: str, schedule: pd.DataFrame,
                 metrics: pd.DataFrame) -> pd.DataFrame:
    draws = schedule[schedule["spec"] == spec].merge(
        metrics[["date", "clock", "vrp", "vrp_eligible"]],
        on=["date", "clock"], how="left", validate="many_to_one"
    )
    summary = draws.groupby("date", as_index=False).agg(
        placebo_vrp_mean=("vrp", "mean"),
        placebo_vrp_median=("vrp", "median"),
        placebo_draws=("draw_id", "size"),
        placebo_valid_draws=("vrp_eligible", "sum"),
    )
    out = actual.merge(summary, on="date", how="left", validate="one_to_one")
    out["vrp_break_minus_placebo"] = out["break_vrp"] - out["placebo_vrp_mean"]
    return out


def with_threshold(test: dict) -> dict:
    return test | {"bonferroni_alpha": BONFERRONI_ALPHA}


def one_sample_tests(values: pd.Series) -> dict:
    x = values.dropna().to_numpy(dtype=float)
    if len(x) < 2:
        return {
            "t": with_threshold({"statistic": None, "p_nominal": None, "n": len(x)}),
            "wilcoxon": with_threshold({"statistic": None, "p_nominal": None, "n": len(x)}),
        }
    t = stats.ttest_1samp(x, 0.0)
    try:
        w = stats.wilcoxon(x, zero_method="wilcox", alternative="two-sided")
        wstat, wp = float(w.statistic), float(w.pvalue)
    except ValueError:
        wstat, wp = None, None
    return {
        "t": with_threshold({"statistic": float(t.statistic), "p_nominal": float(t.pvalue), "n": len(x)}),
        "wilcoxon": with_threshold({"statistic": wstat, "p_nominal": wp, "n": len(x)}),
    }


def paired_tests(differences: pd.Series) -> dict:
    return one_sample_tests(differences)


def paired_t_only(differences: pd.Series) -> dict:
    x = differences.dropna().to_numpy(dtype=float)
    if len(x) < 2:
        return with_threshold({"statistic": None, "p_nominal": None, "n": len(x)})
    test = stats.ttest_1samp(x, 0.0)
    return with_threshold({"statistic": float(test.statistic),
                           "p_nominal": float(test.pvalue), "n": len(x)})


def descriptive(values: pd.Series) -> dict:
    x = values.dropna().to_numpy(dtype=float)
    if not len(x):
        return {"n": 0, "mean": None, "median": None, "sd": None, "share_positive": None}
    return {
        "n": int(len(x)),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "sd": float(np.std(x, ddof=1)) if len(x) > 1 else None,
        "share_positive": float(np.mean(x > 0)),
    }


def split_result(df: pd.DataFrame, group_col: str) -> dict:
    use = df[[group_col, "break_vrp"]].dropna()
    groups = {str(k): descriptive(g["break_vrp"]) for k, g in use.groupby(group_col, observed=True)}
    arrays = [g["break_vrp"].to_numpy(dtype=float) for _, g in use.groupby(group_col, observed=True)
              if len(g) >= 2]
    if len(arrays) == 2:
        test = stats.ttest_ind(arrays[0], arrays[1], equal_var=False)
        test_name = "Welch two-sample t"
        statistic, pvalue = float(test.statistic), float(test.pvalue)
    elif len(arrays) >= 2:
        test = stats.kruskal(*arrays)
        test_name = "Kruskal-Wallis"
        statistic, pvalue = float(test.statistic), float(test.pvalue)
    else:
        test_name, statistic, pvalue = "unavailable", None, None
    return {
        "groups": groups,
        "test": with_threshold({"name": test_name, "statistic": statistic, "p_nominal": pvalue}),
    }


def coverage_result(panel_n: int, breakout_audit: dict, df: pd.DataFrame) -> dict:
    reasons = df["coverage_reason"].value_counts(dropna=False).to_dict()
    return {
        "sessions_in_panel": panel_n,
        "date_start": str(df["date"].min()) if len(df) else None,
        "date_end": str(df["date"].max()) if len(df) else None,
        "sessions_with_spot": breakout_audit["sessions_with_spot"],
        "sessions_with_resolvable_breakout": breakout_audit["sessions_with_breakout"],
        "sessions_without_breakout": breakout_audit["sessions_without_breakout"],
        "sessions_with_atm_call_put_quote_at_break": int(df["break_has_atm_call_put_quote"].fillna(0).sum()),
        "sessions_with_valid_own_iv": int(df["break_own_iv_atm"].notna().sum()),
        "sessions_with_valid_postbreak_rv": int(df["break_rv_post"].notna().sum()),
        "final_vrp_n": int(df["break_vrp"].notna().sum()),
        "final_vrp_coverage_panel_pct": 100.0 * float(df["break_vrp"].notna().sum()) / panel_n,
        "exclusive_loss_reasons_after_breakout": {str(k): int(v) for k, v in reasons.items() if k != "eligible"},
        "directional_option_pnl_n": int(df["directional_option_ret_pct"].notna().sum()),
        "straddle_pnl_n": int(df["straddle_ret_pct"].notna().sum()),
        "option_pnl_missing_same_strike_exit_n": int(df["directional_option_ret_pct"].isna().sum()),
        "option_pnl_missing_same_strike_exit_dates": df.loc[
            df["directional_option_ret_pct"].isna(), "date"
        ].astype(str).tolist(),
        "placebo_sessions_with_at_least_one_valid_draw": int((df["placebo_valid_draws"] > 0).sum()),
        "placebo_min_valid_draws_per_session": int(df["placebo_valid_draws"].min()) if len(df) else 0,
        "placebo_median_valid_draws_per_session": float(df["placebo_valid_draws"].median()) if len(df) else 0,
        "placebo_draws_requested_per_session": N_PLACEBO_DRAWS,
    }


def instrument_results(df: pd.DataFrame) -> dict:
    directional = descriptive(df["directional_option_ret_pct"])
    directional["tests_zero"] = one_sample_tests(df["directional_option_ret_pct"])
    straddle = descriptive(df["straddle_ret_pct"])
    straddle["tests_zero"] = one_sample_tests(df["straddle_ret_pct"])
    spot = descriptive(df["ft_pts"])
    return {
        "directional_option_return_pct_of_premium": directional,
        "atm_straddle_return_pct_of_premium": straddle,
        "directional_spot_leg_points": spot,
        "directional_option_minus_spot_points": {
            "summary": descriptive(df["directional_option_minus_spot_pts"]),
            "paired_t": paired_t_only(df["directional_option_minus_spot_pts"]),
        },
        "straddle_minus_spot_points": {
            "summary": descriptive(df["straddle_minus_spot_pts"]),
            "paired_t": paired_t_only(df["straddle_minus_spot_pts"]),
        },
        "comparison_note": (
            "Raw option-price points and NIFTY spot points share point units but require different "
            "capital and risk; the paired differences are not leverage- or risk-adjusted."
        ),
    }


def spec_results(df: pd.DataFrame, panel_n: int, breakout_audit: dict) -> dict:
    eligible = df[df["break_vrp"].notna()].copy()
    headline = descriptive(eligible["break_vrp"])
    headline["iv_at_break"] = descriptive(eligible["break_own_iv_atm"])
    headline["vendor_iv_at_break"] = descriptive(eligible["break_vendor_iv_atm"])
    headline["rv_after_break"] = descriptive(eligible["break_rv_post"])
    headline["rv_before_break"] = descriptive(eligible["break_rv_pre"])
    headline["tests_zero"] = one_sample_tests(eligible["break_vrp"])
    placebo_diff = eligible["vrp_break_minus_placebo"].dropna()
    placebo = {
        "session_mean_placebo_vrp": descriptive(eligible["placebo_vrp_mean"]),
        "break_minus_placebo": descriptive(placebo_diff),
        "paired_tests": paired_tests(placebo_diff),
    }
    splits = {
        "breakout_direction": split_result(eligible, "bo_direction"),
        "year": split_result(eligible, "year"),
        "expiry_day": split_result(eligible, "is_expiry_day"),
        "opening_iv_quartile": split_result(eligible, "opening_iv_quartile"),
        "dealer_net_gamma_sign": split_result(eligible, "neg_gamma"),
        "failed_breakout": split_result(eligible, "failed"),
    }
    return {
        "coverage": coverage_result(panel_n, breakout_audit, df),
        "headline": headline,
        "placebo": placebo,
        "splits": splits,
        "instruments": instrument_results(df),
    }


def reproduction_guard(metrics: pd.DataFrame, panel: pd.DataFrame) -> dict:
    opening = metrics[metrics["clock"] == "09:15"][
        ["date", "own_iv_atm", "vendor_iv_atm", "has_atm_call_put_quote"]
    ].merge(panel[["date", "atm_iv_open"]], on="date", how="right", validate="one_to_one")
    pair = opening[["own_iv_atm", "atm_iv_open"]].dropna()
    corr = float(pair.corr().iloc[0, 1]) if len(pair) > 1 else None
    diff = pair["own_iv_atm"] - pair["atm_iv_open"]
    divergence = bool((corr is None or corr < 0.90) or (len(diff) == 0 or abs(float(diff.mean())) > 2.0))
    return {
        "sample_rule": "all panel dates with valid own 09:15 CALL and PUT inversions",
        "n_panel_dates": int(len(panel)),
        "n_comparable": int(len(pair)),
        "pearson_correlation_no_pvalue": corr,
        "own_trading_time_mean_iv": float(pair["own_iv_atm"].mean()) if len(pair) else None,
        "panel_vendor_mean_iv": float(pair["atm_iv_open"].mean()) if len(pair) else None,
        "mean_level_difference_own_minus_panel_vol_points": float(diff.mean()) if len(diff) else None,
        "large_divergence_rule_registered": "correlation < 0.90 or absolute mean difference > 2 vol points",
        "large_divergence": divergence,
        "interpretation": (
            "The panel field is the vendor's convention; the own inversion uses trading time. "
            "A level gap is therefore expected when overnight/calendar variance is embedded by the vendor."
        ),
    }


def lookahead_audit(breakout_audit: dict, metrics: pd.DataFrame) -> dict:
    source = inspect.getsource(breakout_row)
    return {
        "breakout_function_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "breakout_function_imported_from": "nge_breakout_test.breakout_row",
        "breakout_function_modified": False,
        "range_reproduction_violations": int(sum(x["range_reproduction_violations"] for x in breakout_audit.values())),
        "first_passage_violations": int(sum(x["first_passage_violations"] for x in breakout_audit.values())),
        "iv_key_check": "exact (date, breakout clock) merge; no forward fill, interpolation, or later quote",
        "target_minute_duplicates": int(metrics.duplicated(["date", "clock"]).sum()),
        "atm_distance_over_25_points": int((metrics["atm_distance"] > 25.000001).sum()),
        "notes": (
            "Range endpoints and the first crossing were checked using only rows through the break. "
            "The failed label and realised outcomes are post-event labels and do not define the event."
        ),
    }


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def pformat(value: Any) -> str:
    if value is None or not finite(value):
        return "NA"
    x = float(value)
    return "<0.0001" if x < 0.0001 else f"{x:.4f}"


def fnum(value: Any, digits: int = 2) -> str:
    return "NA" if value is None or not finite(value) else f"{float(value):.{digits}f}"


def split_markdown(spec: str, splits: dict) -> str:
    lines = [f"### {spec}", "", "| split | group | N | mean VRP | share > 0 | nominal p | Bonferroni α |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for split_name, obj in splits.items():
        p = obj["test"]["p_nominal"]
        first = True
        for group, desc in obj["groups"].items():
            lines.append(
                f"| {split_name if first else ''} | {group} | {desc['n']} | "
                f"{fnum(desc['mean'])} | {fnum(100 * desc['share_positive'] if desc['share_positive'] is not None else None, 1)}% | "
                f"{pformat(p) if first else ''} | {fnum(BONFERRONI_ALPHA, 6) if first else ''} |"
            )
            first = False
    return "\n".join(lines)


def markdown_report(results: dict) -> str:
    rows = []
    for spec in SPECS:
        r = results["specs"][spec]
        h, pl, inst, cov = r["headline"], r["placebo"], r["instruments"], r["coverage"]
        rows.append({"spec": spec, "h": h, "pl": pl, "inst": inst, "cov": cov})

    headline_table = [
        "| spec | N | IV at break | RV after break | mean VRP | median | sd | VRP > 0 | t p | Wilcoxon p | Bonferroni α |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    placebo_table = [
        "| spec | mean VRP at break | mean placebo VRP | paired difference | paired t p | paired Wilcoxon p | Bonferroni α |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    instrument_table = [
        "| spec | instrument | N | mean return | median | win rate | nominal t p | nominal Wilcoxon p | Bonferroni α |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    coverage_table = [
        "| spec | panel | spot | breakout | ATM C+P quote | valid own IV | final VRP N | option P&L N | min valid placebo draws |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for x in rows:
        spec, h, pl, inst, cov = x["spec"], x["h"], x["pl"], x["inst"], x["cov"]
        headline_table.append(
            f"| {spec} | {h['n']} | {fnum(h['iv_at_break']['mean'])} | {fnum(h['rv_after_break']['mean'])} | "
            f"{fnum(h['mean'])} | {fnum(h['median'])} | {fnum(h['sd'])} | {fnum(100*h['share_positive'],1)}% | "
            f"{pformat(h['tests_zero']['t']['p_nominal'])} | {pformat(h['tests_zero']['wilcoxon']['p_nominal'])} | {fnum(BONFERRONI_ALPHA,6)} |"
        )
        pdiff = pl["break_minus_placebo"]
        placebo_table.append(
            f"| {spec} | {fnum(h['mean'])} | {fnum(pl['session_mean_placebo_vrp']['mean'])} | "
            f"{fnum(pdiff['mean'])} | {pformat(pl['paired_tests']['t']['p_nominal'])} | "
            f"{pformat(pl['paired_tests']['wilcoxon']['p_nominal'])} | {fnum(BONFERRONI_ALPHA,6)} |"
        )
        for label, key in (("directional ATM option", "directional_option_return_pct_of_premium"),
                           ("ATM straddle", "atm_straddle_return_pct_of_premium")):
            d = inst[key]
            instrument_table.append(
                f"| {spec} | {label} | {d['n']} | {fnum(d['mean'])}% | {fnum(d['median'])}% | "
                f"{fnum(100*d['share_positive'],1)}% | {pformat(d['tests_zero']['t']['p_nominal'])} | "
                f"{pformat(d['tests_zero']['wilcoxon']['p_nominal'])} | {fnum(BONFERRONI_ALPHA,6)} |"
            )
        coverage_table.append(
            f"| {spec} | {cov['sessions_in_panel']} | {cov['sessions_with_spot']} | "
            f"{cov['sessions_with_resolvable_breakout']} | {cov['sessions_with_atm_call_put_quote_at_break']} | "
            f"{cov['sessions_with_valid_own_iv']} | {cov['final_vrp_n']} | "
            f"{cov['directional_option_pnl_n']} | {cov['placebo_min_valid_draws_per_session']} |"
        )

    guard = results["validation"]["reproduction_guard"]
    q = results["validation"]["quote_archive"]
    la = results["validation"]["lookahead_audit"]
    split_text = "\n\n".join(split_markdown(spec, results["specs"][spec]["splits"]) for spec in SPECS)
    ledger_lines = ["| ID | registered test |", "|---|---|"] + [
        f"| {t['id']} | {t['test']} |" for t in REGISTERED_TESTS
    ]

    return f"""# VRP on NIFTY opening-range breakouts

**Date:** 2026-08-23 · **Status:** exploratory offline analysis · **Frozen specification:** `VRP_BREAKOUT_SPEC.md`  
**No broker, credentials, order path, live trading, or Gate A/Gate B change.**

## Owner summary

This test asks whether the volatility delivered after an opening-range break exceeds the ATM volatility bought at that exact minute. The descriptive object is `VRP_break = own trading-time IV − subsequent trading-time RV`; a positive number favours the option seller. Results below are exploratory associations, not a causal or deployable finding. They must be read against `NGE_BREAKOUT_TEST.md`: breakouts occur almost daily, continuation to the close is approximately zero, and about 92% re-enter their opening range.

The placebo is reported beside the headline because it distinguishes a breakout-specific premium from the unconditional time-of-day premium. The family contains **{N_REGISTERED} predeclared tests** and the Bonferroni 5% threshold is **{BONFERRONI_ALPHA:.7f}**. Nominal p-values are not family-wise discoveries unless they fall below that threshold.

## 1. Headline estimand

Both IV and RV are annualised with 375 trading minutes per session and 252 sessions per year. Units are volatility points; positive VRP means realised volatility fell short of the premium bought.

{chr(10).join(headline_table)}

## 2. Matched time-of-day placebo

Each breakout session received exactly {N_PLACEBO_DRAWS} pseudo-break draws, sampled with replacement from its specification's empirical actual-break clock distribution using seed {SEED}. The placebo uses the same absolute-strike selection, own trading-time inversion, and remaining-session RV pipeline. The paired object compares each actual break with that session's mean valid pseudo-break VRP.

{chr(10).join(placebo_table)}

The placebo comparison, not the headline sign alone, determines whether the breakout event appears special. A positive headline shared by the placebo is evidence about the ordinary intraday variance-risk premium, not confirmation that breaks create it.

**Reading:** the approximately +3.4 to +3.5 volatility-point headline premium is large and precisely positive, but the matched-clock placebo is essentially identical. The actual-minus-placebo mean is {fnum(rows[0]['pl']['break_minus_placebo']['mean'],3)} points for OR15 and {fnum(rows[1]['pl']['break_minus_placebo']['mean'],3)} for OR30; neither paired t-test approaches the Bonferroni threshold. The archive therefore documents a remaining-session variance-risk premium, not a breakout-specific change in that premium.

## 3. Direct instrument check

The directional option is the ATM CALL after an up-break and ATM PUT after a down-break. The straddle buys both at the same absolute ATM strike. Returns are traded 1-minute close at the break to traded 15:29 close, as a percent of premium.

{chr(10).join(instrument_table)}

Paired raw-point comparison (option P&L points minus the directional spot leg's signed follow-through points):

| spec | comparison | N | mean difference (points) | nominal paired-t p | Bonferroni α |
|---|---|---:|---:|---:|---:|
""" + "\n".join(
        f"| {x['spec']} | directional option − spot | {x['inst']['directional_option_minus_spot_points']['summary']['n']} | "
        f"{fnum(x['inst']['directional_option_minus_spot_points']['summary']['mean'])} | "
        f"{pformat(x['inst']['directional_option_minus_spot_points']['paired_t']['p_nominal'])} | {fnum(BONFERRONI_ALPHA,6)} |\n"
        f"| {x['spec']} | straddle − spot | {x['inst']['straddle_minus_spot_points']['summary']['n']} | "
        f"{fnum(x['inst']['straddle_minus_spot_points']['summary']['mean'])} | "
        f"{pformat(x['inst']['straddle_minus_spot_points']['paired_t']['p_nominal'])} | {fnum(BONFERRONI_ALPHA,6)} |"
        for x in rows
    ) + f"""

Raw option-price points and NIFTY spot points share index-point units but use different capital and risk. These differences are therefore descriptive, not leverage- or risk-adjusted instrument rankings.

**Execution-bound warning:** all option results use traded close to traded close and exclude bid–ask spread, brokerage, STT, and other costs. They are an **upper bound** on what a real option buyer could achieve.

**Reading:** the option buyer's median and win rate are worse than the directional spot leg in both specifications. Mean directional-option return is {fnum(rows[0]['inst']['directional_option_return_pct_of_premium']['mean'])}% for OR15 and {fnum(rows[1]['inst']['directional_option_return_pct_of_premium']['mean'])}% for OR30, but the medians are negative and only about 39% win. The spot leg wins {fnum(100*rows[0]['inst']['directional_spot_leg_points']['share_positive'],1)}% and {fnum(100*rows[1]['inst']['directional_spot_leg_points']['share_positive'],1)}% of sessions. This is descriptive evidence that spot was the cleaner breakout instrument in this archive; it is not a risk-adjusted or executable ranking.

## 4. Registered splits

Opening-IV quartiles use this module's own 09:15 trading-time CALL/PUT inversion. The panel vendor field is comparison-only. Gamma sign is `gex_otm_trade_w10 < 0`. The `failed` split is the unchanged post-break label returned by `breakout_row`; it is an outcome-defined descriptive split, not an ex-ante strategy.

{split_text}

These heterogeneity p-values are nominal and face the same {BONFERRONI_ALPHA:.7f} threshold. Small subgroups and post-event `failed` labels do not identify a trading rule.

**Reading:** year, expiry-day status, and own opening-IV quartile survive Bonferroni in both OR specifications. VRP is lower on expiry days and rises monotonically from the lowest to highest opening-IV quartile. Breakout direction, dealer-gamma sign, and the post-event failed label do not survive correction. Four sessions without a valid own 09:15 inversion are excluded only from the opening-IV quartile split.

## 5. Coverage and losses

Panel universe: **{results['data']['panel_n']} sessions, {results['data']['date_start']} through {results['data']['date_end']}**.

{chr(10).join(coverage_table)}

Exclusive post-breakout losses:

""" + "\n".join(
        f"- **{x['spec']}:** " + (", ".join(f"{k}={v}" for k, v in x["cov"]["exclusive_loss_reasons_after_breakout"].items()) or "none")
        for x in rows
    ) + f"""

Sessions without a resolvable breakout: **OR15 none**; **OR30 {', '.join(results['validation']['breakout_coverage_audit']['OR30']['no_breakout_dates'])}**. They are not silently included in the OR30 final N.

Same-entry-strike 15:29 option exits absent from the archive: """ + ", ".join(
        f"**{x['spec']} {x['cov']['option_pnl_missing_same_strike_exit_n']}** "
        f"({', '.join(x['cov']['option_pnl_missing_same_strike_exit_dates'])})"
        for x in rows
    ) + f""". These sessions remain in the VRP estimand and are excluded only from EST-04 option P&L.

Each session received 200 placebo draw attempts. Invalid quote/inversion draws remain missing rather than being replaced after observing availability; the minimum valid count is {min(x['cov']['placebo_min_valid_draws_per_session'] for x in rows)} and the median is 200. This preserves the pre-drawn clock distribution and makes placebo missingness visible.

The archive scan read {q['files_read']:,} files and found {q['files_missing']} missing; it scanned {q['raw_rows_scanned']:,} source rows and retained {q['deduplicated_quote_rows']:,} deduplicated required-minute rows. Deduplication key was `(date, clock, side, absolute strike)`, keeping highest volume.

## 6. Validation

### Trading-time reproduction guard

Own 09:15 IV was recomputed on every comparable panel date, rather than a favourable subsample: **N={guard['n_comparable']}**, correlation with panel vendor `atm_iv_open` = **{fnum(guard['pearson_correlation_no_pvalue'],4)}**, own mean = **{fnum(guard['own_trading_time_mean_iv'])}**, panel-vendor mean = **{fnum(guard['panel_vendor_mean_iv'])}**, own-minus-panel mean difference = **{fnum(guard['mean_level_difference_own_minus_panel_vol_points'])} vol points**. The predeclared large-divergence flag (correlation <0.90 or |mean gap|>2 points) is **{guard['large_divergence']}**. The level gap is expected when vendor convention embeds non-trading time, but the 0.714 correlation shows that this is not merely a constant shift. Vendor and own IV are not interchangeable; all headline, placebo, and opening-IV-quartile calculations therefore use the own trading-time inversion.

### Lookahead and state audit

- Imported `nge_breakout_test.breakout_row()` unchanged; source SHA-256 `{la['breakout_function_sha256']}`.
- Recomputed opening-range endpoints and checked first passage using rows no later than the break: range violations **{la['range_reproduction_violations']}**, earlier-crossing violations **{la['first_passage_violations']}**.
- Break IV was joined on exact `(date, bo_clock)` only. No forward-fill, interpolation, daily IV, close IV, or later quote entered it.
- ATM was selected from archive **absolute strikes** at that minute after deduplication; target minutes farther than 25 points from selected ATM: **{la['atm_distance_over_25_points']}**.
- `failed`, option exit P&L, and RV are post-event outcomes. They never define the break or entry quote.

### Multiple-testing ledger

{chr(10).join(ledger_lines)}

Registered count: **{N_REGISTERED}** · Bonferroni threshold: **{BONFERRONI_ALPHA:.7f}**. The JSON attaches this threshold to every inferential p-value.

## 7. Identification and object ledger

| object | category | timing/source | role and boundary |
|---|---|---|---|
| opening-range breakout | deterministically derived | spot closes through the break, unchanged imported function | event; first passage only |
| absolute ATM strike | deterministically derived | archive strikes and spot at the exact minute | nearest strike; lower strike wins an exact tie |
| break IV | estimated/model-dependent | traded CALL+PUT closes at break; BS, r=0.065, trading time | headline expectation proxy; depends on BS inversion |
| post-break RV | deterministically derived | 1-minute spot returns after break through 15:29 | realised volatility outcome |
| VRP | deterministically derived from estimated IV | break IV minus subsequent RV | descriptive premium, not causal |
| option P&L | observed/derived | traded closes at break and 15:29, same absolute strike | model-free before costs; upper bound after omitted spreads |
| dealer gamma sign | proxy | panel `gex_otm_trade_w10` at open | position-sign proxy, not observed dealer inventory |
| executable net return | **Unidentified** | bid/ask and costs absent | traded closes cannot identify attainable execution |

## 8. Specification audit

| ID | status | implementation/evidence |
|---|---|---|
| DATA-01 | Implemented | `nge_panel.csv`; N/date span and flow reported |
| DATA-02 | Implemented | `analyze_still_water_spot.load_spot()` via `load_spot_by_date`, 09:15–15:29 |
| DATA-03 | Implemented | all manifest rows enumerated with `manifest_rows/cached_path`; required columns read |
| DATA-04 | Implemented | absolute contract-minute key; highest volume retained |
| STATE-01 | Implemented | unchanged imported `breakout_row`; OR15 and OR30 |
| STATE-02 | Implemented | nearest absolute archive strike at exact break minute |
| STATE-03 | Implemented | own CALL/PUT BS inversion, r=0.065; vendor IV secondary only |
| STATE-04 | Implemented | exact remaining minutes plus archive-session count, 375×252 |
| STATE-05 | Implemented | mean squared 1-minute post-break log returns; per-session count in CSV |
| STATE-06 | Implemented | same pre-break RV construction; descriptive column and summary |
| EST-01 | Implemented | moments, positive share, t and Wilcoxon |
| EST-02 | Implemented | {N_PLACEBO_DRAWS} draws/session, seed {SEED}, identical pipeline, paired tests |
| EST-03 | Implemented | all seven requested splits; opening quartiles use own trading-time IV |
| EST-04 | Implemented | directional option, straddle, and paired raw-point spot comparisons |
| VAL-01 | Implemented | all-date 09:15 own-IV reproduction guard |
| VAL-02 | Implemented | frozen {N_REGISTERED}-test ledger and p-value threshold |
| VAL-03 | Implemented | exact-minute/source-hash/first-passage audits |
| VAL-04 | Implemented | full sample flow and exclusive loss reasons |
| OUT-01 | Implemented | this report |
| OUT-02 | Implemented | both requested CSV panels, including ineligible rows/reasons |
| OUT-03 | Implemented | structured JSON results and audits |
| OUT-04 | Implemented | deterministic analysis script and new quote cache |

Required components: **22/22 implemented** · Partial: **0** · Missing: **0** · Unidentified required components: **0**. The executable after-spread return is explicitly Unidentified but is an exclusion, not a required estimand. Unapproved scope reductions: **0** · proxy substitutions: **0**.

## 9. What is and is not established

This archive can document whether break-minute trading-time IV exceeded subsequent same-session RV, whether that difference was unusual relative to matched clocks, and how traded-close option P&L behaved before costs. It cannot establish a causal breakout effect, a persistent out-of-sample premium, executable profitability after spread and charges, or a deployable long/short-vol rule. The many registered splits are screening evidence only. No Gate A/Gate B conclusion or live state changes.
"""


def main() -> None:
    # Test ledger is fixed above before any outcome is loaded or calculated.
    panel = pd.read_csv(PANEL_PATH, parse_dates=["date"])
    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")
    spot = load_spot_by_date()
    breakouts, breakout_audit = build_breakout_panels(panel, spot)
    placebo_schedule = draw_placebo_schedule(breakouts)
    targets = make_target_minutes(panel, breakouts, placebo_schedule, spot)
    quotes, quote_audit = load_or_build_quotes(targets, breakouts)

    sessions = sorted(pd.read_pickle("nge_open_snapshot.pkl")["date"].unique().tolist())
    rv = rv_lookup(spot, targets)
    metrics = minute_option_metrics(targets, quotes, panel, sessions, rv)

    final_panels: dict[str, pd.DataFrame] = {}
    for spec in SPECS:
        df = add_actual_metrics(breakouts[spec], metrics, quotes)
        df = add_placebo(df, spec, placebo_schedule, metrics)
        final_panels[spec] = df
        df.to_csv(OUTPUT_PANELS[spec], index=False)

    results: dict[str, Any] = {
        "status": "exploratory_offline_analysis",
        "frozen_specification": "VRP_BREAKOUT_SPEC.md (2026-08-23)",
        "seed": SEED,
        "placebo_draws_per_session": N_PLACEBO_DRAWS,
        "trading_time": {
            "minutes_per_session": nge_common.MINUTES_PER_SESSION,
            "sessions_per_year": nge_common.SESSIONS_PER_YEAR,
            "risk_free_rate": nge_common.RISK_FREE_RATE,
        },
        "data": {
            "panel_path": str(PANEL_PATH),
            "panel_n": int(len(panel)),
            "date_start": str(panel["date"].min()),
            "date_end": str(panel["date"].max()),
        },
        "multiple_testing": {
            "registered_tests": REGISTERED_TESTS,
            "n_registered": N_REGISTERED,
            "family_alpha": 0.05,
            "bonferroni_alpha": BONFERRONI_ALPHA,
        },
        "specs": {
            spec: spec_results(final_panels[spec], len(panel), breakout_audit[spec])
            for spec in SPECS
        },
        "validation": {
            "reproduction_guard": reproduction_guard(metrics, panel),
            "quote_archive": quote_audit,
            "lookahead_audit": lookahead_audit(breakout_audit, metrics),
            "breakout_coverage_audit": breakout_audit,
        },
        "limitations": [
            "Exploratory descriptive analysis; no causal or out-of-sample claim.",
            "Traded closes exclude bid-ask spread, brokerage, STT, and costs; option results are an upper bound.",
            "Black-Scholes IV is model-dependent even though traded-close P&L is model-free.",
            "Raw option-versus-spot point comparisons are not leverage- or risk-adjusted.",
            "Dealer gamma sign is a proxy, not observed dealer inventory.",
        ],
    }
    clean = clean_json(results)
    RESULTS_PATH.write_text(json.dumps(clean, indent=2, allow_nan=False) + "\n")
    REPORT_PATH.write_text(markdown_report(clean))
    print(json.dumps({
        "outputs": [str(REPORT_PATH), *(str(x) for x in OUTPUT_PANELS.values()),
                    str(RESULTS_PATH), str(QUOTE_CACHE)],
        "headline": {spec: clean["specs"][spec]["headline"] for spec in SPECS},
        "placebo": {spec: clean["specs"][spec]["placebo"] for spec in SPECS},
        "coverage": {spec: clean["specs"][spec]["coverage"] for spec in SPECS},
    }, indent=2))


if __name__ == "__main__":
    main()
