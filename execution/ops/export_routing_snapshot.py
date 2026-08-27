#!/usr/bin/env python3
"""Offline, fail-closed exporter for Shaurya Execution routing snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from shaurya.contracts import (
    DhanInstrumentMaster,
    ExchangeSegment,
    InstrumentKind,
    KotakInstrumentMaster,
)
from shaurya.data import DhanInstrumentIndex, KotakInstrumentIndex


SCHEMA_VERSION = "1.0.0"
EXPORTER_VERSION = "1.0.0"
MAX_MASTER_BYTES = 256 * 1024 * 1024
MAX_UNIVERSE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_INSTRUMENTS = 4096
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ROUTE_TEXT_RE = re.compile(r"^[A-Za-z0-9._&-]{1,128}$")
UNDERLYING_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class ExportError(RuntimeError):
    """Non-secret refusal with a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InputArtifact:
    path: Path
    payload: bytes
    sha256: str
    byte_length: int
    identity: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ExportResult:
    snapshot_path: Path
    manifest_path: Path
    snapshot_sha256: str
    record_count: int
    already_present: bool


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _load_json(payload: bytes, code: str) -> Any:
    try:
        text = payload.decode("utf-8")
        if text.startswith("\ufeff") or "\x00" in text:
            raise ValueError
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey, ValueError) as exc:
        raise ExportError(code) from exc


def _canonical_json(document: Any) -> bytes:
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExportError("OUTPUT_VERIFY_FAILED") from exc
    return encoded + b"\n"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_date(raw: str, code: str) -> date:
    try:
        value = date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ExportError(code) from exc
    if value.isoformat() != raw:
        raise ExportError(code)
    return value


def _read_input(path: Path, limit: int) -> InputArtifact:
    if not path.is_absolute():
        raise ExportError("INPUT_PATH_INVALID")
    try:
        before = path.lstat()
    except OSError as exc:
        raise ExportError("INPUT_MISSING") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ExportError("INPUT_UNSAFE")
    if before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) & 0o022:
        raise ExportError("INPUT_UNSAFE")
    if before.st_size > limit:
        raise ExportError("INPUT_TOO_LARGE")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ExportError("INPUT_UNSAFE")
            payload = handle.read(limit + 1)
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError("INPUT_UNSAFE") from exc
    if len(payload) > limit:
        raise ExportError("INPUT_TOO_LARGE")
    identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    if identity != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise ExportError("INPUT_CHANGED")
    return InputArtifact(path, payload, _sha256(payload), len(payload), identity)


def _verify_input_unchanged(artifact: InputArtifact) -> None:
    current = _read_input(artifact.path, max(artifact.byte_length, 1))
    if current.identity != artifact.identity or current.sha256 != artifact.sha256:
        raise ExportError("INPUT_CHANGED")


def _csv_rows(artifact: InputArtifact, required: frozenset[str]) -> list[dict[str, str]]:
    try:
        text = artifact.payload.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError
        parsed = list(csv.reader(text.splitlines()))
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise ExportError("MASTER_MALFORMED") from exc
    if not parsed or not parsed[0] or any(not name for name in parsed[0]):
        raise ExportError("MASTER_MALFORMED")
    header = parsed[0]
    if len(header) != len(set(header)) or required.difference(header):
        raise ExportError("MASTER_MALFORMED")
    rows: list[dict[str, str]] = []
    for values in parsed[1:]:
        if not values or all(not value.strip() for value in values):
            continue
        if len(values) != len(header):
            raise ExportError("MASTER_MALFORMED")
        rows.append(dict(zip(header, values, strict=True)))
    if not rows:
        raise ExportError("MASTER_MALFORMED")
    return rows


