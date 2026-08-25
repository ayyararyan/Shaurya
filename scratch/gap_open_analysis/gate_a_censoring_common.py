#!/usr/bin/env python3
"""Shared path construction for the Gate-A PUT holding-horizon censoring study.

New module.  It does not modify, and is not imported by, any pre-existing script.

It rebuilds the *same* Black-Scholes premium construction used by
``bs_gate_a_put_stop_take.py`` (ATM strike fixed at the 09:17 spot, that day's opening
implied volatility held constant all session, expiry at 15:30 the same day, the same
risk-free rate and strike step), and additionally stores two counterfactual premium
paths needed for the theta decomposition:

* ``prices_spot_only``  -- premium repriced at each minute's spot but with time to
  expiry FROZEN at its 09:17 value.  Movement in this series is attributable to the
  underlying's move alone (delta and gamma), with no time decay.
* ``prices_decay_only`` -- premium repriced at each minute's time to expiry but with
  spot FROZEN at its 09:17 value.  Movement in this series is pure time decay.

Because the source construction holds implied volatility constant at the opening value,
an implied-volatility-change component is **not identified** in this proxy.  Whatever
the market's intraday volatility path did is absorbed into the (unobserved) difference
between this proxy and an executable premium.  See GATE_A_HORIZON_CENSORING.md.

The universe built here is ALL expiry-day gap-down candidate paths (the wider set), with
the observed overnight-VIX-rise label retained, exactly as
``walkforward_gate_a_put_stop_take.py`` does, so the same shuffled-label placebo is
available.

No broker, credential, network, or order path is used anywhere in this module.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_still_water_spot import load_spot
from bs_gap_fill_pnl import RISK_FREE_RATE, STRIKE_STEP, bs_call
from ml_gated_put_call import build_dataset

ENTRY_CLOCK = "09:17"
CACHE = Path("gate_a_censoring_paths.pkl")

# Hard exit horizons in minutes after the 09:17 entry.  ``None`` means hold to close.
HORIZONS: tuple[int | None, ...] = (10, 15, 20, 25, 30, 40, 45, 60, 90, None)


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put from the existing call helper via put-call parity."""
    return bs_call(S, K, T, r, sigma) - S + K * np.exp(-r * T)


def _clock_to_minutes(clock: str) -> int:
    hh, mm = clock.split(":")
    return int(hh) * 60 + int(mm)


