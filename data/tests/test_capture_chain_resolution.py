from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from shaurya.data.dhan_client import DhanClient, DhanCredentials
from shaurya.data_cli.capture_chain import coverage_failure_reason, resolve_live_spot_and_expiries


class FakeSDK:
    def __init__(self, expiries: list[str], spot: float) -> None:
        self._expiries = expiries
        self._spot = spot

    def expiry_list(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "success", "data": {"data": list(self._expiries)}}

    def option_chain(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "success",
            "data": {"data": {"last_price": self._spot, "oc": {}}},
        }


def _client(expiries: list[str], spot: float) -> DhanClient:
    return DhanClient(DhanCredentials("client", "token"), sdk=FakeSDK(expiries, spot))


def test_resolve_live_spot_and_expiries_picks_the_nearest_expiries() -> None:
    client = _client(["2026-09-29", "2026-09-01", "2026-10-06"], 24405.0)
    spot, expiries = resolve_live_spot_and_expiries(client, "nifty", expiry_count=2)
    assert spot == 24405.0
    assert expiries == ["2026-09-01", "2026-09-29"]
    for value in expiries:
        date.fromisoformat(value)


def test_resolve_live_spot_and_expiries_rejects_unknown_underlying() -> None:
    client = _client(["2026-09-01"], 24405.0)
    with pytest.raises(ValueError, match="no index security id"):
        resolve_live_spot_and_expiries(client, "SENSEX", expiry_count=1)


def test_resolve_live_spot_and_expiries_rejects_too_few_live_expiries() -> None:
    client = _client(["2026-09-01"], 24405.0)
    with pytest.raises(ValueError, match="only 1 live expiries"):
        resolve_live_spot_and_expiries(client, "NIFTY", expiry_count=2)


def test_resolve_live_spot_and_expiries_rejects_nonpositive_spot() -> None:
    client = _client(["2026-09-01", "2026-09-29"], 0.0)
    with pytest.raises(ValueError, match="no positive underlying price"):
        resolve_live_spot_and_expiries(client, "NIFTY", expiry_count=2)


def test_resolve_live_spot_and_expiries_rejects_nonpositive_count() -> None:
    client = _client(["2026-09-01", "2026-09-29"], 24405.0)
    with pytest.raises(ValueError, match="expiry_count must be positive"):
        resolve_live_spot_and_expiries(client, "NIFTY", expiry_count=0)


def test_coverage_gate_accepts_capture_at_threshold() -> None:
    assert (
        coverage_failure_reason(
            requested_count=100,
            covered_count=95,
            minimum_coverage_fraction=0.95,
        )
        is None
    )


def test_coverage_gate_rejects_plausible_but_partial_chain() -> None:
    reason = coverage_failure_reason(
        requested_count=120,
        covered_count=80,
        minimum_coverage_fraction=0.95,
    )
    assert reason is not None
    assert "80/120" in reason
    assert "below required" in reason


def test_coverage_gate_rejects_stream_error_even_with_full_coverage() -> None:
    assert coverage_failure_reason(
        requested_count=120,
        covered_count=120,
        minimum_coverage_fraction=0.95,
        stream_error_type="DhanFatalStreamError",
    ) == "stream failed: DhanFatalStreamError"


def test_coverage_gate_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="minimum-coverage-fraction"):
        coverage_failure_reason(
            requested_count=120,
            covered_count=120,
            minimum_coverage_fraction=0.0,
        )
