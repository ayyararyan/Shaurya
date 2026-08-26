from __future__ import annotations

import json
import stat
from datetime import date
from pathlib import Path

import pytest

from shaurya.contracts.instruments import InstrumentKind, KotakInstrumentMaster, OptionType
from shaurya.data.instrument_master import (
    DailyInstrumentMasterStore,
    DhanDailyInstrumentMaster,
    DhanInstrumentIndex,
    KotakInstrumentIndex,
)


def _master_payload() -> bytes:
    return (
        b"SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
        b"SEM_TRADING_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,"
        b"SEM_LOT_UNITS,SEM_TICK_SIZE,SM_SYMBOL_NAME\n"
        b"NSE,D,58072,FUTIDX,NIFTY-Aug2026-FUT,2026-08-25 14:30:00,"
        b"-0.01000,XX,65,10.0000,NIFTY\n"
    )


def test_dhan_master_refreshes_once_per_day_and_indexes_same_day(tmp_path: Path) -> None:
    calls = 0

    def fetch(url: str) -> bytes:
        nonlocal calls
        calls += 1
        assert url.startswith("https://")
        return _master_payload()

    trading_date = date(2026, 8, 19)
    daily = DhanDailyInstrumentMaster(tmp_path, fetch=fetch)
    first = daily.refresh(trading_date)
    second = daily.refresh(trading_date)
    assert calls == 1
    mapping = first.find_by_security_id("58072")
    assert second.find_by_security_id("58072") == mapping
    index = DhanInstrumentIndex(first.mappings(), trading_date=trading_date)
    assert index.by_security_id("58072") == mapping
    assert index.by_instrument_id(mapping.instrument.canonical) == mapping
    data_path, manifest_path = daily.store.paths(trading_date)
    assert stat.S_IMODE(data_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert json.loads(manifest_path.read_text())["retention"] == "permanent"


def test_master_store_retains_distinct_daily_artifacts(tmp_path: Path) -> None:
    store = DailyInstrumentMasterStore(
        tmp_path,
        broker="kotak",
        source_url="https://example.test/kotak-master.csv",
        fetch=lambda _: b"token,symbol\n1,NIFTY\n",
    )
    first = store.refresh(date(2026, 8, 18))
    second = store.refresh(date(2026, 8, 19))
    assert first.data_file != second.data_file
    assert len(tuple(tmp_path.glob("kotak_instrument_master_*.csv"))) == 2
    assert first.retention == second.retention == "permanent"


def test_master_rejects_stale_mapping_and_partial_or_tampered_cache(tmp_path: Path) -> None:
    trading_date = date(2026, 8, 19)
    daily = DhanDailyInstrumentMaster(tmp_path, fetch=lambda _: _master_payload())
    master = daily.refresh(trading_date)
    with pytest.raises(ValueError, match="stale"):
        DhanInstrumentIndex(master.mappings(), trading_date=date(2026, 8, 20))
    data_path, _ = daily.store.paths(trading_date)
    data_path.write_bytes(data_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="manifest validation"):
        daily.refresh(trading_date)

    partial_root = tmp_path / "partial"
    partial_root.mkdir()
    partial = DailyInstrumentMasterStore(
        partial_root,
        broker="dhan",
        source_url="https://example.test/master.csv",
        fetch=lambda _: _master_payload(),
    )
    partial.paths(trading_date)[0].write_bytes(_master_payload())
    with pytest.raises(ValueError, match="partial"):
        partial.refresh(trading_date)


def test_kotak_routing_master_maps_to_same_canonical_identity_and_daily_index(
    tmp_path: Path,
) -> None:
    master_path = tmp_path / "kotak_nse_fo.csv"
    master_path.write_text(
        "pSymbol,pSymbolName,pTrdSymbol,pScripRefKey,pInstType,pOptionType,"
        "pExpiryDate,dStrikePrice;\n"
        "58072,NIFTY,NIFTY26AUGFUT,NIFTY25AUG26FUT,FUTIDX,XX,1472135400,-1\n"
        "45106,NIFTY,NIFTY2681824400CE,NIFTY18AUG2624400.00CE,OPTIDX,CE,"
        "1471530600,2440000\n",
        encoding="utf-8",
    )
    trading_date = date(2026, 8, 19)
    master = KotakInstrumentMaster(master_path, as_of_date=trading_date)
    option = master.find_by_instrument_token("45106")
    assert option.instrument.kind is InstrumentKind.OPTION
    assert option.instrument.option_type is OptionType.CALL
    assert str(option.instrument.strike) == "24400"
    assert option.instrument.canonical == "NSE:NSE_FNO:NIFTY:option:2026-08-18:24400:CE"
    index = KotakInstrumentIndex(master.mappings(), trading_date=trading_date)
    assert index.by_instrument_token("45106") == option
    assert index.by_instrument_id(option.instrument.canonical) == option
