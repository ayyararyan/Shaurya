#!/usr/bin/env python3
"""Shared construction for the Gate-B reversal CALL real-premium validation.

New module.  It does not modify, and is not imported by, any pre-existing script.

Gate B, exactly as specified in ``GAP_FILL_SIGNAL_MODULE_SPEC.md``:

    NOT an expiry day  AND  gap direction DOWN  AND  India VIX rose overnight
    AND  opening IV bucket == middle_14_18  AND  the gap fills (spot returns to or
    through the prior session's 15:29 close) at some minute strictly after 09:17.

    Trade: buy one ATM NIFTY CALL (strike = fill-minute spot rounded to the nearest 50)
    at the fill minute, nearest weekly expiry.  Incumbent exit: hold to 15:29.

Two premium series are constructed for every trade:

* ``bs_prices``   -- the Black-Scholes proxy the project has been relying on, rebuilt to
  match ``bs_gap_fill_pnl.py`` byte for byte in construction: ATM strike fixed at the fill
  minute, that day's OPENING implied volatility held CONSTANT for the whole session,
  ``RISK_FREE_RATE``, time to the actual holiday-adjusted next weekly expiry.  Because IV
  is frozen, this series is structurally incapable of showing any intraday volatility
  change, including the opening volatility crush.

* ``real_prices`` -- traded one-minute bar CLOSES for the ACTUAL entry strike, tracked
  through the session.  The strike is held fixed and looked up by its absolute value, so
  this does NOT repeat the earlier data bug where the labelled "ATM" series rolled strike
  mid-session.  Sourced from the local Dhan minute cache (ATM-10 .. ATM+10 CALL files).
  ``real_iv`` carries the same contract's own implied volatility minute by minute.

Both series share one index: the minute clocks from entry to 15:29 on which a traded bar
for the tracked strike exists.  Where the tracked strike is not quoted the real series
carries NaN and the trade is treated as unpriceable at that minute.

The wider universe (all non-expiry gap-down days whose gap fills after 09:17, with the
Gate-B membership label retained) is built too, so a shuffled-label placebo can permute
Gate-B membership while preserving N, the CALL direction, the time-of-day distribution of
entries, chronology and the entire exit machinery.

Offline analysis only.  No broker, credential, exchange network, or order path is used
anywhere in this module.  No live order is authorised.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_still_water_spot import load_spot
from bs_gap_fill_pnl import RISK_FREE_RATE, STRIKE_STEP, bs_call, next_expiry
from ml_gated_put_call import build_dataset

CACHE = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options"
)
MANIFEST = CACHE / "manifest.jsonl"

PATH_CACHE = Path("gate_b_paths.pkl")
QUOTE_CACHE = Path("gate_b_call_quotes.pkl")

ENTRY_FLOOR_CLOCK = "09:17"   # the fill must occur strictly after this minute
SESSION_END_CLOCK = "15:29"

# Fixed-clock exits requested for the exit grid, plus hold-to-close (``None``).
CLOCK_EXITS: tuple[str | None, ...] = (
    "10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "15:00", None,
)


def clock_to_minutes(clock: str) -> int:
    hh, mm = clock.split(":")
    return int(hh) * 60 + int(mm)


# --------------------------------------------------------------------------------------
# traded CALL minute bars
# --------------------------------------------------------------------------------------

def manifest_rows() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def cached_path(row: dict) -> Path:
    return CACHE / str(row["from_date"])[:4] / Path(str(row["path"])).name


def load_call_quotes(rebuild: bool = False) -> pd.DataFrame:
    """Every hydrated CALL minute bar, keyed by date / clock / absolute strike."""
    if QUOTE_CACHE.exists() and not rebuild:
        return pd.read_pickle(QUOTE_CACHE)
    frames = []
    for row in manifest_rows():
        if row.get("drv_option_type") != "CALL":
            continue
        path = cached_path(row)
        if not path.exists():
            continue
        frames.append(
            pd.read_csv(
                path,
                usecols=["close", "iv", "strike", "datetime", "rel_strike", "spot", "volume", "oi"],
            )
        )
    if not frames:
        raise FileNotFoundError("no hydrated CALL minute files found in the local cache")
    quotes = pd.concat(frames, ignore_index=True)
    quotes["datetime"] = pd.to_datetime(quotes["datetime"], errors="raise")
    quotes["date"] = quotes["datetime"].dt.strftime("%Y-%m-%d")
    quotes["clock"] = quotes["datetime"].dt.strftime("%H:%M")
    quotes["minutes"] = quotes["datetime"].dt.hour * 60 + quotes["datetime"].dt.minute
    quotes = quotes[quotes["close"] > 0]
    # One row per (date, minute, absolute strike).  Different rel_strike files can carry
    # the same absolute strike at the same minute; they are the same contract.
    quotes = quotes.sort_values(["date", "minutes", "strike", "volume"], ascending=[1, 1, 1, 0])
    quotes = quotes.drop_duplicates(subset=["date", "clock", "strike"], keep="first")
    quotes = quotes[["date", "clock", "minutes", "strike", "close", "iv", "spot", "volume", "oi"]]
    quotes.to_pickle(QUOTE_CACHE)
    return quotes


# --------------------------------------------------------------------------------------
# path construction
# --------------------------------------------------------------------------------------

def build_paths() -> list[dict]:
    """All non-expiry gap-down days whose gap fills after 09:17.

    ``is_gate_b`` marks the subset that additionally satisfies the overnight VIX rise and
    the mid opening-IV bucket -- the label the placebo permutes.
    """
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    expiry_dates = sorted(cal["actual_expiry"].dt.date.tolist())

    df = build_dataset()
    candidates = (
        df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down")]
        .copy()
        .sort_values("date")
        .reset_index(drop=True)
    )
    candidates["date_str"] = candidates["date"].dt.strftime("%Y-%m-%d")

    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    dm["date_str"] = dm["date"].dt.strftime("%Y-%m-%d")
    candidates = candidates.merge(
        dm[["date_str", "prior_session_1529_spot"]], on="date_str", how="left"
    )

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= SESSION_END_CLOCK)].copy()

    quotes = load_call_quotes()
    by_date = {d: g for d, g in quotes.groupby("date")}

    paths: list[dict] = []
    for _, day in candidates.iterrows():
        date_str = day["date_str"]
        prior_close = day["prior_session_1529_spot"]
        opening_iv_pct = day["opening_iv"]
        if pd.isna(prior_close) or pd.isna(opening_iv_pct):
            continue
        opening_iv = float(opening_iv_pct) / 100.0

        path = spot[spot["date"] == date_str].sort_values("clock")
        if path.empty:
            continue
        after = path[path["clock"] > ENTRY_FLOOR_CLOCK].reset_index(drop=True)
        fill = after[after["spot"] >= prior_close]
        if fill.empty:
            continue                                  # gap never fills -> Gate B stands aside

        entry_row = fill.iloc[0]
        entry_clock = str(entry_row["clock"])
        S0 = float(entry_row["spot"])
        K = float(round(S0 / STRIKE_STEP) * STRIKE_STEP)

        trade_date = pd.to_datetime(date_str).date()
        expiry = next_expiry(trade_date, expiry_dates)
        if expiry is None:
            continue
        expiry_dt = pd.Timestamp(expiry) + pd.Timedelta(hours=15, minutes=30)
        entry_dt = pd.Timestamp(f"{date_str} {entry_clock}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0_bs = bs_call(S0, K, T0, RISK_FREE_RATE, opening_iv)
        if not np.isfinite(C0_bs) or C0_bs <= 0:
            continue

        rest = path[path["clock"] >= entry_clock].reset_index(drop=True)
        clocks = [str(c) for c in rest["clock"]]
        spots = rest["spot"].astype(float).to_numpy()
        entry_minute = clock_to_minutes(entry_clock)
        elapsed = np.asarray([clock_to_minutes(c) - entry_minute for c in clocks], dtype=int)

        bs_prices = np.asarray(
            [
                bs_call(
                    float(s),
                    K,
                    max(
                        (expiry_dt - pd.Timestamp(f"{date_str} {c}:00")).total_seconds()
                        / (365.0 * 24 * 3600),
                        1e-6,
                    ),
                    RISK_FREE_RATE,
                    opening_iv,
                )
                for c, s in zip(clocks, spots)
            ],
            dtype=float,
        )

        # --- traded bars for the tracked strike, aligned onto the same clock index ---
        real_prices = np.full(len(clocks), np.nan)
        real_iv = np.full(len(clocks), np.nan)
        day_quotes = by_date.get(date_str)
        if day_quotes is not None:
            tracked = day_quotes[day_quotes["strike"] == K]
            if not tracked.empty:
                px = dict(zip(tracked["clock"], tracked["close"]))
                iv = dict(zip(tracked["clock"], tracked["iv"]))
                for i, c in enumerate(clocks):
                    if c in px:
                        real_prices[i] = float(px[c])
                        v = float(iv[c])
                        real_iv[i] = v if v > 0 else np.nan

        # running-ATM implied volatility for the whole session: an observed surface-level
        # series that does not depend on the tracked strike surviving.
        atm_iv_clocks: list[str] = []
        atm_iv_vals: list[float] = []
        if day_quotes is not None:
            full_day = spot[spot["date"] == date_str].sort_values("clock")
            spot_by_clock = dict(zip(full_day["clock"].astype(str), full_day["spot"].astype(float)))
            for c, s in spot_by_clock.items():
                k_atm = float(round(s / STRIKE_STEP) * STRIKE_STEP)
                hit = day_quotes[(day_quotes["clock"] == c) & (day_quotes["strike"] == k_atm)]
                if hit.empty:
                    continue
                v = float(hit["iv"].iloc[0])
                if v > 0:
                    atm_iv_clocks.append(c)
                    atm_iv_vals.append(v)

        is_gate_b = int(
            (int(day["vix_rose"]) == 1) and (str(day["iv_bucket"]) == "middle_14_18")
        )

        paths.append(
            {
                "date": date_str,
                "is_gate_b": is_gate_b,
                "vix_rose": int(day["vix_rose"]),
                "iv_bucket": str(day["iv_bucket"]),
                "reversed": bool(day["initial_high_first"] != day["target_high_first"]),
                "entry_clock": entry_clock,
                "entry_minute": entry_minute,
                "S0": S0,
                "K": K,
                "opening_iv": opening_iv,
                "expiry": str(expiry),
                "T0_days": T0 * 365.0,
                "C0_bs": float(C0_bs),
                "prior_close": float(prior_close),
                "clocks": clocks,
                "elapsed": elapsed,
                "spots": spots,
                "bs_prices": bs_prices,
                "real_prices": real_prices,
                "real_iv": real_iv,
                "atm_iv_clocks": atm_iv_clocks,
                "atm_iv_vals": np.asarray(atm_iv_vals, dtype=float),
            }
        )
    return paths


def load_paths(rebuild: bool = False) -> list[dict]:
    if PATH_CACHE.exists() and not rebuild:
        with PATH_CACHE.open("rb") as handle:
            return pickle.load(handle)
    paths = build_paths()
    with PATH_CACHE.open("wb") as handle:
        pickle.dump(paths, handle)
    return paths


def gate_b_subset(paths: list[dict]) -> list[dict]:
    return [p for p in paths if p["is_gate_b"] == 1]


# --------------------------------------------------------------------------------------
# exit machinery
# --------------------------------------------------------------------------------------

def clock_exit_index(path: dict, clock: str | None) -> int:
    """Index of the last observed minute at or before ``clock``; ``None`` means close.

    Convention for a fire that occurs AFTER the clock (four of the 33 Gate-B entries are
    at 12:50 or later): the clock cap has already passed at entry, so the position runs to
    the close.  This keeps N constant across every clock variant instead of silently
    dropping the late-filling days, and it is what the incumbent hold-to-close rule would
    do anyway.  ``gate_b_exit_grid_real.py`` reports the traded-only convention -- where
    those days are excluded rather than held -- as a declared sensitivity.
    """
    if clock is None:
        return len(path["clocks"]) - 1
    limit = clock_to_minutes(clock)
    if limit <= path["entry_minute"]:
        return len(path["clocks"]) - 1
    minutes = path["entry_minute"] + path["elapsed"]
    eligible = np.flatnonzero(minutes <= limit)
    if len(eligible) == 0:
        return len(path["clocks"]) - 1
    return int(eligible[-1])


def horizon_exit_index(path: dict, offset: int) -> int:
    """Index of the last observed minute at or before ``offset`` minutes after ENTRY."""
    eligible = np.flatnonzero(path["elapsed"] <= offset)
    if len(eligible) == 0:
        return 0
    return int(eligible[-1])


def rule_return(
    path: dict,
    series: str,
    stop: float | None = None,
    target: float | None = None,
    clock: str | None = None,
    offset: int | None = None,
) -> float:
    """Percentage return of one trade under a mechanical exit rule.

    ``series`` is ``"bs_prices"`` or ``"real_prices"``.  Exit priority is stop, then
    target, then the fixed clock, then hold to the last priced minute -- the same priority
    order used throughout this project.  Stops and targets are evaluated on the SAME series
    that is being valued, so the rule is executable within that series.

    Returns NaN when the series cannot price the entry, or cannot price the exit minute.
    """
    prices = path[series]
    if offset is not None:
        last = horizon_exit_index(path, offset)
    else:
        last = clock_exit_index(path, clock)
    if last < 0:
        return np.nan
    C0 = prices[0]
    if not np.isfinite(C0) or C0 <= 0:
        return np.nan

    exit_i = None
    for i in range(last + 1):
        px = prices[i]
        if not np.isfinite(px):
            continue
        ret = (px - C0) / C0
        if stop is not None and ret <= -stop:
            exit_i = i
            break
        if target is not None and ret >= target:
            exit_i = i
            break
    if exit_i is None:
        # no threshold hit: exit at the last PRICED minute at or before the clock limit
        priced = np.flatnonzero(np.isfinite(prices[: last + 1]))
        if len(priced) == 0:
            return np.nan
        exit_i = int(priced[-1])
        # A hold-to-clock exit is only honest if the series is still quoted near that
        # clock.  Allow a two-minute grace, matching the Gate-A cross-check convention.
        if (last - exit_i) > 2:
            return np.nan
    return (prices[exit_i] - C0) / C0 * 100.0


def rule_returns(
    paths: list[dict],
    series: str,
    stop: float | None = None,
    target: float | None = None,
    clock: str | None = None,
    offset: int | None = None,
) -> np.ndarray:
    return np.asarray(
        [rule_return(p, series, stop, target, clock, offset) for p in paths], dtype=float
    )


# --------------------------------------------------------------------------------------
# reproduction guard
# --------------------------------------------------------------------------------------

def reproduction_guard(gate: list[dict]) -> None:
    """Refuse to proceed unless the published Gate-B construction is recovered.

    The published artifacts are N = 33 fires out of 56 mid-IV Gate-B days, and the three
    trailing-stop means in ``bs_gap_fill_trades.csv`` produced by ``bs_gap_fill_pnl.py``.
    """
    if len(gate) != 33:
        raise AssertionError(f"Expected 33 Gate-B fires, got {len(gate)}")

    published = pd.read_csv("bs_gap_fill_trades.csv")
    ours = {p["date"]: p for p in gate}
    theirs = published[published["stop_pct"] == 0.15]
    if set(theirs["date"]) != set(ours):
        missing = set(theirs["date"]) - set(ours)
        extra = set(ours) - set(theirs["date"])
        raise AssertionError(f"fire set differs: missing={sorted(missing)} extra={sorted(extra)}")
    for _, row in theirs.iterrows():
        p = ours[row["date"]]
        if p["entry_clock"] != row["entry_clock"]:
            raise AssertionError(
                f"{row['date']}: entry clock {p['entry_clock']} != published {row['entry_clock']}"
            )
        if not np.isclose(p["K"], row["K"]):
            raise AssertionError(f"{row['date']}: strike {p['K']} != published {row['K']}")
        if not np.isclose(p["C0_bs"], row["C0"], rtol=1e-6):
            raise AssertionError(
                f"{row['date']}: BS entry premium {p['C0_bs']:.4f} != published {row['C0']:.4f}"
            )

    # Reproduce the published trailing-stop means on the Black-Scholes series.
    for stop_pct in (0.15, 0.20, 0.25):
        want = published[published["stop_pct"] == stop_pct]["return_pct"].mean()
        got = []
        for p in gate:
            prices = p["bs_prices"]
            C0 = prices[0]
            peak = C0
            exit_price = prices[-1]
            for px in prices:
                peak = max(peak, px)
                if peak > 0 and (peak - px) / peak >= stop_pct:
                    exit_price = px
                    break
            got.append((exit_price - C0) / C0 * 100.0)
        got = float(np.mean(got))
        if not np.isclose(got, want, atol=0.06):
            raise AssertionError(
                f"trailing stop {stop_pct:.0%} no longer reproduces {want:.2f}%: got {got:.2f}%"
            )

    # Reproduce the fixed-clock exit numbers published in GAP_FILL_SIGNAL_MODULE_SPEC.md.
    # Those were never persisted to a script, so they are pinned here from the spec text.
    # They reproduce ONLY under the traded-only convention -- a day whose gap fills after
    # the exit clock is not traded at all -- which is therefore the convention the
    # published Gate-B evidence uses.
    published_clocks = {
        "10:00": (-11.9, 0.013), "10:30": (-13.2, 0.006), "11:00": (-10.9, 0.018),
        "12:00": (-13.1, 0.045), "13:00": (-13.2, 0.044), "14:00": (-7.7, 0.282),
    }
    from scipy import stats as _stats

    for clock, (want_mean, want_p) in published_clocks.items():
        limit = clock_to_minutes(clock)
        keep = [p for p in gate if p["entry_minute"] < limit]
        r = np.asarray(
            [rule_return(p, "bs_prices", None, None, clock) for p in keep], dtype=float
        )
        r = r[np.isfinite(r)]
        got_mean = float(r.mean())
        got_p = float(_stats.ttest_1samp(r, 0.0).pvalue)
        if not np.isclose(got_mean, want_mean, atol=0.06):
            raise AssertionError(
                f"clock exit {clock} no longer reproduces the published {want_mean}%: "
                f"got {got_mean:.2f}%"
            )
        if not np.isclose(got_p, want_p, atol=0.001):
            raise AssertionError(
                f"clock exit {clock} no longer reproduces the published p={want_p}: "
                f"got {got_p:.4f}"
            )
    r = np.asarray([rule_return(p, "bs_prices") for p in gate], dtype=float)
    if not np.isclose(float(r.mean()), 1.8, atol=0.06):
        raise AssertionError(
            f"hold-to-close no longer reproduces the published +1.8%: got {r.mean():.2f}%"
        )


if __name__ == "__main__":
    quotes = load_call_quotes(rebuild=True)
    print(f"hydrated CALL minute bars: {len(quotes):,} over {quotes['date'].nunique():,} dates")
    paths = load_paths(rebuild=True)
    gate = gate_b_subset(paths)
    reproduction_guard(gate)
    print(f"non-expiry gap-down days whose gap fills after 09:17 : {len(paths)}")
    print(f"Gate-B fires (VIX rose + mid opening-IV bucket)       : {len(gate)}")
    print(f"Gate-B date range                                    : {gate[0]['date']} .. {gate[-1]['date']}")
    priced_entry = sum(np.isfinite(p["real_prices"][0]) for p in gate)
    priced_close = sum(np.isfinite(rule_return(p, "real_prices")) for p in gate)
    print(f"Gate-B fires with a traded entry bar at the tracked strike : {priced_entry}/{len(gate)}")
    print(f"Gate-B fires priceable on real premiums at 15:29           : {priced_close}/{len(gate)}")
    print("Reproduction guard: PASSED "
          "(fire set, entry clocks, strikes, BS entry premiums and all three published "
          "trailing-stop means recovered)")
