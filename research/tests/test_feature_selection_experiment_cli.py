from __future__ import annotations

import json
from pathlib import Path

import pytest

from shaurya.cli import feature_selection_experiment as cli
from shaurya.signals.feature_selection import FeatureSelectionRow


def test_bounded_futures_reader_overrides_legacy_replication_date(monkeypatch) -> None:
    observed_dates = []

    def fake_rows(tape: Path, *, trading_date):
        del tape
        observed_dates.append(trading_date)
        yield {
            "receive_ts": "2026-08-21T08:06:12.449470+00:00",
            "event_type": "depth20",
        }

    monkeypatch.setattr(cli, "iter_session_rows", fake_rows)
    rows = tuple(
        cli._bounded_session_rows(
            Path("unused.jsonl"),
            start_ts_ns=1_787_299_572_000_000_000,
            end_ts_ns=1_787_299_573_000_000_000,
        )
    )
    assert len(rows) == 1
    assert observed_dates == [cli.TRADING_DATE]
    assert cli.TRADING_DATE.isoformat() == "2026-08-21"


def test_sha_bound_materialization_cache_has_exact_deterministic_readback() -> None:
    row = FeatureSelectionRow(
        anchor_ts_ns=1_000_000_000,
        connection_epoch=3,
        target_start_ts_ns=1_500_000_000,
        target_end_ts_ns=11_500_000_000,
        target_ticks=1.25,
        feature_values={"surface__example": None, "ofi__example": -2.5},
        feature_available_ts_ns={"surface__example": None, "ofi__example": 999_000_000},
    )
    futures = {"tape_sha256": "a" * 64, "rows": 10}
    surface = {
        "dataset_id": cli.SURFACE_DATASET_ID,
        "tape_sha256": "b" * 64,
        "rows": 20,
    }
    encoded = cli._materialization_cache_bytes(
        (row,),
        grid_seconds=1,
        futures_source=futures,
        surface_source=surface,
        constructed_row_count=2,
    )
    assert encoded == cli._materialization_cache_bytes(
        (row,),
        grid_seconds=1,
        futures_source=futures,
        surface_source=surface,
        constructed_row_count=2,
    )
    rows, read_futures, read_surface, constructed = cli._materialization_cache_from_bytes(
        encoded,
        grid_seconds=1,
        futures_sha256="a" * 64,
        surface_dataset_id=cli.SURFACE_DATASET_ID,
        surface_sha256="b" * 64,
    )
    assert rows == (row,)
    assert read_futures == futures
    assert read_surface == surface
    assert constructed == 2


def test_compute_checkpoint_resumes_without_refit_and_rejects_identity_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "checkpoint.json"
    calls = 0

    def factory() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"selected_estimators": 7}

    def serializer(value: dict[str, int]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def reader(value: str) -> dict[str, int]:
        payload = json.loads(value)
        return {str(name): int(item) for name, item in payload.items()}
    identity = {"row_sha256": "a" * 64, "fold": "outer_01"}
    first = cli._load_or_build_checkpoint(
        path,
        kind="walk_forward",
        identity=identity,
        factory=factory,
        serializer=serializer,
        reader=reader,
    )
    second = cli._load_or_build_checkpoint(
        path,
        kind="walk_forward",
        identity=identity,
        factory=factory,
        serializer=serializer,
        reader=reader,
    )
    assert first == second == {"selected_estimators": 7}
    assert calls == 1
    assert not tuple(tmp_path.glob(".*.partial.*"))
    with pytest.raises(ValueError, match="identity changed"):
        cli._load_or_build_checkpoint(
            path,
            kind="walk_forward",
            identity={**identity, "fold": "outer_02"},
            factory=factory,
            serializer=serializer,
            reader=reader,
        )
    assert calls == 1