def _validate_canonical_id(value: Any) -> str:
    if not isinstance(value, str) or not value.isascii() or len(value) > 200:
        raise ExportError("UNIVERSE_MALFORMED")
    parts = value.split(":")
    if len(parts) not in {5, 7}:
        raise ExportError("UNIVERSE_MALFORMED")
    if parts[0] != "NSE" or parts[1] != "NSE_FNO" or not UNDERLYING_RE.fullmatch(parts[2]):
        raise ExportError("UNSUPPORTED_INSTRUMENT")
    kind = parts[3]
    _parse_date(parts[4], "UNIVERSE_MALFORMED")
    if kind == "future" and len(parts) == 5:
        return value
    if kind == "option" and len(parts) == 7:
        try:
            strike = Decimal(parts[5])
        except InvalidOperation as exc:
            raise ExportError("UNIVERSE_MALFORMED") from exc
        if not strike.is_finite() or strike <= 0 or format(strike.normalize(), "f") != parts[5]:
            raise ExportError("UNIVERSE_MALFORMED")
        if parts[6] not in {"CE", "PE"}:
            raise ExportError("UNIVERSE_MALFORMED")
        return value
    raise ExportError("UNSUPPORTED_INSTRUMENT")


def _load_universe(artifact: InputArtifact, trading_date: date) -> tuple[str, ...]:
    document = _load_json(artifact.payload, "UNIVERSE_MALFORMED")
    required = {
        "schema_version",
        "trading_date",
        "dhan_master_as_of_date",
        "kotak_master_as_of_date",
        "canonical_instrument_ids",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ExportError("UNIVERSE_MALFORMED")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ExportError("UNIVERSE_VERSION_UNSUPPORTED")
    declared_dates = (
        document["trading_date"],
        document["dhan_master_as_of_date"],
        document["kotak_master_as_of_date"],
    )
    if any(not isinstance(raw, str) for raw in declared_dates):
        raise ExportError("UNIVERSE_MALFORMED")
    if any(_parse_date(raw, "UNIVERSE_MALFORMED") != trading_date for raw in declared_dates):
        raise ExportError("TRADING_DATE_MISMATCH")
    requested = document["canonical_instrument_ids"]
    if not isinstance(requested, list) or not 1 <= len(requested) <= MAX_INSTRUMENTS:
        raise ExportError("UNIVERSE_MALFORMED")
    normalized = tuple(_validate_canonical_id(value) for value in requested)
    if len(normalized) != len(set(normalized)):
        raise ExportError("UNIVERSE_DUPLICATE")
    return normalized


def _positive_integral(raw: str, code: str) -> int:
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ExportError(code) from exc
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ExportError(code)
    integer = int(value)
    if integer > 2**63 - 1:
        raise ExportError(code)
    return integer


def _assert_unique_mappings(mappings: tuple[Any, ...], id_attribute: str) -> None:
    canonical: set[str] = set()
    broker_ids: set[str] = set()
    for mapping in mappings:
        instrument_id = mapping.instrument.canonical
        broker_id = str(getattr(mapping, id_attribute))
        if instrument_id in canonical or broker_id in broker_ids:
            raise ExportError("MAPPING_DUPLICATE")
        canonical.add(instrument_id)
        broker_ids.add(broker_id)


def _supported_mapping(mapping: Any, requested: str) -> None:
    instrument = mapping.instrument
    if instrument.canonical != requested:
        raise ExportError("MAPPING_AMBIGUOUS")
    if (
        instrument.exchange.upper() != "NSE"
        or instrument.segment is not ExchangeSegment.NSE_FNO
        or instrument.kind not in {InstrumentKind.FUTURE, InstrumentKind.OPTION}
    ):
        raise ExportError("UNSUPPORTED_INSTRUMENT")


def _find_one_raw(rows: list[dict[str, str]], key: str, value: str) -> dict[str, str]:
    matching = [row for row in rows if row.get(key, "").strip() == value]
    if not matching:
        raise ExportError("MAPPING_MISSING")
    if len(matching) != 1:
        raise ExportError("MAPPING_DUPLICATE")
    return matching[0]


def _build_records(
    dhan_artifact: InputArtifact,
    kotak_artifact: InputArtifact,
    trading_date: date,
    requested: tuple[str, ...],
    scratch_parent: Path,
) -> list[dict[str, Any]]:
    dhan_rows = _csv_rows(dhan_artifact, DhanInstrumentMaster.REQUIRED_COLUMNS)
    kotak_rows = _csv_rows(kotak_artifact, KotakInstrumentMaster.REQUIRED_COLUMNS)
    try:
        with tempfile.TemporaryDirectory(prefix=".routing-input-", dir=scratch_parent) as raw_dir:
            private_dir = Path(raw_dir)
            private_dir.chmod(0o700)
            dhan_copy = private_dir / "dhan.csv"
            kotak_copy = private_dir / "kotak.csv"
            for path, payload in (
                (dhan_copy, dhan_artifact.payload),
                (kotak_copy, kotak_artifact.payload),
            ):
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                )
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            dhan_mappings = tuple(
                DhanInstrumentMaster(dhan_copy, as_of_date=trading_date).mappings()
            )
            kotak_mappings = tuple(
                KotakInstrumentMaster(kotak_copy, as_of_date=trading_date).mappings()
            )
    except (OSError, ValueError, csv.Error, InvalidOperation) as exc:
        raise ExportError("MASTER_MALFORMED") from exc
    if not dhan_mappings or not kotak_mappings:
        raise ExportError("MASTER_MALFORMED")
    _assert_unique_mappings(dhan_mappings, "security_id")
    _assert_unique_mappings(kotak_mappings, "instrument_token")
    try:
        dhan_index = DhanInstrumentIndex(dhan_mappings, trading_date=trading_date)
        kotak_index = KotakInstrumentIndex(kotak_mappings, trading_date=trading_date)
    except ValueError as exc:
        raise ExportError("MAPPING_DUPLICATE") from exc

    records: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    for canonical_id in sorted(requested):
        try:
            dhan = dhan_index.by_instrument_id(canonical_id)
            kotak = kotak_index.by_instrument_id(canonical_id)
        except KeyError as exc:
            raise ExportError("MAPPING_MISSING") from exc
        _supported_mapping(dhan, canonical_id)
        _supported_mapping(kotak, canonical_id)
        if dhan.instrument != kotak.instrument:
            raise ExportError("MAPPING_AMBIGUOUS")

        dhan_row = _find_one_raw(dhan_rows, "SEM_SMST_SECURITY_ID", dhan.security_id)
        lot_size = _positive_integral(dhan_row.get("SEM_LOT_UNITS", ""), "LOT_INVALID")
        tick_size = _positive_integral(dhan_row.get("SEM_TICK_SIZE", ""), "TICK_INVALID")
        if dhan.lot_size != lot_size or dhan.tick_size_paise != Decimal(tick_size):
            raise ExportError("MASTER_MALFORMED")

        token = kotak.instrument_token.strip()
        segment = kotak.exchange_segment.strip()
        symbol = kotak.trading_symbol.strip()
        kotak_row = _find_one_raw(kotak_rows, "pSymbol", token)
        if (
            kotak_row.get("pTrdSymbol", "").strip() != symbol
            or not TOKEN_RE.fullmatch(token)
            or segment != "nse_fo"
            or not ROUTE_TEXT_RE.fullmatch(symbol)
        ):
            raise ExportError("ROUTE_INVALID")
        route = (segment, symbol)
        if token in seen_tokens or route in seen_routes:
            raise ExportError("ROUTE_DUPLICATE")
        seen_tokens.add(token)
        seen_routes.add(route)
        records.append(
            {
                "canonical_instrument_id": canonical_id,
                "exchange_segment": segment,
                "instrument_token": token,
                "lot_size": lot_size,
                "tick_size_paise": tick_size,
                "trading_symbol": symbol,
            }
        )

    _verify_input_unchanged(dhan_artifact)
    _verify_input_unchanged(kotak_artifact)
    return records


