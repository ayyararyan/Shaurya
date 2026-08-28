from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from shaurya.data import CompleteLineJsonlTail

from shaurya.analytics.depth_thinning_analysis import DEPTH20, BookState
from shaurya.analytics.ofi_dashboard import (
    CELL_COUNT,
    OfiDashboardEngine,
    RefitArtifactSink,
    WalkForwardConfig,
    WalkForwardEvaluator,
    WalkForwardRatchet,
    enforce_response_geometry,
    offline_parity_probe,
)
from shaurya.analytics.ofi_dashboard_server import (
    ALLOWED_METHODS,
    MATRIX_HORIZONS_SECONDS,
    MATRIX_LOOKBACKS_SECONDS,
    MATRIX_TRAINING_WINDOWS_MINUTES,
    OfiDashboardState,
    build_server,
    compact_dashboard_payload,
    render_html,
)
from shaurya.signals.ccz_ofi import (
    average_feature,
    best_level_feature,
    denominator_feature,
    level_feature,
    normalised_level_feature,
)
from shaurya.signals.deep_book_normal_activity import SplitIndex
from shaurya.signals.deep_book_ofi import OFI_WINDOWS_SECONDS
from shaurya.signals.ofi_horserace import (
    CCZ_LEVEL_COUNTS,
    CCZ_PRIMARY_LEVELS,
    MODEL_ORDER,
    RETURN_HORIZONS_SECONDS,
    HorseRaceObservation,
    cks_feature,
    model_features,
    normalised_trade_feature,
    trade_feature,
)

SECOND = 1_000_000_000
BASE = 1_777_000_000 * SECOND

# `MICRO-03`: nine families (M0-M8) across five predictor windows and five horizons.  Pinned
# explicitly so a change to MODEL_ORDER cannot silently resize the frozen grid.
EXPECTED_CELL_COUNT = 9 * 5 * 5


def test_grid_size_is_pinned_to_the_declared_family_and_axis_counts() -> None:
    assert CELL_COUNT == EXPECTED_CELL_COUNT
    assert len(MODEL_ORDER) == 9
    assert MODEL_ORDER[-2:] == ("M7", "M8")


def _observation(
    index: int,
    *,
    future_only: bool = False,
    past_only: bool = False,
) -> HorseRaceObservation:
    signal = float(((index * 7) % 23) - 11)
    noise = float(((index * 13) % 17) - 8) / 8.0
    features: dict[str, float] = {
        "log1p_l1_depth": 5.0 + ((index * 3) % 5) / 10.0,
        "spread_ticks": 1.0 + index % 2,
        "l1_queue_imbalance": signal / 11.0,
        # `MICRO-01`: the M7 regressor, a family under D38 rather than an unused control.
        "microprice_tilt_ticks": signal / 14.0,
    }
    for window in OFI_WINDOWS_SECONDS:
        features[trade_feature(window)] = signal * (1.0 + window / 20.0)
        features[normalised_trade_feature(window)] = signal / 12.0
        features[cks_feature(window)] = signal * (2.0 + window / 20.0)
        for count in CCZ_LEVEL_COUNTS:
            features[denominator_feature(window, count)] = 40.0 + count
            features[average_feature(window, count)] = signal / (count + 1) + noise / 20
        features[best_level_feature(window)] = signal / 40.0 + noise / 40
        for level in range(1, max(CCZ_LEVEL_COUNTS) + 1):
            features[level_feature(window, level)] = signal * level / 10.0 + noise
        for level in range(1, CCZ_PRIMARY_LEVELS + 1):
            features[normalised_level_feature(window, level, CCZ_PRIMARY_LEVELS)] = (
                signal * level / 500.0 + noise / 10
            )
    if future_only:
        future = {horizon: 1.2 * signal + noise for horizon in RETURN_HORIZONS_SECONDS}
        past = {horizon: noise for horizon in RETURN_HORIZONS_SECONDS}
    elif past_only:
        future = {horizon: noise for horizon in RETURN_HORIZONS_SECONDS}
        past = {horizon: 1.2 * signal + noise for horizon in RETURN_HORIZONS_SECONDS}
    else:
        future = {horizon: 0.4 * signal + noise for horizon in RETURN_HORIZONS_SECONDS}
        past = {horizon: 0.1 * signal + noise for horizon in RETURN_HORIZONS_SECONDS}
    return HorseRaceObservation(
        tape_index=0,
        run_id="synthetic",
        receive_ts_ns=BASE + index * SECOND,
        features=features,
        future_ticks=future,
        past_ticks=past,
        same_window_ticks={window: signal for window in OFI_WINDOWS_SECONDS},
        window_start_ts_ns={
            window: BASE + index * SECOND - int(window * SECOND) + 1
            for window in OFI_WINDOWS_SECONDS
        },
        # `MICRO-02`: the discrete state the Stoikov chain conditions on.  Two states, so the
        # chain is estimable and the M8 arm is scored rather than blocked.
        microprice_state=f"i{9 if signal > 0 else 0}_s{index % 2}",
    )


