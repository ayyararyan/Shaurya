"""Prepare or locally evaluate the restricted OpenEvolve alpha experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shaurya.research.openevolve_alpha import (
    evaluate_discovery_program,
    prepare_discovery_cache,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--index-zip", type=Path, required=True)
    prepare.add_argument("--cache", type=Path, required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--program", type=Path, required=True)
    evaluate.add_argument("--cache", type=Path, required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--program", type=Path, required=True)
    promote.add_argument("--index-zip", type=Path, required=True)
    promote.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        payload = prepare_discovery_cache(args.index_zip, args.cache)
    elif args.command == "evaluate":
        payload = evaluate_discovery_program(args.program, args.cache)
    else:
        from shaurya.research.openevolve_alpha import promote_discovery_program

        payload = promote_discovery_program(args.program, args.index_zip, args.cache)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
