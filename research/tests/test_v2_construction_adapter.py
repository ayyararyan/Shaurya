from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import DataCaptureSession, DataCatalog
from shaurya.research.registry import registry_by_version
from shaurya.research.source import derive_research_dataset, discover_completed_sources

REGISTRIES = Path("registries")


def _capture_futures(root: Path) -> tuple[DataCatalog, str]:
    session_date = date(2026, 8, 27)
    stamp = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    instrument = "NSE:NSE_FNO:NIFTY:future:2026-09-24"
    run_id = RunId("sha-20260827T034500.000000Z-1234abcd")
    catalog = DataCatalog(root / "catalog.jsonl")
    capture = DataCaptureSession.create(
        catalog=catalog,
        request=DatasetRequest(
            consumer="SIG",
            purpose="v2 construction adapter regression",
            trading_date=session_date,
            channels=(DataChannel.DEPTH20,),
            instrument_ids=(instrument,),
        ),
        output_root=root / "raw",
        run_id=run_id,
        fsync_every=1,
        index_stride_rows=10,
    )
    for index in range(75):
        midpoint = 25_000.0 + 0.05 * index + 0.02 * ((index % 5) - 2)
        bid_quantities = (130 + index, 115, 100, 90, 80)
        ask_quantities = (90 + index // 2, 95, 100, 105, 110)
        capture.write(
            TapeRow(
                run_id=str(run_id),
                receive_sequence=index + 1,
                connection_epoch=1,
                source="synthetic_v2_fixture",
                event_type="depth20",
                instrument_id=instrument,
                broker_security_id="58072",
                exchange_segment="NSE_FNO",
                receive_ts=stamp + timedelta(seconds=index),
                raw_message_size_bytes=100,
                update_side="both",
                bids=tuple(
                    DepthLevel(midpoint - 0.05 * (level + 1), quantity, 5 - level)
                    for level, quantity in enumerate(bid_quantities)
                ),
                asks=tuple(
                    DepthLevel(midpoint + 0.05 * (level + 1), quantity, level + 1)
                    for level, quantity in enumerate(ask_quantities)
                ),
            )
        )
    handle = capture.close()
    return catalog, handle.dataset_id


def test_v2_futures_derivation_uses_registry_semantics_and_explicit_missingness(
    tmp_path: Path,
) -> None:
    catalog, dataset_id = _capture_futures(tmp_path)
    sources = discover_completed_sources(catalog, through=date(2026, 8, 27))
    assert tuple(item.dataset_id for item in sources) == (dataset_id,)

    features = registry_by_version(
        REGISTRIES, "microstructure_features_v2", expected_type="features"
    )
    targets = registry_by_version(
        REGISTRIES, "microstructure_targets_v2", expected_type="targets"
    )
    dataset = derive_research_dataset(
        sources, feature_registry=features, target_registry=targets
    )

    row = next(
        item
        for item in dataset.features
        if item.value_map["futures.quantity_imbalance_cum1.v1"] is not None
        and item.value_map["risk.midpoint_vol_10s.v2"] is not None
    )
    assert row.value_map["liquidity.log_l1_depth.v1"] is not None
    assert row.value_map["futures.ccz_ofi_0p5s_m1_average.v1"] is not None
    # Cross-option context has no legal substitute on a futures-only tape.
    assert row.value_map["parity.pressure.v1"] is None
    assert row.value_map["option.call_put_surface_residual_diff.v2"] is None

    one_second = next(
        item.target
        for item in dataset.rows
        if item.target.target_id == "target.futures.mid_move_ticks_1s.v1"
        and item.target.value is not None
    )
    assert abs(one_second.value or 0.0) < 10.0
    assert one_second.registry_version == "microstructure_targets_v2"

    range_target = next(
        item.target
        for item in dataset.rows
        if item.target.target_id == "target.futures.range_ticks_10s.v1"
        and item.target.value is not None
    )
    assert (range_target.value or 0.0) >= 0.0
