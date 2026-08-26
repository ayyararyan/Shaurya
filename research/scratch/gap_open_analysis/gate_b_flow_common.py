#!/usr/bin/env python3
"""Volume / open-interest / true-OHLC data layer for the Gate-B population study.

New module.  It does not modify, and is not imported by, any pre-existing script.  It builds
its own caches under new filenames so nothing already on disk is touched.

Why this module exists
----------------------
Every analysis in this project so far has consumed exactly two columns of the Dhan minute
archive: ``close`` and ``spot``.  The archive also carries ``open``, ``high``, ``low``,
``volume`` and ``oi``, for CALL **and** PUT, at every one of the 21 relative strikes it
stages.  Those five columns are genuinely unused information rather than another re-slice of
the price path that has already been searched to exhaustion.

Three facts about the source that materially shape the construction:

1.  **The relative-strike label rolls intraday.**  A file named ``ATM+6`` does not carry one
    contract: on 2022-02-25 its ``strike`` column jumps 16850 -> 16800 -> 16850 -> 16900 ->
    ... minute by minute as the running ATM label chases spot.  Everything here is therefore
    keyed on the **absolute** ``strike`` value, never on the relative label.  This is the same
    defect ``gate_b_common.py`` documents, and it is fatal to any OI series built on the
    label: the OI column of a single rel-strike file swings from 16,700 to 567,000 inside one
    session purely because it is describing different contracts.

2.  **``volume`` is per-bar, not cumulative.**  Verified: the within-day first difference is
    non-negative on only 49% of bars, which is impossible for a running total.

3.  **``oi`` is a snapshot of the contract's open interest at that minute.**  Held at the
    absolute-strike level it is slow-moving, as open interest should be.

Coverage is restricted to the dates that appear in the 264-path Gate-B pool, which keeps the
cache to a workable size without dropping a single day the study can use.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json
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

FLOW_QUOTE_CACHE = Path("gate_b_flow_quotes.pkl")
FLOW_AUDIT_CACHE = Path("gate_b_flow_quotes_audit.json")

USE_COLS = [
    "open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot",
    "datetime", "rel_strike",
]


def manifest_rows() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def cached_path(row: dict) -> Path:
    return CACHE / str(row["from_date"])[:4] / Path(str(row["path"])).name


def build_flow_quotes(keep_dates: set[str]) -> tuple[pd.DataFrame, dict]:
    """Every hydrated CALL and PUT minute bar on ``keep_dates``, keyed by absolute strike.

    Returns the deduplicated frame plus an audit dict recording exactly what was dropped and
    how much the duplicate rel-strike files disagreed before deduplication.
    """
    frames: list[pd.DataFrame] = []
    files_read = 0
    files_missing = 0
    for row in manifest_rows():
        side = row.get("drv_option_type")
        if side not in ("CALL", "PUT"):
            continue
        path = cached_path(row)
        if not path.exists():
            files_missing += 1
            continue
        frame = pd.read_csv(path, usecols=USE_COLS)
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise")
        frame["date"] = frame["datetime"].dt.strftime("%Y-%m-%d")
        frame = frame[frame["date"].isin(keep_dates)]
        files_read += 1
        if frame.empty:
            continue
        frame["side"] = side
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("no hydrated minute files matched the requested dates")

    q = pd.concat(frames, ignore_index=True)
    raw_rows = len(q)
    q["clock"] = q["datetime"].dt.strftime("%H:%M")
    q["minutes"] = q["datetime"].dt.hour * 60 + q["datetime"].dt.minute

    non_positive_close = int((q["close"] <= 0).sum())
    q = q[q["close"] > 0]

    # How badly do duplicate rel-strike files disagree about the same contract-minute?
    key = ["date", "clock", "side", "strike"]
    grp = q.groupby(key, sort=False)
    dup_groups = int((grp.size() > 1).sum())
    vol_spread = grp["volume"].agg(lambda s: s.max() - s.min() if len(s) > 1 else 0)
    oi_spread = grp["oi"].agg(lambda s: s.max() - s.min() if len(s) > 1 else 0)
    close_spread = grp["close"].agg(lambda s: s.max() - s.min() if len(s) > 1 else 0)
    audit_dup = {
        "duplicate_contract_minutes": dup_groups,
        "duplicate_share_pct": round(100.0 * dup_groups / max(grp.ngroups, 1), 3),
        "volume_disagreement_share_pct": round(
            100.0 * float((vol_spread > 0).mean()), 3),
        "oi_disagreement_share_pct": round(100.0 * float((oi_spread > 0).mean()), 3),
        "close_disagreement_share_pct": round(100.0 * float((close_spread > 0).mean()), 3),
        "median_volume_spread_where_disagreeing": (
            float(vol_spread[vol_spread > 0].median()) if (vol_spread > 0).any() else 0.0),
    }

    # Same dedup convention as ``gate_b_common.load_call_quotes``: keep the highest-volume
    # row for a contract-minute.  Recorded here because for a VOLUME study this convention is
    # upward-biased by construction and must not be silently inherited.
    q = q.sort_values(["date", "minutes", "side", "strike", "volume"],
                      ascending=[True, True, True, True, False])
    q = q.drop_duplicates(subset=key, keep="first")

    q = q[["date", "clock", "minutes", "side", "strike",
           "open", "high", "low", "close", "iv", "volume", "oi", "spot"]]
    for col in ("open", "high", "low", "close", "iv", "spot"):
        q[col] = q[col].astype("float32")
    for col in ("volume", "oi"):
        q[col] = q[col].astype("int64")
    q = q.sort_values(["date", "side", "strike", "minutes"]).reset_index(drop=True)

    audit = {
        "files_read": files_read,
        "files_missing": files_missing,
        "raw_rows": raw_rows,
        "non_positive_close_dropped": non_positive_close,
        "deduplicated_rows": len(q),
        "dates": int(q["date"].nunique()),
        "duplicate_audit": audit_dup,
        "ohlc_consistent_share_pct": round(
            100.0 * float(((q["high"] >= q["close"]) & (q["close"] >= q["low"])
                           & (q["high"] >= q["open"]) & (q["open"] >= q["low"])).mean()), 4),
        "zero_range_bar_share_pct": round(100.0 * float((q["high"] == q["low"]).mean()), 3),
        "zero_volume_bar_share_pct": round(100.0 * float((q["volume"] == 0).mean()), 3),
        "zero_oi_bar_share_pct": round(100.0 * float((q["oi"] == 0).mean()), 3),
    }
    return q, audit


def load_flow_quotes(keep_dates: set[str] | None = None, rebuild: bool = False) -> pd.DataFrame:
    if FLOW_QUOTE_CACHE.exists() and not rebuild:
        return pd.read_pickle(FLOW_QUOTE_CACHE)
    if keep_dates is None:
        raise ValueError("keep_dates is required to build the cache")
    q, audit = build_flow_quotes(keep_dates)
    tmp = FLOW_QUOTE_CACHE.with_suffix(".incoming")
    q.to_pickle(tmp)
    os.replace(tmp, FLOW_QUOTE_CACHE)
    FLOW_AUDIT_CACHE.write_text(json.dumps(audit, indent=2))
    return q


if __name__ == "__main__":
    import gate_b_full_paths as gbf

    paths = gbf.load_full_paths()
    keep = {p["date"] for p in paths}
    print(f"pool dates: {len(keep)}")
    q = load_flow_quotes(keep, rebuild=True)
    audit = json.loads(FLOW_AUDIT_CACHE.read_text())
    print(json.dumps(audit, indent=2))
    print(f"rows={len(q):,} dates={q['date'].nunique()} "
          f"sides={sorted(q['side'].unique())} "
          f"strikes/date/side median="
          f"{q.groupby(['date','side'])['strike'].nunique().median():.0f}")
