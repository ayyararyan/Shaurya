"""Run DAT-15 over retained canonical tapes and write one immutable JSON artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shaurya.data.alignment_analysis import analyze_alignment_tapes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--post-quote-horizon-ms", type=float, default=1000.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = analyze_alignment_tapes(args.tape, post_quote_horizon_ms=args.post_quote_horizon_ms)
    payload = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": "completed", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
