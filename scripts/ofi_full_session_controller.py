#!/usr/bin/env python3
"""Durable read-only controller for R-OFI-FULLSESSION-2026-08-20."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any

# Keep the documented executable-script path safe as well as `python -m scripts...`.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sig21_construction_replay import (
    capture_metrics_for,
    manifest_sha256_for,
    sha256_file,
)
from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds
from shaurya.data.instrument_master import DhanDailyInstrumentMaster
from shaurya.data.ofi_replication import (
    PROTOCOL_ID,
    REGISTRATION_COMMIT,
    SOURCE_AMENDMENT,
    SOURCE_SPEC,
    TRADING_DATE,
    inspect_replication_capture,
    require_accepted_receipt,
    resolve_nifty_front_month_future,
)

CAPTURE_CONNECT_TIME = clock_time(9, 12)
POST_CLOSE_BUFFER_SECONDS = 5
MINIMUM_FREE_BYTES = 25 * 1024**3
POLL_SECONDS = 30.0


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def atomic_text(path: Path, value: str) -> None:
    _atomic_bytes(path, value.encode())


def hash_files(paths: Sequence[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths}


def checkpoint_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hashes = value.get("outputs")
    if not isinstance(hashes, dict) or not hashes:
        return False
    return all(
        Path(name).is_file() and sha256_file(Path(name)) == digest
        for name, digest in hashes.items()
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_commit_is_remote_ancestor(repo: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _find_one(directory: Path, pattern: str) -> Path:
    matches = tuple(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} under {directory}, found {len(matches)}")
    return matches[0]


def _cell(rows: Sequence[Mapping[str, Any]], **wanted: Any) -> dict[str, Any]:
    matched = [row for row in rows if all(row.get(key) == value for key, value in wanted.items())]
    if len(matched) != 1:
        raise ValueError(f"expected one result cell for {wanted}, found {len(matched)}")
    return dict(matched[0])


def build_fixed_lead_summary(
    scalar: Mapping[str, Any], horse: Mapping[str, Any]
) -> dict[str, Any]:
    """Extract only the two leads named before the replication tape existed."""

    scalar_cell = _cell(
        scalar["grid"],
        depth_levels=10,
        ofi_window_seconds=10,
        return_horizon_seconds=10,
    )
    horse_future = _cell(
        horse["normalised_subarms_future"],
        subarm="M3b_depth_normalised_cks",
        h1_seconds=2.0,
        h2_seconds=2.0,
    )
    horse_past = _cell(
        horse["normalised_subarms_past"],
        subarm="M3b_depth_normalised_cks",
        h1_seconds=2.0,
        h2_seconds=2.0,
    )
    scalar_increment = float(scalar_cell["incremental_oos_r2_over_state"])
    scalar_coefficient = float(scalar_cell["standardised_ofi_coefficient_ticks"])
    scalar_past = float(scalar_cell["past_incremental_oos_r2_over_state"])
    horse_increment = float(horse_future["incremental_oos_r2_over_m0"])
    horse_coefficient = float(horse_future["coefficient_ticks_per_training_sd"])
    horse_past_increment = float(horse_past["incremental_oos_r2_over_m0"])
    return {
        "schema_version": "1.0.0",
        "protocol_id": PROTOCOL_ID,
        "registration_commit": REGISTRATION_COMMIT,
        "sample_role": "prospective_full_session_replication",
        "confirmatory_eligible": False,
        "scalar_top10_10s_to_10s": {
            "prior_incremental_oos_r2": 0.0791,
            "incremental_oos_r2": scalar_increment,
            "coefficient_ticks_per_training_sd": scalar_coefficient,
            "past_incremental_oos_r2": scalar_past,
            "positive_increment": scalar_increment > 0,
            "same_positive_sign": scalar_coefficient > 0,
            "future_stronger_than_past": scalar_increment > scalar_past,
            "replicates_all_frozen_conditions": (
                scalar_increment > 0 and scalar_coefficient > 0 and scalar_increment > scalar_past
            ),
            "dependence_inference": scalar_cell["future_error_improvement_inference"],
            "test_n": scalar_cell["test_n"],
        },
        "horse_m3b_2s_to_2s": {
            "prior_incremental_oos_r2": 0.062036652388938185,
            "incremental_oos_r2": horse_increment,
            "coefficient_ticks_per_training_sd": horse_coefficient,
            "past_incremental_oos_r2": horse_past_increment,
            "positive_increment": horse_increment > 0,
            "same_positive_sign": horse_coefficient > 0,
            "future_stronger_than_past": horse_increment > horse_past_increment,
            "replicates_all_frozen_conditions": (
                horse_increment > 0
                and horse_coefficient > 0
                and horse_increment > horse_past_increment
            ),
            "dependence_inference": horse_future["error_improvement_inference_over_m0"],
            "test_n": horse_future["test_n"],
        },
        "cross_tape_stability_supported": False,
        "horse_30_second_gate_passed": bool(horse["gate_30_seconds"]["gate_passed"]),
    }


def fixed_lead_markdown(summary: Mapping[str, Any]) -> str:
    scalar = summary["scalar_top10_10s_to_10s"]
    horse = summary["horse_m3b_2s_to_2s"]
    return (
        "# OFI full-session fixed-lead replication\n\n"
        f"Protocol: `{PROTOCOL_ID}`  \n"
        f"Registration: `{REGISTRATION_COMMIT}`  \n"
        "Status: selection-aware prospective replication; not confirmatory and not SIG-21.\n\n"
        "## Pre-named scalar lead\n\n"
        "Top-10 price-keyed OFI, 10 s accumulation to next 10 s return.\n\n"
        f"- incremental held-out R²: {100 * scalar['incremental_oos_r2']:.3f} pp\n"
        f"- coefficient: {scalar['coefficient_ticks_per_training_sd']:.6g} ticks/training SD\n"
        f"- past-mirror increment: {100 * scalar['past_incremental_oos_r2']:.3f} pp\n"
        f"- all frozen replication conditions: {scalar['replicates_all_frozen_conditions']}\n\n"
        "## Pre-named horse-race lead\n\n"
        "Depth-normalised CKS (`M3b`), 2 s accumulation to next 2 s return.\n\n"
        f"- incremental held-out R² over M0: {100 * horse['incremental_oos_r2']:.3f} pp\n"
        f"- coefficient: {horse['coefficient_ticks_per_training_sd']:.6g} ticks/training SD\n"
        f"- past-mirror increment: {100 * horse['past_incremental_oos_r2']:.3f} pp\n"
        f"- all frozen replication conditions: {horse['replicates_all_frozen_conditions']}\n\n"
        "Cross-tape stability is not estimable from one session. The frozen 30-second gate "
        f"passed: {summary['horse_30_second_gate_passed']}. Complete-grid reranking remains "
        "exploratory.\n"
    )


class Controller:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.repo = args.repo_root.resolve()
        self.run_root = args.run_root.resolve()
        self.logs = self.run_root / "logs"
        self.checkpoints = self.run_root / "checkpoints"
        self.state_path = self.run_root / "state.json"
        self.capture_root = args.capture_output_root.resolve()
        self.partial_analysis = args.analysis_output_root.resolve() / f".{PROTOCOL_ID}.partial"
        self.final_analysis = args.analysis_output_root.resolve() / PROTOCOL_ID
        self.python = self.repo / ".venv/bin/python"
        initial_state: dict[str, Any] = {
            "schema_version": "1.0.0",
            "protocol_id": PROTOCOL_ID,
            "registration_commit": REGISTRATION_COMMIT,
            "controller_pid": os.getpid(),
            "status": "starting",
            "stage": "starting",
            "children": {},
        }
        if self.state_path.is_file():
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("protocol_id") != PROTOCOL_ID:
                raise ValueError("existing controller state belongs to a different protocol")
            initial_state.update(loaded)
            initial_state["controller_pid"] = os.getpid()
        self.state = initial_state
        self._lock_handle: Any = None

    def update(self, *, stage: str, status: str, **extra: Any) -> None:
        self.state.update(
            {
                "stage": stage,
                "status": status,
                "updated_at": datetime.now(IST).isoformat(),
                **extra,
            }
        )
        atomic_json(self.state_path, self.state)

    def log(self, message: str) -> None:
        self.logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.logs / "controller.log"
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(IST).isoformat()} {message}\n")

    def acquire_lock(self) -> None:
        self.run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.run_root / "controller.lock"
        self._lock_handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another full-session controller holds the run lock") from exc

    def preflight(self) -> tuple[Path, str, str]:
        self.update(stage="preflight", status="running")
        if date.fromisoformat(self.args.trading_date) != TRADING_DATE:
            raise ValueError("controller trading date differs from the frozen protocol")
        if not self.python.is_file():
            raise FileNotFoundError(self.python)
        if shutil.which("tmux") is None or shutil.which("git") is None:
            raise RuntimeError("tmux and git are required")
        head = _git(self.repo, "rev-parse", "HEAD")
        if head != self.args.expected_code_commit:
            raise ValueError(
                f"code commit mismatch: expected {self.args.expected_code_commit}, got {head}"
            )
        if _git(self.repo, "status", "--porcelain"):
            raise ValueError("repository worktree is not clean")
        if not _git_commit_is_remote_ancestor(self.repo, head):
            raise ValueError("pinned code commit is not present in fetched origin/main history")
        credentials = self.args.credentials.resolve()
        if not credentials.is_file():
            raise FileNotFoundError(credentials)
        if stat.S_IMODE(credentials.stat().st_mode) & 0o077:
            raise PermissionError("credential handle must not be group/world accessible")
        self.capture_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.args.analysis_output_root.resolve().mkdir(mode=0o700, parents=True, exist_ok=True)
        if shutil.disk_usage(self.capture_root).free < MINIMUM_FREE_BYTES:
            raise OSError("less than 25 GiB free for raw capture and atomic derived outputs")
        daily = DhanDailyInstrumentMaster(self.args.instrument_master_root.resolve())
        master = daily.refresh(TRADING_DATE)
        mapping = resolve_nifty_front_month_future(master, trading_date=TRADING_DATE)
        master_path, manifest_path = daily.store.paths(TRADING_DATE)
        identity = {
            "trading_date": TRADING_DATE.isoformat(),
            "security_id": mapping.security_id,
            "trading_symbol": mapping.trading_symbol,
            "instrument_id": mapping.instrument.canonical,
            "instrument_master": str(master_path),
            "instrument_master_manifest": str(manifest_path),
            "instrument_master_sha256": sha256_file(master_path),
        }
        atomic_json(self.run_root / "artifacts/instrument_identity.json", identity)
        self.update(stage="preflight", status="accepted", code_commit=head, instrument=identity)
        return master_path, mapping.security_id, mapping.trading_symbol

    def wait_for_capture_time(self) -> None:
        connect_at = datetime.combine(TRADING_DATE, CAPTURE_CONNECT_TIME, tzinfo=IST)
        opened, _ = nse_equity_derivatives_session_bounds(TRADING_DATE)
        while datetime.now(IST) < connect_at:
            remaining = (connect_at - datetime.now(IST)).total_seconds()
            self.update(
                stage="wait_for_open",
                status="waiting",
                connect_at=connect_at.isoformat(),
                seconds_remaining=max(remaining, 0.0),
            )
            time.sleep(min(POLL_SECONDS, max(remaining, 0.1)))
        if datetime.now(IST) > opened:
            raise RuntimeError("controller did not begin capture before the regular-session open")

    @staticmethod
    def pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def existing_child_pid(self, stage: str) -> int | None:
        children = self.state.get("children")
        if not isinstance(children, dict):
            return None
        child = children.get(stage)
        if not isinstance(child, dict):
            return None
        raw = child.get("pid")
        if not isinstance(raw, int) or not self.pid_alive(raw):
            return None
        return raw

    def monitor_existing_child(self, stage: str, pid: int) -> None:
        self.log(f"reattached state monitoring for surviving {stage} child PID {pid}")
        while self.pid_alive(pid):
            tape_bytes = sum(
                path.stat().st_size for path in self.capture_root.glob("*/tape_*.jsonl")
            )
            self.update(
                stage=stage,
                status="recovering_existing_child",
                active_child_pid=pid,
                capture_bytes=tape_bytes,
            )
            time.sleep(POLL_SECONDS)
        self.update(stage=stage, status="existing_child_ended", active_child_pid=None)

    def capture_already_started(self) -> bool:
        return (
            checkpoint_valid(self.checkpoints / "capture.json")
            or self.existing_child_pid("capture") is not None
            or any(path.is_dir() for path in self.capture_root.glob("sha-*"))
        )

    def run_child(self, stage: str, command: Sequence[str]) -> None:
        stdout_path = self.logs / f"{stage}.stdout.log"
        stderr_path = self.logs / f"{stage}.stderr.log"
        self.log(f"starting {stage}: {' '.join(command)}")
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, cwd=self.repo, stdout=stdout, stderr=stderr)
            self.state["children"][stage] = {
                "pid": process.pid,
                "started_at": datetime.now(IST).isoformat(),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            }
            while process.poll() is None:
                tape_bytes = sum(
                    path.stat().st_size
                    for path in self.capture_root.glob("*/tape_*.jsonl")
                )
                self.update(
                    stage=stage,
                    status="running",
                    active_child_pid=process.pid,
                    capture_bytes=tape_bytes,
                )
                time.sleep(POLL_SECONDS)
        code = int(process.returncode or 0)
        self.state["children"][stage]["ended_at"] = datetime.now(IST).isoformat()
        self.state["children"][stage]["exit_code"] = code
        self.update(stage=stage, status="finished", active_child_pid=None)
        if code != 0:
            raise RuntimeError(f"stage {stage} exited {code}; inspect {stderr_path}")

    def capture(self, master: Path, security_id: str, symbol: str) -> Path:
        checkpoint = self.checkpoints / "capture.json"
        if checkpoint_valid(checkpoint):
            value = json.loads(checkpoint.read_text(encoding="utf-8"))
            return Path(value["tape"])
        existing_pid = self.existing_child_pid("capture")
        run_dirs_before = tuple(path for path in self.capture_root.glob("sha-*") if path.is_dir())
        if existing_pid is not None:
            self.monitor_existing_child("capture", existing_pid)
        elif not run_dirs_before:
            _, closed = nse_equity_derivatives_session_bounds(TRADING_DATE)
            stop_at = closed + timedelta(seconds=POST_CLOSE_BUFFER_SECONDS)
            duration = math.ceil((stop_at - datetime.now(IST)).total_seconds())
            command = [
                str(self.python),
                "-m",
                "shaurya.cli.capture_dhan",
                "--credentials",
                str(self.args.credentials.resolve()),
                "--security-master",
                str(master),
                "--security-id",
                security_id,
                "--expected-symbol",
                symbol,
                "--duration-seconds",
                str(duration),
                "--output-root",
                str(self.capture_root),
                "--enable-depth200",
                "--ofi-full-session-replication",
                "--channel-start-stagger-seconds",
                "0.5",
            ]
            self.run_child("capture", command)
        run_dirs = sorted(
            (path for path in self.capture_root.glob("sha-*") if path.is_dir()),
            key=lambda path: path.stat().st_mtime_ns,
        )
        if len(run_dirs) != 1:
            raise ValueError(f"capture root must contain exactly one run, found {len(run_dirs)}")
        tape = _find_one(run_dirs[0], "tape_*.jsonl")
        metrics = capture_metrics_for(tape)
        computed = sha256_file(tape)
        recorded = manifest_sha256_for(tape)
        receipt = inspect_replication_capture(
            tape,
            metrics,
            tape_sha256=computed,
            manifest_sha256=recorded,
        )
        atomic_json(self.run_root / "artifacts/capture_acceptance.json", receipt)
        require_accepted_receipt(receipt)
        atomic_json(
            checkpoint,
            {
                "stage": "capture",
                "accepted_at": datetime.now(IST).isoformat(),
                "tape": str(tape),
                "outputs": {str(tape): computed},
            },
        )
        return tape

    def analysis_stage(self, stage: str, command: Sequence[str], outputs: Sequence[Path]) -> None:
        checkpoint = self.checkpoints / f"{stage}.json"
        if checkpoint_valid(checkpoint):
            self.log(f"checkpoint verified; skipping {stage}")
            return
        existing_pid = self.existing_child_pid(stage)
        if existing_pid is not None:
            self.monitor_existing_child(stage, existing_pid)
            missing = [path for path in outputs if not path.is_file()]
            if missing:
                raise RuntimeError(
                    f"recovered {stage} child ended without complete outputs: {missing}"
                )
            atomic_json(
                checkpoint,
                {
                    "stage": stage,
                    "accepted_at": datetime.now(IST).isoformat(),
                    "recovered_existing_child": True,
                    "outputs": hash_files(outputs),
                },
            )
            return
        self.run_child(stage, command)
        missing = [path for path in outputs if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"stage {stage} omitted outputs: {missing}")
        atomic_json(
            checkpoint,
            {
                "stage": stage,
                "accepted_at": datetime.now(IST).isoformat(),
                "outputs": hash_files(outputs),
            },
        )

    def analyze(self, tape: Path) -> None:
        if self.final_analysis.exists():
            self.log("final analysis directory already exists; preserving it")
            return
        self.partial_analysis.mkdir(mode=0o700, parents=True, exist_ok=True)
        seed = "20260820"
        replicates = str(self.args.replicates)
        scalar_outputs = [
            self.partial_analysis / "scalar_ofi.json",
            self.partial_analysis / "scalar_ofi_grid.jsonl",
            self.partial_analysis / "scalar_ofi_nested.jsonl",
        ]
        self.analysis_stage(
            "scalar_ofi",
            [
                str(self.python),
                "scripts/deepbook_ofi_scan.py",
                "--tape",
                str(tape),
                "--output",
                str(scalar_outputs[0]),
                "--grid-output",
                str(scalar_outputs[1]),
                "--nested-output",
                str(scalar_outputs[2]),
                "--replicates",
                replicates,
                "--seed",
                seed,
                "--full-session-replication",
            ],
            scalar_outputs,
        )
        cks_outputs = [
            self.partial_analysis / "cks_l1.json",
            self.partial_analysis / "cks_l1_grid.jsonl",
            self.partial_analysis / "cks_l1_components.jsonl",
        ]
        self.analysis_stage(
            "cks_l1",
            [
                str(self.python),
                "scripts/cks_l1_ofi_scan.py",
                "--tape",
                str(tape),
                "--output",
                str(cks_outputs[0]),
                "--grid-output",
                str(cks_outputs[1]),
                "--components-output",
                str(cks_outputs[2]),
                "--replicates",
                replicates,
                "--seed",
                seed,
                "--full-session-replication",
            ],
            cks_outputs,
        )
        horse_outputs = [
            self.partial_analysis / "horse_race.json",
            self.partial_analysis / "horse_future_cells.jsonl",
            self.partial_analysis / "horse_past_cells.jsonl",
            self.partial_analysis / "horse_ranking.csv",
            self.partial_analysis / "horse_ablations.csv",
            self.partial_analysis / "horse_intensity.csv",
            self.partial_analysis / "horse_support.csv",
            self.partial_analysis / "horse_gate.csv",
        ]
        self.analysis_stage(
            "horse_race",
            [
                str(self.python),
                "scripts/ofi_horserace.py",
                "--tape",
                str(tape),
                "--output",
                str(horse_outputs[0]),
                "--cells-output",
                str(horse_outputs[1]),
                "--past-output",
                str(horse_outputs[2]),
                "--ranking-output",
                str(horse_outputs[3]),
                "--ablation-output",
                str(horse_outputs[4]),
                "--intensity-output",
                str(horse_outputs[5]),
                "--support-output",
                str(horse_outputs[6]),
                "--gate-output",
                str(horse_outputs[7]),
                "--replicates",
                replicates,
                "--seed",
                seed,
                "--full-session-replication",
            ],
            horse_outputs,
        )
        scalar = json.loads(scalar_outputs[0].read_text(encoding="utf-8"))
        horse = json.loads(horse_outputs[0].read_text(encoding="utf-8"))
        summary = build_fixed_lead_summary(scalar, horse)
        summary_path = self.partial_analysis / "fixed_leads.json"
        report_path = self.partial_analysis / "FIXED-LEADS.md"
        atomic_json(summary_path, summary)
        atomic_text(report_path, fixed_lead_markdown(summary))
        all_outputs = sorted(path for path in self.partial_analysis.iterdir() if path.is_file())
        hash_manifest = {
            "schema_version": "1.0.0",
            "protocol_id": PROTOCOL_ID,
            "registration_commit": REGISTRATION_COMMIT,
            "code_commit": self.args.expected_code_commit,
            "source_spec": SOURCE_SPEC,
            "source_amendment": SOURCE_AMENDMENT,
            "tape": str(tape),
            "tape_sha256": sha256_file(tape),
            "artifacts": hash_files(all_outputs),
        }
        atomic_json(self.partial_analysis / "hash_manifest.json", hash_manifest)
        os.replace(self.partial_analysis, self.final_analysis)
        final_report = (
            f"# {PROTOCOL_ID} final run report\n\n"
            "Capture acceptance and every analysis stage completed. See `FIXED-LEADS.md` for "
            "the pre-named leads and `hash_manifest.json` for exact provenance. Complete-grid "
            "reranking is exploratory; cross-tape stability is unavailable; this run is not "
            "SIG-21 calibration and carries no order authority.\n"
        )
        atomic_text(self.run_root / "final-report.md", final_report)

    def run(self) -> int:
        self.acquire_lock()
        try:
            master, security_id, symbol = self.preflight()
            if not self.capture_already_started():
                self.wait_for_capture_time()
            tape = self.capture(master, security_id, symbol)
            self.analyze(tape)
            self.update(
                stage="complete",
                status="complete",
                final_analysis=str(self.final_analysis),
                final_report=str(self.run_root / "final-report.md"),
            )
            return 0
        except BaseException as exc:
            self.log(f"terminal failure: {type(exc).__name__}: {exc}")
            self.update(
                stage=self.state.get("stage", "unknown"),
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--instrument-master-root", required=True, type=Path)
    parser.add_argument("--capture-output-root", required=True, type=Path)
    parser.add_argument("--analysis-output-root", required=True, type=Path)
    parser.add_argument("--expected-code-commit", required=True)
    parser.add_argument("--trading-date", default=TRADING_DATE.isoformat())
    parser.add_argument("--replicates", type=int, default=400)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.replicates < 1:
        raise SystemExit("--replicates must be positive")
    return Controller(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