def _config(**changes: Any) -> WalkForwardConfig:
    values: dict[str, Any] = {
        "test_block_seconds": 20.0,
        "refit_cadence_seconds": 5.0,
        "minimum_training_anchors": 40,
        "minimum_test_anchors": 8,
        "bootstrap_replicates": 20,
        "seed": 99,
    }
    values.update(changes)
    return WalkForwardConfig(**values)


def _first_partition(
    observations: list[HorseRaceObservation], config: WalkForwardConfig
) -> tuple[Any, ...]:
    partitions = WalkForwardRatchet(config).next_partitions(observations)
    assert partitions is not None
    return partitions


def test_walk_forward_ratchet_embargo_and_disjointness() -> None:
    observations = [_observation(index) for index in range(230)]
    ratchet = WalkForwardRatchet(_config())
    first = ratchet.next_partitions(observations)
    second = ratchet.next_partitions(observations)
    assert first is not None and second is not None
    assert {item.embargo_seconds for item in first} == {120.0}
    assert {
        item.embargo_seconds for item in first if item.h2_seconds == max(RETURN_HORIZONS_SECONDS)
    } == {max(120.0, 0.5 + max(RETURN_HORIZONS_SECONDS))}
    first_test = set(first[0].test)
    second_test = set(second[0].test)
    assert first_test.isdisjoint(second_test)
    assert first[0].test_end_ts_ns == second[0].test_start_ts_ns
    assert first_test <= ratchet.tested_ever
    assert ratchet.training_ever.isdisjoint(second_test)
    assert len(ratchet.completed_test_intervals) == 2


def test_block_waits_for_longest_response_endpoint() -> None:
    ratchet = WalkForwardRatchet(_config())
    assert ratchet.next_partitions([_observation(index) for index in range(190)]) is None
    assert ratchet.next_partitions([_observation(index) for index in range(192)]) is not None


def test_training_only_standardisation_ignores_changed_test_features() -> None:
    observations = [_observation(index) for index in range(205)]
    config = _config()
    partitions = _first_partition(observations, config)
    first = WalkForwardEvaluator(config).evaluate_block(
        observations, partitions, trade_identified=True
    )
    test_positions = set(partitions[0].test)
    changed = list(observations)
    for position in test_positions:
        features = dict(changed[position].features)
        for name in features:
            features[name] += 1_000_000.0
        changed[position] = replace(changed[position], features=features)
    second = WalkForwardEvaluator(config).evaluate_block(changed, partitions, trade_identified=True)
    first_cell = next(
        cell
        for cell in first
        if cell["model"] == "M4" and cell["h1_seconds"] == 1.0 and cell["h2_seconds"] == 1.0
    )
    second_cell = next(cell for cell in second if cell["cell_key"] == first_cell["cell_key"])
    assert first_cell["training_standardisation"] == second_cell["training_standardisation"]


