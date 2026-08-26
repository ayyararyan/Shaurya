#!/usr/bin/env python3
"""Full-hydration path cache for the Gate-B population study.

New module.  It does not modify any pre-existing script and it does not overwrite the
caches used by ``gate_b_common.py``; it redirects that module's cache constants to
separate files so both can coexist.

Why a second cache exists
-------------------------
The published Gate B is 33 fires in one opening-IV bucket, and the ATM/ATM+/-1 CALL files
were enough to price those.  The scope-addition question -- whether the mid-IV filter is
real -- needs the SAME trade priced on all 120 gap-fill fires in the three-condition
parent population (non-expiry, gap-down, overnight VIX rise, N=198 days).  Those fires
include much larger moves, so the entry strike drifts up to nine strikes away from the
running ATM label.  Every relative-strike CALL file required to follow the entry strike
from the fill minute to 15:29 on all 120 fires was staged from the source archive before
this cache was built, so the real-premium series is NOT hydration-thinned and there is no
"the missing days are the big movers" bias in what follows.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path

import gate_b_common as gbc

FULL_QUOTE_CACHE = Path("gate_b_call_quotes_full.pkl")
FULL_PATH_CACHE = Path("gate_b_paths_full.pkl")


def _redirect() -> None:
    gbc.QUOTE_CACHE = FULL_QUOTE_CACHE
    gbc.PATH_CACHE = FULL_PATH_CACHE


def load_full_paths(rebuild: bool = False) -> list[dict]:
    _redirect()
    if FULL_PATH_CACHE.exists() and not rebuild:
        with FULL_PATH_CACHE.open("rb") as handle:
            return pickle.load(handle)
    paths = gbc.build_paths()
    tmp = FULL_PATH_CACHE.with_suffix(".incoming")
    with tmp.open("wb") as handle:
        pickle.dump(paths, handle)
    os.replace(tmp, FULL_PATH_CACHE)
    return paths


def load_full_quotes(rebuild: bool = False):
    _redirect()
    return gbc.load_call_quotes(rebuild=rebuild)


if __name__ == "__main__":
    import numpy as np

    quotes = load_full_quotes(rebuild=True)
    print(f"hydrated CALL minute bars: {len(quotes):,} over {quotes['date'].nunique():,} dates")
    paths = load_full_paths(rebuild=True)
    gate = gbc.gate_b_subset(paths)
    gbc.reproduction_guard(gate)
    print(f"non-expiry gap-down days whose gap fills after 09:17 : {len(paths)}")
    print(f"  of which overnight VIX rose (the Gate-B parent)    : "
          f"{sum(p['vix_rose'] == 1 for p in paths)}")
    print(f"  of which also mid opening-IV (published Gate B)    : {len(gate)}")
    fires = [p for p in paths if p["vix_rose"] == 1]
    entry_ok = sum(np.isfinite(p["real_prices"][0]) for p in fires)
    close_ok = sum(np.isfinite(gbc.rule_return(p, "real_prices")) for p in fires)
    print(f"real strike-tracked entry bar available : {entry_ok}/{len(fires)}")
    print(f"real strike-tracked close exit priceable: {close_ok}/{len(fires)}")
    share = np.asarray([np.isfinite(p["real_prices"]).mean() for p in fires])
    print(f"median share of session minutes quoted at the tracked strike: {np.median(share)*100:.1f}%")
    print(f"fires with <95% of minutes quoted: {(share < 0.95).sum()}")
    print("Reproduction guard: PASSED")
