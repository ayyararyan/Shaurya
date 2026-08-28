#!/usr/bin/env python3
"""One-command operator wrapper for prospective Shaurya research.

This script intentionally contains no research formulas.  It only maps an operator workspace to
``shaurya-research daily`` so the installed CLI remains the single workflow authority.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from shaurya.cli.research import main as research_main


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="run_daily_research.py")
    value.add_argument("--date", type=date.fromisoformat, required=True)
    value.add_argument("--next-session", type=date.fromisoformat, required=True)
    value.add_argument("--catalog", type=Path, required=True)
    value.add_argument("--workspace", type=Path, default=Path("derived/research"))
    value.add_argument("--registry-dir", type=Path, default=Path("registries"))
    value.add_argument("--bundle", choices=("high_frequency", "legacy"), default="high_frequency")
    return value


def main() -> int:
    args = parser().parse_args()
    root = args.workspace
    return research_main(
        [
            "daily",
            "--date",
            args.date.isoformat(),
            "--next-session",
            args.next_session.isoformat(),
            "--catalog",
            str(args.catalog),
            "--registry-dir",
            str(args.registry_dir),
            "--bundle",
            args.bundle,
            "--ledger",
            str(root / "alpha-evidence-ledger.jsonl"),
            "--plan-dir",
            str(root / "plans"),
            "--state-dir",
            str(root / "state"),
            "--report-dir",
            str(root / "reports"),
            "--snapshot-dir",
            str(root / "snapshots"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
