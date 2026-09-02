from __future__ import annotations

from datetime import date
from pathlib import Path

from experiments import nifty_banknifty_relative_value as module


def test_future_contract_parser() -> None:
    contract = module._future_contract(Path("BANKNIFTY26FEBFUT_2026_02_17.parquet"), "BANKNIFTY")
    assert contract is not None
    assert contract[0] == date(2026, 2, 26)


def test_adverse_execution_prices() -> None:
    assert module._leg_entry(1, 99.0, 101.0) == 101.0
    assert module._leg_entry(-1, 99.0, 101.0) == 99.0
    assert module._leg_exit(1, 99.0, 101.0) == 99.0
    assert module._leg_exit(-1, 99.0, 101.0) == 101.0


def test_candidate_grid_is_fixed() -> None:
    assert len(module.candidates()) == 36
