from __future__ import annotations

import numpy as np
import pandas as pd

from shaurya.research.formula_alpha_mining import (
    MAX_COMPLEXITY,
    MAX_FORMULAS,
    MAX_VALIDATION_CANDIDATES,
    _frozen_centered_rank,
    formula_specs,
    mine_formula_alphas,
)


def _panel() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-08-17",
            "2026-08-18",
        ]
    )
    rows: list[dict[str, object]] = []
    for day_index, date in enumerate(dates):
        for minute_index in range(12):
            value = (minute_index - 5.5) / 1000.0
            rows.append(
                {
                    "datetime": date + pd.Timedelta(hours=9, minutes=20 + 5 * minute_index),
                    "date": date,
                    "forward_return_bps": (1.0 if value >= 0 else -1.0) * (day_index + 1),
                    "ret_5": value,
                    "ret_15": value * 0.8,
                    "ret_60": -value * 0.3,
                    "session_return": value * 2.0,
                    "overnight_gap": (day_index % 3 - 1) / 1000.0,
                    "rv_30": abs(value),
                }
            )
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)


def test_formula_grammar_is_unique_and_bounded() -> None:
    specs = formula_specs()
    assert len(specs) == 72
    assert len(specs) <= MAX_FORMULAS
    assert len({spec.name for spec in specs}) == len(specs)
    assert max(spec.complexity for spec in specs) <= MAX_COMPLEXITY
    assert {spec.operation for spec in specs} == {"rank", "sum", "product"}
    assert {spec.polarity for spec in specs} == {-1, 1}


def test_frozen_rank_does_not_refit_to_later_extremes() -> None:
    reference = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    first = _frozen_centered_rank(pd.Series([0.5, 100.0]), reference)
    second = _frozen_centered_rank(pd.Series([0.5, 100.0, -1000.0]), reference)
    np.testing.assert_array_equal(first, second[:2])
    assert second[-1] == -1.0


def test_final_returns_cannot_change_selection() -> None:
    panel = _panel()
    original = mine_formula_alphas(panel)
    changed = panel.copy()
    final = changed["date"] >= pd.Timestamp("2026-08-17")
    changed.loc[final, "forward_return_bps"] *= -10_000.0
    perturbed = mine_formula_alphas(changed)

    assert original.validation_candidates == perturbed.validation_candidates
    assert original.selected_candidate == perturbed.selected_candidate
    assert original.metadata["discovery_metrics"] == perturbed.metadata["discovery_metrics"]
    assert original.metadata["validation_metrics"] == perturbed.metadata["validation_metrics"]
    assert len(original.validation_candidates) <= MAX_VALIDATION_CANDIDATES


def test_candidate_arrays_align_and_threshold_is_discovery_frozen() -> None:
    panel = _panel()
    result = mine_formula_alphas(panel)
    assert len(result.candidates) == 72
    for candidate in result.candidates.values():
        assert candidate.score.shape == (len(panel),)
        assert candidate.position.shape == (len(panel),)
        assert set(np.unique(candidate.position)).issubset({-1.0, 0.0, 1.0})
        assert np.isfinite(candidate.discovery_threshold)

