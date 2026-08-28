"""Inspect, validate, preview, export, and migrate datasets through Shaurya Data."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from shaurya.contracts.data import DatasetHandle
from shaurya.data import DataAccess, DataCatalog, LegacySourceState


def _add_catalog(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, required=True)


def _add_selector(parser: argparse.ArgumentParser) -> None:
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--dataset-id")
    selector.add_argument("--date", type=date.fromisoformat, dest="trading_date")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    catalog = commands.add_parser("catalog", help="inspect the immutable dataset catalogue")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    list_parser = catalog_commands.add_parser("list", help="list current dataset states")
    _add_catalog(list_parser)
    list_parser.add_argument("--json", action="store_true", help="emit JSON objects")
    get_parser = catalog_commands.add_parser("get", help="emit one complete dataset handle")
    _add_catalog(get_parser)
    _add_selector(get_parser)

    inspect = commands.add_parser("inspect", help="describe one dataset for a human operator")
    _add_catalog(inspect)
    _add_selector(inspect)

    validate = commands.add_parser("validate", help="fully verify one completed dataset")
    _add_catalog(validate)
    _add_selector(validate)

    for name, help_text in (
        ("preview", "display a bounded logical-row table"),
        ("replay", "emit canonical rows as JSON Lines"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_catalog(command)
        _add_selector(command)
        command.add_argument("--limit", type=int, default=20 if name == "preview" else None)

    export = commands.add_parser("export", help="intentionally export bounded rows to CSV")
    _add_catalog(export)
    _add_selector(export)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--limit", type=int)

    migrate = commands.add_parser(
        "legacy-migrate",
        help="dry-run or explicitly convert one declared legacy source",
    )
    _add_catalog(migrate)
    migrate.add_argument("--tape", type=Path, required=True)
    migrate.add_argument("--source-state", type=LegacySourceState, required=True)
    migrate.add_argument("--source-manifest", type=Path)
    migrate.add_argument("--convert", action="store_true")
    migrate.add_argument(
        "--execute",
        action="store_true",
        help="perform writes; default is dry-run",
    )
    migrate.add_argument("--output-root", type=Path)
    migrate.add_argument("--segment-rows", type=int, default=50_000)
    return parser


def _select(args: argparse.Namespace, catalog: DataCatalog) -> DatasetHandle:
    if getattr(args, "dataset_id", None) is not None:
        return catalog.get(args.dataset_id)
    return catalog.get_dataset(trading_date=args.trading_date)


def _json(handle: DatasetHandle) -> str:
    return handle.model_dump_json(indent=2)


def _check_limit(value: int | None, *, command: str) -> None:
    if value is not None and value < 1:
        raise ValueError(f"{command} limit must be positive")


def _describe(handle: DatasetHandle) -> str:
    coverage = (
        f"{handle.coverage_start.isoformat()} .. {handle.coverage_end.isoformat()}"
        if handle.coverage_start and handle.coverage_end
        else "not yet terminal"
    )
    return "\n".join(
        (
            f"dataset: {handle.dataset_name or handle.dataset_id}",
            f"internal id: {handle.dataset_id}",
            f"state: {handle.status}",
            f"storage: {handle.storage_format or 'legacy_jsonl'}",
            f"trading date: {handle.trading_date.isoformat()}",
            f"coverage: {coverage}",
            f"rows / bytes / segments: {handle.rows} / {handle.bytes} / {len(handle.segments)}",
            f"channels: {', '.join(map(str, handle.channels))}",
            f"instruments: {len(handle.instrument_ids)}",
            f"dataset digest: {handle.dataset_digest or handle.tape_sha256 or 'not published'}",
            f"reason: {handle.invalidation_reason or '-'}",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog = DataCatalog(args.catalog)
    access = DataAccess(catalog)

    if args.command == "legacy-migrate":
        report = access.migrate_legacy_tape(
            args.tape,
            source_state=args.source_state,
            source_manifest=args.source_manifest,
            output_root=args.output_root,
            convert=args.convert,
            dry_run=not args.execute,
            segment_max_rows=args.segment_rows,
        )
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0

    if args.command == "catalog" and args.catalog_command == "list":
        handles = sorted(catalog.handles().values(), key=lambda item: item.dataset_id)
        if args.json:
            for handle in handles:
                print(_json(handle))
        else:
            print("DATE\tSTATE\tFORMAT\tROWS\tSEGMENTS\tDATASET")
            for handle in handles:
                print(
                    "\t".join(
                        (
                            handle.trading_date.isoformat(),
                            str(handle.status),
                            str(handle.storage_format or "legacy_jsonl"),
                            str(handle.rows),
                            str(len(handle.segments)),
                            handle.dataset_name or handle.dataset_id,
                        )
                    )
                )
        return 0

    handle = _select(args, catalog)
    if args.command == "catalog":
        print(_json(handle))
        return 0
    if args.command == "inspect":
        print(_describe(handle))
        return 0
    if args.command == "validate":
        print(json.dumps(access.validate(handle), sort_keys=True, indent=2))
        return 0

    _check_limit(args.limit, command=args.command)
    if args.command == "preview":
        print("SEQ\tRECEIVE_TS\tCHANNEL\tINSTRUMENT\tBID\tASK")
        for index, row in enumerate(access.rows(handle), start=1):
            print(
                "\t".join(
                    (
                        str(row.receive_sequence),
                        row.receive_ts.isoformat(),
                        row.event_type,
                        row.instrument_id,
                        "" if row.best_bid is None else str(row.best_bid),
                        "" if row.best_ask is None else str(row.best_ask),
                    )
                )
            )
            if index >= args.limit:
                break
        return 0
    if args.command == "replay":
        for index, row in enumerate(access.rows(handle), start=1):
            print(json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")))
            if args.limit is not None and index >= args.limit:
                break
        return 0

    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    with args.output.open("x", encoding="utf-8", newline="") as destination:
        writer: csv.DictWriter[str] | None = None
        for index, row in enumerate(access.rows(handle), start=1):
            payload = row.to_dict()
            payload["bids"] = json.dumps(payload["bids"], separators=(",", ":"))
            payload["asks"] = json.dumps(payload["asks"], separators=(",", ":"))
            payload["quality_flags"] = "|".join(payload["quality_flags"])
            if writer is None:
                writer = csv.DictWriter(destination, fieldnames=list(payload))
                writer.writeheader()
            writer.writerow(payload)
            if args.limit is not None and index >= args.limit:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
