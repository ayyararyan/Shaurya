from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from shaurya.contracts.categories import CATEGORY_SEMANTICS, ObjectCategory, ObjectLabel
from shaurya.contracts.config import (
    CredentialHandle,
    LimitComparison,
    RiskLimitDefinition,
    RiskScope,
    ShauryaConfig,
)
from shaurya.contracts.findings import (
    FindingRecord,
    FindingUncertainty,
    FindingWindow,
    SearchContext,
)
from shaurya.contracts.ledger import (
    BookState,
    LedgerEventType,
    LedgerRow,
    OrderSide,
)
from shaurya.contracts.surface import FitDiagnostic, SurfaceFrame, SurfaceParameter
from shaurya.contracts.timing import IST, CausalTimestamps

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "contracts"


def _ts(second: int) -> datetime:
    return datetime(2026, 8, 18, 9, 30, second, tzinfo=IST)


def _timing() -> CausalTimestamps:
    return CausalTimestamps(
        exchange_timestamp=_ts(0),
        receive_timestamp=_ts(1),
        decision_timestamp=_ts(2),
        source_timestamps=(_ts(0),),
    )


def _label(name: str, category: ObjectCategory) -> ObjectLabel:
    return ObjectLabel(
        object_name=name,
        category=category,
        source="test fixture",
    )


def _placement() -> LedgerRow:
    return LedgerRow(
        run_id="sha-20260818T040000.000000Z-1234abcd",
        run_mode="paper",
        execution_stream="paper_shadow",
        event_type=LedgerEventType.ORDER_PLACED,
        timing=_timing(),
        cycle_id="cycle-1",
        order_role="entry",
        order_id="order-1",
        client_order_id="client-1",
        instrument_id="NSE:NSE_FNO:NIFTY:option:2026-08-20:24400:CE",
        broker_instrument_token="45106",
        broker_trading_symbol="NIFTY2682024400CE",
        side=OrderSide.BUY,
        order_type="LIMIT",
        time_in_force="DAY",
        order_quantity=65,
        order_price=Decimal("70.10"),
        quote_price=Decimal("70.10"),
        book_state=BookState(
            best_bid=Decimal("70.05"),
            best_ask=Decimal("70.15"),
            mid=Decimal("70.10"),
            microprice=Decimal("70.11"),
        ),
        width_multiplier_k=Decimal("4"),
        benchmark_reference_price=Decimal("70.10"),
        break_even_spread=Decimal("0.12"),
        benchmark_spread_ticks=3,
        benchmark_spread_price=Decimal("0.15"),
        order_posted_at=_ts(2),
        status="OPEN",
        object_labels=(
            _label("book_state", ObjectCategory.OBSERVED),
            _label("break_even_spread", ObjectCategory.DERIVED),
        ),
    )


def test_object_categories_have_the_six_frozen_values_and_round_trip() -> None:
    assert {item.value for item in ObjectCategory} == {
        "observed",
        "derived",
        "estimated",
        "scenario",
        "proxy",
        "unidentified",
    }
    assert set(CATEGORY_SEMANTICS) == set(ObjectCategory)
    original = _label("queue_position", ObjectCategory.UNIDENTIFIED)
    assert ObjectLabel.model_validate_json(original.model_dump_json()) == original


def test_object_label_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        ObjectLabel.model_validate(
            {"object_name": "fill", "category": "realised", "source": "fixture"}
        )


def test_causal_timestamps_round_trip_in_ist() -> None:
    original = _timing()
    restored = CausalTimestamps.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.decision_timestamp.tzinfo == IST


def test_causal_timestamps_reject_non_ist() -> None:
    with pytest.raises(ValidationError, match="must use IST"):
        CausalTimestamps(
            exchange_timestamp=None,
            receive_timestamp=datetime(2026, 8, 18, 4, 0, tzinfo=UTC),
            decision_timestamp=datetime(2026, 8, 18, 4, 1, tzinfo=UTC),
        )


def test_causal_timestamps_reject_actual_future_information_violation() -> None:
    with pytest.raises(ValidationError, match="causality violation"):
        CausalTimestamps(
            exchange_timestamp=_ts(0),
            receive_timestamp=_ts(3),
            decision_timestamp=_ts(2),
        )


def test_ledger_placement_round_trip_preserves_harvested_fields() -> None:
    original = _placement()
    restored = LedgerRow.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.quote_price == Decimal("70.10")
    assert restored.book_state is not None
    assert restored.width_multiplier_k == Decimal("4")
    assert restored.break_even_spread == Decimal("0.12")


