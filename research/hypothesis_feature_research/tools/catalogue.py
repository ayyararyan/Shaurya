#!/usr/bin/env python3
"""Deterministic inventory and validation for the research catalogue.

This tool deliberately does not infer hypotheses or feature semantics. It validates the
human-curated registries and updates only the mechanically derived test inventory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
from pathlib import Path

CATALOGUE_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_ROOT = RESEARCH_ROOT / "tests"
INVENTORY_PATH = CATALOGUE_ROOT / "tools" / "test_inventory.csv"
MULTI_VALUE_DELIMITER = "|"

ID_PATTERNS = {
    "family": re.compile(r"^HF-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "hypothesis": re.compile(r"^H-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}$"),
    "feature": re.compile(r"^F-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "test": re.compile(r"^T-[a-z0-9]+(?:-[a-z0-9]+)*$"),
}

REQUIRED_COLUMNS = {
    "hypotheses.csv": {
        "hypothesis_id",
        "family_id",
        "title",
        "research_question",
        "null_hypothesis",
        "alternative_hypothesis",
        "expected_direction",
        "feature_ids",
        "test_ids",
        "implementation_status",
        "evidence_status",
        "input_data",
        "output_locations",
        "source_paths",
        "unresolved_questions",
        "statement_basis",
    },
    "features.csv": {
        "feature_id",
        "canonical_name",
        "aliases",
        "feature_family",
        "plain_language_meaning",
        "formula_or_algorithm",
        "units",
        "data_type",
        "valid_domain",
        "frequency",
        "timestamp_convention",
        "observation_key",
        "raw_source_fields",
        "preprocessing",
        "window_and_warmup",
        "lag_and_availability",
        "missing_and_zero_behavior",
        "normalization",
        "sign_interpretation",
        "producing_paths",
        "hypothesis_ids",
        "test_ids",
        "leakage_or_survivorship_risk",
        "verification_status",
    },
    "test_traceability.csv": {
        "test_id",
        "repository_relative_path",
        "entry_points_or_functions",
        "hypothesis_ids",
        "feature_ids",
        "inputs",
        "outputs",
        "dependencies",
        "execution_category",
        "implementation_status",
        "evidence_result_location",
        "notes_or_unresolved_classification",
    },
    "feature_data/manifest.csv": {
        "artifact_id",
        "repository_relative_path",
        "disposition",
        "feature_family",
        "grain",
        "schema_summary",
        "bytes",
        "row_count",
        "coverage",
        "modified_at_utc",
        "sha256",
        "source_pipeline",
        "quality_status",
        "notes",
    },
}

IMPLEMENTATION_STATUSES = {
    "implemented",
    "partially_implemented",
    "planned_or_stub",
    "unclear",
    "disabled",
    "superseded",
}
EVIDENCE_STATUSES = {
    "no result located",
    "result located but not validated",
    "inconclusive",
    "supports hypothesis",
    "rejects hypothesis",
    "mixed",
    "unable to determine",
}


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    path = CATALOGUE_ROOT / relative_path
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{relative_path}: missing CSV header")
        missing = REQUIRED_COLUMNS[relative_path] - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{relative_path}: missing columns {sorted(missing)}")
        rows = list(reader)
        for number, row in enumerate(rows, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{relative_path}:{number}: malformed row shape")
        return rows


def _split(value: str) -> tuple[str, ...]:
    if not value or value in {"none", "not_applicable"}:
        return ()
    return tuple(item for item in value.split(MULTI_VALUE_DELIMITER) if item)


def _unique(rows: list[dict[str, str]], field: str, kind: str, errors: list[str]) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value = row[field]
        if not ID_PATTERNS[kind].fullmatch(value):
            errors.append(f"invalid {kind} ID: {value}")
        if value in values:
            errors.append(f"duplicate {kind} ID: {value}")
        values.add(value)
    return values


def _test_files() -> list[Path]:
    return sorted(
        path
        for path in TEST_ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def _inventory_text() -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("repository_relative_path", "suffix", "bytes", "sha256"))
    for path in _test_files():
        payload = path.read_bytes()
        writer.writerow(
            (
                path.relative_to(REPO_ROOT).as_posix(),
                path.suffix or "none",
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        )
    return output.getvalue()


def update_inventory() -> bool:
    expected = _inventory_text()
    current = INVENTORY_PATH.read_text(encoding="utf-8") if INVENTORY_PATH.exists() else None
    if current == expected:
        return False
    INVENTORY_PATH.write_text(expected, encoding="utf-8", newline="")
    return True


def _check_paths(values: tuple[str, ...], label: str, errors: list[str]) -> None:
    for value in values:
        if value.startswith(("expected:", "not_generated:", "external:", "none")):
            continue
        if not (REPO_ROOT / value).exists():
            errors.append(f"{label}: nonexistent path {value}")


def validate() -> list[str]:
    errors: list[str] = []
    tables: dict[str, list[dict[str, str]]] = {}
    for relative_path in REQUIRED_COLUMNS:
        try:
            tables[relative_path] = _read_csv(relative_path)
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            errors.append(str(exc))
    if errors:
        return errors

    hypotheses = tables["hypotheses.csv"]
    features = tables["features.csv"]
    tests = tables["test_traceability.csv"]
    family_ids = {row["family_id"] for row in hypotheses}
    for family_id in family_ids:
        if not ID_PATTERNS["family"].fullmatch(family_id):
            errors.append(f"invalid family ID: {family_id}")
    hypothesis_ids = _unique(hypotheses, "hypothesis_id", "hypothesis", errors)
    feature_ids = _unique(features, "feature_id", "feature", errors)
    test_ids = _unique(tests, "test_id", "test", errors)

    for row in hypotheses:
        if row["implementation_status"] not in IMPLEMENTATION_STATUSES:
            errors.append(f"{row['hypothesis_id']}: invalid implementation status")
        if row["evidence_status"] not in EVIDENCE_STATUSES:
            errors.append(f"{row['hypothesis_id']}: invalid evidence status")
        for value in _split(row["feature_ids"]):
            if value not in feature_ids:
                errors.append(f"{row['hypothesis_id']}: unknown feature {value}")
        for value in _split(row["test_ids"]):
            if value not in test_ids:
                errors.append(f"{row['hypothesis_id']}: unknown test {value}")
        _check_paths(_split(row["source_paths"]), row["hypothesis_id"], errors)
        _check_paths(_split(row["output_locations"]), row["hypothesis_id"], errors)

    for row in features:
        for value in _split(row["hypothesis_ids"]):
            if value not in hypothesis_ids:
                errors.append(f"{row['feature_id']}: unknown hypothesis {value}")
        for value in _split(row["test_ids"]):
            if value not in test_ids:
                errors.append(f"{row['feature_id']}: unknown test {value}")
        _check_paths(_split(row["producing_paths"]), row["feature_id"], errors)

    traced_paths: set[str] = set()
    all_traced_paths: set[str] = set()
    for row in tests:
        path = row["repository_relative_path"]
        if path in all_traced_paths:
            errors.append(f"duplicate traced path: {path}")
        all_traced_paths.add(path)
        if path.startswith("research/tests/"):
            traced_paths.add(path)
        _check_paths((path,), row["test_id"], errors)
        for value in _split(row["hypothesis_ids"]):
            if value not in hypothesis_ids:
                errors.append(f"{row['test_id']}: unknown hypothesis {value}")
        for value in _split(row["feature_ids"]):
            if value not in feature_ids:
                errors.append(f"{row['test_id']}: unknown feature {value}")
        if row["implementation_status"] not in IMPLEMENTATION_STATUSES:
            errors.append(f"{row['test_id']}: invalid implementation status")
        _check_paths(_split(row["evidence_result_location"]), row["test_id"], errors)

    inventory_paths = {path.relative_to(REPO_ROOT).as_posix() for path in _test_files()}
    for path in sorted(inventory_paths - traced_paths):
        errors.append(f"unmapped test inventory file: {path}")
    for path in sorted(traced_paths - inventory_paths):
        errors.append(f"traceability path is no longer in test inventory: {path}")

    if not INVENTORY_PATH.exists():
        errors.append("tools/test_inventory.csv is missing; run --update-inventory")
    elif INVENTORY_PATH.read_text(encoding="utf-8") != _inventory_text():
        errors.append("tools/test_inventory.csv is stale; run --update-inventory")

    manifest = tables["feature_data/manifest.csv"]
    for row in manifest:
        label = row["artifact_id"]
        path = REPO_ROOT / row["repository_relative_path"]
        if not path.is_file():
            errors.append(
                f"{label}: manifest artifact is not a file: {row['repository_relative_path']}"
            )
            continue
        payload = path.read_bytes()
        if str(len(payload)) != row["bytes"]:
            errors.append(f"{label}: byte count changed")
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append(f"{label}: SHA-256 changed")
        with path.open(newline="", encoding="utf-8") as handle:
            data_rows = sum(1 for _ in csv.reader(handle)) - 1
        if str(data_rows) != row["row_count"]:
            errors.append(f"{label}: row count changed")
        # Git does not preserve filesystem mtimes. The recorded value is useful provenance but
        # cannot be a checkout-stable integrity gate; byte length, row count and SHA-256 are.

    known_by_kind = {
        "family": family_ids,
        "hypothesis": hypothesis_ids,
        "feature": feature_ids,
        "test": test_ids,
    }
    markdown_id_patterns = {
        "family": re.compile(r"\bHF-[a-z0-9]+(?:-[a-z0-9]+)*\b"),
        "hypothesis": re.compile(r"\bH-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}\b"),
        "feature": re.compile(r"\bF-[a-z0-9]+(?:-[a-z0-9]+)*\b"),
        "test": re.compile(r"\bT-[a-z0-9]+(?:-[a-z0-9]+)*\b"),
    }
    markdown_link = re.compile(r"\[[^]]*\]\(([^)]+)\)")
    for path in sorted(CATALOGUE_ROOT.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for kind, pattern in markdown_id_patterns.items():
            for match in pattern.finditer(text):
                value = match.group(0)
                if value not in known_by_kind[kind]:
                    errors.append(f"{path.relative_to(CATALOGUE_ROOT)}: unknown {kind} ID {value}")
        for match in markdown_link.finditer(text):
            target = match.group(1).split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).resolve().exists():
                errors.append(f"{path.relative_to(CATALOGUE_ROOT)}: broken Markdown link {target}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument(
        "--update-inventory", action="store_true", help="update only tools/test_inventory.csv"
    )
    args = parser.parse_args(argv)
    if not args.check and not args.update_inventory:
        parser.error("choose --check or --update-inventory")
    if args.update_inventory:
        changed = update_inventory()
        print("test inventory updated" if changed else "test inventory already current")
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "catalogue valid: "
        f"{len(_test_files())} inventory files, "
        f"{sum(1 for _ in csv.DictReader((CATALOGUE_ROOT / 'hypotheses.csv').open()))} hypotheses, "
        f"{sum(1 for _ in csv.DictReader((CATALOGUE_ROOT / 'features.csv').open()))} features"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
