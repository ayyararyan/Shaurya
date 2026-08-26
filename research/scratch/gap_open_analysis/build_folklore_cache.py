#!/usr/bin/env python3
"""Build the shared three-clock quote cache for the frozen folklore battery.

Offline archive processing only.  This module imports no broker, credential, order,
or live-trading code.  It reuses ``nge_open_snapshot.pkl`` for 09:15 and 15:29 and
scans the archive once for 09:20.  All contract-minute duplicates are resolved on
absolute strike by retaining the highest-volume row.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd

import nge_common


CACHE_PATH = Path("folklore_required_quotes_20260823.pkl")
AUDIT_PATH = Path("folklore_required_quotes_20260823_audit.json")
REQUIRED_CLOCKS = ("09:15", "09:20", "15:29")


def build() -> None:
    started = time.monotonic()
    if CACHE_PATH.exists():
        obj = pd.read_pickle(CACHE_PATH)
        quotes = obj["quotes"]
        clocks = tuple(sorted(quotes["clock"].unique()))
        if clocks != REQUIRED_CLOCKS:
            raise RuntimeError(f"existing cache has clocks {clocks}, expected {REQUIRED_CLOCKS}")
        print(f"cache already valid: {CACHE_PATH} rows={len(quotes):,}", flush=True)
        return

    snapshot = nge_common.load_snapshot(rebuild=False).copy()
    snapshot = snapshot[snapshot["clock"].isin(("09:15", "15:29"))]
    snapshot["source"] = "nge_open_snapshot"

    manifest = [r for r in nge_common.manifest_rows()
                if r.get("drv_option_type") in ("CALL", "PUT")]
    parts: list[pd.DataFrame] = []
    files_read = files_missing = raw_rows = 0
    for i, row in enumerate(manifest, start=1):
        path = nge_common.cached_path(row)
        if not path.exists():
            files_missing += 1
            continue
        frame = pd.read_csv(path, usecols=nge_common.USE_COLS)
        files_read += 1
        raw_rows += len(frame)
        clock = frame["datetime"].str.slice(11, 16)
        keep = clock.eq("09:20")
        if keep.any():
            small = frame.loc[keep].copy()
            small["date"] = small["datetime"].str.slice(0, 10)
            small["clock"] = "09:20"
            small["side"] = str(row["drv_option_type"])
            small["source"] = "archive_0920_scan"
            parts.append(small.drop(columns=["datetime"]))
        if i == 1 or i % 25 == 0 or i == len(manifest):
            elapsed = time.monotonic() - started
            print(
                f"progress files={i:,}/{len(manifest):,} read={files_read:,} "
                f"missing={files_missing:,} raw_rows={raw_rows:,} elapsed_s={elapsed:.1f}",
                flush=True,
            )

    if not parts:
        raise FileNotFoundError("no 09:20 option bars found in the hydrated archive")
    at_0920 = pd.concat(parts, ignore_index=True)
    combined = pd.concat([snapshot, at_0920], ignore_index=True, sort=False)
    before_positive = len(combined)
    combined = combined[combined["close"] > 0].copy()
    key = ["date", "clock", "side", "strike"]
    duplicate_groups = int((combined.groupby(key, sort=False).size() > 1).sum())
    combined = combined.sort_values(
        key + ["volume"], ascending=[True, True, True, True, False], kind="mergesort"
    )
    combined = combined.drop_duplicates(key, keep="first")
    columns = ["date", "clock", "side", "strike", "close", "iv", "oi", "spot",
               "volume", "source"]
    combined = combined[columns].sort_values(key).reset_index(drop=True)

    audit = {
        "cache": str(CACHE_PATH),
        "required_clocks": list(REQUIRED_CLOCKS),
        "source_snapshot_rows": int(len(snapshot)),
        "manifest_option_files": int(len(manifest)),
        "files_read_for_0920": int(files_read),
        "files_missing": int(files_missing),
        "raw_rows_scanned_for_0920": int(raw_rows),
        "rows_before_positive_filter": int(before_positive),
        "non_positive_close_rows_dropped": int(before_positive - len(combined)),
        "duplicate_contract_minutes": duplicate_groups,
        "deduplicated_rows": int(len(combined)),
        "dates": int(combined["date"].nunique()),
        "rows_by_clock": {str(k): int(v) for k, v in combined.groupby("clock").size().items()},
        "dedup_key": key,
        "dedup_keep": "highest volume",
        "absolute_strike": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    incoming = CACHE_PATH.with_suffix(".incoming")
    pd.to_pickle({"quotes": combined, "audit": audit}, incoming)
    os.replace(incoming, CACHE_PATH)
    AUDIT_PATH.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2), flush=True)


if __name__ == "__main__":
    build()
