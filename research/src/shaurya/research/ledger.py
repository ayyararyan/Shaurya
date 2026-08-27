"""Locked, fsynced, hash-chained append-only JSONL evidence authority."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from shaurya.research.contracts import canonical_json, canonical_sha256, utc_iso_now


@dataclass(frozen=True, slots=True)
class LedgerEnvelope:
    sequence: int
    recorded_at: str
    event_id: str
    event_type: str
    event: Mapping[str, Any]
    previous_hash: str
    event_hash: str


def _event_payload(event: object) -> Mapping[str, Any]:
    if is_dataclass(event) and not isinstance(event, type):
        payload = asdict(event)
    elif isinstance(event, Mapping):
        payload = dict(event)
    else:
        raise TypeError("ledger events must be mappings or dataclass instances")
    # Prevalidate the entire JSON boundary before a batch can touch the ledger.
    json.loads(canonical_json(payload))
    return payload


def _identity(event_type: str, payload: Mapping[str, Any]) -> str:
    explicit = payload.get("event_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return f"event-{canonical_sha256({'event_type': event_type, 'event': payload})[:32]}"


def _decode(lines: Sequence[str], *, verify: bool) -> tuple[LedgerEnvelope, ...]:
    envelopes: list[LedgerEnvelope] = []
    previous = "0" * 64
    event_ids: set[str] = set()
    for expected_sequence, line in enumerate(lines, start=1):
        if not line:
            raise ValueError("ledger contains a blank record")
        try:
            raw = json.loads(line)
            envelope = LedgerEnvelope(**raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("ledger contains an invalid record") from exc
        if envelope.event_id in event_ids:
            raise ValueError("ledger contains a duplicate event ID")
        event_ids.add(envelope.event_id)
        if verify:
            if envelope.sequence != expected_sequence or envelope.previous_hash != previous:
                raise ValueError("ledger sequence/hash chain is invalid")
            core = {
                "sequence": envelope.sequence,
                "recorded_at": envelope.recorded_at,
                "event_id": envelope.event_id,
                "event_type": envelope.event_type,
                "event": envelope.event,
                "previous_hash": envelope.previous_hash,
            }
            if canonical_sha256(core) != envelope.event_hash:
                raise ValueError("ledger event content has been modified")
        envelopes.append(envelope)
        previous = envelope.event_hash
    return tuple(envelopes)


class EvidenceLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, *, verify: bool = True) -> tuple[LedgerEnvelope, ...]:
        if not self.path.exists():
            return ()
        descriptor = os.open(self.path, os.O_RDWR)
        with os.fdopen(descriptor, "r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                self._recover_pending_locked(handle)
                handle.seek(0)
                return _decode(handle.read().decode().splitlines(), verify=verify)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _recover_pending_locked(self, handle: Any) -> None:
        """Resolve a durable append journal while holding the ledger's exclusive lock.

        A complete suffix means the append reached durable storage and only journal cleanup was
        interrupted.  A strict prefix means the process died mid-write, so the partial suffix is
        rolled back to the last verified record before any reader can observe it.
        """

        journal = self.path.with_suffix(self.path.suffix + ".txn")
        if not journal.exists():
            return
        try:
            pending = json.loads(journal.read_text(encoding="utf-8"))
            start = int(pending["start_offset"])
            encoded_pending = bytes.fromhex(str(pending["encoded_hex"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("ledger transaction journal is corrupt") from exc
        if canonical_sha256(encoded_pending.hex()) != pending.get("encoded_sha256"):
            raise ValueError("ledger transaction journal is corrupt")
        handle.seek(0, os.SEEK_END)
        length = handle.tell()
        if start < 0 or start > length:
            raise ValueError("ledger transaction journal has an invalid offset")
        handle.seek(start)
        suffix = handle.read()
        if suffix != encoded_pending:
            if not encoded_pending.startswith(suffix):
                raise ValueError("ledger bytes conflict with the pending transaction")
            handle.seek(start)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        journal.unlink()
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def append(self, event_type: str, event: object) -> LedgerEnvelope:
        return self.append_many(((event_type, event),))[0]

    def append_many(self, events: Iterable[tuple[str, object]]) -> tuple[LedgerEnvelope, ...]:
        prepared: list[tuple[str, Mapping[str, Any], str]] = []
        for event_type, event in events:
            if not event_type:
                raise ValueError("event_type is required")
            payload = _event_payload(event)
            prepared.append((event_type, payload, _identity(event_type, payload)))
        if not prepared:
            return ()
        proposed: dict[str, tuple[str, Mapping[str, Any]]] = {}
        for event_type, payload, event_id in prepared:
            prior_proposed = proposed.get(event_id)
            if prior_proposed is not None and (
                prior_proposed[0] != event_type
                or canonical_json(prior_proposed[1]) != canonical_json(payload)
            ):
                raise ValueError("batch contains a conflicting duplicate event ID")
            proposed[event_id] = (event_type, payload)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            journal = self.path.with_suffix(self.path.suffix + ".txn")
            self._recover_pending_locked(handle)
            handle.seek(0)
            existing = _decode(handle.read().decode().splitlines(), verify=True)
            by_id = {item.event_id: item for item in existing}
            returned: list[LedgerEnvelope] = []
            additions: list[LedgerEnvelope] = []
            previous_hash = existing[-1].event_hash if existing else "0" * 64
            next_sequence = len(existing) + 1
            for event_type, payload, event_id in prepared:
                existing_envelope = by_id.get(event_id)
                if existing_envelope is not None:
                    if (
                        existing_envelope.event_type != event_type
                        or canonical_json(existing_envelope.event) != canonical_json(payload)
                    ):
                        raise ValueError("event ID conflicts with existing ledger evidence")
                    returned.append(existing_envelope)
                    continue
                recorded_at = utc_iso_now()
                core = {
                    "sequence": next_sequence,
                    "recorded_at": recorded_at,
                    "event_id": event_id,
                    "event_type": event_type,
                    "event": payload,
                    "previous_hash": previous_hash,
                }
                envelope = LedgerEnvelope(
                    sequence=next_sequence,
                    recorded_at=recorded_at,
                    event_id=event_id,
                    event_type=event_type,
                    event=payload,
                    previous_hash=previous_hash,
                    event_hash=canonical_sha256(core),
                )
                additions.append(envelope)
                returned.append(envelope)
                by_id[event_id] = envelope
                previous_hash = envelope.event_hash
                next_sequence += 1
            if additions:
                encoded = "".join(
                    canonical_json(asdict(item)) + "\n" for item in additions
                ).encode()
                handle.seek(0, os.SEEK_END)
                start_offset = handle.tell()
                _atomic_create_once(
                    journal,
                    (
                        canonical_json(
                            {
                                "start_offset": start_offset,
                                "encoded_hex": encoded.hex(),
                                "encoded_sha256": canonical_sha256(encoded.hex()),
                            }
                        )
                        + "\n"
                    ).encode(),
                )
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(0)
                _decode(handle.read().decode().splitlines(), verify=True)
                journal.unlink()
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return tuple(returned)

    def events(self, *, event_type: str | None = None) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            envelope.event
            for envelope in self.read()
            if event_type is None or envelope.event_type == event_type
        )


def _atomic_create_once(path: Path, encoded: bytes) -> None:
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError("content-addressed artifact conflicts with existing content")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise ValueError(
                    "content-addressed artifact conflicts with existing content"
                ) from None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def materialize_snapshot(ledger: EvidenceLedger, directory: Path, *, parquet: bool = False) -> Path:
    """Create a verified content-addressed snapshot and manifest."""

    rows = [asdict(envelope) for envelope in ledger.read()]
    digest = canonical_sha256(rows)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if parquet:
        target = directory / f"alpha-evidence-ledger-{digest}.parquet"
        # The canonical writer is deterministic across environments and produces one required
        # BYTE_ARRAY row per envelope, so retry verification never depends on an optional engine.
        _atomic_create_once(target, _canonical_event_parquet(rows))
    else:
        target = directory / f"alpha-evidence-ledger-{digest}.json"
        _atomic_create_once(
            target,
            (canonical_json({"ledger_sha256": digest, "rows": rows}) + "\n").encode(),
        )
    manifest = {
        "artifact": target.name,
        "format": target.suffix.removeprefix("."),
        "ledger_sha256": digest,
        "rows": len(rows),
        "artifact_sha256": _sha256_path(target),
    }
    _atomic_create_once(
        target.with_suffix(target.suffix + ".manifest.json"),
        (canonical_json(manifest) + "\n").encode(),
    )
    verify_snapshot(target, ledger.read())
    return target


def verify_snapshot(path: Path, envelopes: Sequence[LedgerEnvelope]) -> None:
    """Recompute a snapshot and manifest exactly; existence alone is not evidence."""

    rows = [asdict(envelope) for envelope in envelopes]
    digest = canonical_sha256(rows)
    suffix = path.suffix.removeprefix(".")
    if suffix not in {"json", "parquet"}:
        raise ValueError("published snapshot format is unsupported")
    expected_name = f"alpha-evidence-ledger-{digest}.{suffix}"
    if path.name != expected_name:
        raise ValueError("published snapshot name is not bound to its ledger content")
    expected_artifact = (
        _canonical_event_parquet(rows)
        if suffix == "parquet"
        else (canonical_json({"ledger_sha256": digest, "rows": rows}) + "\n").encode()
    )
    if not path.is_file() or path.read_bytes() != expected_artifact:
        raise ValueError("published snapshot content or artifact hash is invalid")
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    expected_manifest = {
        "artifact": path.name,
        "format": suffix,
        "ledger_sha256": digest,
        "rows": len(rows),
        "artifact_sha256": _sha256_path(path),
    }
    expected_manifest_bytes = (canonical_json(expected_manifest) + "\n").encode()
    if not manifest_path.is_file() or manifest_path.read_bytes() != expected_manifest_bytes:
        raise ValueError("published snapshot manifest is invalid")


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def _compact_binary(value: str) -> bytes:
    encoded = value.encode()
    return _varint(len(encoded)) + encoded


def _compact_field(field_id: int, previous: int, compact_type: int, payload: bytes) -> bytes:
    delta = field_id - previous
    if 0 < delta <= 15:
        return bytes([(delta << 4) | compact_type]) + payload
    zigzag = (field_id << 1) ^ (field_id >> 15)
    return bytes([compact_type]) + _varint(zigzag) + payload


def _compact_list(compact_type: int, values: Sequence[bytes]) -> bytes:
    size = len(values)
    header = (
        bytes([(size << 4) | compact_type])
        if size < 15
        else bytes([0xF0 | compact_type]) + _varint(size)
    )
    return header + b"".join(values)


def _compact_integer(value: int) -> bytes:
    return _varint((value << 1) ^ (value >> 63))


def _canonical_event_parquet(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Build a standards-readable one-column Parquet snapshot of canonical ledger events."""

    encoded_rows = tuple(canonical_json(row).encode() for row in rows)
    page_body = b"".join(len(value).to_bytes(4, "little") + value for value in encoded_rows)
    data_page = b"".join(
        (
            _compact_field(1, 0, 5, _compact_integer(len(encoded_rows))),
            _compact_field(2, 1, 5, _compact_integer(0)),
            _compact_field(3, 2, 5, _compact_integer(3)),
            _compact_field(4, 3, 5, _compact_integer(3)),
            b"\x00",
        )
    )
    page_header = b"".join(
        (
            _compact_field(1, 0, 5, _compact_integer(0)),
            _compact_field(2, 1, 5, _compact_integer(len(page_body))),
            _compact_field(3, 2, 5, _compact_integer(len(page_body))),
            _compact_field(5, 3, 12, data_page),
            b"\x00",
        )
    )
    page = page_header + page_body
    root_schema = b"".join(
        (
            _compact_field(4, 0, 8, _compact_binary("shaurya_ledger")),
            _compact_field(5, 4, 5, _compact_integer(1)),
            b"\x00",
        )
    )
    event_schema = b"".join(
        (
            _compact_field(1, 0, 5, _compact_integer(6)),
            _compact_field(3, 1, 5, _compact_integer(0)),
            _compact_field(4, 3, 8, _compact_binary("event_json")),
            b"\x00",
        )
    )

    def key_value(key: str, value: str) -> bytes:
        return b"".join(
            (
                _compact_field(1, 0, 8, _compact_binary(key)),
                _compact_field(2, 1, 8, _compact_binary(value)),
                b"\x00",
            )
        )

    metadata_values = (
        key_value("shaurya.ledger.sha256", canonical_sha256(rows)),
        key_value("shaurya.ledger.encoding", "canonical-json-per-row"),
    )
    column_metadata = b"".join(
        (
            _compact_field(1, 0, 5, _compact_integer(6)),
            _compact_field(
                2,
                1,
                9,
                _compact_list(5, (_compact_integer(0), _compact_integer(3))),
            ),
            _compact_field(3, 2, 9, _compact_list(8, (_compact_binary("event_json"),))),
            _compact_field(4, 3, 5, _compact_integer(0)),
            _compact_field(5, 4, 6, _compact_integer(len(encoded_rows))),
            _compact_field(6, 5, 6, _compact_integer(len(page))),
            _compact_field(7, 6, 6, _compact_integer(len(page))),
            _compact_field(9, 7, 6, _compact_integer(4)),
            b"\x00",
        )
    )
    column_chunk = b"".join(
        (
            _compact_field(2, 0, 6, _compact_integer(4)),
            _compact_field(3, 2, 12, column_metadata),
            b"\x00",
        )
    )
    row_group = b"".join(
        (
            _compact_field(1, 0, 9, _compact_list(12, (column_chunk,))),
            _compact_field(2, 1, 6, _compact_integer(len(page))),
            _compact_field(3, 2, 6, _compact_integer(len(encoded_rows))),
            _compact_field(6, 3, 6, _compact_integer(len(page))),
            b"\x00",
        )
    )
    footer = b"".join(
        (
            _compact_field(1, 0, 5, _compact_integer(1)),
            _compact_field(2, 1, 9, _compact_list(12, (root_schema, event_schema))),
            _compact_field(3, 2, 6, _compact_integer(len(encoded_rows))),
            _compact_field(4, 3, 9, _compact_list(12, (row_group,))),
            _compact_field(5, 4, 9, _compact_list(12, metadata_values)),
            _compact_field(6, 5, 8, _compact_binary("Shaurya dependency-free snapshot")),
            b"\x00",
        )
    )
    return b"PAR1" + page + footer + len(footer).to_bytes(4, "little") + b"PAR1"


def _sha256_path(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
