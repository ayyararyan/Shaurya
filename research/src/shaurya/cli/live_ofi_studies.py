"""Run D38, D39 and D40 on complete prefixes of one active DAT dataset."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DatasetStatus
from shaurya.contracts.timing import IST
from shaurya.data import DataAccess, DataCatalog, resolve_data_catalog

from shaurya.analytics.live_ofi_studies import (
    D40_HORIZONS_SECONDS,
    LiveStudyStateWriter,
    atomic_write_json,
    build_live_d38,
    snapshot_growing_tape,
    summarize_d39_cell,
    summarize_d40_cell,
)
from shaurya.signals.deep_book_normal_activity import EMBARGO_SECONDS
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.effective_touch import build_trade_prints
from shaurya.signals.fixed_target_panel import (
    CCZ_LEVEL_COUNTS,
    D39_REFERENCE_PRICE_LADDER,
    HORIZONS_SECONDS,
    WINDOWS_SECONDS,
    build_fixed_target_panel,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id")
    source.add_argument("--tape", type=Path, help="pre-DAT append-only tape to register as active")
    parser.add_argument("--legacy-producer-pid", type=int)
    parser.add_argument("--data-catalog", type=Path)
    parser.add_argument("--trading-date", type=date.fromisoformat, default=datetime.now(IST).date())
    parser.add_argument("--allow-nonarchive-catalog", action="store_true")
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=399)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--refresh-seconds", type=float, default=300.0)
    parser.add_argument("--once", action="store_true")
    return parser


def _publish_metadata(
    artifact: dict[str, Any],
    *,
    source: Mapping[str, Any],
    study: str,
) -> None:
    artifact.update(
        {
            "live_study": study,
            "sample_role": "growing_prefix_exploration",
            "confirmatory_eligible": False,
            "registered_replication_eligible": False,
            "order_entry_enabled": False,
            "successive_prefixes_independent": False,
            "source_prefix": dict(source),
            "live_amendment": "research/docs/D38-D39-D40-LIVE-AMENDMENT-2026-08-21.md",
        }
    )


def _run_cycle(
    *,
    tape_path: Path,
    dataset_id: str,
    writer: LiveStudyStateWriter,
    cycle: int,
    replicates: int,
    seed: int,
) -> int:
    snapshot = snapshot_growing_tape(tape_path, dataset_id=dataset_id)
    writer.begin_cycle(snapshot, cycle=cycle)
    print(
        json.dumps(
            {
                "stage": "snapshot_complete",
                "cycle": cycle,
                "prefix_bytes": snapshot.prefix_bytes,
                "last_receive_ts": snapshot.last_receive_ts,
                "observations": len(snapshot.tape.observations),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    d38 = build_live_d38(snapshot)
    writer.publish_d38(d38)
    atomic_write_json(
        writer.artifact_dir / f"cycle-{cycle}-d38.json",
        d38,
    )
    print(json.dumps({"stage": "d38_complete", "cycle": cycle}, sort_keys=True), flush=True)

    prints = build_trade_prints(snapshot.full_rows)
    d40_cells_path = writer.start_cells("d40", total=len(D40_HORIZONS_SECONDS))

    def d40_cell(cell: dict[str, Any], completed: int, total: int) -> None:
        summary = summarize_d40_cell(cell)
        writer.publish_cell(
            "d40",
            cell=cell,
            summary=summary,
            completed=completed,
            total=total,
            artifact_path=d40_cells_path,
        )
        print(
            json.dumps(
                {
                    "stage": "d40",
                    "completed_cells": completed,
                    "total_cells": total,
                    **summary,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    d40 = build_fixed_target_panel(
        snapshot.tape,
        prints=prints.prints,
        references=("displayed_mid",),
        levels=(10,),
        windows=(10.0,),
        horizons=D40_HORIZONS_SECONDS,
        replicates=replicates,
        seed=seed,
        embargo_seconds=max(EMBARGO_SECONDS, CAUSAL_GAP_SECONDS + max(D40_HORIZONS_SECONDS)),
        cell_callback=d40_cell,
    )
    _publish_metadata(d40, source=snapshot.provenance(), study="D40")
    d40_full_path = writer.artifact_dir / f"cycle-{cycle}-d40-full.json"
    atomic_write_json(d40_full_path, d40)
    writer.complete_study("d40", full_artifact_path=d40_full_path)

    d39_total = (
        len(D39_REFERENCE_PRICE_LADDER)
        * len(CCZ_LEVEL_COUNTS)
        * len(WINDOWS_SECONDS)
        * len(HORIZONS_SECONDS)
    )
    d39_cells_path = writer.start_cells("d39", total=d39_total)

    def d39_cell(cell: dict[str, Any], completed: int, total: int) -> None:
        summary = summarize_d39_cell(cell)
        writer.publish_cell(
            "d39",
            cell=cell,
            summary=summary,
            completed=completed,
            total=total,
            artifact_path=d39_cells_path,
        )
        print(
            json.dumps(
                {
                    "stage": "d39",
                    "completed_cells": completed,
                    "total_cells": total,
                    **summary,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    references = (
        "displayed_mid",
        *(value for value in D39_REFERENCE_PRICE_LADDER if value != "displayed_mid"),
    )
    levels = (10, *(value for value in CCZ_LEVEL_COUNTS if value != 10))
    d39 = build_fixed_target_panel(
        snapshot.tape,
        prints=prints.prints,
        references=references,
        levels=levels,
        windows=WINDOWS_SECONDS,
        horizons=HORIZONS_SECONDS,
        replicates=replicates,
        seed=seed + 100_000_000,
        cell_callback=d39_cell,
    )
    _publish_metadata(d39, source=snapshot.provenance(), study="D39")
    d39_full_path = writer.artifact_dir / f"cycle-{cycle}-d39-full.json"
    atomic_write_json(d39_full_path, d39)
    writer.complete_study("d39", full_artifact_path=d39_full_path)
    writer.complete_cycle()
    print(json.dumps({"stage": "cycle_complete", "cycle": cycle}, sort_keys=True), flush=True)
    return snapshot.prefix_bytes


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.replicates != 399:
        raise ValueError("live D38/D39/D40 requires the frozen 399 bootstrap replicates")
    if args.refresh_seconds <= 0:
        raise ValueError("refresh_seconds must be positive")
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=args.trading_date,
        allow_nonarchive=args.allow_nonarchive_catalog,
    )
    access = DataAccess(DataCatalog(catalog_path))
    if args.dataset_id is not None:
        handle = access.handle(args.dataset_id)
    else:
        if args.legacy_producer_pid is None:
            raise ValueError("active pre-DAT tape requires --legacy-producer-pid")
        handle = access.adopt_active_legacy_tape(
            args.tape,
            consumer="ANL-06-LIVE-D38-D39-D40",
            purpose="intraday D38/D39/D40 complete-prefix evaluation",
            producer_pid=args.legacy_producer_pid,
        )
    if handle.status is DatasetStatus.INVALIDATED:
        raise ValueError("live studies cannot consume an invalidated DAT dataset")
    tape_path = Path(handle.tape_path)
    writer = LiveStudyStateWriter(
        args.state_output,
        args.artifact_dir,
        run_id=f"live-d38-d39-d40-{handle.dataset_id}",
        dataset_id=handle.dataset_id,
    )
    cycle = 0
    last_prefix = 0
    while True:
        cycle += 1
        try:
            last_prefix = _run_cycle(
                tape_path=tape_path,
                dataset_id=handle.dataset_id,
                writer=writer,
                cycle=cycle,
                replicates=args.replicates,
                seed=args.seed + cycle * 1_000_000_000,
            )
        except BaseException as exc:  # noqa: BLE001 - durable state records exact failure
            writer.fail(exc)
            if args.once:
                raise
            print(
                json.dumps(
                    {"stage": "failed", "type": type(exc).__name__, "message": str(exc)},
                    sort_keys=True,
                ),
                flush=True,
            )
        if args.once:
            break
        while tape_path.stat().st_size <= last_prefix:
            time.sleep(min(args.refresh_seconds, 5.0))
        time.sleep(args.refresh_seconds)
    return writer.state


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