def test_warm_up_gate_refuses_scores_and_keeps_all_cells_visible() -> None:
    observations = [_observation(index) for index in range(205)]
    partitions = _first_partition(observations, _config())
    config = _config(minimum_training_anchors=100)
    cells = WalkForwardEvaluator(config).evaluate_block(
        observations, partitions, trade_identified=True
    )
    assert len(cells) == CELL_COUNT
    assert {cell["status"] for cell in cells} == {"WARMING"}
    assert all(cell["accumulated"] is None for cell in cells)


def test_m2_is_blocked_without_fabricated_score_but_m6_remains_identified() -> None:
    observations = [_observation(index) for index in range(205)]
    config = _config()
    cells = WalkForwardEvaluator(config).evaluate_block(
        observations,
        _first_partition(observations, config),
        trade_identified=False,
    )
    m2 = [cell for cell in cells if cell["model"] == "M2"]
    assert len(m2) == 25
    assert {cell["status"] for cell in m2} == {"BLOCKED_UNIDENTIFIED"}
    assert all(cell["block"] is None for cell in m2)
    assert all(cell["status"] == "ESTIMATED" for cell in cells if cell["model"] == "M6")
    assert all(
        trade_feature(float(cell["h1_seconds"])) not in cell["features"]
        for cell in cells
        if cell["model"] == "M6"
    )


def _benchmarked_m1(observations: list[HorseRaceObservation]) -> float:
    config = _config()
    cells = WalkForwardEvaluator(config).evaluate_block(
        observations,
        _first_partition(observations, config),
        trade_identified=True,
    )
    cell = next(
        item
        for item in cells
        if item["model"] == "M1" and item["h1_seconds"] == 1.0 and item["h2_seconds"] == 1.0
    )
    return float(cell["accumulated"]["placebo_benchmarked_increment"])


def test_leakage_probe_detects_future_only_and_rejects_past_only() -> None:
    future_only = [_observation(index, future_only=True) for index in range(205)]
    past_only = [_observation(index, past_only=True) for index in range(205)]
    future_increment = _benchmarked_m1(future_only)
    past_increment = _benchmarked_m1(past_only)
    assert future_increment > 0.5
    assert past_increment <= 0.0


def test_bh_fdr_keeps_full_family_and_bootstrap_stratifies_blocks() -> None:
    observations = [_observation(index, future_only=True) for index in range(230)]
    config = _config()
    ratchet = WalkForwardRatchet(config)
    evaluator = WalkForwardEvaluator(config)
    first = ratchet.next_partitions(observations)
    second = ratchet.next_partitions(observations)
    assert first is not None and second is not None
    first_cells = evaluator.evaluate_block(observations, first, trade_identified=True)
    second_cells = evaluator.evaluate_block(observations, second, trade_identified=True)
    assert sum(cell["bh_fdr_q_value"] is not None for cell in first_cells) == CELL_COUNT
    assert all(cell["bh_fdr_q_value"] == 1.0 for cell in first_cells if cell["model"] == "M0")
    assert len(second_cells) == CELL_COUNT
    accumulator = evaluator.accumulators["M1|1|1"].future
    assert set(accumulator.tapes) == {0, 1}


def test_past_mirror_uses_exact_gap_and_never_crosses_epoch() -> None:
    def state(index: int, tick: int, epoch: int = 0) -> BookState:
        bid = 100.0 + tick * 0.05
        return BookState(
            channel=DEPTH20,
            receive_ts_ns=BASE + index * SECOND // 2,
            receive_sequence=index,
            connection_epoch=epoch,
            bids=((bid, 10, 1),),
            asks=((bid + 0.05, 10, 1),),
            rows_in_burst=1,
            quality_flags=(),
        )

    # The jump is inside [t-Z-h2, t-Z] but outside the old [t-h2, t] approximation.
    states = [state(index, 0 if index < 4 else 10) for index in range(13)]
    observation = replace(
        _observation(6),
        receive_ts_ns=BASE + 3 * SECOND,
        connection_epoch=0,
    )
    rebuilt, excluded = enforce_response_geometry([observation], states)
    assert excluded == 0
    assert rebuilt[0].past_ticks[1.0] == pytest.approx(10.0)
    assert rebuilt[0].future_ticks[1.0] == pytest.approx(0.0)

    epoch_states = [state(index, index, epoch=0 if index <= 6 else 1) for index in range(13)]
    assert enforce_response_geometry([observation], epoch_states) == ([], 1)


