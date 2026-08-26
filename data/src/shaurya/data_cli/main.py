"""Inspect, validate, and replay datasets through the public Shaurya Data interface."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from shaurya.contracts.data import DatasetHandle
from shaurya.data import DataAccess, DataCatalog


def _add_catalog(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, required=True)


def _add_selector(parser: argparse.ArgumentParser) -> None:
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--dataset-id")
    selector.add_argument("--date", type=date.fromisoformat, dest="trading_date")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    catalog = commands.add_parser("catalog", help="inspect the append-only dataset catalogue")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    list_parser = catalog_commands.add_parser("list", help="list the latest handle per dataset")
    _add_catalog(list_parser)
    get_parser = catalog_commands.add_parser("get", help="resolve one dataset")
    _add_catalog(get_parser)
    _add_selector(get_parser)

    validate = commands.add_parser("validate", help="stream and verify one completed dataset")
    _add_catalog(validate)
    _add_selector(validate)

    replay = commands.add_parser("replay", help="emit canonical tape rows as JSON Lines")
    _add_catalog(replay)
    _add_selector(replay)
    replay.add_argument("--limit", type=int)
    return parser


def _select(args: argparse.Namespace, catalog: DataCatalog) -> DatasetHandle:
    if getattr(args, "dataset_id", None) is not None:
        return catalog.get(args.dataset_id)
    return catalog.get_dataset(trading_date=args.trading_date)


def _json(handle: DatasetHandle) -> str:
    return handle.model_dump_json(indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog = DataCatalog(args.catalog)
    if args.command == "catalog" and args.catalog_command == "list":
        for handle in sorted(catalog.handles().values(), key=lambda item: item.dataset_id):
            print(_json(handle))
        return 0

    handle = _select(args, catalog)
    if args.command == "catalog":
        print(_json(handle))
        return 0

    access = DataAccess(catalog)
    if args.command == "validate":
        rows = sum(1 for _ in access.rows(handle))
        if handle.rows is not None and rows != handle.rows:
            raise ValueError(f"catalogue row count {handle.rows} differs from replay count {rows}")
        print(json.dumps({"dataset_id": handle.dataset_id, "rows": rows, "valid": True}))
        return 0

    if args.limit is not None and args.limit < 1:
        raise ValueError("replay limit must be positive")
    for index, row in enumerate(access.rows(handle), start=1):
        print(json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")))
        if args.limit is not None and index >= args.limit:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