def _validate_output_parent(snapshot_path: Path, manifest_path: Path) -> Path:
    if not snapshot_path.is_absolute() or not manifest_path.is_absolute():
        raise ExportError("OUTPUT_PATH_INVALID")
    if (
        snapshot_path == manifest_path
        or snapshot_path.parent != manifest_path.parent
        or not OUTPUT_NAME_RE.fullmatch(snapshot_path.name)
        or not OUTPUT_NAME_RE.fullmatch(manifest_path.name)
    ):
        raise ExportError("OUTPUT_PATH_INVALID")
    parent = snapshot_path.parent
    try:
        parent_stat = parent.lstat()
    except OSError as exc:
        raise ExportError("OUTPUT_PARENT_UNSAFE") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
    ):
        raise ExportError("OUTPUT_PARENT_UNSAFE")
    try:
        if parent.resolve(strict=True) != parent:
            raise ExportError("OUTPUT_PARENT_UNSAFE")
    except OSError as exc:
        raise ExportError("OUTPUT_PARENT_UNSAFE") from exc
    return parent


def _existing_bytes(path: Path) -> bytes | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ExportError("OUTPUT_UNSAFE") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ExportError("OUTPUT_UNSAFE")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            ):
                raise ExportError("OUTPUT_UNSAFE")
            payload = handle.read(MAX_OUTPUT_BYTES + 1)
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError("OUTPUT_UNSAFE") from exc
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ExportError("OUTPUT_UNSAFE")
    return payload