@pytest.mark.parametrize(
    ("event_type", "fields"),
    [
        (
            LedgerEventType.ORDER_EXECUTED,
            {
                "order_id": "order-1",
                "execution_id": "execution-1",
                "fill_quantity": 65,
                "remaining_quantity": 0,
                "fill_price": Decimal("70.10"),
                "order_posted_at": _ts(0),
                "order_age_seconds": Decimal("2"),
            },
        ),
        (
            LedgerEventType.CANCEL_REQUESTED,
            {"order_id": "order-1", "reason": "entry timeout"},
        ),
        (
            LedgerEventType.REJECTED,
            {"order_id": "order-1", "reason": "broker rejection"},
        ),
        (
            LedgerEventType.CYCLE_COMPLETE,
            {"cycle_id": "cycle-1", "cycle_pnl_rupees": Decimal("13.50")},
        ),
    ],
)
def test_ledger_accepts_each_harvested_lifecycle_event(
    event_type: LedgerEventType, fields: dict[str, object]
) -> None:
    row = LedgerRow(
        run_id="sha-20260818T040000.000000Z-1234abcd",
        run_mode="paper",
        execution_stream="paper_shadow",
        event_type=event_type,
        timing=_timing(),
        instrument_id="NSE:NSE_FNO:NIFTY:option:2026-08-20:24400:CE",
        status="RECORDED",
        object_labels=(_label("ledger_event", ObjectCategory.OBSERVED),),
        **fields,
    )
    assert LedgerRow.model_validate_json(row.model_dump_json()) == row


def test_ledger_rejects_execution_without_fill_price() -> None:
    with pytest.raises(ValidationError, match="fill_price"):
        LedgerRow(
            run_id="sha-20260818T040000.000000Z-1234abcd",
            run_mode="paper",
            execution_stream="paper_shadow",
            event_type=LedgerEventType.ORDER_EXECUTED,
            timing=_timing(),
            instrument_id="NSE:NSE_FNO:NIFTY:option:2026-08-20:24400:CE",
            order_id="order-1",
            execution_id="execution-1",
            fill_quantity=65,
            remaining_quantity=0,
            order_posted_at=_ts(0),
            order_age_seconds=Decimal("2"),
            status="FILLED",
            object_labels=(_label("fill", ObjectCategory.OBSERVED),),
        )


def test_ledger_rejects_inconsistent_order_age() -> None:
    payload = json.loads(
        (FIXTURE_ROOT / "ledger_v1.json").read_text(encoding="utf-8")
    )
    payload["order_age_seconds"] = "2"
    with pytest.raises(ValidationError, match="order_age_seconds"):
        LedgerRow.model_validate(payload)


def test_surface_frame_round_trip_preserves_parameters_diagnostics_and_age() -> None:
    original = SurfaceFrame(
        run_id="sha-20260818T040000.000000Z-1234abcd",
        surface_id="nifty-front-expiry",
        model_name="eSSVI",
        instrument_scope=("NSE:NSE_FNO:NIFTY",),
        timing=_timing(),
        surface_timestamp=_ts(0),
        parameters=(
            SurfaceParameter(name="theta", value=Decimal("0.04")),
            SurfaceParameter(name="rho", value=Decimal("-0.35")),
        ),
        diagnostics=(
            FitDiagnostic(name="weighted_r_squared", value=0.992),
            FitDiagnostic(name="fit_status", value="converged"),
        ),
        surface_age_seconds=Decimal("2"),
        staleness_threshold_seconds=Decimal("5"),
        is_stale=False,
        object_labels=(
            _label("parameters", ObjectCategory.ESTIMATED),
            _label("diagnostics", ObjectCategory.DERIVED),
        ),
    )
    assert SurfaceFrame.model_validate_json(original.model_dump_json()) == original


