from __future__ import annotations

import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import shaurya.data_cli.daily_chain_launch as launcher
from shaurya.data_cli.daily_chain_launch import (
    DEFAULT_CREDENTIALS_PATH,
    ChainPreflight,
    _launch_tmux,
    _parser,
    build_capture_command,
    default_security_master_path,
    duration_seconds_to_close,
    preflight_capture,
    require_launch_tools,
    run,
)

IST = ZoneInfo("Asia/Kolkata")


def test_duration_seconds_to_close_counts_down_to_regular_close() -> None:
    trading_date = date(2026, 8, 28)
    now = datetime(2026, 8, 28, 9, 57, tzinfo=IST)
    remaining = duration_seconds_to_close(trading_date, now=now)
    assert remaining == pytest.approx(float(15 * 3600 + 40 * 60 - (9 * 3600 + 57 * 60)))


def test_duration_seconds_to_close_rejects_a_finished_session() -> None:
    trading_date = date(2026, 8, 28)
    now = datetime(2026, 8, 28, 16, 0, tzinfo=IST)
    with pytest.raises(ValueError, match="already closed"):
        duration_seconds_to_close(trading_date, now=now)


def test_build_capture_command_omits_spot_and_expiry_without_preflight() -> None:
    command = build_capture_command(
        "NIFTY",
        credentials=Path("/secrets/dhan.env"),
        security_master=Path("/masters/dhan.csv"),
        duration_seconds=1234.0,
        expiry_count=2,
        strike_window_fraction=0.06,
        max_options=120,
    )
    assert command == [
        "shaurya-chain-capture",
        "--credentials",
        "/secrets/dhan.env",
        "--security-master",
        "/masters/dhan.csv",
        "--underlying",
        "NIFTY",
        "--expiry-count",
        "2",
        "--strike-window-fraction",
        "0.06",
        "--max-options",
        "120",
        "--minimum-coverage-fraction",
        "0.95",
        "--duration-seconds",
        "1234",
        "--archive-on-close",
    ]
    assert "--spot" not in command
    assert "--expiry" not in command
    assert "--output-root" not in command


def test_build_capture_command_pins_preflight_spot_and_expiries() -> None:
    command = build_capture_command(
        "NIFTY",
        credentials=Path("/secrets/dhan.env"),
        security_master=Path("/masters/dhan.csv"),
        duration_seconds=1234.0,
        expiry_count=2,
        strike_window_fraction=0.06,
        max_options=120,
        spot=24405.0,
        expiries=("2026-09-01", "2026-09-29"),
    )
    assert command[command.index("--spot") + 1] == "24405.0"
    expiry_positions = [index for index, value in enumerate(command) if value == "--expiry"]
    assert [command[index + 1] for index in expiry_positions] == ["2026-09-01", "2026-09-29"]


def test_build_capture_command_forwards_an_explicit_output_root() -> None:
    command = build_capture_command(
        "NIFTY",
        credentials=Path("/secrets/dhan.env"),
        security_master=Path("/masters/dhan.csv"),
        duration_seconds=1234.0,
        expiry_count=2,
        strike_window_fraction=0.06,
        max_options=120,
        output_root=Path("/mnt/nse-archive"),
    )
    assert command[-2:] == ["--output-root", "/mnt/nse-archive"]


def test_default_security_master_path_is_dated_for_the_trading_date() -> None:
    path = default_security_master_path(date(2026, 8, 28))
    assert path.name == "dhan_instrument_master_2026-08-28.csv"
    assert path.parent.name == "instrument-masters"


def test_preflight_fails_before_network_when_credentials_are_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="credentials"):
        preflight_capture(
            ["NIFTY"],
            credentials=tmp_path / "missing.env",
            security_master=tmp_path / "missing.csv",
            trading_date=date(2026, 9, 1),
            expiry_count=2,
            strike_window_fraction=0.06,
            max_options=120,
            output_root=None,
        )


def test_require_launch_tools_names_missing_runtime_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None if name == "tmux" else "/bin/tool")
    with pytest.raises(FileNotFoundError, match="tmux"):
        require_launch_tools()


def test_run_resolves_default_credentials_and_security_master_when_omitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _parser().parse_args(["--underlying", "NIFTY"])
    code = run(args, now=datetime(2026, 8, 28, 9, 57, tzinfo=IST))
    assert code == 0
    out = capsys.readouterr().out
    assert f"--credentials {DEFAULT_CREDENTIALS_PATH}" in out
    expected_master = default_security_master_path(date(2026, 8, 28))
    assert f"--security-master {expected_master}" in out


