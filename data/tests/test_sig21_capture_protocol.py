from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal

import pytest

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)
from shaurya.data_cli.capture_dhan import (
    OFI_FULL_SESSION_SECONDS,
    SIG21_FULL_SESSION_SECONDS,
    _ofi_full_session_protocol_metadata,
    _parser,
    _sig21_protocol_metadata,
    _validate_depth_tier_scope,
    _validate_ofi_full_session_protocol,
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


def replication_args(*extra: str) -> argparse.Namespace:
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
            "--ofi-full-session-replication",
            *extra,
        ]
    )


def mapping(
    *, underlying: str = "NIFTY", kind: InstrumentKind = InstrumentKind.FUTURE
) -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying=underlying,
            kind=kind,
            expiry=date(2026, 8, 27),
            strike=Decimal("25000") if kind is InstrumentKind.OPTION else None,
            option_type=OptionType.CALL if kind is InstrumentKind.OPTION else None,
        ),
        security_id="123",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol=f"{underlying}-AUG2026-{kind.value.upper()}",
        lot_size=75,
        tick_size_paise=Decimal("5"),
        as_of_date=date(2026, 8, 20),
        source="fixture",
    )


def test_sig21_calibration_accepts_depth200_plus_depth20_for_a_full_session() -> None:
    assert SIG21_FULL_SESSION_SECONDS == 23_100.0
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


def test_protocol_flags_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        protocol_args("--ofi-full-session-replication")


def test_ofi_full_session_replication_accepts_all_three_channels_and_records_limits() -> None:
    args = replication_args(
        "--enable-depth200",
        "--duration-seconds",
        str(OFI_FULL_SESSION_SECONDS),
    )

    _validate_ofi_full_session_protocol(args)
    _validate_depth_tier_scope(args, mapping())
    assert _ofi_full_session_protocol_metadata(args) == {
        "protocol_id": "R-OFI-FULLSESSION-2026-08-20",
        "source_spec": (
            "research/docs/live-evidence/"
            "OFI-FULL-SESSION-REPLICATION-SPEC-2026-08-20.md"
        ),
        "source_amendment": (
            "research/docs/live-evidence/OFI-FULL-SESSION-REPLICATION-SPEC-AMENDMENT-1-2026-08-19.md"
        ),
        "registration_commit": "af9bec17694b5cf45f1d670113f14b02efb1e418",
        "sample_role": "prospective_full_session_replication",
        "trading_date": "2026-08-20",
        "required_channels": ["standard", "depth20", "depth200"],
        "regular_session": {
            "timezone": "Asia/Kolkata",
            "open": "09:15:00",
            "close": "15:40:00",
            "seconds": 23_100,
        },
        "duration_is_final_coverage_acceptance": False,
        "final_coverage_acceptance": (
            "actual receive timestamps on every required channel must start no later than "
            "09:15:02 and end no earlier than 15:39:58 IST; analysis clips exactly to the "
            "09:15:00-15:40:00 regular session"
        ),
        "outcome_join_allowed": True,
        "sig21_calibration_eligible": False,
        "order_entry_enabled": False,
    }


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--enable-depth200", "--no-standard"), "Standard/Full"),
        (("--enable-depth200", "--no-depth20"), "depth20"),
        ((), "depth200"),
        (
            (
                "--enable-depth200",
                "--duration-seconds",
                str(OFI_FULL_SESSION_SECONDS - 1),
            ),
            "23,100 seconds",
        ),
    ],
)
def test_ofi_full_session_replication_rejects_incomplete_capture_profiles(
    extra: tuple[str, ...], message: str
) -> None:
    args = replication_args(*extra)

    with pytest.raises(ValueError, match=message):
        _validate_ofi_full_session_protocol(args)


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (mapping(underlying="BANKNIFTY"), "requires a NIFTY future"),
        (mapping(kind=InstrumentKind.OPTION), "restricted to futures and equity books"),
    ],
)
def test_ofi_full_session_replication_rejects_non_nifty_futures(
    candidate: DhanInstrumentMapping, message: str
) -> None:
    args = replication_args(
        "--enable-depth200",
        "--duration-seconds",
        str(OFI_FULL_SESSION_SECONDS),
    )

    with pytest.raises(ValueError, match=message):
        _validate_depth_tier_scope(args, candidate)
