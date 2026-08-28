from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from shaurya.cli.research import main
from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import DataCaptureSession, DataCatalog
from shaurya.research.ledger import EvidenceLedger
from shaurya.research.state import StateStore


def _session(root: Path, trading_date: date, seed: int) -> None:
    stamp = datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC) + timedelta(hours=4)
    run_id = RunId(f"sha-{stamp:%Y%m%dT%H%M%S}.000000Z-{seed:08x}")
    instrument = "NSE:NSE_FNO:NIFTY:future:2026-09-24"
    capture = DataCaptureSession.create(
        catalog=DataCatalog(root / "catalog.jsonl"),
        request=DatasetRequest(
            consumer="SIG",
            purpose="daily automation warmup fixture",
            trading_date=trading_date,
            channels=(DataChannel.DEPTH20,),
            instrument_ids=(instrument,),
        ),
        output_root=root / "raw",
        run_id=run_id,
        fsync_every=1,
        index_stride_rows=5,
    )
    for index in range(16):
        mid = 25_000.0 + seed + index * 0.05
        capture.write(
            TapeRow(
                run_id=str(run_id),
                receive_sequence=index + 1,
                connection_epoch=1,
                source="daily_warmup_fixture",
                event_type="depth20",
                instrument_id=instrument,
                broker_security_id="58072",
                exchange_segment="NSE_FNO",
                receive_ts=stamp + timedelta(seconds=index),
                raw_message_size_bytes=100,
                update_side="both",
                bids=tuple(
                    DepthLevel(mid - 0.05 * (level + 1), 100 + level + index, 3)
                    for level in range(5)
                ),
                asks=tuple(
                    DepthLevel(mid + 0.05 * (level + 1), 95 + level + index, 3)
                    for level in range(5)
                ),
            )
        )
    capture.close()


def test_daily_auto_bootstrap_advances_cleanly_during_warmup(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    for seed, trading_date in enumerate(
        (date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 31)), start=1
    ):
        _session(source_root, trading_date, seed)

    workspace = tmp_path / "research"
    result = main(
        [
            "daily",
            "--date",
            "2026-08-31",
            "--next-session",
            "2026-09-01",
            "--catalog",
            str(source_root / "catalog.jsonl"),
            "--registry-dir",
            str(Path(__file__).resolve().parents[1] / "registries"),
            "--ledger",
            str(workspace / "ledger.jsonl"),
            "--plan-dir",
            str(workspace / "plans"),
            "--state-dir",
            str(workspace / "state"),
            "--report-dir",
            str(workspace / "reports"),
            "--snapshot-dir",
            str(workspace / "snapshots"),
        ]
    )
    assert result == 0

    ledger = EvidenceLedger(workspace / "ledger.jsonl")
    events = ledger.events()
    warmups = [
        event
        for event in events
        if event.get("terminal_reason") == "insufficient_prior_sessions_for_prospective_fold"
    ]
    assert len(warmups) == 1
    assert warmups[0]["prior_sessions"] == 2
    assert warmups[0]["required_prior_sessions"] == 6

    state = StateStore(workspace / "state").load_as_of(date(2026, 8, 31))
    assert state is not None
    assert state.as_of_date == date(2026, 8, 31)
    assert state.intended_for_session == date(2026, 9, 1)
    assert len(state.source_prefix_manifest) == 3
    assert state.plan_hash
    # A scheduler retry for the same completed session is a deterministic no-op.
    before_events = ledger.events()
    before_state = state.state_hash
    assert (
        main(
            [
                "daily",
                "--date",
                "2026-08-31",
                "--next-session",
                "2026-09-01",
                "--catalog",
                str(source_root / "catalog.jsonl"),
                "--registry-dir",
                str(Path(__file__).resolve().parents[1] / "registries"),
                "--ledger",
                str(workspace / "ledger.jsonl"),
                "--plan-dir",
                str(workspace / "plans"),
                "--state-dir",
                str(workspace / "state"),
                "--report-dir",
                str(workspace / "reports"),
                "--snapshot-dir",
                str(workspace / "snapshots"),
            ]
        )
        == 0
    )
    assert ledger.events() == before_events
    repeated = StateStore(workspace / "state").load_as_of(date(2026, 8, 31))
    assert repeated is not None
    assert repeated.state_hash == before_state
