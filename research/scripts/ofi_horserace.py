#!/usr/bin/env python3
"""Run exploratory predictor horse race `X-OFI-HORSERACE-DAT20-05`."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sig21_construction_replay import (
    capture_metrics_for,
    iter_tape_rows,
    manifest_sha256_for,
    sha256_file,
    verify_instrument,
)
from shaurya.analytics.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    build_states,
    build_states_streaming,
)
from shaurya.analytics.ofi_live_partial import (
    inspect_late_partial_snapshot,
    iter_late_partial_rows,
    partial_claim,
)
from shaurya.analytics.ofi_replication import (
    PROTOCOL_ID as REPLICATION_PROTOCOL_ID,
)
from shaurya.analytics.ofi_replication import (
    REGISTRATION_COMMIT as REPLICATION_REGISTRATION_COMMIT,
)
from shaurya.analytics.ofi_replication import (
    filtered_session_rows,
    inspect_replication_capture,
    iter_session_rows,
    require_accepted_receipt,
)
from shaurya.signals.deep_book_normal_activity import assert_permitted_tape
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND
from shaurya.signals.ofi_horserace import (
    HorseRaceTapeInput,
    build_horserace_artifact,
    build_horserace_observations,
)


def code_commit() -> str | None:
    pinned = os.environ.get("SHAURYA_CODE_COMMIT")
    if pinned:
        if len(pinned) != 40 or any(character not in "0123456789abcdef" for character in pinned):
            raise ValueError("SHAURYA_CODE_COMMIT must be a lowercase 40-character Git SHA")
        return pinned
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_tape_input(
    tape: Path,
    *,
    tape_index: int,
    full_session_replication: bool = False,
    late_partial_exploratory: bool = False,
    level_counts: tuple[int, ...] | None = None,
    response_horizons: tuple[float, ...] | None = None,
) -> HorseRaceTapeInput:
    if late_partial_exploratory:
        snapshot = inspect_late_partial_snapshot(tape)
        run_id = snapshot.run_id
        instrument_id = snapshot.instrument_id
        computed = snapshot.tape_sha256
        depth200 = build_states_streaming(iter_late_partial_rows(tape), DEPTH200)
        depth20 = build_states_streaming(iter_late_partial_rows(tape), DEPTH20)
        rows = [row for row in iter_late_partial_rows(tape) if row.get("event_type") == "full"]
    else:
        metrics = capture_metrics_for(tape)
        run_id, instrument_id, _, _ = verify_instrument(metrics, tape)
        computed = sha256_file(tape)
        recorded = manifest_sha256_for(tape)
        if recorded is not None and recorded != computed:
            raise ValueError(f"{tape} SHA-256 {computed} does not match manifest {recorded}")
    if full_session_replication and not late_partial_exploratory:
        receipt = inspect_replication_capture(
            tape,
            metrics,
            tape_sha256=computed,
            manifest_sha256=recorded,
        )
        require_accepted_receipt(receipt)
        depth200 = build_states_streaming(iter_session_rows(tape), DEPTH200)
        depth20 = build_states_streaming(iter_session_rows(tape), DEPTH20)
        rows = filtered_session_rows(tape, {"full"})
    elif not late_partial_exploratory:
        assert_permitted_tape(run_id=run_id, tape_sha256=computed)
        rows = list(iter_tape_rows(tape))
        depth200 = build_states(rows, DEPTH200)
        depth20 = build_states(rows, DEPTH20)
    if level_counts is None:
        observations, failures = build_horserace_observations(
            depth200_states=depth200,
            depth20_states=depth20,
            rows=rows,
            tape_index=tape_index,
            run_id=run_id,
            response_horizons=response_horizons,
        )
    else:
        observations, failures = build_horserace_observations(
            depth200_states=depth200,
            depth20_states=depth20,
            rows=rows,
            tape_index=tape_index,
            run_id=run_id,
            level_counts=level_counts,
            response_horizons=response_horizons,
        )
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / NANOSECONDS_PER_SECOND
        if len(depth200) > 1
        else 0.0
    )
    return HorseRaceTapeInput(
        tape_index=tape_index,
        run_id=run_id,
        instrument_id=instrument_id,
        tape_sha256=computed,
        observations=tuple(observations),
        depth200_publications=len(depth200),
        depth20_publications=len(depth20),
        observed_seconds=observed_seconds,
        failures=failures,
    )


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _ranking_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fields = (
        "h2_seconds",
        "rank",
        "model",
        "h1_seconds",
        "oos_r2",
        "incremental_oos_r2_over_m0",
        "tape_0_increment",
        "tape_1_increment",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        per_tape = row["per_tape_increment"]
        writer.writerow(
            {
                **{key: row[key] for key in fields[:6]},
                "tape_0_increment": per_tape.get("0"),
                "tape_1_increment": per_tape.get("1"),
            }
        )
    return output.getvalue()


def _flat_csv(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _ablation_csv(rows: list[dict[str, Any]]) -> str:
    return _flat_csv(
        rows,
        (
            "h1_seconds",
            "h2_seconds",
            "excluded_family",
            "status",
            "full_m6_oos_r2",
            "without_family_oos_r2",
            "family_incremental_oos_r2",
            "full_alpha",
            "reduced_alpha",
        ),
    )


def _intensity_csv(rows: list[dict[str, Any]]) -> str:
    return _flat_csv(
        rows,
        (
            "h1_seconds",
            "feature",
            "n",
            "missing_n",
            "mean",
            "standard_deviation",
            "mean_absolute",
            "zero_share",
        ),
    )


def _support_csv(rows: list[dict[str, Any]]) -> str:
    fields = (
        "source",
        "category",
        "label",
        "h1_seconds",
        "h2_seconds",
        "status",
        "common_total_n",
        "common_train_n",
        "common_embargoed_n",
        "common_test_n",
        "tape_0_test_n",
        "tape_1_test_n",
        "model_specific_total_n",
        "model_specific_train_n",
        "model_specific_embargoed_n",
        "model_specific_test_n",
        "loss_to_common_total_n",
        "loss_to_common_train_n",
        "loss_to_common_embargoed_n",
        "loss_to_common_test_n",
    )
    return _flat_csv(rows, fields)


def _ccz_arm_csv(rows: list[dict[str, Any]]) -> str:
    """`EST-CCZ-05` / `EST-CCZ-06`: one row per declared aggregation arm and level count."""

    return _flat_csv(
        rows,
        (
            "source",
            "estimator",
            "arm",
            "levels",
            "h1_seconds",
            "h2_seconds",
            "status",
            "primary_arm",
            "primary_level_count",
            "train_n",
            "test_n",
            "selected_alpha",
            "oos_r2_training_mean",
            "baseline_oos_r2_training_mean",
            "incremental_oos_r2_over_m0",
            "rmse_ticks",
            "explained_variance_ratio",
        ),
    )


def _gate_csv(gate: dict[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    for candidate in gate["evaluated_candidates"]:
        conditions = candidate.get("conditions", {})
        rows.append(
            {
                "gate_passed": gate["gate_passed"],
                "model": candidate.get("model"),
                "status": candidate.get("status", "evaluated"),
                "h1_seconds": candidate.get("h1_seconds"),
                "future_incremental_oos_r2_over_m0": candidate.get(
                    "future_incremental_oos_r2_over_m0"
                ),
                "past_incremental_oos_r2_over_m0": candidate.get("past_incremental_oos_r2_over_m0"),
                "pooled_increment_strictly_positive": conditions.get(
                    "pooled_increment_strictly_positive"
                ),
                "per_tape_increment_non_negative": conditions.get(
                    "per_tape_increment_non_negative"
                ),
                "direction_stable_across_tapes": conditions.get("direction_stable_across_tapes"),
                "future_increment_stronger_than_past_mirror": conditions.get(
                    "future_increment_stronger_than_past_mirror"
                ),
                "all_conditions": candidate.get("all_conditions"),
            }
        )
    return _flat_csv(
        rows,
        (
            "gate_passed",
            "model",
            "status",
            "h1_seconds",
            "future_incremental_oos_r2_over_m0",
            "past_incremental_oos_r2_over_m0",
            "pooled_increment_strictly_positive",
            "per_tape_increment_non_negative",
            "direction_stable_across_tapes",
            "future_increment_stronger_than_past_mirror",
            "all_conditions",
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cells-output", required=True, type=Path)
    parser.add_argument("--past-output", required=True, type=Path)
    parser.add_argument("--ranking-output", required=True, type=Path)
    parser.add_argument("--ablation-output", required=True, type=Path)
    parser.add_argument("--intensity-output", required=True, type=Path)
    parser.add_argument("--support-output", required=True, type=Path)
    parser.add_argument("--gate-output", required=True, type=Path)
    parser.add_argument("--ccz-arm-output", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260819)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--full-session-replication",
        action="store_true",
        help="Validate and clip the registered R-OFI-FULLSESSION-2026-08-20 tape instead of "
        "using the immutable DAT-20 exploratory allowlist.",
    )
    scope.add_argument(
        "--late-partial-exploratory",
        action="store_true",
        help="Run X-OFI-LATEPARTIAL-2026-08-20 on its exact immutable snapshot.",
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if (args.full_session_replication or args.late_partial_exploratory) and len(args.tape) != 1:
        raise ValueError("the one-session scoped modes consume exactly one tape")
    tapes = [
        build_tape_input(
            tape,
            tape_index=index,
            full_session_replication=args.full_session_replication,
            late_partial_exploratory=args.late_partial_exploratory,
        )
        for index, tape in enumerate(args.tape)
    ]
    artifact = build_horserace_artifact(
        tapes, code_commit=code_commit(), replicates=args.replicates, seed=args.seed
    )
    if args.full_session_replication:
        artifact["replication_protocol"] = {
            "protocol_id": REPLICATION_PROTOCOL_ID,
            "registration_commit": REPLICATION_REGISTRATION_COMMIT,
            "source_scan_id": "X-OFI-HORSERACE-DAT20-05",
            "sample_role": "prospective_full_session_replication",
            "confirmatory_eligible": False,
            "cross_tape_stability_supported": False,
            "gate_30_seconds_forced_closed_by_single_tape": True,
        }
        if artifact["gate_30_seconds"]["gate_passed"] is not False:
            raise AssertionError("one-tape replication cannot open the frozen 30-second gate")
    if args.late_partial_exploratory:
        artifact["partial_session_exploration"] = partial_claim(
            "X-OFI-HORSERACE-DAT20-05", inspect_late_partial_snapshot(args.tape[0])
        )
        artifact["partial_session_exploration"]["gate_30_seconds_forced_closed"] = True
        if artifact["gate_30_seconds"]["gate_passed"] is not False:
            raise AssertionError("one-tape partial exploration cannot open the 30-second gate")
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run(args)
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    _write(args.cells_output, _jsonl(artifact["future_cells"]))
    _write(args.past_output, _jsonl(artifact["past_mirror_cells"]))
    _write(args.ranking_output, _ranking_csv(artifact["rankings"]))
    _write(args.ablation_output, _ablation_csv(artifact["combined_ablations"]))
    _write(args.intensity_output, _intensity_csv(artifact["feature_intensity"]))
    _write(args.support_output, _support_csv(artifact["support_table"]))
    _write(args.gate_output, _gate_csv(artifact["gate_30_seconds"]))
    _write(
        args.ccz_arm_output,
        _ccz_arm_csv(
            [*artifact["ccz_aggregation_arms_future"], *artifact["ccz_aggregation_arms_past"]]
        ),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "future_cells": len(artifact["future_cells"]),
                "past_cells": len(artifact["past_mirror_cells"]),
                "observations": artifact["sample"]["observations"],
                "train_n": artifact["sample"]["train_n"],
                "test_n": artifact["sample"]["test_n"],
                "gate_30_seconds": artifact["gate_30_seconds"]["gate_passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
