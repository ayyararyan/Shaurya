from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from shaurya.contracts.artifacts import ArtifactManifest, RunId
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
)
from shaurya.contracts.tape import QualityFlag
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig, StreamMetrics
from shaurya.data.quality import CollectorQualityAudit, write_quality_audit
from tests.test_dhan_stream import _deep_message

IST = ZoneInfo("Asia/Kolkata")


def _mapping() -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.FUTURE,
            expiry=date(2026, 8, 25),
        ),
        security_id="58072",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="NIFTY-Aug2026-FUT",
        lot_size=65,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 18),
        source="fixture",
    )


def test_split_book_marks_stale_other_side_and_counts_it() -> None:
    rows = []
    metrics = StreamMetrics()
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        rows.append,
        run_id="sha-20260818T053000.000000Z-1234abcd",
        metrics=metrics,
        config=DhanStreamConfig(stale_quote_after_seconds=1.0),
    )
    stream._epochs["depth20"] = 1
    from shaurya.data.dhan_stream import parse_deep_packets

    bid = parse_deep_packets(_deep_message(41))[0]
    ask = parse_deep_packets(_deep_message(51))[0]
    now = datetime(2026, 8, 18, 5, 30, tzinfo=UTC)
    stream._emit_deep(ask, now, channel="depth20")  # type: ignore[arg-type]
    stream._emit_deep(bid, now + timedelta(seconds=2), channel="depth20")  # type: ignore[arg-type]
    assert QualityFlag.STALE_QUOTE in rows[-1].quality_flags
    assert metrics.quality_counts[QualityFlag.STALE_QUOTE.value] == 1


def test_quality_audit_emits_required_zero_and_nonzero_counters(tmp_path: Path) -> None:
    run_id = RunId("sha-20260818T053000.000000Z-1234abcd")
    manifest = ArtifactManifest.create(tmp_path, run_id)
    metrics = StreamMetrics(rows=4)
    metrics.quality_counts[QualityFlag.CROSSED_BOOK.value] = 1
    metrics.quality_counts[QualityFlag.CONNECTION_GAP.value] = 2
    audit = CollectorQualityAudit.from_metrics(
        str(run_id),
        metrics,
        recorded_at=datetime(2026, 8, 18, 11, 0, tzinfo=IST),
    )
    assert audit.crossed_book == 1
    assert audit.stale_quote == 0
    assert audit.invalid_depth == 0
    assert audit.gap_count == 2
    path = write_quality_audit(manifest, audit)
    payload = json.loads(path.read_text())
    assert payload["stale_quote"] == 0
    assert payload["category"] == "derived"
