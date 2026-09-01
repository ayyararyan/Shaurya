from __future__ import annotations

from pathlib import Path

import pandas as pd

from experiments import subminute_option_futures_lead as module


def test_parse_weekly_contract() -> None:
    item = module.parse_contract(Path("NIFTY2610626700CE_2026_01_06.parquet"))
    assert item is not None
    assert item.expiry.isoformat() == "2026-01-06"
    assert item.strike == 26_700
    assert item.kind == "CE"


def test_parse_monthly_future() -> None:
    item = module.parse_contract(Path("NIFTY26JANFUT_2026_01_06.parquet"))
    assert item is not None
    assert item.expiry.isoformat() == "2026-01-29"
    assert item.kind == "FUT"


def test_embargo_target_starts_after_decision() -> None:
    index = pd.date_range("2026-01-06 09:16:00", periods=100, freq="1s")
    frame = pd.DataFrame(index=index)
    frame["implied_forward"] = 25_000.0 + pd.Series(range(100), index=index)
    frame["future_mid"] = 25_000.0 + pd.Series(range(100), index=index)
    rows = module.session_statistics(frame)
    assert len(rows) == 5 * 5 * 3 * 3
    assert {row["embargo_seconds"] for row in rows} == {0, 1, 2}