def _validate_snapshot(document: Any, trading_date: str, record_count: int) -> None:
    required = {
        "records",
        "requested_universe_sha256",
        "schema_version",
        "sources",
        "trading_date",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    if document["schema_version"] != SCHEMA_VERSION or document["trading_date"] != trading_date:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    if not SHA256_RE.fullmatch(document["requested_universe_sha256"]):
        raise ExportError("OUTPUT_VERIFY_FAILED")
    records = document["records"]
    if not isinstance(records, list) or len(records) != record_count:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    if [record.get("canonical_instrument_id") for record in records] != sorted(
        record.get("canonical_instrument_id") for record in records
    ):
        raise ExportError("OUTPUT_VERIFY_FAILED")
    sources = document["sources"]
    if not isinstance(sources, list) or [source.get("broker") for source in sources] != ["dhan", "kotak"]:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    if any(set(source) != {"broker", "sha256"} or not SHA256_RE.fullmatch(source["sha256"]) for source in sources):
        raise ExportError("OUTPUT_VERIFY_FAILED")


def _validate_manifest(
    document: Any,
    trading_date: str,
    snapshot_name: str,
    snapshot_bytes: bytes,
    record_count: int,
    universe_sha256: str,
    sources: list[dict[str, str]],
) -> None:
    required = {
        "bytes",
        "exporter_version",
        "record_count",
        "requested_universe_sha256",
        "schema_version",
        "snapshot_file",
        "snapshot_sha256",
        "sources",
        "trading_date",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    expected = {
        "bytes": len(snapshot_bytes),
        "exporter_version": EXPORTER_VERSION,
        "record_count": record_count,
        "requested_universe_sha256": universe_sha256,
        "schema_version": SCHEMA_VERSION,
        "snapshot_file": snapshot_name,
        "snapshot_sha256": _sha256(snapshot_bytes),
        "sources": sources,
        "trading_date": trading_date,
    }
    if document != expected:
        raise ExportError("OUTPUT_VERIFY_FAILED")


def _write_temp(parent: Path, prefix: str, payload: bytes) -> tuple[int, Path]:
    if not payload or len(payload) > MAX_OUTPUT_BYTES:
        raise ExportError("OUTPUT_VERIFY_FAILED")
    descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=parent)
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w+b", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            if handle.read(MAX_OUTPUT_BYTES + 1) != payload:
                raise ExportError("OUTPUT_VERIFY_FAILED")
            metadata = os.fstat(handle.fileno())
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ExportError("OUTPUT_VERIFY_FAILED")
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return metadata.st_ino, path


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _install_pair(
    snapshot_path: Path,
    manifest_path: Path,
    snapshot_bytes: bytes,
    manifest_bytes: bytes,
) -> bool:
    existing_snapshot = _existing_bytes(snapshot_path)
    existing_manifest = _existing_bytes(manifest_path)
    if (existing_snapshot is None) != (existing_manifest is None):
        raise ExportError("OUTPUT_PARTIAL")
    if existing_snapshot is not None and existing_manifest is not None:
        if existing_snapshot == snapshot_bytes and existing_manifest == manifest_bytes:
            return True
        raise ExportError("OUTPUT_EXISTS_DIFFERENT")

    parent = snapshot_path.parent
    snapshot_inode, snapshot_temp = _write_temp(parent, ".routing-snapshot-", snapshot_bytes)
    _, manifest_temp = _write_temp(parent, ".routing-manifest-", manifest_bytes)
    snapshot_installed = False
    try:
        os.link(snapshot_temp, snapshot_path, follow_symlinks=False)
        snapshot_installed = True
        os.link(manifest_temp, manifest_path, follow_symlinks=False)
    except FileExistsError as exc:
        if snapshot_installed:
            try:
                if snapshot_path.lstat().st_ino == snapshot_inode:
                    snapshot_path.unlink()
            except OSError:
                pass
        _fsync_directory(parent)
        raise ExportError("OUTPUT_RACE") from exc
    except OSError as exc:
        if snapshot_installed:
            try:
                if snapshot_path.lstat().st_ino == snapshot_inode:
                    snapshot_path.unlink()
            except OSError:
                pass
        _fsync_directory(parent)
        raise ExportError("OUTPUT_WRITE_FAILED") from exc
    finally:
        snapshot_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
    _fsync_directory(parent)
    return False


def export_snapshot(
    *,
    dhan_master: Path,
    kotak_master: Path,
    universe: Path,
    snapshot: Path,
    manifest: Path,
    trading_date_text: str,
) -> ExportResult:
    trading_date = _parse_date(trading_date_text, "TRADING_DATE_INVALID")
    output_parent = _validate_output_parent(snapshot, manifest)

    dhan_artifact = _read_input(dhan_master, MAX_MASTER_BYTES)
    kotak_artifact = _read_input(kotak_master, MAX_MASTER_BYTES)
    universe_artifact = _read_input(universe, MAX_UNIVERSE_BYTES)
    requested = _load_universe(universe_artifact, trading_date)
    records = _build_records(
        dhan_artifact,
        kotak_artifact,
        trading_date,
        requested,
        output_parent,
    )
    _verify_input_unchanged(universe_artifact)

    sources = [
        {"broker": "dhan", "sha256": dhan_artifact.sha256},
        {"broker": "kotak", "sha256": kotak_artifact.sha256},
    ]
    snapshot_document = {
        "records": records,
        "requested_universe_sha256": universe_artifact.sha256,
        "schema_version": SCHEMA_VERSION,
        "sources": sources,
        "trading_date": trading_date.isoformat(),
    }
    snapshot_bytes = _canonical_json(snapshot_document)
    manifest_document = {
        "bytes": len(snapshot_bytes),
        "exporter_version": EXPORTER_VERSION,
        "record_count": len(records),
        "requested_universe_sha256": universe_artifact.sha256,
        "schema_version": SCHEMA_VERSION,
        "snapshot_file": snapshot.name,
        "snapshot_sha256": _sha256(snapshot_bytes),
        "sources": sources,
        "trading_date": trading_date.isoformat(),
    }
    manifest_bytes = _canonical_json(manifest_document)
    _validate_snapshot(_load_json(snapshot_bytes, "OUTPUT_VERIFY_FAILED"), trading_date_text, len(records))
    _validate_manifest(
        _load_json(manifest_bytes, "OUTPUT_VERIFY_FAILED"),
        trading_date_text,
        snapshot.name,
        snapshot_bytes,
        len(records),
        universe_artifact.sha256,
        sources,
    )
    already_present = _install_pair(snapshot, manifest, snapshot_bytes, manifest_bytes)
    return ExportResult(snapshot, manifest, _sha256(snapshot_bytes), len(records), already_present)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export an offline Shaurya routing snapshot")
    parser.add_argument("--dhan-master", required=True, type=Path)
    parser.add_argument("--kotak-master", required=True, type=Path)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--trading-date", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        result = export_snapshot(
            dhan_master=arguments.dhan_master,
            kotak_master=arguments.kotak_master,
            universe=arguments.universe,
            snapshot=arguments.snapshot,
            manifest=arguments.manifest,
            trading_date_text=arguments.trading_date,
        )
    except ExportError as exc:
        print(f"[ROUTING_EXPORT_REFUSED] code={exc.code}", file=sys.stderr)
        return 2
    state = "already-present" if result.already_present else "created"
    print(
        f"[ROUTING_EXPORT_OK] state={state} records={result.record_count} "
        f"snapshot_sha256={result.snapshot_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
