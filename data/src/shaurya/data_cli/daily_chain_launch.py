"""Canonical daily launcher for production option-chain capture.

Computes today's remaining session duration and prints (or, with `--launch`, starts in
tmux) the `shaurya-chain-capture` invocation needed for each configured underlying.
`--preflight` performs the live checks that matter before the open: credentials and the dated
security master must exist, the production archive must be mounted and writable, Dhan must resolve
spot and expiries, and the selected research chain must contain options for every requested expiry.
`--launch` always performs that same preflight before creating any tmux window.

`--credentials` and `--security-master` default to this machine's live operational paths but
stay overridable; `--output-root` overrides where captures land, on top of the archive's own
`SHAURYA_NSE_ARCHIVE_ROOT` environment override (default `/Volumes/Aryan/NSE`).
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds
from shaurya.data.dhan_client import DhanClient, DhanCredentials
from shaurya.data.storage import resolve_raw_capture_root
from shaurya.data.universe import select_chain_universe
from shaurya.data_cli.capture_chain import (
    DEFAULT_MINIMUM_COVERAGE_FRACTION,
    resolve_live_spot_and_expiries,
)

DEFAULT_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
DEFAULT_CREDENTIALS_PATH = Path.home() / "Documents" / "Market-Making-Secrets" / "dhan.env"
DEFAULT_SECURITY_MASTER_DIR = Path(__file__).resolve().parents[3] / "instrument-masters"


@dataclass(frozen=True, slots=True)
class ChainPreflight:
    underlying: str
    spot: float
    expiries: tuple[str, ...]
    option_count: int
    future_count: int

    @property
    def total_instruments(self) -> int:
        return self.option_count + self.future_count


def default_security_master_path(trading_date: date) -> Path:
    return DEFAULT_SECURITY_MASTER_DIR / f"dhan_instrument_master_{trading_date.isoformat()}.csv"


def duration_seconds_to_close(trading_date: date, *, now: datetime) -> float:
    """Seconds remaining in the regular session, so a mid-morning launch still runs to close."""

    _, closed = nse_equity_derivatives_session_bounds(trading_date)
    remaining = (closed - now).total_seconds()
    if remaining <= 0:
        raise ValueError(f"the {trading_date.isoformat()} regular session has already closed")
    return remaining


def require_launch_tools() -> None:
    """Fail before touching Dhan if the detached production launch cannot be created."""

    missing = [name for name in ("tmux", "shaurya-chain-capture") if shutil.which(name) is None]
    if missing:
        raise FileNotFoundError(f"required production launch tool(s) not found on PATH: {missing}")


def preflight_capture(
    underlyings: Sequence[str],
    *,
    credentials: Path,
    security_master: Path,
    trading_date: date,
    expiry_count: int,
    strike_window_fraction: float,
    max_options: int,
    output_root: Path | None,
) -> dict[str, ChainPreflight]:
    """Resolve and validate all inputs needed for a production chain launch.

    The returned spot/expiry values are threaded into the child commands so the exact universe
    checked here is the universe the detached capture uses; the child does not re-resolve a
    different chain a few seconds later.
    """

    if not credentials.is_file():
        raise FileNotFoundError(f"Dhan credentials file not found: {credentials}")
    if not security_master.is_file():
        raise FileNotFoundError(f"dated Dhan security master not found: {security_master}")
    if expiry_count <= 0:
        raise ValueError("expiries must be positive")
    if not 0 < strike_window_fraction <= 1:
        raise ValueError("strike-window-fraction must lie in (0, 1]")
    if max_options <= 0:
        raise ValueError("max-options must be positive")

    # Fail closed on the production storage target before opening market-data sockets.
    resolve_raw_capture_root(output_root, trading_date=trading_date, allow_nonarchive=False)

    master = DhanInstrumentMaster(security_master)
    mappings = list(master.mappings())
    if not mappings:
        raise ValueError(f"security master contains no instrument mappings: {security_master}")
    client = DhanClient(DhanCredentials.from_env_file(credentials))

    results: dict[str, ChainPreflight] = {}
    for requested_underlying in underlyings:
        underlying = requested_underlying.strip().upper()
        spot, expiry_values = resolve_live_spot_and_expiries(
            client,
            underlying,
            expiry_count=expiry_count,
        )
        expiry_dates = tuple(date.fromisoformat(value) for value in expiry_values)
        universe = select_chain_universe(
            mappings,
            underlying=underlying,
            expiries=expiry_dates,
            spot_reference=spot,
            strike_window_fraction=strike_window_fraction,
            max_options=max_options,
        )
        if not universe.options:
            raise ValueError(f"{underlying} preflight selected no options")
        option_expiries = {mapping.instrument.expiry for mapping in universe.options}
        missing_expiries = [
            expiry.isoformat() for expiry in expiry_dates if expiry not in option_expiries
        ]
        if missing_expiries:
            raise ValueError(
                f"{underlying} security master has no selected options for expiries "
                f"{missing_expiries}"
            )
        results[underlying] = ChainPreflight(
            underlying=underlying,
            spot=spot,
            expiries=tuple(expiry_values),
            option_count=len(universe.options),
            future_count=len(universe.futures),
        )
    return results


def build_capture_command(
    underlying: str,
    *,
    credentials: Path,
    security_master: Path,
    duration_seconds: float,
    expiry_count: int,
    strike_window_fraction: float,
    max_options: int,
    minimum_coverage_fraction: float = DEFAULT_MINIMUM_COVERAGE_FRACTION,
    spot: float | None = None,
    expiries: Sequence[str] | None = None,
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
    ]
    if spot is not None:
        command += ["--spot", str(spot)]
    if expiries:
        for expiry in expiries:
            command += ["--expiry", expiry]
    command += [
        "--expiry-count",
        str(expiry_count),
        "--strike-window-fraction",
        str(strike_window_fraction),
        "--max-options",
        str(max_options),
        "--minimum-coverage-fraction",
        str(minimum_coverage_fraction),
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

    if not 0 < args.minimum_coverage_fraction <= 1:
        raise ValueError("minimum-coverage-fraction must lie in (0, 1]")
    if args.launch:
        require_launch_tools()

    preflight: dict[str, ChainPreflight] = {}
    if args.preflight or args.launch:
        preflight = preflight_capture(
            underlyings,
            credentials=credentials,
            security_master=security_master,
            trading_date=trading_date,
            expiry_count=args.expiries,
            strike_window_fraction=args.strike_window_fraction,
            max_options=args.max_options,
            output_root=args.output_root,
        )
        for underlying in underlyings:
            result = preflight[underlying.strip().upper()]
            print(
                "preflight "
                f"underlying={result.underlying} spot={result.spot:g} "
                f"expiries={','.join(result.expiries)} "
                f"options={result.option_count} futures={result.future_count} "
                f"total={result.total_instruments}"
            )

    commands: list[tuple[str, list[str]]] = []
    for underlying in underlyings:
        resolved = preflight.get(underlying.strip().upper())
        command = build_capture_command(
            underlying,
            credentials=credentials,
            security_master=security_master,
            duration_seconds=duration_seconds,
            expiry_count=args.expiries,
            strike_window_fraction=args.strike_window_fraction,
            max_options=args.max_options,
            minimum_coverage_fraction=args.minimum_coverage_fraction,
            spot=resolved.spot if resolved is not None else None,
            expiries=resolved.expiries if resolved is not None else None,
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
    parser.add_argument(
        "--minimum-coverage-fraction",
        type=float,
        default=DEFAULT_MINIMUM_COVERAGE_FRACTION,
        help=(
            "Minimum requested-instrument fraction that must emit at least one packet. "
            "Default 0.95; lower coverage invalidates the child capture."
        ),
    )
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
        "--preflight",
        action="store_true",
        help=(
            "Verify credentials, dated security master, archive mount, live Dhan spot/expiries, "
            "and the selected universe, then print commands without launching."
        ),
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help=(
            "Run the production preflight, then start each resolved capture in its own tmux "
            "window. Without --preflight or --launch, the command only prints auto-resolving "
            "child commands."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
