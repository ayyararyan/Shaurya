from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from shaurya.contracts.categories import CATEGORY_SEMANTICS, ObjectCategory, ObjectLabel
from shaurya.contracts.timing import (
    IST,
    CausalTimestamps,
    nse_equity_derivatives_close,
    nse_equity_derivatives_session_bounds,
    nse_equity_derivatives_session_seconds,
)

from shaurya.research_contracts.findings import (
    FindingRecord,
    FindingUncertainty,
    FindingWindow,
    SearchContext,
)
from shaurya.research_contracts.surface import FitDiagnostic, SurfaceFrame, SurfaceParameter

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
    return ObjectLabel(object_name=name, category=category, source="test fixture")


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


def test_nse_equity_derivatives_clock_is_date_versioned() -> None:
    assert nse_equity_derivatives_close(date(2026, 8, 2)) == time(15, 30)
    assert nse_equity_derivatives_close(date(2026, 8, 3)) == time(15, 40)
    assert nse_equity_derivatives_session_seconds(date(2026, 8, 2)) == 22_500
    assert nse_equity_derivatives_session_seconds(date(2026, 8, 3)) == 23_100
    opened, closed = nse_equity_derivatives_session_bounds(date(2026, 8, 20))
    assert opened == datetime(2026, 8, 20, 9, 15, tzinfo=IST)
    assert closed == datetime(2026, 8, 20, 15, 40, tzinfo=IST)


def test_surface_frame_round_trip_preserves_parameters_diagnostics_and_age() -> None:
    original = SurfaceFrame(
        run_id="sha-20260818T040000.000000Z-1234abcd",
        surface_id="nifty-front-expiry",
        model_name="eSSVI",
        instrument_scope=("NSE:NSE_FNO:NIFTY",),
        timing=_timing(),
        surface_timestamp=_ts(0),
        parameters=(SurfaceParameter(name="theta", value=Decimal("0.04")),),
        diagnostics=(FitDiagnostic(name="fit_status", value="converged"),),
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


def _finding() -> FindingRecord:
    return FindingRecord(
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


def test_finding_round_trip_preserves_uncertainty_search_context_and_label() -> None:
    original = _finding()
    assert FindingRecord.model_validate_json(original.model_dump_json()) == original


def test_finding_rejects_missing_uncertainty() -> None:
    with pytest.raises(ValidationError, match="confidence/significance"):
        FindingUncertainty()


def test_finding_rejects_window_after_decision() -> None:
    with pytest.raises(ValidationError, match="finding window"):
        FindingRecord(
            **{
                **_finding().model_dump(),
                "window": FindingWindow(start_timestamp=_ts(1), end_timestamp=_ts(3)),
            }
        )


@pytest.mark.parametrize("model", [SurfaceFrame, FindingRecord])
def test_versioned_contracts_reject_unsupported_schema_versions(model: type[object]) -> None:
    with pytest.raises(ValidationError, match="1.0.0"):
        model.model_validate({"schema_version": "2.0.0"})  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("filename", "model"),
    [("surface_v1.json", SurfaceFrame), ("finding_v1.json", FindingRecord)],
)
def test_golden_contract_fixture_round_trip(filename: str, model: type[object]) -> None:
    payload = (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
    parsed = model.model_validate_json(payload)  # type: ignore[attr-defined]
    reparsed = model.model_validate_json(parsed.model_dump_json())  # type: ignore[attr-defined]
    assert reparsed == parsed
