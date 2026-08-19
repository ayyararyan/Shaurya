"""Causal, outcome-blind signal feature construction."""

from .deep_book_anomaly import (
    BASELINE_THRESHOLDS,
    FAR_BOUNDARY_RUPEES,
    AtomicEventType,
    BaselineContext,
    CandidateEvent,
    DetectionResult,
    PreviousSessionEmpiricalBaseline,
    ScoredCandidate,
    detect_candidates,
)

__all__ = [
    "BASELINE_THRESHOLDS",
    "FAR_BOUNDARY_RUPEES",
    "AtomicEventType",
    "BaselineContext",
    "CandidateEvent",
    "DetectionResult",
    "PreviousSessionEmpiricalBaseline",
    "ScoredCandidate",
    "detect_candidates",
]
