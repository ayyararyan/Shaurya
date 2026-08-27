"""Immutable, content-addressed daily research state and historical reconstruction."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from shaurya.research.contracts import canonical_json, canonical_sha256


@dataclass(frozen=True, slots=True)
class ResearchState:
    as_of_date: date
    intended_for_session: date
    active_hypotheses: tuple[str, ...]
    lifecycle: tuple[tuple[str, str], ...]
    evidence_grades: tuple[tuple[str, str], ...]
    coefficient_estimates: tuple[tuple[str, float], ...]
    shrinkage_state: tuple[tuple[str, float], ...]
    regime_models: tuple[tuple[str, str], ...]
    performance_history_hash: str
    dormant_hypotheses: tuple[str, ...]
    parameter_surface_hashes: tuple[tuple[str, str], ...]
    model_weights: tuple[tuple[str, float], ...]
    source_ledger_hash: str
    plan_hash: str = ""
    planned_hypothesis_ids: tuple[str, ...] = ()
    source_prefix_manifest: tuple[tuple[str, str, str], ...] = ()
    derivation_prefixes: tuple[tuple[str, str], ...] = ()
    policy_fingerprint: str = ""
    historical_effects: tuple[tuple[str, tuple[float, ...]], ...] = ()
    diagnostic_hashes: tuple[tuple[str, str], ...] = ()
    block_bootstrap_hashes: tuple[tuple[str, str], ...] = ()
    historical_coefficients: tuple[
        tuple[str, tuple[tuple[str, str, float, float], ...]], ...
    ] = ()
    evidence_mode: str = "confirmatory_walk_forward"
    published_at: str = ""
    publication_event_hash: str = ""
    report_path: str = ""
    report_sha256: str = ""
    report_manifest_sha256: str = ""
    state_hash: str = ""

    def __post_init__(self) -> None:
        if self.source_prefix_manifest != tuple(sorted(self.source_prefix_manifest)):
            raise ValueError("state source prefix manifest must be chronological and canonical")
        if len({item[1] for item in self.source_prefix_manifest}) != len(
            self.source_prefix_manifest
        ):
            raise ValueError("state source prefix contains duplicate datasets")
        if self.derivation_prefixes != tuple(sorted(self.derivation_prefixes)):
            raise ValueError("state derivation prefixes must be chronological and canonical")
        if self.historical_effects != tuple(sorted(self.historical_effects)):
            raise ValueError("state historical effects must be canonical")
        if self.diagnostic_hashes != tuple(sorted(self.diagnostic_hashes)):
            raise ValueError("state diagnostic hashes must be canonical")
        if self.block_bootstrap_hashes != tuple(sorted(self.block_bootstrap_hashes)):
            raise ValueError("state block-bootstrap hashes must be canonical")
        if self.historical_coefficients != tuple(sorted(self.historical_coefficients)):
            raise ValueError("state historical coefficients must be canonical")
        if self.evidence_mode not in {"confirmatory_walk_forward", "live_shadow"}:
            raise ValueError("state evidence mode must be prospective or confirmatory")
        for digest in (
            *(item[2] for item in self.source_prefix_manifest),
            *(item[1] for item in self.derivation_prefixes),
            *(item[1] for item in self.diagnostic_hashes),
            *(item[1] for item in self.block_bootstrap_hashes),
            *((self.policy_fingerprint,) if self.policy_fingerprint else ()),
            *((self.publication_event_hash,) if self.publication_event_hash else ()),
            *((self.report_sha256,) if self.report_sha256 else ()),
            *((self.report_manifest_sha256,) if self.report_manifest_sha256 else ()),
        ):
            if len(digest) != 64:
                raise ValueError("state scientific bindings must be SHA-256 digests")

    def with_hash(self) -> ResearchState:
        payload = asdict(self)
        payload["state_hash"] = ""
        return ResearchState(**{**payload, "state_hash": canonical_sha256(payload)})


class StateStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, state: ResearchState) -> Path:
        resolved = state if state.state_hash else state.with_hash()
        expected = resolved.with_hash().state_hash
        if resolved.state_hash != expected:
            raise ValueError("state hash does not match content")
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        lock_descriptor = os.open(self.directory / ".state.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            existing = sorted(self.directory.glob(f"{resolved.as_of_date.isoformat()}-*.json"))
            encoded = canonical_json(asdict(resolved)) + "\n"
            if existing:
                for path in existing:
                    try:
                        stored = json.loads(path.read_text(encoding="utf-8"))
                        stored_hash = str(stored["state_hash"])
                    except (json.JSONDecodeError, KeyError, TypeError) as exc:
                        raise ValueError("existing state artifact is unreadable") from exc
                    canonical_name = f"{resolved.as_of_date.isoformat()}-{stored_hash}.json"
                    if path.name != canonical_name:
                        raise ValueError(
                            "existing state artifact has a non-content-addressed filename"
                        )
                if len(existing) == 1 and existing[0].read_text(encoding="utf-8") == encoded:
                    return existing[0]
                raise ValueError("an immutable state already exists for this date")
            path = self.directory / f"{resolved.as_of_date.isoformat()}-{resolved.state_hash}.json"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", dir=self.directory
            )
            temporary = Path(temporary_name)
            try:
                os.chmod(temporary, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(temporary, path)
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            return path
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

    def load_as_of(self, requested_date: date) -> ResearchState | None:
        candidates: list[tuple[date, Path]] = []
        for path in self.directory.glob("????-??-??-*.json") if self.directory.exists() else ():
            try:
                state_date = date.fromisoformat(path.name[:10])
            except ValueError:
                continue
            if state_date <= requested_date:
                candidates.append((state_date, path))
        if not candidates:
            return None
        selected_date = max(item[0] for item in candidates)
        selected = [path for state_date, path in candidates if state_date == selected_date]
        if len(selected) != 1:
            raise ValueError("state store contains conflicting immutable states for one date")
        path = selected[0]
        raw: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        state = ResearchState(
            as_of_date=date.fromisoformat(str(raw["as_of_date"])),
            intended_for_session=date.fromisoformat(str(raw["intended_for_session"])),
            active_hypotheses=tuple(raw["active_hypotheses"]),
            lifecycle=tuple(tuple(item) for item in raw["lifecycle"]),
            evidence_grades=tuple(tuple(item) for item in raw["evidence_grades"]),
            coefficient_estimates=tuple(
                (item[0], float(item[1])) for item in raw["coefficient_estimates"]
            ),
            shrinkage_state=tuple((item[0], float(item[1])) for item in raw["shrinkage_state"]),
            regime_models=tuple(tuple(item) for item in raw["regime_models"]),
            performance_history_hash=str(raw["performance_history_hash"]),
            dormant_hypotheses=tuple(raw["dormant_hypotheses"]),
            parameter_surface_hashes=tuple(tuple(item) for item in raw["parameter_surface_hashes"]),
            model_weights=tuple((item[0], float(item[1])) for item in raw["model_weights"]),
            source_ledger_hash=str(raw["source_ledger_hash"]),
            plan_hash=str(raw.get("plan_hash", "")),
            planned_hypothesis_ids=tuple(raw.get("planned_hypothesis_ids", ())),
            source_prefix_manifest=tuple(
                (str(item[0]), str(item[1]), str(item[2]))
                for item in raw.get("source_prefix_manifest", ())
            ),
            derivation_prefixes=tuple(
                (str(item[0]), str(item[1])) for item in raw.get("derivation_prefixes", ())
            ),
            policy_fingerprint=str(raw.get("policy_fingerprint", "")),
            historical_effects=tuple(
                (str(item[0]), tuple(float(value) for value in item[1]))
                for item in raw.get("historical_effects", ())
            ),
            diagnostic_hashes=tuple(
                (str(item[0]), str(item[1])) for item in raw.get("diagnostic_hashes", ())
            ),
            block_bootstrap_hashes=tuple(
                (str(item[0]), str(item[1]))
                for item in raw.get("block_bootstrap_hashes", ())
            ),
            historical_coefficients=tuple(
                (
                    str(item[0]),
                    tuple(
                        (str(value[0]), str(value[1]), float(value[2]), float(value[3]))
                        for value in item[1]
                    ),
                )
                for item in raw.get("historical_coefficients", ())
            ),
            evidence_mode=str(raw.get("evidence_mode", "confirmatory_walk_forward")),
            published_at=str(raw.get("published_at", "")),
            publication_event_hash=str(raw.get("publication_event_hash", "")),
            report_path=str(raw.get("report_path", "")),
            report_sha256=str(raw.get("report_sha256", "")),
            report_manifest_sha256=str(raw.get("report_manifest_sha256", "")),
            state_hash=str(raw["state_hash"]),
        )
        if state.with_hash().state_hash != state.state_hash:
            raise ValueError("stored research state failed content verification")
        expected_name = f"{state.as_of_date.isoformat()}-{state.state_hash}.json"
        if path.name != expected_name:
            raise ValueError("stored research state filename is not content-addressed")
        if state.report_path:
            report = Path(state.report_path)
            manifest = report.with_suffix(".manifest.json")
            if (
                not report.is_file()
                or not manifest.is_file()
                or _sha256_file(report) != state.report_sha256
                or _sha256_file(manifest) != state.report_manifest_sha256
            ):
                raise ValueError("stored research state report binding is invalid")
        return state

    def load_exact(self, path: Path) -> ResearchState:
        if path.parent.resolve() != self.directory.resolve():
            raise ValueError("state path is outside this immutable state store")
        try:
            state_date = date.fromisoformat(path.name[:10])
        except ValueError as exc:
            raise ValueError("state path does not carry an as-of date") from exc
        state = self.load_as_of(state_date)
        if state is None:
            raise FileNotFoundError(path)
        expected = self.directory / f"{state.as_of_date.isoformat()}-{state.state_hash}.json"
        if expected.resolve() != path.resolve():
            raise ValueError("requested state is not the verified content-addressed artifact")
        return state


def write_checkpoint(
    directory: Path, *, kind: str, bindings: Mapping[str, object], artifact: object
) -> Path:
    """Publish a complete checkpoint only after canonical exact readback."""

    payload = {"kind": kind, "bindings": dict(bindings), "artifact": artifact}
    digest = canonical_sha256(payload)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / f"{kind}-{digest}.json"
    encoded = canonical_json({**payload, "checkpoint_hash": digest}) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("checkpoint content conflict")
        return path
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if json.loads(path.read_text(encoding="utf-8"))["checkpoint_hash"] != digest:
        raise ValueError("checkpoint exact readback failed")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checkpoint(path: Path, *, expected_bindings: Mapping[str, object]) -> object:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["bindings"] != dict(expected_bindings):
        raise ValueError("checkpoint bindings do not match current inputs")
    expected = canonical_sha256(
        {"kind": payload["kind"], "bindings": payload["bindings"], "artifact": payload["artifact"]}
    )
    if payload["checkpoint_hash"] != expected:
        raise ValueError("checkpoint hash is invalid")
    return payload["artifact"]
