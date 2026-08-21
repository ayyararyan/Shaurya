"""Acceptance probes for live D38/D39/D40 complete-prefix publication."""

from __future__ import annotations

import json
from pathlib import Path

from shaurya.analytics.live_ofi_studies import (
    LiveStudyStateWriter,
    complete_prefix_offset,
    d40_curve_summary,
)


def test_live_prefix_boundary_excludes_a_torn_final_jsonl_row(tmp_path: Path) -> None:
    tape = tmp_path / "growing.jsonl"
    complete = b'{"receive_sequence":1}\n{"receive_sequence":2}\n'
    tape.write_bytes(complete + b'{"receive_sequence":3')

    assert complete_prefix_offset(tape) == len(complete)


def test_d40_curve_reports_peak_and_first_decline_only_when_all_horizons_exist() -> None:
    rows = [
        {"horizon_seconds": horizon, "absolute_oos_r2": value}
        for horizon, value in zip(
            (10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0),
            (0.01, 0.02, 0.03, 0.025, 0.024, 0.02, 0.01),
            strict=True,
        )
    ]

    summary = d40_curve_summary(rows)

    assert summary["complete"] is True
    assert summary["peak_horizon_seconds"] == 30.0
    assert summary["first_decline_horizon_seconds"] == 45.0
    assert summary["strictly_increasing"] is False


def test_live_state_writer_publishes_each_partial_cell_atomically(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    writer = LiveStudyStateWriter(
        state_path,
        tmp_path / "artifacts",
        run_id="live-test",
        dataset_id="dataset-test",
    )
    cells_path = writer.start_cells("d39", total=600)
    cell = {"reference_price": "displayed_mid", "levels": 10, "competitors": []}
    summary = {"reference_price": "displayed_mid", "levels": 10, "status": "estimated"}

    writer.publish_cell(
        "d39",
        cell=cell,
        summary=summary,
        completed=1,
        total=600,
        artifact_path=cells_path,
    )

    published = json.loads(state_path.read_text(encoding="utf-8"))
    assert published["d39"]["status"] == "running"
    assert published["d39"]["completed_cells"] == 1
    assert published["d39"]["cells"] == [summary]
    assert json.loads(cells_path.read_text(encoding="utf-8")) == cell
    assert published["confirmatory_eligible"] is False
    assert published["successive_prefixes_independent"] is False
