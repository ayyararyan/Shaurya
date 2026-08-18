"""DAT-07: daily broker-master refresh and same-day Dhan identity indexes."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import model_validator

from shaurya.contracts.base import ContractModel
from shaurya.contracts.instruments import DhanInstrumentMapping, DhanInstrumentMaster
from shaurya.contracts.timing import IST

DHAN_COMPACT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


class InstrumentMasterArtifact(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    broker: str
    as_of_date: date
    source_url: str
    data_file: str
    fetched_at: datetime
    sha256: str
    bytes: int
    retention: Literal["permanent"] = "permanent"

    @model_validator(mode="after")
    def _valid_artifact(self) -> Self:
        if not self.broker.strip() or not self.source_url.strip() or not self.data_file.strip():
            raise ValueError("instrument-master broker, source, and file are required")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("instrument-master sha256 is invalid")
        if self.bytes <= 0:
            raise ValueError("instrument-master artifact cannot be empty")
        return self


FetchBytes = Callable[[str], bytes]


def _fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed HTTPS URL
        return cast(bytes, response.read())


class DailyInstrumentMasterStore:
    """Fetch at most once per broker/trading date and retain every dated master forever."""

    def __init__(
        self,
        root: Path,
        *,
        broker: str,
        source_url: str,
        fetch: FetchBytes = _fetch_bytes,
    ) -> None:
        if not broker.strip():
            raise ValueError("broker is required")
        self.root = root
        self.broker = broker.strip().lower()
        self.source_url = source_url
        self._fetch = fetch

    def paths(self, as_of_date: date) -> tuple[Path, Path]:
        stem = f"{self.broker}_instrument_master_{as_of_date.isoformat()}"
        return self.root / f"{stem}.csv", self.root / f"{stem}.manifest.json"

    def refresh(self, as_of_date: date) -> InstrumentMasterArtifact:
        data_path, manifest_path = self.paths(as_of_date)
        if data_path.is_file() and manifest_path.is_file():
            artifact = InstrumentMasterArtifact.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            observed_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
            if artifact.sha256 != observed_hash or artifact.as_of_date != as_of_date:
                raise ValueError("cached instrument master failed manifest validation")
            return artifact
        if data_path.exists() or manifest_path.exists():
            raise ValueError("instrument master is partial; preserve and inspect before retry")
        payload = self._fetch(self.source_url)
        if not payload.strip():
            raise ValueError("instrument-master download was empty")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fetched_at = datetime.now(IST)
        artifact = InstrumentMasterArtifact(
            broker=self.broker,
            as_of_date=as_of_date,
            source_url=self.source_url,
            data_file=data_path.name,
            fetched_at=fetched_at,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
        )
        self._install_exclusive(data_path, payload)
        try:
            self._install_exclusive(
                manifest_path,
                (artifact.model_dump_json(indent=2) + "\n").encode(),
            )
        except BaseException:
            # Keep the dated data file: partial state is explicit and never overwritten.
            raise
        return artifact

    def _install_exclusive(self, target: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.root)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


class DhanDailyInstrumentMaster:
    def __init__(
        self,
        root: Path,
        *,
        fetch: FetchBytes = _fetch_bytes,
        source_url: str = DHAN_COMPACT_MASTER_URL,
    ) -> None:
        self.store = DailyInstrumentMasterStore(
            root,
            broker="dhan",
            source_url=source_url,
            fetch=fetch,
        )

    def refresh(self, as_of_date: date) -> DhanInstrumentMaster:
        self.store.refresh(as_of_date)
        data_path, _ = self.store.paths(as_of_date)
        master = DhanInstrumentMaster(data_path, as_of_date=as_of_date)
        if not next(master.mappings(), None):
            raise ValueError("dated Dhan instrument master contains no usable NSE mappings")
        return master


class DhanInstrumentIndex:
    """Bidirectional same-day lookup over canonical CON-05 Dhan mappings."""

    def __init__(
        self, mappings: Iterable[DhanInstrumentMapping], *, trading_date: date
    ) -> None:
        values = tuple(mappings)
        if not values:
            raise ValueError("instrument mapping index cannot be empty")
        if any(mapping.as_of_date != trading_date for mapping in values):
            raise ValueError("instrument mapping is stale for the requested trading date")
        self.trading_date = trading_date
        self._by_security_id: dict[str, DhanInstrumentMapping] = {}
        self._by_instrument_id: dict[str, DhanInstrumentMapping] = {}
        for mapping in values:
            canonical = mapping.instrument.canonical
            if mapping.security_id in self._by_security_id:
                raise ValueError(f"duplicate Dhan security_id {mapping.security_id}")
            if canonical in self._by_instrument_id:
                raise ValueError(f"duplicate canonical instrument_id {canonical}")
            self._by_security_id[mapping.security_id] = mapping
            self._by_instrument_id[canonical] = mapping

    def by_security_id(self, security_id: str) -> DhanInstrumentMapping:
        try:
            return self._by_security_id[str(security_id)]
        except KeyError as exc:
            raise KeyError(f"unmapped Dhan security_id {security_id}") from exc

    def by_instrument_id(self, instrument_id: str) -> DhanInstrumentMapping:
        try:
            return self._by_instrument_id[instrument_id]
        except KeyError as exc:
            raise KeyError(f"unmapped canonical instrument_id {instrument_id}") from exc
