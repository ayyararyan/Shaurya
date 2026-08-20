from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from shaurya.analytics.ofi_dashboard import (
    CELL_COUNT,
    CompleteLineJsonlTail,
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
    OfiDashboardState,
    build_server,
    render_html,
)
from shaurya.data.depth_thinning_analysis import DEPTH20, BookState
from shaurya.signals.deep_book_normal_activity import SplitIndex
from shaurya.signals.deep_book_ofi import OFI_WINDOWS_SECONDS
from shaurya.signals.ofi_horserace import (
    BANDS,
    MODEL_ORDER,
    RETURN_HORIZONS_SECONDS,
    HorseRaceObservation,
    adjusted_band_feature,
    cks_feature,
    model_features,
    normalised_trade_feature,
    pk_band_feature,
    trade_feature,
)

SECOND = 1_000_000_000
BASE = 1_777_000_000 * SECOND


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
    }
    for window in OFI_WINDOWS_SECONDS:
        features[trade_feature(window)] = signal * (1.0 + window / 20.0)
        features[normalised_trade_feature(window)] = signal / 12.0
        features[cks_feature(window)] = signal * (2.0 + window / 20.0)
        for band_index, band in enumerate(BANDS, start=1):
            features[pk_band_feature(window, *band)] = signal * band_index + noise
            features[adjusted_band_feature(window, *band)] = signal / band_index + noise / 10
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
    assert sum(cell["bh_fdr_q_value"] is not None for cell in first_cells) == 175
    assert all(cell["bh_fdr_q_value"] == 1.0 for cell in first_cells if cell["model"] == "M0")
    assert len(second_cells) == 175
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
    assert probe["canonical_cells"] == 175
    assert probe["dashboard_cells"] == 175
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


def test_rendering_theme_and_frozen_field_parity(tmp_path: Path) -> None:
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
        "RAW OOS R² + PLACEBO-BENCHMARKED INCREMENT ALWAYS VISIBLE",
        "BRICK",
        "WARMING",
        "INSUFFICIENT",
        "SAME-WINDOW CONSTRUCTION DIAGNOSTIC",
        "BH-FDR",
        "READ-ONLY",
        "NO SOCKET",
        "NO ORDER PATH",
    )
    assert all(field in html for field in required)
    assert payload["axes"]["cells"] == 175
    assert len(payload["cells"]) == 175
    assert payload["honesty"]["expected_by_chance_at_5pct"] == 8.75
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


def test_read_only_server_exposes_four_get_routes_and_no_write_method(tmp_path: Path) -> None:
    engine, tail = _empty_dashboard(tmp_path)
    state = OfiDashboardState(engine, tail)
    server = build_server(state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for route in ("/", "/api/state", "/api/cells"):
            with urllib.request.urlopen(base + route, timeout=2) as response:
                assert response.status == 200
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
        assert len(lines) == 175
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
