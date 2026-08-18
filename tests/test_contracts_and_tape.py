from __future__ import annotations

import json
import stat
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shaurya.contracts.artifacts import ArtifactManifest, RunId
from shaurya.contracts.instruments import DhanInstrumentMaster, InstrumentKind
from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow
from shaurya.data.tape import JsonlTapeReader, JsonlTapeWriter, TapeIntegrityError


def _row(run_id: str) -> TapeRow:
    return TapeRow(
        run_id=run_id,
        receive_sequence=1,
        source_sequence=None,
        connection_epoch=1,
        source="dhan",
        event_type="depth20",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        exchange_ts=None,
        receive_ts=datetime(2026, 8, 18, 5, 30, tzinfo=UTC),
        raw_message_size_bytes=332,
        update_side="bid",
        bids=(DepthLevel(24999.0, 130, 2),),
        quality_flags=(
            QualityFlag.SOURCE_SEQUENCE_UNAVAILABLE,
            QualityFlag.PARTIAL_BOOK,
        ),
    )


def test_tape_row_round_trip_preserves_depth_and_quality() -> None:
    original = _row("sha-20260818T053000.000000Z-1234abcd")
    restored = TapeRow.from_dict(original.to_dict())
    assert restored == original
    assert restored.best_bid == 24999.0
    assert restored.best_ask is None


def test_instrument_master_maps_dhan_id_to_broker_neutral_identity(tmp_path: Path) -> None:
    master = tmp_path / "security_id_list.csv"
    master.write_text(
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
        "SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,"
        "SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,"
        "SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME\n"
        "NSE,D,58072,FUTIDX,0,NIFTY-Aug2026-FUT,65,NIFTY AUG FUT,"
        "2026-08-25 14:30:00,-0.01000,XX,10.0000,M,FUTIDX,,NIFTY\n",
        encoding="utf-8",
    )
    mapping = DhanInstrumentMaster(master, as_of_date=date(2026, 8, 18)).find_by_security_id(
        "58072"
    )
    assert mapping.instrument.kind is InstrumentKind.FUTURE
    assert mapping.instrument.canonical == "NSE:NSE_FNO:NIFTY:future:2026-08-25"
    assert mapping.security_id == "58072"
    assert mapping.tick_size_paise is not None
    assert str(mapping.tick_size_paise) == "10.0000"


def test_manifest_and_tape_are_append_only_and_permission_restricted(tmp_path: Path) -> None:
    run_id = RunId("sha-20260818T053000.000000Z-1234abcd")
    manifest = ArtifactManifest.create(tmp_path, run_id)
    writer = JsonlTapeWriter(manifest, fsync_every=1)
    writer.write(_row(str(run_id)))
    writer.close()
    manifest.complete(rows=1)

    assert stat.S_IMODE(writer.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.path.stat().st_mode) == 0o600
    with writer.path.open(encoding="utf-8") as handle:
        payloads = [json.loads(line) for line in handle]
    assert payloads[0]["run_id"] == str(run_id)
    events = [json.loads(line)["event_type"] for line in manifest.path.read_text().splitlines()]
    assert events == ["run_started", "artifact_opened", "artifact_closed", "run_completed"]
    with pytest.raises(FileExistsError):
        JsonlTapeWriter(manifest)
    with pytest.raises(FileExistsError):
        ArtifactManifest.create(tmp_path, run_id)


def test_invalidation_appends_without_removing_the_tape(tmp_path: Path) -> None:
    run_id = RunId("sha-20260818T053000.000000Z-deadbeef")
    manifest = ArtifactManifest.create(tmp_path, run_id)
    writer = JsonlTapeWriter(manifest)
    writer.write(_row(str(run_id)))
    writer.close()
    manifest.invalidate("test-only invalidation")
    assert writer.path.exists()
    last = json.loads(manifest.path.read_text().splitlines()[-1])
    assert last["event_type"] == "run_invalidated"
    assert last["status"] == "invalidated"


def test_deterministic_replay_preserves_rows_order_and_quality(tmp_path: Path) -> None:
    run_id = RunId("sha-20260818T053000.000000Z-feedface")
    manifest = ArtifactManifest.create(tmp_path, run_id)
    first = _row(str(run_id))
    second_payload = first.to_dict()
    second_payload["receive_sequence"] = 2
    second_payload["update_side"] = "ask"
    second_payload["quality_flags"] = [QualityFlag.CROSSED_BOOK]
    second = TapeRow.from_dict(second_payload)
    with JsonlTapeWriter(manifest, fsync_every=1) as writer:
        writer.write(first)
        writer.write(second)

    replayed: list[TapeRow] = []
    count = JsonlTapeReader(writer.path, expected_run_id=str(run_id)).replay(replayed.append)
    assert count == 2
    assert replayed == [first, second]
    assert replayed[1].quality_flags == (QualityFlag.CROSSED_BOOK,)


def test_replay_rejects_sequence_gap_before_delivering_later_row(tmp_path: Path) -> None:
    run_id = "sha-20260818T053000.000000Z-feedface"
    first = _row(run_id).to_dict()
    third = dict(first, receive_sequence=3)
    path = tmp_path / "tape.jsonl"
    path.write_text(json.dumps(first) + "\n" + json.dumps(third) + "\n", encoding="utf-8")
    delivered: list[TapeRow] = []
    with pytest.raises(TapeIntegrityError, match="sequence gap"):
        JsonlTapeReader(path, expected_run_id=run_id).replay(delivered.append)
    assert [row.receive_sequence for row in delivered] == [1]


def test_replay_rejects_mixed_run_ids_and_blank_rows(tmp_path: Path) -> None:
    first = _row("sha-20260818T053000.000000Z-feedface").to_dict()
    second = _row("sha-20260818T053000.000000Z-deadbeef").to_dict()
    second["receive_sequence"] = 2
    mixed = tmp_path / "mixed.jsonl"
    mixed.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    with pytest.raises(TapeIntegrityError, match="run_id changed"):
        list(JsonlTapeReader(mixed).rows())

    blank = tmp_path / "blank.jsonl"
    blank.write_text(json.dumps(first) + "\n\n", encoding="utf-8")
    with pytest.raises(TapeIntegrityError, match="blank tape row"):
        list(JsonlTapeReader(blank).rows())
