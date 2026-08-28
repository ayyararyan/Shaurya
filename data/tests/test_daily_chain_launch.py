from __future__ import annotations

import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from shaurya.data_cli.daily_chain_launch import (
    _launch_tmux,
    _parser,
    build_capture_command,
    duration_seconds_to_close,
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


def test_build_capture_command_omits_spot_and_expiry_for_live_resolution() -> None:
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
        "--duration-seconds",
        "1234",
        "--archive-on-close",
    ]
    assert "--spot" not in command
    assert "--expiry" not in command


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


def test_run_launches_one_tmux_window_per_underlying(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, check: calls.append(list(command)),
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
        [("NIFTY", ["shaurya-chain-capture"]), ("BANKNIFTY", ["shaurya-chain-capture"])],
    )
    assert calls[0][1] == "new-session"
    assert calls[1][1] == "new-window"


def test_parser_requires_credentials_and_security_master() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([])