def test_run_forwards_an_explicit_output_root(capsys: pytest.CaptureFixture[str]) -> None:
    args = _parser().parse_args(
        ["--underlying", "NIFTY", "--output-root", "/mnt/nse-archive"]
    )
    code = run(args, now=datetime(2026, 8, 28, 9, 57, tzinfo=IST))
    assert code == 0
    out = capsys.readouterr().out
    assert "--output-root /mnt/nse-archive" in out


def test_run_defaults_to_both_underlyings_without_launching(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _parser().parse_args(
        [
            "--credentials",
            "/secrets/dhan.env",
            "--security-master",
            "/masters/dhan.csv",
        ]
    )
    code = run(args, now=datetime(2026, 8, 28, 9, 57, tzinfo=IST))
    assert code == 0
    out = capsys.readouterr().out
    assert "--underlying NIFTY" in out
    assert "--underlying BANKNIFTY" in out
    assert "tmux" not in out


def test_run_launches_only_after_preflight_and_pins_resolved_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, check: calls.append(list(command)),
    )
    monkeypatch.setattr(launcher, "require_launch_tools", lambda: None)
    monkeypatch.setattr(
        launcher,
        "preflight_capture",
        lambda *args, **kwargs: {
            "NIFTY": ChainPreflight(
                underlying="NIFTY",
                spot=24405.0,
                expiries=("2026-09-01", "2026-09-29"),
                option_count=120,
                future_count=1,
            )
        },
    )
    args = _parser().parse_args(
        [
            "--credentials",
            "/secrets/dhan.env",
            "--security-master",
            "/masters/dhan.csv",
            "--underlying",
            "NIFTY",
            "--launch",
        ]
    )
    code = run(args, now=datetime(2026, 8, 28, 9, 57, tzinfo=IST))
    assert code == 0
    assert len(calls) == 1
    assert calls[0][:5] == ["tmux", "new-session", "-d", "-s", "shaurya-dat-chain-2026-08-28"]
    assert "-n" in calls[0] and "nifty" in calls[0]
    # The real shaurya-chain-capture invocation is watchdog-wrapped (see
    # _watchdog_wrapped_command), so its flags now live inside one quoted zsh -c script
    # rather than as separate argv elements.
    assert calls[0][-2:-1] == ["-c"]
    script = calls[0][-1]
    assert "--spot 24405.0" in script
    assert script.count("--expiry ") == 2


def test_launch_tmux_reuses_the_session_for_later_underlyings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, check: calls.append(list(command)),
    )
    _launch_tmux(
        "shaurya-dat-chain-2026-08-28",
        [
            ("NIFTY", ["shaurya-chain-capture", "--duration-seconds", "20580"]),
            ("BANKNIFTY", ["shaurya-chain-capture", "--duration-seconds", "20580"]),
        ],
    )
    assert calls[0][1] == "new-session"
    assert calls[1][1] == "new-window"


def test_watchdog_wrapped_command_grace_period_is_duration_plus_buffer() -> None:
    """Live-observed 2026-09-01: the capture's own --duration-seconds deadline and a
    direct SIGINT both failed to stop it post-close; SIGTERM did, instantly. This OS-
    level watchdog is the backstop, so it must fire meaningfully after the command's
    own deadline (giving graceful --archive-on-close shutdown a fair chance first),
    not at some unrelated fixed time that could kill an early-session capture."""

    command = ["shaurya-chain-capture", "--underlying", "NIFTY", "--duration-seconds", "100"]
    wrapped = launcher._watchdog_wrapped_command(command, grace_buffer_seconds=180.0)
    assert wrapped[:2] == ["zsh", "-c"]
    script = wrapped[2]
    assert "shaurya-chain-capture --underlying NIFTY --duration-seconds 100" in script
    assert "sleep 280" in script  # 100 + 180
    assert "kill -TERM $child" in script
    assert "kill -KILL $child" in script


def test_watchdog_wrapped_command_requires_duration_seconds_in_the_command() -> None:
    with pytest.raises(ValueError):
        launcher._watchdog_wrapped_command(["shaurya-chain-capture"], grace_buffer_seconds=180.0)


def test_parser_does_not_require_credentials_or_security_master() -> None:
    args = _parser().parse_args([])
    assert args.credentials is None
    assert args.security_master is None
    assert args.output_root is None
    assert args.preflight is False