def build_paths() -> list[dict]:
    """All expiry-day gap-down PUT paths; ``vix_rose`` retained as the Gate-A label."""
    df = build_dataset()
    candidates = (
        df[(df["is_expiry_day"] == 1) & (df["gap_dir"] == "down")]
        .copy()
        .sort_values("date")
        .reset_index(drop=True)
    )
    candidates["date_str"] = candidates["date"].dt.strftime("%Y-%m-%d")

    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    dm["date_str"] = dm["date"].dt.strftime("%Y-%m-%d")
    candidates = candidates.merge(
        dm[["date_str", "prior_session_1529_spot"]],
        on="date_str",
        how="left",
        validate="one_to_one",
    )

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    entry_minute = _clock_to_minutes(ENTRY_CLOCK)
    paths: list[dict] = []
    for _, day in candidates.iterrows():
        date_str = day["date_str"]
        prior_close = day["prior_session_1529_spot"]
        opening_iv = day["opening_iv"] / 100.0
        path = spot[spot["date"] == date_str].sort_values("clock")
        if path.empty or pd.isna(prior_close) or pd.isna(opening_iv):
            continue
        entry_row = path.loc[path["clock"] == ENTRY_CLOCK]
        if entry_row.empty:
            continue

        S0 = float(entry_row["spot"].iloc[0])
        K = round(S0 / STRIKE_STEP) * STRIKE_STEP
        expiry_dt = pd.Timestamp(f"{date_str} 15:30:00")
        entry_dt = pd.Timestamp(f"{date_str} {ENTRY_CLOCK}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0 = bs_put(S0, K, T0, RISK_FREE_RATE, opening_iv)
        if not np.isfinite(C0) or C0 <= 0:
            continue

        rest = path[path["clock"] >= ENTRY_CLOCK].reset_index(drop=True)
        prices: list[float] = []
        prices_spot_only: list[float] = []
        prices_decay_only: list[float] = []
        spots: list[float] = []
        clocks: list[str] = []
        elapsed: list[int] = []
        for _, row in rest.iterrows():
            clock = row["clock"]
            now = pd.Timestamp(f"{date_str} {clock}:00")
            T = max((expiry_dt - now).total_seconds() / (365.0 * 24 * 3600), 1e-6)
            S = float(row["spot"])
            prices.append(bs_put(S, K, T, RISK_FREE_RATE, opening_iv))
            prices_spot_only.append(bs_put(S, K, T0, RISK_FREE_RATE, opening_iv))
            prices_decay_only.append(bs_put(S0, K, T, RISK_FREE_RATE, opening_iv))
            spots.append(S)
            clocks.append(clock)
            elapsed.append(_clock_to_minutes(clock) - entry_minute)

        gap_fill_idx = None
        for i, S in enumerate(spots):
            if S >= prior_close:
                gap_fill_idx = i
                break

        paths.append(
            {
                "date": date_str,
                "vix_rose": int(day["vix_rose"]),
                "S0": S0,
                "K": K,
                "opening_iv": opening_iv,
                "T0_minutes": T0 * 365.0 * 24 * 60,
                "C0": C0,
                "prior_close": float(prior_close),
                "clocks": clocks,
                "elapsed": np.asarray(elapsed, dtype=int),
                "spots": np.asarray(spots, dtype=float),
                "prices": np.asarray(prices, dtype=float),
                "prices_spot_only": np.asarray(prices_spot_only, dtype=float),
                "prices_decay_only": np.asarray(prices_decay_only, dtype=float),
                "gap_fill_idx": gap_fill_idx,
            }
        )
    return paths


def load_paths(rebuild: bool = False) -> list[dict]:
    if CACHE.exists() and not rebuild:
        with CACHE.open("rb") as handle:
            return pickle.load(handle)
    paths = build_paths()
    with CACHE.open("wb") as handle:
        pickle.dump(paths, handle)
    return paths


def gate_a_subset(paths: list[dict]) -> list[dict]:
    return [p for p in paths if p["vix_rose"] == 1]


def horizon_exit_index(path: dict, horizon: int | None) -> int:
    """Index of the last observed minute at or before ``horizon`` minutes after entry.

    ``horizon=None`` means hold to the last available minute (session close).
    """
    if horizon is None:
        return len(path["prices"]) - 1
    eligible = np.flatnonzero(path["elapsed"] <= horizon)
    return int(eligible[-1])


def reproduction_guard(gate_paths: list[dict]) -> None:
    """Refuse to proceed unless the published in-sample numbers are reproduced."""
    if len(gate_paths) != 55:
        raise AssertionError(f"Expected 55 Gate-A PUT paths, got {len(gate_paths)}")

    def rule_returns(stop, target, gap_fill=True, horizon=None):
        out = []
        for p in gate_paths:
            C0 = p["C0"]
            prices = p["prices"]
            last = horizon_exit_index(p, horizon)
            exit_i = last
            for i in range(last + 1):
                ret = (prices[i] - C0) / C0
                if stop is not None and ret <= -stop:
                    exit_i = i
                    break
                if target is not None and ret >= target:
                    exit_i = i
                    break
                if gap_fill and p["gap_fill_idx"] is not None and i == p["gap_fill_idx"]:
                    exit_i = i
                    break
            out.append((prices[exit_i] - C0) / C0 * 100.0)
        return np.asarray(out)

    baseline = rule_returns(None, None)
    if not np.isclose(baseline.mean(), 39.0, atol=0.06):
        raise AssertionError(
            f"gap-fill-only baseline no longer reproduces +39.0%: got {baseline.mean():.2f}%"
        )
    expected = {
        (0.30, 0.50): 25.8, (0.30, 0.75): 31.2, (0.30, 1.00): 34.9,
        (0.50, 0.50): 22.7, (0.50, 0.75): 28.2, (0.50, 1.00): 31.6,
        (0.60, 0.50): 23.1, (0.60, 0.75): 29.4, (0.60, 1.00): 33.0,
    }
    for (sl, tp), want in expected.items():
        got = rule_returns(sl, tp).mean()
        if not np.isclose(got, want, atol=0.06):
            raise AssertionError(
                f"cell -{sl*100:.0f}/+{tp*100:.0f} no longer reproduces {want}%: got {got:.2f}%"
            )


if __name__ == "__main__":
    paths = load_paths(rebuild=True)
    gate = gate_a_subset(paths)
    reproduction_guard(gate)
    print(f"expiry-day gap-down candidate paths : {len(paths)}")
    print(f"Gate-A (VIX rose) PUT paths         : {len(gate)}")
    print(f"Gate-A date range                   : {gate[0]['date']} .. {gate[-1]['date']}")
    gaps = [int(np.max(np.diff(p['elapsed']))) for p in gate]
    print(f"max minute gap inside a Gate-A path : {max(gaps)} minute(s)")
    print(f"paths with any gap > 1 minute       : {sum(g > 1 for g in gaps)} of {len(gate)}")
    print("Reproduction guard: PASSED (baseline +39.0% and all nine published cells recovered)")
