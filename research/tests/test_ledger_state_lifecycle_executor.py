from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shaurya.research.contracts import (
    EvidenceGrade,
    ExperimentStatus,
    HypothesisStatus,
    ResearchMode,
    canonical_json,
    canonical_sha256,
)
from shaurya.research.evidence import EvidenceRecord, SelectionProvenance, assess_lifecycle
from shaurya.research.ledger import EvidenceLedger, LedgerEnvelope, materialize_snapshot
from shaurya.research.state import ResearchState, StateStore


def _record(evaluation_date: date, *, score: float = 0.2) -> EvidenceRecord:
    evaluation_start = datetime.combine(evaluation_date, datetime.min.time(), tzinfo=UTC)
    return EvidenceRecord(
        hypothesis_id="alpha-a",
        evaluation_date=evaluation_date,
        mode=ResearchMode.CONFIRMATORY,
        training_interval=("2025-01-01", "2025-12-30"),
        validation_interval=("2025-12-31T00:00:00+00:00", "2025-12-31T23:59:59+00:00"),
        test_interval=(
            evaluation_date.isoformat(),
            (evaluation_date + timedelta(days=1)).isoformat(),
        ),
        observation_count=100,
        effective_sample_size=60,
        model_class="ridge",
        hyperparameters=(("ridge_penalty", 1.0),),
        feature_registry_version="features-v1",
        target_registry_version="targets-v1",
        policy_registry_version="policy-v1",
        feature_run_hashes=("a" * 64,),
        metrics=(
            ("coefficient", score),
            ("economic_gate_pass", True),
            ("neighbor_robustness", 1.0),
            ("regime_comparison_pass", True),
            ("score", score),
            ("score_gate_pass", True),
        ),
        uncertainty=(
            ("adjusted_p_value", 0.01),
            ("empirical_null_p_value", 0.01),
            ("standard_error", 0.05),
        ),
        selection=SelectionProvenance(
            ("alpha-a",),
            "pearson_correlation",
            (evaluation_start - timedelta(microseconds=1)).isoformat(),
            evaluation_start.isoformat(),
            1,
            (("alpha-a", score),),
            None,
            (),
            "benjamini_yekutieli",
            ResearchMode.CONFIRMATORY,
        ),
        competing_hypotheses=1,
        terminal_status=ExperimentStatus.COMPLETED,
        plan_hash="c" * 64,
        pre_session_state_hash="0" * 64,
        source_identity_hash="d" * 64,
        fold_hashes=(f"{evaluation_date.day:064x}",),
        selected_for_outer=True,
    )


