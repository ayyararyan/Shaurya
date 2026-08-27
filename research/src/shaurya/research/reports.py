"""Deterministic daily research reports with explicit evidence boundaries."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from shaurya.research.contracts import canonical_json
from shaurya.research.evidence import EvidenceRecord, LifecycleAssessment
from shaurya.research.ledger import _atomic_create_once, _sha256_path
from shaurya.research.mechanisms import MechanismSummary
from shaurya.research.surfaces import PredictiveSurface, SurfaceRobustness


def daily_report(
    *,
    report_date: date,
    lifecycle_before: Mapping[str, LifecycleAssessment],
    lifecycle_after: Mapping[str, LifecycleAssessment],
    evaluated: Sequence[EvidenceRecord],
    surfaces: Mapping[str, tuple[PredictiveSurface, SurfaceRobustness]],
    mechanisms: Sequence[MechanismSummary],
    multiplicity: Mapping[str, object],
    diagnostics: Mapping[str, object],
    warnings: Sequence[str],
) -> dict[str, Any]:
    strengthened: list[str] = []
    weakened: list[str] = []
    dormant: list[str] = []
    reactivated: list[str] = []
    new_exploratory: list[str] = []
    exploratory_ids = {
        record.hypothesis_id for record in evaluated if record.mode.value == "exploratory"
    }
    for hypothesis_id, after in sorted(lifecycle_after.items()):
        before = lifecycle_before.get(hypothesis_id)
        if before is None:
            if hypothesis_id in exploratory_ids:
                new_exploratory.append(hypothesis_id)
            continue
        elif after.status.value == "DORMANT" and before.status.value != "DORMANT":
            dormant.append(hypothesis_id)
        elif before.status.value == "DORMANT" and after.status.value != "DORMANT":
            reactivated.append(hypothesis_id)
        elif (after.rolling_score or 0) > (before.rolling_score or 0):
            strengthened.append(hypothesis_id)
        elif (after.rolling_score or 0) < (before.rolling_score or 0):
            weakened.append(hypothesis_id)
    return {
        "schema_version": "1.0.0",
        "report_date": report_date.isoformat(),
        "language_boundary": "research evidence only; no trading or execution claim",
        "existing_alpha_health": {
            "strengthened": strengthened,
            "weakened": weakened,
            "dormant": dormant,
            "reactivated": reactivated,
            "unchanged_count": max(
                0,
                len(lifecycle_after)
                - len(strengthened)
                - len(weakened)
                - len(dormant)
                - len(reactivated)
                - len(new_exploratory),
            ),
        },
        "new_exploratory_findings": new_exploratory,
        "evaluations": [asdict(record) for record in evaluated],
        "lifecycle_before": {
            identity: asdict(value) for identity, value in sorted(lifecycle_before.items())
        },
        "lifecycle_after": {
            identity: asdict(value) for identity, value in sorted(lifecycle_after.items())
        },
        "predictive_surfaces": {
            name: {"surface": asdict(surface), "robustness": asdict(robustness)}
            for name, (surface, robustness) in sorted(surfaces.items())
        },
        "multiple_testing_context": dict(multiplicity),
        "mechanism_summary": [asdict(summary) for summary in mechanisms],
        "scientific_diagnostics": dict(diagnostics),
        "research_warnings": list(warnings),
        "evidence_language": (
            "Patterns are reported with their evidence grade and OOS session support; "
            "no single-session result establishes predictive alpha."
        ),
    }


def write_daily_report(report: Mapping[str, Any], directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    report_date = str(report["report_date"])
    path = directory / f"alpha-research-{report_date}.json"
    encoded = canonical_json(report) + "\n"
    _atomic_create_once(path, encoded.encode())
    manifest = {
        "artifact": path.name,
        "report_date": report_date,
        "artifact_sha256": _sha256_path(path),
    }
    _atomic_create_once(
        path.with_suffix(".manifest.json"),
        (canonical_json(manifest) + "\n").encode(),
    )
    return path


def render_daily_markdown(report: Mapping[str, Any]) -> str:
    health = report["existing_alpha_health"]
    multiplicity = report["multiple_testing_context"]
    warnings = report["research_warnings"]
    return "\n".join(
        (
            f"# Post-market alpha research — {report['report_date']}",
            "",
            "Research evidence only; no trading or execution claim.",
            "",
            "## Existing alpha health",
            "",
            f"Strengthened: {len(health['strengthened'])}; "
            f"weakened: {len(health['weakened'])}; dormant: {len(health['dormant'])}; "
            f"reactivated: {len(health['reactivated'])}.",
            "",
            "## New exploratory findings",
            "",
            f"{len(report['new_exploratory_findings'])} newly observed registered hypotheses. "
            "None is promoted from one session.",
            "",
            "## Multiple-testing context",
            "",
            f"Hypotheses considered: {multiplicity.get('hypotheses_considered', 0)}; "
            f"adjusted findings: {multiplicity.get('adjusted_findings', 0)}.",
            "",
            "## Research warnings",
            "",
            *(f"- {warning}" for warning in warnings),
            "",
        )
    )
