from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shaurya.contracts.instruments import OptionType
from shaurya.data.dhan_client import DhanClient, DhanCredentials, RetryPolicy


class FakeSDK:
    def __init__(self) -> None:
        self.expiry_calls = 0

    def expiry_list(self, **kwargs):
        self.expiry_calls += 1
        return {"status": "success", "data": {"data": ["2026-08-25", "2026-09-01"]}}

    def option_chain(self, **kwargs):
        return {
            "status": "success",
            "data": {
                "data": {
                    "last_price": 25012.0,
                    "oc": {
                        "25000.00000": {
                            "ce": {"security_id": 12345, "last_price": 120.0, "lot_size": 65},
                            "pe": {"security_id": 12346, "last_price": 108.0, "lot_size": 65},
                        },
                        "25050.00000": {
                            "ce": {"security_id": 12347, "last_price": 96.0, "lot_size": 65},
                            "pe": {"security_id": 12348, "last_price": 135.0, "lot_size": 65},
                        },
                    },
                }
            },
        }


def test_credentials_are_redacted_and_require_private_file(tmp_path: Path) -> None:
    path = tmp_path / "dhan.env"
    path.write_text("DHAN_CLIENT_ID=client-secret\nDHAN_ACCESS_TOKEN=token-secret\n")
    os.chmod(path, 0o600)
    credentials = DhanCredentials.from_env_file(path)
    assert "client-secret" not in repr(credentials)
    assert "token-secret" not in repr(credentials)
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError):
        DhanCredentials.from_env_file(path)


def test_rate_limit_response_retries_with_bounded_backoff() -> None:
    calls = 0
    sleeps: list[float] = []

    class RateLimitedSDK:
        def expiry_list(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "status": "failure",
                    "remarks": {"error_code": "DH-429"},
                    "data": "",
                }
            return {"status": "success", "data": ["2026-08-25"]}

    client = DhanClient(
        DhanCredentials("client", "token"),
        sdk=RateLimitedSDK(),
        retry=RetryPolicy(max_attempts=2, base_delay_seconds=0.5),
        sleep=sleeps.append,
        random_uniform=lambda low, high: high,
    )
    assert client.expiry_list() == ("2026-08-25",)
    assert calls == 2
    assert sleeps == [0.5]


def test_atm_resolution_is_typed_and_expiry_is_cached() -> None:
    sdk = FakeSDK()
    client = DhanClient(DhanCredentials("client", "token"), sdk=sdk)
    mapping = client.resolve_atm_option(
        OptionType.CALL,
        now=datetime(2026, 8, 18, 4, 0, tzinfo=UTC),
    )
    assert mapping.security_id == "12345"
    assert mapping.instrument.strike is not None
    assert str(mapping.instrument.strike) == "25000.00000"
    assert mapping.instrument.option_type is OptionType.CALL
    client.expiry_list()
    assert sdk.expiry_calls == 1


def test_rolling_option_normalization_and_execution_boundary() -> None:
    nested = {
        "status": "success",
        "data": {"data": {"ce": {"timestamp": [1], "close": [100.0]}}},
    }
    assert DhanClient._normalize_rolling_option(nested, "CALL")["data"]["close"] == [100.0]
    client = DhanClient(DhanCredentials("client", "token"), sdk=FakeSDK())
    assert not hasattr(client, "place_order")
    assert not hasattr(client, "cancel_order")