def test_ledger_is_hash_chained_append_only_and_snapshot_is_create_once(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    first = ledger.append("hypothesis_evidence", _record(date(2026, 1, 1)))
    second = ledger.append("hypothesis_evidence", _record(date(2026, 1, 2)))
    assert second.previous_hash == first.event_hash
    snapshot = materialize_snapshot(ledger, tmp_path / "snapshots")
    assert materialize_snapshot(ledger, tmp_path / "snapshots") == snapshot


def test_ledger_read_rolls_back_a_real_mid_record_partial_write(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    first = ledger.append("base", {"value": 1})
    event = {"value": 2}
    core = {
        "sequence": 2,
        "recorded_at": "2026-08-26T00:00:00+00:00",
        "event_id": f"event-{canonical_sha256({'event_type': 'next', 'event': event})[:32]}",
        "event_type": "next",
        "event": event,
        "previous_hash": first.event_hash,
    }
    envelope = LedgerEnvelope(**core, event_hash=canonical_sha256(core))
    encoded = (canonical_json(envelope) + "\n").encode()
    start = ledger.path.stat().st_size
    with ledger.path.open("ab") as handle:
        handle.write(encoded[: len(encoded) // 2])
        handle.flush()
    journal = ledger.path.with_suffix(".jsonl.txn")
    journal.write_text(
        canonical_json(
            {
                "start_offset": start,
                "encoded_hex": encoded.hex(),
                "encoded_sha256": canonical_sha256(encoded.hex()),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert ledger.read() == (first,)
    assert not journal.exists()
    assert ledger.append("next", event).sequence == 2
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["event"]["observation_count"] = 1_000
    lines[0] = json.dumps(tampered)
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="modified"):
        ledger.read()


def test_missing_scores_interrupt_decay_and_rejected_is_terminal() -> None:
    start = date(2026, 1, 1)
    history = [_record(start + timedelta(days=index), score=-0.2) for index in range(2)]
    missing = replace(
        _record(start + timedelta(days=2)),
        metrics=(("coefficient", 0.0), ("score", None)),
        terminal_status=ExperimentStatus.SKIPPED,
        terminal_reason="missing_registered_score",
    )
    history.extend((missing, _record(start + timedelta(days=3), score=-0.2)))
    assessment = assess_lifecycle("alpha-a", history, as_of=start + timedelta(days=3))
    assert assessment.status is not HypothesisStatus.DORMANT
    rejected = assess_lifecycle(
        "alpha-a",
        [*history, _record(start + timedelta(days=4), score=0.8)],
        as_of=start + timedelta(days=4),
        previous_status=HypothesisStatus.REJECTED,
    )
    assert rejected.status is HypothesisStatus.REJECTED


def _state(state_date: date, coefficient: float) -> ResearchState:
    return ResearchState(
        state_date,
        state_date + timedelta(days=1),
        ("alpha-a",),
        (("alpha-a", "EXPLORATORY"),),
        (("alpha-a", EvidenceGrade.E1.value),),
        (("alpha-a", coefficient),),
        (),
        (),
        canonical_sha256([coefficient]),
        (),
        (),
        (("alpha-a", 1.0),),
        "b" * 64,
    ).with_hash()


def test_historical_state_reconstruction_and_filename_validation(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    first = _state(date(2026, 1, 1), 0.2)
    path = store.write(first)
    store.write(_state(date(2026, 1, 2), -0.8))
    assert store.load_as_of(date(2026, 1, 1)) == first
    with pytest.raises(ValueError, match="already exists"):
        store.write(replace(first, coefficient_estimates=(("alpha-a", 999.0),), state_hash=""))
    renamed = path.with_name("2026-01-01-" + "f" * 64 + ".json")
    path.rename(renamed)
    with pytest.raises(ValueError, match="filename"):
        store.load_as_of(date(2026, 1, 1))
    with pytest.raises(ValueError, match="non-content-addressed filename"):
        store.write(first)


def test_skipped_evidence_interrupts_decay_streak() -> None:
    start = date(2026, 1, 1)
    positive = [_record(start + timedelta(days=index), score=0.2) for index in range(20)]
    skipped = replace(
        _record(start + timedelta(days=21), score=0.0),
        terminal_status=ExperimentStatus.SKIPPED,
        terminal_reason="not_selected_by_nested_validation",
    )
    history = [
        *positive,
        _record(start + timedelta(days=20), score=-0.1),
        skipped,
        _record(start + timedelta(days=22), score=-0.1),
        _record(start + timedelta(days=23), score=-0.1),
    ]
    assessed = assess_lifecycle(
        "alpha-a",
        history,
        as_of=start + timedelta(days=23),
        previous_status=HypothesisStatus.STABLE,
    )
    assert assessed.status is not HypothesisStatus.DECAYING


def test_unselected_skip_interrupts_post_dormancy_reactivation() -> None:
    start = date(2026, 1, 1)
    skipped_base = _record(start + timedelta(days=1), score=0.2)
    skipped = replace(
        skipped_base,
        selection=replace(skipped_base.selection, selected_rank=None),
        terminal_status=ExperimentStatus.SKIPPED,
        terminal_reason="not_selected_by_nested_validation",
        selected_for_outer=False,
    )
    latest = _record(start + timedelta(days=2), score=0.2)
    assessment = assess_lifecycle(
        "alpha-a",
        (_record(start, score=0.2), skipped, latest),
        as_of=latest.evaluation_date,
        previous_status=HypothesisStatus.DORMANT,
        policy={"reactivation": {"minimum_new_confirmatory_sessions": 2}},
    )
    assert assessment.status is HypothesisStatus.DORMANT
    assert "reactivation_requires_three_new_preselected_sessions" in assessment.reasons
