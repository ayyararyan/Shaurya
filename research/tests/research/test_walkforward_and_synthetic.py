from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from shaurya.research.contracts import (
    EvaluationRow,
    FeatureObservation,
    FeatureValue,
    HypothesisDefinition,
    ResearchMode,
    TargetObservation,
)
from shaurya.research.stability import regime_comparison, stability_summary
from shaurya.research.walkforward import freeze_historical_folds, run_nested_walk_forward

NS = 1_000_000_000


def _hypothesis(feature: str, *, regime: str = "global") -> HypothesisDefinition:
    return HypothesisDefinition(
        display_name=f"{feature}-{regime}",
        family="ORDER_FLOW/OFI",
        predictor_feature_ids=(feature,),
        target_id="future_mid_return.horizon=1s",
        target_horizon_seconds=1,
        conditioning_variables=(),
        admissible_regime=regime,
        model_class="ridge",
        fitting_window_sessions=5,
        training_cadence_seconds=1,
        regularization=(("ridge_penalty", 1.0),),
        evaluation_metric="pearson_correlation",
        transaction_cost_relevance="diagnostic_only",
        first_registration_date=date(2026, 1, 1),
        registry_version="hypotheses-v1",
        minimum_observations=3,
        minimum_effective_sample_size=3,
    )


def _rows(session_count: int = 10) -> tuple[EvaluationRow, ...]:
    start = date(2026, 1, 1)
    rows: list[EvaluationRow] = []
    for session_index in range(session_count):
        session = start + timedelta(days=session_index)
        for index in range(8):
            anchor = (session_index * 100 + index) * NS
            x = float(index - 3) + 0.1 * session_index
            noise = float((index * 17 + session_index * 11) % 7 - 3)
            feature = FeatureObservation(
                f"{session.isoformat()}-{index}",
                session,
                anchor,
                1,
                "features-v1",
                "synthetic",
                f"{session_index + 1:064x}",
                (
                    FeatureValue("noise", noise, anchor),
                    FeatureValue("x", x, anchor),
                ),
            )
            target = TargetObservation(
                feature.observation_id,
                "future_mid_return.horizon=1s",
                session,
                anchor + NS // 2,
                anchor + 3 * NS // 2,
                anchor + 3 * NS // 2,
                2.0 * x + 0.02 * noise,
                "targets-v1",
                "synthetic",
                f"{session_index + 1:064x}",
            )
            rows.append(EvaluationRow(feature, target))
    return tuple(rows)


def test_folds_and_inner_selection_are_frozen_against_future_append_and_outer_targets() -> None:
    rows = _rows(10)
    dates = [row.feature.session_date for row in rows]
    through = date(2026, 1, 10)
    folds = freeze_historical_folds(dates, through=through)
    appended = freeze_historical_folds(
        (*dates, date(2026, 2, 1), date(2026, 2, 2)), through=through
    )
    assert appended == folds

    hypotheses = (_hypothesis("x"), _hypothesis("noise"))
    baseline = run_nested_walk_forward(rows, hypotheses, folds, mode=ResearchMode.CONFIRMATORY)
    outer_dates = {max(item for fold in folds for item in fold.outer_evaluation_dates)}
    mutated = tuple(
        EvaluationRow(row.feature, replace(row.target, value=-float(row.target.value)))
        if row.feature.session_date in outer_dates and row.target.value is not None
        else row
        for row in rows
    )
    changed = run_nested_walk_forward(mutated, hypotheses, folds, mode=ResearchMode.CONFIRMATORY)
    assert [item.selected_for_outer for item in changed.candidate_results] == [
        item.selected_for_outer for item in baseline.candidate_results
    ]
    assert [item.model_hash for item in changed.candidate_results] == [
        item.model_hash for item in baseline.candidate_results
    ]
    assert [item.training_metadata_hash for item in changed.candidate_results] == [
        item.training_metadata_hash for item in baseline.candidate_results
    ]


def test_stable_injected_alpha_is_recovered_after_repeated_oos_evidence() -> None:
    rows = _rows(20)
    folds = freeze_historical_folds(
        [row.feature.session_date for row in rows], through=date(2026, 1, 20)
    )
    signal = _hypothesis("x")
    noise = _hypothesis("noise")
    result = run_nested_walk_forward(rows, (signal, noise), folds, mode=ResearchMode.CONFIRMATORY)
    selected = [
        item
        for item in result.candidate_results
        if item.hypothesis_id == signal.hypothesis_id and item.selected_for_outer
    ]
    assert len(selected) >= 10
    assert all((item.outer_score or 0) > 0.99 for item in selected)


def test_structural_break_and_regime_alpha_diagnostics_do_not_need_future_state() -> None:
    summary = stability_summary([1.0] * 10 + [-1.0] * 10)
    assert summary.structural_break_detected
    assert summary.sign_stability == 0.5
    regime = regime_comparison(
        [0.1] * 100,
        {"high_vol": [0.8] * 60, "normal": [-0.1] * 60},
        minimum_n=50,
    )
    assert regime["conditioned_earns_complexity"]


def test_regime_predicate_is_applied_to_causal_feature_rows_only() -> None:
    rows = _rows(10)
    folds = freeze_historical_folds(
        [row.feature.session_date for row in rows], through=date(2026, 1, 10)
    )
    regime_hypothesis = _hypothesis("x", regime="positive_x_state")
    result = run_nested_walk_forward(
        rows,
        (regime_hypothesis,),
        folds,
        mode=ResearchMode.CONFIRMATORY,
        regime_predicates={"positive_x_state": lambda values: (values.get("x") or 0.0) > 0.0},
    )
    assert all(item.outer_observations < 8 for item in result.candidate_results)
