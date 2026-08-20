from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.ofi_full_session_controller import (
    _git_commit_is_remote_ancestor,
    build_fixed_lead_summary,
    fixed_lead_markdown,
)
from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds
from shaurya.data.depth_thinning_analysis import (
    DEPTH200,
    build_states,
    build_states_streaming,
)
from shaurya.data.ofi_replication import (
    REGISTRATION_COMMIT,
    inspect_replication_capture,
    iter_session_rows,
    require_accepted_receipt,
    resolve_nifty_front_month_future,
)


@pytest.mark.parametrize(
    "script_name",
    [
        "ofi_full_session_controller.py",
        "cks_l1_ofi_scan.py",
        "ofi_horserace.py",
        "surface_ofi_reconciliation.py",
        "sig21_exploratory_response_scan.py",
        "deepbook_normal_activity_scan.py",
    ],
)
def test_script_namespace_entrypoints_work_directly_from_other_cwd(
    tmp_path: Path,
    script_name: str,
) -> None:
    controller = Path(__file__).resolve().parents[1] / "scripts" / script_name

    result = subprocess.run(
        [sys.executable, str(controller), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert Path(script_name).stem in result.stdout


def _metrics() -> dict[str, object]:
    return {
        "run_id": "sha-20260820T034200.000000Z-1234abcd",
        "instrument_id": "NSE:NSE_FNO:NIFTY:future:2026-08-25",
        "dhan_security_id": "58072",
        "trading_symbol": "NIFTY-Aug2026-FUT",
        "test_configuration": {
            "standard_full_5_level": True,
            "depth20": True,
            "depth200": True,
            "ofi_full_session_replication_protocol": {
                "protocol_id": "R-OFI-FULLSESSION-2026-08-20",
                "source_spec": "docs/OFI-FULL-SESSION-REPLICATION-SPEC-2026-08-20.md",
                "source_amendment": (
                    "docs/OFI-FULL-SESSION-REPLICATION-SPEC-AMENDMENT-1-2026-08-19.md"
                ),
                "registration_commit": REGISTRATION_COMMIT,
                "sample_role": "prospective_full_session_replication",
                "trading_date": "2026-08-20",
                "outcome_join_allowed": True,
                "sig21_calibration_eligible": False,
                "order_entry_enabled": False,
            },
        },
    }


def _row(event_type: str, stamp: datetime, sequence: int) -> dict[str, object]:
    level = {"price": 25_000.0, "quantity": 10, "orders": 1}
    return {
        "run_id": "sha-20260820T034200.000000Z-1234abcd",
        "instrument_id": "NSE:NSE_FNO:NIFTY:future:2026-08-25",
        "event_type": event_type,
        "receive_ts": stamp.astimezone(UTC).isoformat(),
        "receive_sequence": sequence,
        "connection_epoch": 1,
        "bids": [level],
        "asks": [{**level, "price": 25_000.05}],
        "quality_flags": [],
    }


def _write_tape(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_actual_channel_timestamps_accept_and_exact_session_clip(tmp_path: Path) -> None:
    opened, closed = nse_equity_derivatives_session_bounds(date(2026, 8, 20))
    rows: list[dict[str, object]] = []
    sequence = 1
    for stamp in (
        opened + timedelta(seconds=1),
        closed - timedelta(milliseconds=1),
        closed + timedelta(seconds=1),
    ):
        for channel in ("full", "depth20", "depth200"):
            rows.append(_row(channel, stamp, sequence))
            sequence += 1
    tape = tmp_path / "tape_sha-20260820T034200.000000Z-1234abcd.jsonl"
    _write_tape(tape, rows)

    receipt = inspect_replication_capture(
        tape,
        _metrics(),
        tape_sha256="a" * 64,
        manifest_sha256="a" * 64,
        inspected_at=closed + timedelta(seconds=5),
    )

    assert receipt["accepted"] is True
    assert receipt["channel_rows"] == {"standard": 3, "depth20": 3, "depth200": 3}
    require_accepted_receipt(receipt)
    clipped = list(iter_session_rows(tape))
    assert len(clipped) == 6
    assert all(
        datetime.fromisoformat(str(row["receive_ts"])).astimezone(IST) <= closed
        for row in clipped
    )


def test_requested_duration_cannot_rescue_missing_closing_channel_rows(tmp_path: Path) -> None:
    opened, closed = nse_equity_derivatives_session_bounds(date(2026, 8, 20))
    rows = [
        _row("full", opened, 1),
        _row("depth20", opened, 2),
        _row("depth200", opened, 3),
        _row("full", closed + timedelta(seconds=1), 4),
        _row("depth20", closed + timedelta(seconds=1), 5),
    ]
    tape = tmp_path / "tape_sha-20260820T034200.000000Z-1234abcd.jsonl"
    _write_tape(tape, rows)

    receipt = inspect_replication_capture(
        tape,
        _metrics(),
        tape_sha256="b" * 64,
        manifest_sha256="b" * 64,
        inspected_at=closed + timedelta(seconds=5),
    )

    assert receipt["accepted"] is False
    assert any("depth200 misses the closing" in reason for reason in receipt["reasons"])
    with pytest.raises(ValueError, match="ineligible"):
        require_accepted_receipt(receipt)


def test_front_month_resolution_is_same_day_nearest_and_unique(tmp_path: Path) -> None:
    master_path = tmp_path / "master.csv"
    header = (
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
        "SEM_TRADING_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,"
        "SEM_LOT_UNITS,SEM_TICK_SIZE,SM_SYMBOL_NAME\n"
    )
    master_path.write_text(
        header
        + "NSE,D,58072,FUTIDX,NIFTY-Aug2026-FUT,2026-08-25,-1,XX,65,5,NIFTY\n"
        + "NSE,D,58073,FUTIDX,NIFTY-Sep2026-FUT,2026-09-29,-1,XX,65,5,NIFTY\n"
        + "NSE,D,58074,FUTIDX,BANKNIFTY-Aug2026-FUT,2026-08-25,-1,XX,30,5,BANKNIFTY\n",
        encoding="utf-8",
    )
    trading_date = date(2026, 8, 20)

    resolved = resolve_nifty_front_month_future(
        DhanInstrumentMaster(master_path, as_of_date=trading_date),
        trading_date=trading_date,
    )

    assert resolved.security_id == "58072"
    assert resolved.instrument.expiry == date(2026, 8, 25)


def test_streaming_state_collapse_matches_existing_builder() -> None:
    opened = datetime(2026, 8, 20, 9, 15, tzinfo=IST)
    rows = [
        _row(DEPTH200, opened, 1),
        {**_row(DEPTH200, opened, 2), "quality_flags": ["partial_book"]},
        _row(DEPTH200, opened + timedelta(milliseconds=200), 3),
    ]

    assert build_states_streaming(rows, DEPTH200) == build_states(rows, DEPTH200)


def test_fixed_lead_report_does_not_substitute_a_new_full_grid_argmax() -> None:
    scalar = {
        "protocol": {
            "level_one_is_ccz_base_case": "CCZ Eq. (1); retained unchanged by CCZ-IMPL-05"
        }
    }
    future = {
        "subarm": "M3b_depth_normalised_cks",
        "h1_seconds": 2.0,
        "h2_seconds": 2.0,
        "incremental_oos_r2_over_m0": 0.03,
        "coefficient_ticks_per_training_sd": 0.5,
        "error_improvement_inference_over_m0": {"newey_west_t": 2.2},
        "test_n": 95,
    }
    horse = {
        "normalised_subarms_future": [future],
        "normalised_subarms_past": [
            {
                **future,
                "incremental_oos_r2_over_m0": 0.01,
            }
        ],
        "gate_30_seconds": {"gate_passed": False},
    }

    summary = build_fixed_lead_summary(scalar, horse)

    # CCZ-IMPL-02: this pre-named lead is defined on the retired price-keyed estimator.  It is
    # reported as retired with its reason and no substitute number, because re-pointing a
    # pre-registered estimand at a CCZ quantity would need explicit approval.
    scalar_lead = summary["scalar_top10_10s_to_10s"]
    assert scalar_lead["status"] == "estimator_retired"
    assert scalar_lead["incremental_oos_r2"] is None
    assert scalar_lead["replicates_all_frozen_conditions"] is None
    assert scalar_lead["prior_incremental_oos_r2"] == 0.0791
    assert scalar_lead["retired_by"] == "D37 / CCZ-OFI-MIGRATION-2026-08-20"
    assert summary["horse_m3b_2s_to_2s"]["replicates_all_frozen_conditions"] is True
    assert summary["cross_tape_stability_supported"] is False

    report = fixed_lead_markdown(summary)
    assert "estimator_retired" in report
    assert "no replacement number" in report


def test_pinned_commit_may_be_behind_remote_main_but_must_be_in_its_history(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    marker = repo / "marker.txt"
    marker.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "one"], cwd=repo, check=True, capture_output=True)
    pinned = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    marker.write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "two"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=repo,
        check=True,
    )

    assert _git_commit_is_remote_ancestor(repo, pinned) is True
    assert _git_commit_is_remote_ancestor(repo, "0" * 40) is False
