#!/usr/bin/env python3
"""Black-Scholes theoretical option P&L for the Gate-B gap-fill CALL trade.

Aryan's point: we don't need historical option-chain premium data for this test -- we
already have the real spot minute path, the day's opening IV, and the actual weekly
expiry calendar. That's enough to compute a theoretical option price at every minute via
Black-Scholes and simulate a trailing-stop exit against it.

Trade definition (Gate B, N=56 mid-IV non-expiry gap-down VIX-rise days):
- Only trade the 33 days where the gap actually fills (per the gap-fill signal already
  found -- 28 true reversals, 5 false fires; skip the 23 no-fill days, no edge there).
- Entry: at the gap-fill moment, buy one ATM CALL (strike = spot rounded to nearest 50),
  theoretical premium via Black-Scholes using that moment's spot, the day's opening IV
  (held constant intraday -- a simplifying assumption), a fixed risk-free rate, and time
  to the actual next weekly expiry (from k2_expiry_calendar.csv, holiday-adjusted).
- Exit: trailing stop on the theoretical premium -- track the running peak premium since
  entry; exit the first time premium drops (peak - current)/peak >= stop_pct. If never
  triggered, exit at 15:29 (session close). Tested at stop_pct in {15%, 20%, 25%}.
"""
from __future__ import annotations

import sys
import math
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from analyze_still_water_spot import load_spot
from ml_gated_put_call import build_dataset

RISK_FREE_RATE = 0.065
STRIKE_STEP = 50
STOP_PCTS = [0.15, 0.20, 0.25]


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(S, K, T, r, sigma):
    if T <= 0:
        return max(S - K, 0.0)
    if sigma <= 0:
        return max(S - K * math.exp(-r * T), 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def next_expiry(trade_date, expiry_dates):
    future = [e for e in expiry_dates if e >= trade_date]
    return min(future) if future else None


def main():
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    expiry_dates = sorted(cal["actual_expiry"].dt.date.tolist())

    df = build_dataset()
    gate_b = df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)].copy()
    mid = gate_b[gate_b["iv_bucket"] == "middle_14_18"].copy().sort_values("date").reset_index(drop=True)
    mid["date_str"] = mid["date"].dt.strftime("%Y-%m-%d")
    mid["reversed"] = mid["initial_high_first"] != mid["target_high_first"]

    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    dm["date_str"] = dm["date"].dt.strftime("%Y-%m-%d")
    mid = mid.merge(dm[["date_str", "prior_session_1529_spot"]], on="date_str", how="left")

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    trades = []
    for _, day in mid.iterrows():
        d = day["date_str"]
        prior_close = day["prior_session_1529_spot"]
        opening_iv = day["opening_iv"] / 100.0
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty or pd.isna(prior_close):
            continue
        after = path[path["clock"] > "09:17"].reset_index(drop=True)
        fill = after[after["spot"] >= prior_close]
        if fill.empty:
            continue  # only trade gap-fill days
        entry_row = fill.iloc[0]
        entry_clock = entry_row["clock"]
        S0 = float(entry_row["spot"])
        K = round(S0 / STRIKE_STEP) * STRIKE_STEP
        trade_date = pd.to_datetime(d).date()
        exp = next_expiry(trade_date, expiry_dates)
        if exp is None:
            continue
        expiry_dt = pd.Timestamp(exp) + pd.Timedelta(hours=15, minutes=30)
        entry_dt = pd.Timestamp(f"{d} {entry_clock}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0 = bs_call(S0, K, T0, RISK_FREE_RATE, opening_iv)
        if C0 <= 0:
            continue

        rest = path[path["clock"] >= entry_clock].reset_index(drop=True)
        path_prices = []
        for _, r in rest.iterrows():
            t_dt = pd.Timestamp(f"{d} {r['clock']}:00")
            T = max((expiry_dt - t_dt).total_seconds() / (365.0 * 24 * 3600), 1e-6)
            C = bs_call(float(r["spot"]), K, T, RISK_FREE_RATE, opening_iv)
            path_prices.append((r["clock"], C))

        for stop_pct in STOP_PCTS:
            peak = C0
            exit_price = path_prices[-1][1]
            exit_clock = path_prices[-1][0]
            for clock, C in path_prices:
                peak = max(peak, C)
                if peak > 0 and (peak - C) / peak >= stop_pct:
                    exit_price = C
                    exit_clock = clock
                    break
            ret = (exit_price - C0) / C0
            trades.append({
                "date": d, "reversed": bool(day["reversed"]), "stop_pct": stop_pct,
                "entry_clock": entry_clock, "exit_clock": exit_clock,
                "S0": S0, "K": K, "T0_days": T0 * 365, "opening_iv": opening_iv,
                "C0": C0, "exit_price": exit_price, "return_pct": ret * 100,
            })

    trades_df = pd.DataFrame(trades)
    trades_df.to_csv("bs_gap_fill_trades.csv", index=False)

    print(f"Total gap-fill trade-days: {trades_df['date'].nunique()} "
          f"(of {mid['date'].nunique()} mid-IV Gate-B days)")
    print()
    for stop_pct in STOP_PCTS:
        sub = trades_df[trades_df["stop_pct"] == stop_pct]
        rev = sub[sub["reversed"]]
        cont = sub[~sub["reversed"]]
        print(f"=== Trailing stop {stop_pct*100:.0f}% ===")
        print(f"  ALL {len(sub)} trades: mean return={sub['return_pct'].mean():.2f}%  "
              f"median={sub['return_pct'].median():.2f}%  win rate={(sub['return_pct']>0).mean()*100:.1f}%")
        print(f"  On TRUE reversal days (N={len(rev)}): mean={rev['return_pct'].mean():.2f}%  "
              f"median={rev['return_pct'].median():.2f}%  win rate={(rev['return_pct']>0).mean()*100:.1f}%")
        print(f"  On FALSE-fire (continued) days (N={len(cont)}): mean={cont['return_pct'].mean():.2f}%  "
              f"median={cont['return_pct'].median():.2f}%  win rate={(cont['return_pct']>0).mean()*100:.1f}%")
        # simple t-test
        from scipy import stats
        if len(sub) > 1:
            t, p = stats.ttest_1samp(sub["return_pct"], 0)
            print(f"  t-test mean return != 0: t={t:.2f}, p={p:.4f}")
        print()

    print("Sample of trades (first stop level):")
    print(trades_df[trades_df["stop_pct"] == STOP_PCTS[0]][
        ["date", "reversed", "entry_clock", "exit_clock", "T0_days", "C0", "exit_price", "return_pct"]
    ].to_string())


if __name__ == "__main__":
    main()