def test_canonical_offline_cell_parity_for_equivalent_split() -> None:
    observations = [_observation(index) for index in range(140)]
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 100)),
        test=tuple(range(100, 140)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    probe = offline_parity_probe(
        observations,
        split,
        trade_identified=True,
        tolerance=1e-12,
        replicates=20,
        seed=99,
    )
    assert probe["passed"]
    assert probe["canonical_cells"] == CELL_COUNT
    assert probe["dashboard_cells"] == CELL_COUNT
    assert probe["maximum_absolute_difference"] <= 1e-12


def test_torn_line_bytewise_tail_matches_complete_read(tmp_path: Path) -> None:
    rows = [{"receive_sequence": index, "value": index * 2} for index in range(6)]
    payload = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
    complete_path = tmp_path / "complete.jsonl"
    complete_path.write_bytes(payload)
    complete_reader = CompleteLineJsonlTail(complete_path)
    expected = complete_reader.drain_available()
    assert complete_reader.torn_lines == 0

    growing = tmp_path / "growing.jsonl"
    growing.write_bytes(b"")
    reader = CompleteLineJsonlTail(growing)
    observed: list[dict[str, Any]] = []
    with growing.open("ab") as handle:
        for value in payload:
            handle.write(bytes((value,)))
            handle.flush()
            observed.extend(reader.poll(max_bytes=1).rows)
    assert tuple(observed) == expected
    assert reader.trailing_partial_bytes == 0
    assert reader.malformed_lines == 0
    assert reader.torn_lines == len(rows)


def test_refit_without_a_new_block_retains_last_valid_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _empty_dashboard(tmp_path)
    estimated = dict(engine.cells[0])
    estimated["status"] = "ESTIMATED"
    estimated["accumulated"] = {"placebo_benchmarked_increment": 0.1}
    engine.cells[0] = estimated
    engine.ratchet.completed_test_intervals.append((BASE, BASE + SECOND))
    engine.last_tape_ts_ns = BASE + 10 * SECOND
    monkeypatch.setattr(engine, "_rebuild_observations", lambda: None)
    monkeypatch.setattr(engine.ratchet, "next_partitions", lambda observations: None)
    assert engine.refit() == 1
    assert engine.cells[0]["status"] == "ESTIMATED"


def test_malformed_complete_line_counted_and_not_zero_filled(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b'{"ok":1}\n{"broken":\n{"ok":2}\n')
    reader = CompleteLineJsonlTail(path)
    assert reader.drain_available() == ({"ok": 1}, {"ok": 2})
    assert reader.malformed_lines == 1


def test_two_logical_torn_lines_count_when_one_append_finishes_and_starts_next(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-torn.jsonl"
    path.write_bytes(b'{"first":')
    reader = CompleteLineJsonlTail(path)
    assert reader.poll().rows == ()
    assert reader.torn_lines == 1
    with path.open("ab") as handle:
        handle.write(b'1}\n{"second":')
    assert reader.poll().rows == ({"first": 1},)
    assert reader.torn_lines == 2
    with path.open("ab") as handle:
        handle.write(b"2}\n")
    assert reader.poll().rows == ({"second": 2},)
    assert reader.trailing_partial_bytes == 0


def _empty_dashboard(tmp_path: Path) -> tuple[OfiDashboardEngine, CompleteLineJsonlTail]:
    tape = tmp_path / "empty.jsonl"
    tape.write_bytes(b"")
    tail = CompleteLineJsonlTail(tape)
    engine = OfiDashboardEngine(
        run_id="test",
        drive_mode="replay",
        tape_identity="pinned#sha256=test",
        config=_config(),
    )
    return engine, tail


def test_val_ccz_08_dashboard_payload_carries_the_estimator_block(tmp_path: Path) -> None:
    """`VAL-CCZ-08`: the dashboard publishes estimator, level count, EVR and ID-CCZ-01."""

    engine, tail = _empty_dashboard(tmp_path)

    payload = engine.payload(
        rows_parsed=tail.rows_parsed,
        torn_lines=tail.torn_lines,
        trailing_partial_bytes=tail.trailing_partial_bytes,
        malformed_lines=tail.malformed_lines,
    )

    ccz = payload["ccz"]
    assert ccz["estimator"] == "CCZ"
    assert ccz["primary_level_count"] == CCZ_PRIMARY_LEVELS
    assert ccz["declared_level_counts"] == list(CCZ_LEVEL_COUNTS)
    assert ccz["cumulates_across_levels"] is False
    assert ccz["per_band_denominator"] is False
    assert "ID-CCZ-01" in ccz["limitation"]
    assert payload["migration_document"] == "research/docs/legacy/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md"
    # Before any refit there is no fitted component, and none is fabricated.
    assert payload["ccz_integrated_weights"] == {}
    assert ccz["explained_variance_ratio"] == {}
    assert engine.cells_payload()["ccz"]["estimator"] == "CCZ"


def test_ccz_integrated_weights_are_fitted_on_the_training_block_only() -> None:
    """`VAL-CCZ-04` at the dashboard boundary: the component never sees a test row."""

    observations = [_observation(index) for index in range(400)]
    engine = OfiDashboardEngine(
        run_id="test",
        drive_mode="replay",
        tape_identity="pinned#sha256=test",
        config=_config(),
    )
    engine.observations = observations
    partitions = WalkForwardRatchet(engine.config).next_partitions(observations)
    assert partitions is not None

    diagnostics = engine._integrated_arm_diagnostics(partitions)

    assert diagnostics
    for key, value in diagnostics.items():
        assert key.endswith(f"__m{CCZ_PRIMARY_LEVELS}")
        if value["status"] != "ESTIMATED":
            continue
        assert value["fitted_on"] == "training_rows_only"
        assert value["training_rows"] <= len(partitions[0].train)
        assert 0.0 <= value["explained_variance_ratio"] <= 1.0
        assert abs(sum(abs(weight) for weight in value["normalised_weights"]) - 1.0) < 1e-9


def test_rendering_theme_and_matrix_view_field_parity(tmp_path: Path) -> None:
    engine, tail = _empty_dashboard(tmp_path)
    payload = engine.payload(
        rows_parsed=tail.rows_parsed,
        torn_lines=tail.torn_lines,
        trailing_partial_bytes=tail.trailing_partial_bytes,
        malformed_lines=tail.malformed_lines,
    )
    html = render_html(payload)
    required = (
        "anl06-theme",
        "prefers-color-scheme",
        "#46586b",
        "#8199b0",
        "#b5851f",
        "#d3a44a",
        "#8f3327",
        "#c05c46",
        "#5b7a52",
        "#8faa7c",
        "#f4f2ec",
        "#17191c",
        "CCZ OFI (C8) · displayed mid · 10 book levels",
        "OFI sampling horizon \\u2192",
        "Forecast horizon \\u2193",
        "past 2, 5, 10, 15 or 30 minutes",
        "const LOOKBACKS=[0.5,1,2,5,10],HORIZONS=[0.5,1,2,5,10,20]",
        "Live walk-forward",
        "5m score '+score+' · n='+cell.scoreN",
        "+1 when the realised move reaches the forecast magnitude",
        "READ-ONLY",
        "NO SOCKET",
        "NO ORDER PATH",
        "fetch('/api/overview')",
    )
    assert all(field in html for field in required)
    assert "WHAT MATTERS NOW" not in html
    assert "Full ANL-06 diagnostic grids" not in html
    assert "fetch('/api/cells')" not in html
    assert payload["axes"]["cells"] == CELL_COUNT
    assert len(payload["cells"]) == CELL_COUNT
    # 5% of the grid; the grid grew with M7 and M8, so the false-positive budget grew with it
    assert payload["honesty"]["expected_by_chance_at_5pct"] == pytest.approx(
        0.05 * EXPECTED_CELL_COUNT
    )
    assert payload["same_window_diagnostic"]["ranked_with_future_cells"] is False
    rail = payload["status_rail"]
    assert set(rail) >= {
        "anchors_consumed",
        "rows_parsed",
        "torn_lines",
        "malformed_lines",
        "current_epoch",
        "fit_age_seconds",
        "refits_completed",
        "refits_skipped",
        "warming_cells",
        "insufficient_cells",
        "last_completed_refit_wall_clock",
    }


def test_compact_matrix_payload_uses_only_rolling_c8_scores() -> None:
    primary = {
        "reference_price": "displayed_mid",
        "levels": 10,
        "h1_seconds": 1.0,
        "h2_seconds": 5.0,
        "verdict": "predictive",
        "c8_ccz_ofi_absolute_oos_r2": 0.07,
    }
    payload = {
        "schema_version": "test",
        "drive_mode": "follow",
        "tape_identity": "tape",
        "run_id": "run",
        "history_length": 2,
        "status_rail": {"rows_parsed": 3},
        "honesty": {"bh_fdr_positive_5pct": 0},
        "leader": None,
        "axes": {"cells": 225, "models": ["M0"]},
        "config": {"refit_cadence_seconds": 60},
        "cells": [{"large": "x" * 5000}],
        "ccz": {"large": "x" * 5000},
        "live_studies": {
            "status": "cycle_complete",
            "source": {"last_receive_ts": "2026-08-21T05:11:57+00:00"},
            "d38": {},
            "d39": {
                "completed_cells": 600,
                "total_cells": 600,
                "cells": [primary, {**primary, "reference_price": "last_trade"}],
            },
            "d40": {
                "completed_cells": 7,
                "total_cells": 7,
                "rows": [{"horizon_seconds": 20.0, "absolute_oos_r2": -0.22}],
            },
        },
        "rolling_c8": {
            "status": "running",
            "training_windows_seconds": [120.0, 300.0, 600.0, 900.0, 1800.0],
            "forecast_cadence_seconds": 5.0,
            "source": {"last_receive_ts": "2026-08-21T05:12:02+00:00"},
            "cells": [
                {
                    "training_window_minutes": 30.0,
                    "lookback_seconds": 1.0,
                    "horizon_seconds": 5.0,
                    "cumulative_oos_r2": 0.13,
                    "rolling_mean_win_score_5m": 0.2,
                    "rolling_win_score_n_5m": 20,
                    "rolling_wins_5m": 7,
                    "rolling_neutral_5m": 10,
                    "rolling_losses_5m": 3,
                    "scored_n": 25,
                    "forecasts_issued": 27,
                }
            ],
        },
    }

    compact = compact_dashboard_payload(payload)

    assert "cells" not in compact
    assert "ccz" not in compact
    assert compact["live_studies"]["d39"]["primary_displayed_mid_m10"] == [primary]
    assert [matrix["training_window_minutes"] for matrix in compact["matrices"]] == list(
        MATRIX_TRAINING_WINDOWS_MINUTES
    )
    matrix = compact["matrices"][-1]
    assert matrix["h1_seconds"] == list(MATRIX_LOOKBACKS_SECONDS)
    assert matrix["h2_seconds"] == list(MATRIX_HORIZONS_SECONDS)
    matrix_cells = {(cell["h1_seconds"], cell["h2_seconds"]): cell for cell in matrix["cells"]}
    assert matrix_cells[(1.0, 5.0)]["cumulative_oos_r2"] == pytest.approx(0.13)
    assert matrix_cells[(1.0, 5.0)]["rolling_mean_win_score_5m"] == pytest.approx(0.2)
    assert matrix_cells[(1.0, 5.0)]["source"] == "rolling_c8_30m"
    assert (10.0, 20.0) not in matrix_cells
    assert len(json.dumps(compact)) < len(json.dumps(payload))


def test_live_studies_remain_available_while_dashboard_refit_is_in_progress(
    tmp_path: Path,
) -> None:
    engine, tail = _empty_dashboard(tmp_path)
    live_path = tmp_path / "live-studies.json"
    live_payload = {
        "status": "running",
        "current_stage": "d39",
        "d39": {"status": "running", "completed_cells": 17, "total_cells": 600},
    }
    live_path.write_text(json.dumps(live_payload), encoding="utf-8")
    state = OfiDashboardState(engine, tail, live_studies_path=live_path)
    initial = state.payload()
    engine.fit_in_progress = True
    engine.payload = lambda **_kwargs: pytest.fail("refit request recomputed dashboard payload")  # type: ignore[method-assign]
    engine.cells_payload = lambda: pytest.fail("refit request recomputed cell payload")  # type: ignore[method-assign]

    payload = state.payload()
    cells = state.cells()

    assert initial["live_studies"] == live_payload
    assert payload["live_studies"] == live_payload
    assert payload["status_rail"]["refit_in_progress"] is True
    assert cells["refit_in_progress"] is True


def test_read_only_server_exposes_live_study_get_route_and_no_write_method(
    tmp_path: Path,
) -> None:
    engine, tail = _empty_dashboard(tmp_path)
    live_path = tmp_path / "live-studies.json"
    live_path.write_text('{"status":"running","current_stage":"d40"}\n', encoding="utf-8")
    rolling_path = tmp_path / "rolling-c8.json"
    rolling_path.write_text('{"status":"running","model":"C8"}\n', encoding="utf-8")
    state = OfiDashboardState(
        engine, tail, live_studies_path=live_path, rolling_c8_path=rolling_path
    )
    server = build_server(state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for route in (
            "/",
            "/api/overview",
            "/api/state",
            "/api/cells",
            "/api/live-studies",
            "/api/rolling-c8",
        ):
            with urllib.request.urlopen(base + route, timeout=2) as response:
                assert response.status == 200
        with urllib.request.urlopen(base + "/api/live-studies", timeout=2) as response:
            assert json.load(response)["current_stage"] == "d40"
        with urllib.request.urlopen(base + "/api/rolling-c8", timeout=2) as response:
            assert json.load(response)["model"] == "C8"
        with pytest.raises(urllib.error.HTTPError) as missing_history:
            urllib.request.urlopen(base + "/api/history?index=0", timeout=2)
        assert missing_history.value.code == 404
        request = urllib.request.Request(base + "/api/state", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as write_attempt:
            urllib.request.urlopen(request, timeout=2)
        assert write_attempt.value.code == 501
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert ALLOWED_METHODS == ("GET", "HEAD")


def test_artifact_is_complete_and_replay_hash_is_deterministic(tmp_path: Path) -> None:
    cells = OfiDashboardEngine(
        run_id="artifact",
        drive_mode="replay",
        tape_identity="pinned",
        config=_config(),
    ).cells
    summaries: list[dict[str, Any]] = []
    for name in ("one", "two"):
        sink = RefitArtifactSink(tmp_path / name)
        sink.append(cells)
        summaries.append(sink.close({"scan": "test"}))
        lines = (tmp_path / name / "ofi_dashboard_cells.jsonl").read_text().splitlines()
        assert len(lines) == CELL_COUNT
        assert all(
            json.loads(line)["status"] in {"WARMING", "BLOCKED_UNIDENTIFIED"} for line in lines
        )
    assert summaries[0]["cells_sha256"] == summaries[1]["cells_sha256"]


def test_cli_module_has_no_socket_credential_or_order_path_import() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / relative).read_text()
        for relative in (
            "src/shaurya/analytics/ofi_dashboard.py",
            "src/shaurya/analytics/ofi_dashboard_server.py",
            "src/shaurya/cli/ofi_dashboard.py",
            "src/shaurya/analytics/live_ofi_studies.py",
            "src/shaurya/cli/live_ofi_studies.py",
            "src/shaurya/analytics/rolling_c8.py",
            "src/shaurya/cli/rolling_c8.py",
        )
    ).lower()
    forbidden_imports = (
        "from shaurya.data.dhan_stream",
        "from shaurya.data.dhan_client",
        "import websockets",
        "from shaurya.execution",
        "from shaurya.orders",
    )
    assert not any(value in sources for value in forbidden_imports)
    assert "--credentials" not in sources


def test_every_model_feature_set_comes_from_canonical_signal_module() -> None:
    engine_cells = OfiDashboardEngine(
        run_id="features",
        drive_mode="replay",
        tape_identity="pinned",
        config=_config(),
    ).cells
    for cell in engine_cells:
        assert tuple(cell["features"]) == model_features(
            cell["model"], float(cell["h1_seconds"]), trade_identified=False
        )
    assert {cell["model"] for cell in engine_cells} == set(MODEL_ORDER)


def _ranked_cell(
    engine: OfiDashboardEngine,
    index: int,
    *,
    future_increment: float,
    past_increment: float,
) -> str:
    cell = dict(engine.cells[index])
    cell["status"] = "ESTIMATED"
    cell["accumulated"] = {
        "future_incremental_oos_r2_over_m0": future_increment,
        "past_incremental_oos_r2_over_m0": past_increment,
        "placebo_benchmarked_increment": future_increment - past_increment,
    }
    cell["past_mirror_exceeds_or_equals_future"] = past_increment >= future_increment
    cell["green"] = False
    engine.cells[index] = cell
    return str(cell["cell_key"])


def test_leader_ranks_by_future_increment_not_by_a_collapsed_placebo(tmp_path: Path) -> None:
    """AMENDMENT-1: a cell must not lead because its past mirror collapsed.

    Reproduces the 2026-08-20 live pathology: M2|10|10 showed a future increment of +0.039
    against a past mirror of -0.777, so its benchmarked difference was +0.816 and it led the
    board while barely predicting anything. Ranking by the difference rewards the broken
    placebo; ranking by the future increment does not.
    """
    engine, _ = _empty_dashboard(tmp_path)
    collapsed_placebo = _ranked_cell(engine, 0, future_increment=0.039, past_increment=-0.777)
    genuine_predictor = _ranked_cell(engine, 1, future_increment=0.100, past_increment=0.020)

    engine._update_churn()

    assert engine.current_leader == genuine_predictor
    assert engine.current_leader != collapsed_placebo
    benchmarked = engine.cells[0]["accumulated"]["placebo_benchmarked_increment"]
    assert benchmarked > engine.cells[1]["accumulated"]["placebo_benchmarked_increment"]


def test_cell_failing_the_placebo_guard_never_leads(tmp_path: Path) -> None:
    engine, _ = _empty_dashboard(tmp_path)
    _ranked_cell(engine, 0, future_increment=0.500, past_increment=0.900)
    survivor = _ranked_cell(engine, 1, future_increment=0.010, past_increment=-0.005)

    engine._update_churn()

    assert engine.current_leader == survivor


def test_no_leader_when_every_cell_fails_the_placebo_guard(tmp_path: Path) -> None:
    engine, _ = _empty_dashboard(tmp_path)
    _ranked_cell(engine, 0, future_increment=0.100, past_increment=0.400)
    _ranked_cell(engine, 1, future_increment=0.020, past_increment=0.020)

    engine._update_churn()

    assert engine.current_leader is None