@pytest.mark.parametrize(
    ("surface_age_seconds", "is_stale", "match"),
    [
        (Decimal("3"), False, "surface_age_seconds"),
        (Decimal("2"), True, "is_stale"),
    ],
)
def test_surface_frame_rejects_inconsistent_age_or_staleness(
    surface_age_seconds: Decimal, is_stale: bool, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        SurfaceFrame(
            run_id="run-1",
            surface_id="surface-1",
            model_name="eSSVI",
            instrument_scope=("NIFTY",),
            timing=_timing(),
            surface_timestamp=_ts(0),
            parameters=(SurfaceParameter(name="theta", value=Decimal("0.04")),),
            diagnostics=(FitDiagnostic(name="fit_status", value="converged"),),
            surface_age_seconds=surface_age_seconds,
            staleness_threshold_seconds=Decimal("5"),
            is_stale=is_stale,
            object_labels=(
                _label("parameters", ObjectCategory.ESTIMATED),
                _label("diagnostics", ObjectCategory.DERIVED),
            ),
        )


def test_config_round_trip_requires_explicit_handles_and_limits() -> None:
    original = ShauryaConfig(
        config_id="paper-research",
        credential_handles=(
            CredentialHandle(
                provider="dhan",
                handle="market-data-session",
                required_fields=("client_id", "access_token"),
            ),
        ),
        risk_limits=(
            RiskLimitDefinition(
                name="account_daily_loss",
                scope=RiskScope.ACCOUNT,
                metric="daily_pnl_rupees",
                comparison=LimitComparison.GREATER_THAN_OR_EQUAL,
                threshold=Decimal("-2000"),
                unit="INR",
            ),
        ),
    )
    restored = ShauryaConfig.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.risk_limits[0].threshold == Decimal("-2000")


def test_config_rejects_secret_values_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ShauryaConfig.model_validate(
            {
                "config_id": "unsafe",
                "credential_handles": [],
                "risk_limits": [],
                "access_token": "must-not-be-in-config",
            }
        )


def test_config_rejects_instrument_limit_without_instrument_identity() -> None:
    with pytest.raises(ValidationError, match="instrument_id"):
        RiskLimitDefinition(
            name="position_cap",
            scope=RiskScope.INSTRUMENT,
            metric="net_quantity",
            comparison=LimitComparison.LESS_THAN_OR_EQUAL,
            threshold=Decimal("65"),
            unit="contracts",
        )


def test_finding_round_trip_preserves_uncertainty_search_context_and_label() -> None:
    original = FindingRecord(
        finding_id="finding-1",
        run_id="sha-20260818T040000.000000Z-1234abcd",
        subject="NIFTY front-expiry variance risk premium",
        window=FindingWindow(start_timestamp=_ts(0), end_timestamp=_ts(1)),
        timing=_timing(),
        statistic_name="mean_difference",
        statistic_value=Decimal("1.75"),
        magnitude=Decimal("1.75"),
        magnitude_unit="volatility_points",
        uncertainty=FindingUncertainty(
            p_value=Decimal("0.02"),
            confidence_level=Decimal("0.95"),
            confidence_interval=(Decimal("0.40"), Decimal("3.10")),
        ),
        search_context=SearchContext(
            tests_evaluated=24,
            adjustment_method="Romano-Wolf",
            trial_log_id="trial-log-1",
        ),
        object_label=_label("variance_risk_premium", ObjectCategory.DERIVED),
    )
    assert FindingRecord.model_validate_json(original.model_dump_json()) == original


def test_finding_rejects_missing_uncertainty() -> None:
    with pytest.raises(ValidationError, match="confidence/significance"):
        FindingUncertainty()


def test_finding_rejects_window_after_decision() -> None:
    with pytest.raises(ValidationError, match="finding window"):
        FindingRecord(
            finding_id="finding-1",
            run_id="run-1",
            subject="future leak",
            window=FindingWindow(start_timestamp=_ts(1), end_timestamp=_ts(3)),
            timing=_timing(),
            statistic_name="mean",
            statistic_value=Decimal("1"),
            magnitude=Decimal("1"),
            magnitude_unit="points",
            uncertainty=FindingUncertainty(p_value=Decimal("0.5")),
            search_context=SearchContext(
                tests_evaluated=1,
                adjustment_method=None,
                trial_log_id=None,
            ),
            object_label=_label("future_leak", ObjectCategory.DERIVED),
        )


@pytest.mark.parametrize("model", [LedgerRow, SurfaceFrame, ShauryaConfig, FindingRecord])
def test_versioned_contracts_reject_unsupported_schema_versions(model: type[object]) -> None:
    with pytest.raises(ValidationError, match="1.0.0"):
        model.model_validate({"schema_version": "2.0.0"})  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("ledger_v1.json", LedgerRow),
        ("surface_v1.json", SurfaceFrame),
        ("config_v1.json", ShauryaConfig),
        ("finding_v1.json", FindingRecord),
    ],
)
def test_golden_contract_fixture_round_trip(filename: str, model: type[object]) -> None:
    payload = (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
    parsed = model.model_validate_json(payload)  # type: ignore[attr-defined]
    reparsed = model.model_validate_json(parsed.model_dump_json())  # type: ignore[attr-defined]
    assert reparsed == parsed
