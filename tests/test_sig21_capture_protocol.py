from __future__ import annotations

import argparse

import pytest

from shaurya.cli.capture_dhan import (
    SIG21_FULL_SESSION_SECONDS,
    _parser,
    _sig21_protocol_metadata,
    _validate_sig21_protocol,
)


def protocol_args(*extra: str) -> argparse.Namespace:
    return _parser().parse_args(
        [
            "--credentials",
            "credentials.env",
            "--security-master",
            "master.csv",
            "--security-id",
            "123",
            "--expected-symbol",
            "NIFTY-AUG2026-FUT",
            "--sig21-calibration",
            *extra,
        ]
    )


def test_sig21_calibration_accepts_depth200_plus_depth20_for_a_full_session() -> None:
    args = protocol_args(
        "--enable-depth200",
        "--duration-seconds",
        str(SIG21_FULL_SESSION_SECONDS),
    )

    _validate_sig21_protocol(args)
    assert _sig21_protocol_metadata(args) == {
        "protocol_id": "H-SIG21",
        "sample_role": "calibration_only",
        "signal_source_channel": "depth200",
        "response_control_channel": "depth20",
        "registered_family_size": 384,
        "registration_commit": "f2cf65011d02882191b5cfda566c1024119964d7",
        "outcome_join_allowed": False,
    }


def test_sig21_calibration_rejects_missing_depth200_signal_source() -> None:
    args = protocol_args("--duration-seconds", str(SIG21_FULL_SESSION_SECONDS))

    with pytest.raises(ValueError, match="depth200 signal-source"):
        _validate_sig21_protocol(args)


def test_sig21_calibration_rejects_depth20_disabled() -> None:
    args = protocol_args(
        "--enable-depth200",
        "--no-depth20",
        "--duration-seconds",
        str(SIG21_FULL_SESSION_SECONDS),
    )

    with pytest.raises(ValueError, match="depth20 for response/control"):
        _validate_sig21_protocol(args)


def test_sig21_calibration_rejects_partial_session_duration() -> None:
    args = protocol_args(
        "--enable-depth200",
        "--duration-seconds",
        str(SIG21_FULL_SESSION_SECONDS - 1),
    )

    with pytest.raises(ValueError, match="full NSE session"):
        _validate_sig21_protocol(args)
