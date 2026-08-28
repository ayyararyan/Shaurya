"""Canonical daily launcher for full option-chain capture.

Computes today's remaining session duration and prints (or, with `--launch`, starts in
tmux) the `shaurya-chain-capture` invocation needed to record the whole chain for each
underlying. `shaurya-chain-capture` resolves live spot and expiries itself when they are
omitted, so this launcher never duplicates that Dhan call; it only owns scheduling and
per-underlying orchestration. `shaurya-dhan-capture` (single instrument) remains available
for isolated diagnostics, but it is never the daily production entry point: this command is.

`--credentials` and `--security-master` default to this machine's live operational paths but
stay overridable; `--output-root` overrides where captures land, on top of the archive's own
`SHAURYA_NSE_ARCHIVE_ROOT` environment override (default `/Volumes/Aryan/NSE`).
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds

DEFAULT_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
DEFAULT_CREDENTIALS_PATH = Path.home() / "Documents" / "Market-Making-Secrets" / "dhan.env"
DEFAULT_SECURITY_MASTER_DIR = Path(__file__).resolve().parents[3] / "instrument-masters"


def default_security_master_path(trading_date: date) -> Path:
    return DEFAULT_SECURITY_MASTER_DIR / f"dhan_instrument_master_{trading_date.isoformat()}.csv"


def duration_seconds_to_close(trading_date: date, *, now: datetime) -> float:
    """Seconds remaining in the regular session, so a mid-morning launch still runs to close."""

    _, closed = nse_equity_derivatives_session_bounds(trading_date)
    remaining = (closed - now).total_seconds()
    if remaining <= 0:
        raise ValueError(f"the {trading_date.isoformat()} regular session has already closed")
    return remaining


def build_capture_command(
    underlying: str,
    *,
    credentials: Path,
    security_master: Path,
    duration_seconds: float,
    expiry_count: int,
    strike_window_fraction: float,
    max_options: int,
    output_root: Path | None = None,
) -> list[str]:
    command = [
        "shaurya-chain-capture",
        "--credentials",
        str(credentials),
        "--security-master",
        str(security_master),
        "--underlying",
        underlying,
        "--expiry-count",
        str(expiry_count),
        "--strike-window-fraction",
        str(strike_window_fraction),
        "--max-options",
        str(max_options),
        "--duration-seconds",
        str(int(duration_seconds)),
        "--archive-on-close",
    ]
    if output_root is not None:
        command += ["--output-root", str(output_root)]
    return command


def _launch_tmux(session: str, commands: Sequence[tuple[str, list[str]]]) -> None:
    for index, (underlying, command) in enumerate(commands):
        window = underlying.lower()
        if index == 0:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session, "-n", window, *command],
                check=True,
            )
        else:
            subprocess.run(
                ["tmux", "new-window", "-t", session, "-n", window, *command],
                check=True,
            )


def run(args: argparse.Namespace, *, now: datetime | None = None) -> int:
    resolved_now = now or datetime.now(tz=IST)
    trading_date = args.date or resolved_now.date()
    underlyings: list[str] = args.underlying or list(DEFAULT_UNDERLYINGS)
    duration_seconds = duration_seconds_to_close(trading_date, now=resolved_now)
    credentials = args.credentials or DEFAULT_CREDENTIALS_PATH
    security_master = args.security_master or default_security_master_path(trading_date)
    commands: list[tuple[str, list[str]]] = []
    for underlying in underlyings:
        command = build_capture_command(
            underlying,
            credentials=credentials,
            security_master=security_master,
            duration_seconds=duration_seconds,
            expiry_count=args.expiries,
            strike_window_fraction=args.strike_window_fraction,
            max_options=args.max_options,
            output_root=args.output_root,
        )
        commands.append((underlying, command))
        print(shlex.join(command))
    if args.launch:
        tmux_session = args.tmux_session or f"shaurya-dat-chain-{trading_date.isoformat()}"
        _launch_tmux(tmux_session, commands)
        windows = [underlying.lower() for underlying, _ in commands]
        print(f"launched tmux session {tmux_session!r} with windows {windows}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials",
        type=Path,
        default=None,
        help=f"Defaults to {DEFAULT_CREDENTIALS_PATH} (this machine's live Dhan credentials).",
    )
    parser.add_argument(
        "--security-master",
        type=Path,
        default=None,
        help=(
            "Defaults to "
            f"{DEFAULT_SECURITY_MASTER_DIR}/dhan_instrument_master_<date>.csv for the "
            "resolved trading date."
        ),
    )
    parser.add_argument(
        "--underlying",
        action="append",
        default=None,
        help="Repeat for more than one underlying; default is NIFTY and BANKNIFTY.",
    )
    parser.add_argument(
        "--expiries",
        type=int,
        default=2,
        help="Nearest live expiries to capture per underlying (matches a weekly plus monthly).",
    )
    parser.add_argument("--strike-window-fraction", type=float, default=0.06)
    parser.add_argument("--max-options", type=int, default=120)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Override where captures land. Default is the configured NSE archive root "
            "(/Volumes/Aryan/NSE, or the SHAURYA_NSE_ARCHIVE_ROOT environment override)."
        ),
    )
    parser.add_argument("--tmux-session", default=None)
    parser.add_argument(
        "--launch",
        action="store_true",
        help=(
            "Start each resolved capture in its own tmux window. Default only prints the "
            "resolved shaurya-chain-capture commands for an operator to review first."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
