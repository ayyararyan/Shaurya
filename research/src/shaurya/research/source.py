"""Verified canonical DAT inputs and deterministic source-bound research derivation."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from math import log, sqrt
from pathlib import Path
from types import MappingProxyType

from shaurya.contracts.data import DataChannel, DatasetHandle, DatasetStatus, StorageFormat
from shaurya.contracts.tape import TapeRow
from shaurya.data import (
    DataAccess,
    DataCatalog,
    TapeIntegrityError,
    data_channel_for_row,
)
from shaurya.data.high_frequency import TimedValue

from shaurya.analytics.depth_thinning_analysis import BookState
from shaurya.research.construction import construct_v2_feature, construct_v2_target
from shaurya.research.contracts import (
    EvaluationRow,
    FeatureObservation,
    TargetObservation,
    canonical_sha256,
)
from shaurya.research.features import build_feature_observation, feature_run_hash
from shaurya.research.registry import FrozenRegistry, declared_feature_ids
from shaurya.research.targets import build_target_observation
from shaurya.signals.ccz_ofi import CczFlowSeries

_DATASET_FACTORY_TOKEN = object()
_SOURCE_FACTORY_TOKEN = object()
_BREAK_FLAGS = frozenset(
    {
        "sequence_gap",
        "sequence_regression",
        "duplicate_sequence",
        "connection_gap",
        "reconnected",
        "heartbeat_timeout",
    }
)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedResearchSource:
    dataset_id: str
    trading_date: date
    catalog_path: Path
    storage_format: str
    dataset_digest: str
    canonical_row_digest: str
    logical_run_id: str
    rows: int
    bytes: int
    coverage_start: str
    coverage_end: str
    authorized_instrument_ids: tuple[str, ...]
    authorized_channels: tuple[str, ...]
    source_identity_hash: str

    def __init__(
        self,
        dataset_id: str,
        trading_date: date,
        catalog_path: Path,
        storage_format: str,
        dataset_digest: str,
        canonical_row_digest: str,
        logical_run_id: str,
        rows: int,
        bytes: int,
        coverage_start: str,
        coverage_end: str,
        authorized_instrument_ids: tuple[str, ...],
        authorized_channels: tuple[str, ...],
        source_identity_hash: str,
        *,
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _SOURCE_FACTORY_TOKEN:
            raise TypeError("research sources require exact canonical DAT catalog verification")
        for name, value in locals().items():
            if name not in {"self", "_factory_token"}:
                object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True, init=False)
class DerivedResearchDataset:
    """Rows derived only by replaying the sources named in the source manifest."""

    sources: tuple[VerifiedResearchSource, ...]
    feature_registry_version: str
    feature_registry_fingerprint: str
    target_registry_version: str
    target_registry_fingerprint: str
    features: tuple[FeatureObservation, ...]
    targets: tuple[TargetObservation, ...]
    rows: tuple[EvaluationRow, ...]
    source_manifest_hash: str
    derivation_hash: str

    def __init__(
        self,
        sources: tuple[VerifiedResearchSource, ...],
        feature_registry_version: str,
        feature_registry_fingerprint: str,
        target_registry_version: str,
        target_registry_fingerprint: str,
        features: tuple[FeatureObservation, ...],
        targets: tuple[TargetObservation, ...],
        rows: tuple[EvaluationRow, ...],
        source_manifest_hash: str,
        derivation_hash: str,
        *,
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _DATASET_FACTORY_TOKEN:
            raise TypeError("research datasets can only be created by verified DAT derivation")
        for name, value in (
            ("sources", sources),
            ("features", features),
            ("targets", targets),
            ("rows", rows),
        ):
            if not isinstance(value, tuple):
                raise TypeError(f"research dataset {name} must be a frozen tuple")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "feature_registry_version", feature_registry_version)
        object.__setattr__(self, "feature_registry_fingerprint", feature_registry_fingerprint)
        object.__setattr__(self, "target_registry_version", target_registry_version)
        object.__setattr__(self, "target_registry_fingerprint", target_registry_fingerprint)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "source_manifest_hash", source_manifest_hash)
        object.__setattr__(self, "derivation_hash", derivation_hash)
        self._validate_exact_derivation()

    def _validate_exact_derivation(self) -> None:
        if not self.sources or not self.features or not self.targets or not self.rows:
            raise ValueError("research derivation cannot be empty")
        if (
            len(self.feature_registry_fingerprint) != 64
            or len(self.target_registry_fingerprint) != 64
        ):
            raise ValueError("research derivation registry fingerprints are invalid")
        if self.sources != tuple(
            sorted(self.sources, key=lambda item: (item.trading_date, item.dataset_id))
        ) or len({item.dataset_id for item in self.sources}) != len(self.sources):
            raise ValueError("research derivation sources are not canonical and unique")
        source_ids = {(item.dataset_id, item.source_identity_hash) for item in self.sources}
        if self.source_manifest_hash != canonical_sha256([asdict(item) for item in self.sources]):
            raise ValueError("research derivation source manifest hash is invalid")
        features_by_id = {item.observation_id: item for item in self.features}
        if len(features_by_id) != len(self.features):
            raise ValueError("research derivation contains duplicate feature observations")
        target_keys = [(item.observation_id, item.target_id) for item in self.targets]
        targets_by_key = dict(zip(target_keys, self.targets, strict=True))
        if len(targets_by_key) != len(self.targets):
            raise ValueError("research derivation contains duplicate target observations")
        row_keys: list[tuple[str, str]] = []
        for row in self.rows:
            identity = (row.feature.source_dataset_id, row.feature.source_sha256)
            if identity not in source_ids:
                raise ValueError("derived row is not bound to a verified source")
            key = (row.feature.observation_id, row.target.target_id)
            if features_by_id.get(key[0]) != row.feature or targets_by_key.get(key) != row.target:
                raise ValueError("research derivation row does not exactly join frozen artifacts")
            row_keys.append(key)
        if len(row_keys) != len(set(row_keys)) or set(row_keys) != set(target_keys):
            raise ValueError("research derivation rows do not exactly cover frozen targets")
        if {item.registry_version for item in self.features} != {self.feature_registry_version} or {
            item.registry_version for item in self.targets
        } != {self.target_registry_version}:
            raise ValueError("research derivation registry versions are inconsistent")
        derivation_payload = {
            "source_manifest_hash": self.source_manifest_hash,
            "feature_registry": (
                self.feature_registry_version,
                self.feature_registry_fingerprint,
            ),
            "target_registry": (
                self.target_registry_version,
                self.target_registry_fingerprint,
            ),
            "feature_run_hash": feature_run_hash(self.features),
            "target_hashes": [item.target_run_hash for item in self.targets],
            "join_count": len(self.rows),
        }
        if self.derivation_hash != canonical_sha256(derivation_payload):
            raise ValueError("research derivation hash is invalid")


def derivation_hash_for_sources(
    dataset: DerivedResearchDataset, sources: tuple[VerifiedResearchSource, ...]
) -> str:
    """Rebuild the exact derivation identity for a chronological source prefix."""

    if sources != dataset.sources[: len(sources)]:
        raise ValueError("historical sources must be an exact chronological prefix")
    source_ids = {item.dataset_id for item in sources}
    features = tuple(item for item in dataset.features if item.source_dataset_id in source_ids)
    targets = tuple(item for item in dataset.targets if item.source_dataset_id in source_ids)
    rows = tuple(item for item in dataset.rows if item.feature.source_dataset_id in source_ids)
    return canonical_sha256(
        {
            "source_manifest_hash": canonical_sha256([asdict(item) for item in sources]),
            "feature_registry": (
                dataset.feature_registry_version,
                dataset.feature_registry_fingerprint,
            ),
            "target_registry": (
                dataset.target_registry_version,
                dataset.target_registry_fingerprint,
            ),
            "feature_run_hash": feature_run_hash(features),
            "target_hashes": [item.target_run_hash for item in targets],
            "join_count": len(rows),
        }
    )


def discover_completed_sources(
    catalog: DataCatalog,
    *,
    through: date,
    include_dates: frozenset[date] | None = None,
) -> tuple[VerifiedResearchSource, ...]:
    """Discover and fully verify completed canonical datasets in deterministic order.

    The catalogue, not filesystem naming, is the source authority.  All completed handles up to
    ``through`` are considered; callers may restrict to an exact date set when constructing a
    prospective prefix.  Duplicate dataset identities are impossible by catalogue contract.
    """

    handles = [
        handle
        for handle in catalog.handles().values()
        if handle.status is DatasetStatus.COMPLETED
        and handle.trading_date <= through
        and (include_dates is None or handle.trading_date in include_dates)
    ]
    handles.sort(key=lambda item: (item.trading_date, item.dataset_id))
    if not handles:
        raise ValueError("no completed canonical DAT sources match the requested research prefix")
    return tuple(
        verify_completed_source(handle, through=through, catalog=catalog) for handle in handles
    )


def verify_completed_source(
    handle: DatasetHandle,
    *,
    catalog: DataCatalog,
    through: date | None = None,
) -> VerifiedResearchSource:
    """Fully stream, hash, and index-verify one completed DAT handle."""

    if handle.status is not DatasetStatus.COMPLETED:
        raise ValueError("research requires a completed DAT dataset handle")
    canonical = catalog.get(handle.dataset_id)
    if canonical != handle:
        raise ValueError("source handle is not the exact completed DAT catalog authority")
    if through is not None and handle.trading_date > through:
        raise ValueError("DAT source is later than the research cutoff")
    if handle.completed_at is None or handle.coverage_start is None or handle.coverage_end is None:
        raise ValueError("completed DAT source lacks terminal coverage metadata")
    access = DataAccess(catalog)
    validation = access.validate(handle)
    row_start = str(validation["coverage_start"])
    row_end = str(validation["coverage_end"])
    physical_digest = handle.dataset_digest or handle.tape_sha256
    if not physical_digest:
        raise ValueError("completed DAT source lacks a physical integrity digest")
    row_digest = str(validation["canonical_row_digest"])
    logical_run_id = handle.row_run_id or handle.dataset_id
    identity = {
        "dataset_id": handle.dataset_id,
        "trading_date": handle.trading_date.isoformat(),
        "storage_format": str(handle.storage_format or StorageFormat.LEGACY_JSONL),
        "dataset_digest": physical_digest,
        "canonical_row_digest": row_digest,
        "logical_run_id": logical_run_id,
        "rows": handle.rows,
        "bytes": handle.bytes,
        "coverage_start": row_start,
        "coverage_end": row_end,
        "authorized_instrument_ids": handle.instrument_ids,
        "authorized_channels": tuple(str(item) for item in handle.channels),
    }
    return VerifiedResearchSource(
        handle.dataset_id,
        handle.trading_date,
        catalog.path,
        str(handle.storage_format or StorageFormat.LEGACY_JSONL),
        physical_digest,
        row_digest,
        logical_run_id,
        handle.rows,
        handle.bytes,
        row_start,
        row_end,
        handle.instrument_ids,
        tuple(str(item) for item in handle.channels),
        canonical_sha256(identity),
        _factory_token=_SOURCE_FACTORY_TOKEN,
    )


def _ts_ns(row: TapeRow) -> int:
    return round(row.receive_ts.timestamp() * 1_000_000_000)


def _mid(row: TapeRow) -> float | None:
    if row.best_bid is None or row.best_ask is None or row.best_ask < row.best_bid:
        return None
    return (row.best_bid + row.best_ask) / 2


def _depth(row: TapeRow, levels: int) -> tuple[int, int]:
    return (
        sum(level.quantity for level in row.bids[:levels]),
        sum(level.quantity for level in row.asks[:levels]),
    )


@dataclass(frozen=True, slots=True)
class _AnchorPoint:
    stamp_ns: int
    midpoint: float
    observation_id: str
    instrument_id: str
    channel: str
    connection_id: str
    connection_epoch: int
    segment: int


def _partition(row: TapeRow) -> tuple[str, str, str, int]:
    return (row.instrument_id, row.event_type, row.connection_id, row.connection_epoch)


def _book_state(row: TapeRow) -> BookState:
    return BookState(
        row.event_type,
        _ts_ns(row),
        row.receive_sequence,
        row.connection_epoch,
        tuple((item.price, item.quantity, item.orders) for item in row.bids),
        tuple((item.price, item.quantity, item.orders) for item in row.asks),
        1,
        tuple(str(item) for item in row.quality_flags),
    )


def _declared_ofi_coordinates(declared: tuple[str, ...]) -> tuple[tuple[int, float], ...]:
    values: set[tuple[int, float]] = set()
    for feature_id in declared:
        if not feature_id.startswith("ofi.cumulative.depth="):
            continue
        parts = feature_id.split(".")
        values.add(
            (
                int(parts[2].split("=", 1)[1]),
                float(parts[3].split("=", 1)[1].removesuffix("s")),
            )
        )
    return tuple(sorted(values))


def _source_bytes_are_unchanged(source: VerifiedResearchSource) -> None:
    catalog = DataCatalog(source.catalog_path)
    handle = catalog.get(source.dataset_id)
    report = DataAccess(catalog).validate(handle)
    if (
        (handle.dataset_digest or handle.tape_sha256) != source.dataset_digest
        or report["canonical_row_digest"] != source.canonical_row_digest
        or report["rows"] != source.rows
        or report["bytes"] != source.bytes
    ):
        raise TapeIntegrityError("canonical DAT source changed during research derivation")


def _derive_source_features(
    source: VerifiedResearchSource, registry: FrozenRegistry
) -> tuple[tuple[FeatureObservation, ...], tuple[_AnchorPoint, ...]]:
    declared = declared_feature_ids(registry)
    coordinates = _declared_ofi_coordinates(declared)
    level_counts = tuple(sorted({level for level, _ in coordinates})) or (1,)
    _source_bytes_are_unchanged(source)
    catalog = DataCatalog(source.catalog_path)
    handle = catalog.get(source.dataset_id)
    tape_rows = tuple(DataAccess(catalog).rows(handle))
    if len(tape_rows) != source.rows:
        raise TapeIntegrityError("canonical DAT row count changed during derivation")
    required_depth = max(level_counts)
    if any(len(row.bids) < required_depth or len(row.asks) < required_depth for row in tape_rows):
        raise TapeIntegrityError(
            "canonical DAT source lacks genuine depth for the registered OFI construction"
        )
    authorized_channels = {DataChannel(item) for item in source.authorized_channels}
    if any(
        row.run_id != source.logical_run_id
        or row.instrument_id not in source.authorized_instrument_ids
        or data_channel_for_row(row) not in authorized_channels
        for row in tape_rows
    ):
        raise TapeIntegrityError("canonical DAT replay no longer matches its source authority")
    raw_tick_sizes = registry.payload.get("instrument_tick_sizes")
    if not isinstance(raw_tick_sizes, Mapping) or not raw_tick_sizes:
        raise ValueError("feature registry requires canonical instrument tick-size metadata")
    tick_by_instrument: dict[str, float | None] = {}
    for instrument_id in source.authorized_instrument_ids:
        matches = [
            float(value)
            for applicability, value in raw_tick_sizes.items()
            if _instrument_is_applicable(instrument_id, (applicability,))
        ]
        if len(matches) == 1 and matches[0] > 0:
            tick_by_instrument[instrument_id] = matches[0]
        elif registry.version == "microstructure_features_v2" and ":option:" in instrument_id:
            # v2 does not currently declare an options tick authority.  Do not invent one: book
            # constructions that do not require a tick remain usable and tick metadata stays absent.
            tick_by_instrument[instrument_id] = None
        else:
            raise ValueError(
                f"feature registry lacks one exact tick-size authority for {instrument_id}"
            )
    prior_stamp: int | None = None
    prior_sequence: int | None = None
    segment_by_partition: dict[tuple[str, str, str, int], int] = defaultdict(int)
    grouped: dict[tuple[str, str, str, int, int], list[TapeRow]] = defaultdict(list)
    row_segment: dict[int, int] = {}
    for row in tape_rows:
        stamp = _ts_ns(row)
        if prior_stamp is not None and stamp < prior_stamp:
            raise TapeIntegrityError("canonical DAT receive timestamps regress")
        if prior_sequence is not None and row.receive_sequence <= prior_sequence:
            raise TapeIntegrityError("canonical DAT receive sequence is not strictly increasing")
        prior_stamp = stamp
        prior_sequence = row.receive_sequence
        partition_key = _partition(row)
        if set(map(str, row.quality_flags)) & _BREAK_FLAGS and grouped:
            segment_by_partition[partition_key] += 1
        segment = segment_by_partition[partition_key]
        row_segment[row.receive_sequence] = segment
        grouped[(*partition_key, segment)].append(row)
    state_series: dict[tuple[str, str, str, int, int], tuple[CczFlowSeries, dict[int, int]]] = {}
    for series_key, group in grouped.items():
        states = tuple(_book_state(row) for row in group)
        stamps = tuple(state.receive_ts_ns for state in states)
        if stamps != tuple(sorted(stamps)):
            raise TapeIntegrityError("book partition timestamps regress")
        state_series[series_key] = (
            CczFlowSeries.from_states(states, level_counts=level_counts),
            {row.receive_sequence: index for index, row in enumerate(group)},
        )
    trailing: dict[tuple[str, str, str, int, int], deque[tuple[int, float]]] = defaultdict(deque)
    first_ts: dict[tuple[str, str, str, int, int], int] = {}
    control_state: dict[tuple[str, str, str, int, int], float] = {}
    features: list[FeatureObservation] = []
    anchors: list[_AnchorPoint] = []
    for row in tape_rows:
        mid = _mid(row)
        if mid is None:
            continue
        stamp = _ts_ns(row)
        base = _partition(row)
        segment = row_segment[row.receive_sequence]
        series_key = (*base, segment)
        first_ts.setdefault(series_key, stamp)
        values_history = trailing[series_key]
        cutoff = stamp - 1_000_000_000_000
        while values_history and values_history[0][0] < cutoff:
            values_history.popleft()
        series, positions = state_series[series_key]
        right = positions[row.receive_sequence]
        values: dict[str, float | None] = {}
        for feature_id in declared:
            if feature_id.startswith("ofi.cumulative.depth="):
                parts = feature_id.split(".")
                level = int(parts[2].split("=", 1)[1])
                window = float(parts[3].split("=", 1)[1].removesuffix("s"))
                left = series.locate(stamp - round(window * 1_000_000_000), right)
                evaluated = series.window(left, right, levels=level, window_seconds=window)
                values[feature_id] = (
                    None
                    if evaluated is None
                    else (evaluated.best_level if level == 1 else evaluated.simple_average)
                )
            elif feature_id == "book.spread_ticks":
                assert row.best_bid is not None and row.best_ask is not None
                tick = tick_by_instrument.get(row.instrument_id)
                if tick is None or tick <= 0:
                    raise TapeIntegrityError("source cannot establish an instrument tick size")
                values[feature_id] = float((row.best_ask - row.best_bid) / tick)
            elif feature_id == "book.depth_imbalance_l5":
                if len(row.bids) < 5 or len(row.asks) < 5:
                    values[feature_id] = None
                else:
                    bid, ask = _depth(row, 5)
                    values[feature_id] = (bid - ask) / (bid + ask) if bid + ask else None
            elif feature_id == "book.log1p_l1_depth":
                bid, ask = _depth(row, 1)
                values[feature_id] = log(1 + bid + ask) if bid + ask else None
            elif feature_id == "regime.trailing_volatility":
                past_mids = [value for _, value in values_history]
                returns = [
                    log(right_mid / left_mid)
                    for left_mid, right_mid in zip(past_mids, past_mids[1:], strict=False)
                ]
                if len(returns) < 2:
                    values[feature_id] = None
                else:
                    mean = sum(returns) / len(returns)
                    values[feature_id] = sqrt(
                        sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
                    )
            elif feature_id == "regime.trailing_activity":
                values[feature_id] = len(values_history) / 60.0
            elif feature_id == "regime.minutes_from_open":
                values[feature_id] = (stamp - first_ts[series_key]) / 60_000_000_000
            elif feature_id == "control.source_keyed_ar1_phi_0_8":
                # Target-blind negative control with market-like persistence. The innovation is
                # keyed only by immutable source/partition/time identity; reconnects and breaks
                # start a new AR(1) path because ``series_key`` includes both epoch and segment.
                innovation_hash = canonical_sha256(
                    {
                        "source": source.source_identity_hash,
                        "partition": series_key,
                        "stamp_ns": stamp,
                        "receive_sequence": row.receive_sequence,
                        "control": "source_keyed_ar1_phi_0_8",
                    }
                )
                innovation = 2.0 * (int(innovation_hash[:16], 16) / (2**64 - 1)) - 1.0
                previous = control_state.get(series_key, 0.0)
                control = 0.8 * previous + 0.6 * innovation
                control_state[series_key] = control
                values[feature_id] = control
            elif feature_id == "surface.front_skew_ew_innovation":
                # This canonical construction is missing unless an options-surface tape is
                # present; missingness is explicit and interactions propagate it.
                values[feature_id] = None
            elif feature_id.startswith("interaction."):
                # Declared interactions are filled below after their causal inputs exist.
                values[feature_id] = None
            elif registry.version == "microstructure_features_v2":
                history = tuple(
                    TimedValue(
                        datetime.fromtimestamp(history_stamp / 1_000_000_000, tz=UTC),
                        row.connection_epoch,
                        history_mid,
                    )
                    for history_stamp, history_mid in values_history
                ) + (TimedValue(row.receive_ts, row.connection_epoch, mid),)
                group_rows = grouped[series_key]
                context_left = right
                context_cutoff = row.receive_ts.timestamp() - 0.5
                while (
                    context_left > 0
                    and group_rows[context_left].receive_ts.timestamp() > context_cutoff
                ):
                    context_left -= 1
                context_left = max(0, context_left - 1)
                current_rows = tuple(group_rows[context_left : right + 1])
                result = construct_v2_feature(
                    feature_id,
                    row=row,
                    tick_size=float(tick_by_instrument.get(row.instrument_id) or 1.0),
                    partition_rows=current_rows,
                    midpoint_history=history,
                )
                # Missing cross-instrument context is explicit.  Never substitute an alternate
                # formula for a frozen semantic identity.
                values[feature_id] = result.value if result.handled else None
            else:
                raise ValueError(f"feature {feature_id} has no executable construction strategy")
        base_ofi = values.get("ofi.cumulative.depth=10.window=10s")
        spread = values.get("book.spread_ticks")
        depth_l1 = values.get("book.log1p_l1_depth")
        volatility = values.get("regime.trailing_volatility")
        if "interaction.ofi_w10_d10_x_spread" in values:
            values["interaction.ofi_w10_d10_x_spread"] = (
                None if base_ofi is None or spread is None else base_ofi * spread
            )
        if "interaction.ofi_w10_d10_x_inverse_l1_depth" in values:
            values["interaction.ofi_w10_d10_x_inverse_l1_depth"] = (
                None
                if base_ofi is None or depth_l1 is None or depth_l1 == 0
                else base_ofi / depth_l1
            )
        if "interaction.ofi_w10_d10_x_trailing_volatility" in values:
            values["interaction.ofi_w10_d10_x_trailing_volatility"] = (
                None if base_ofi is None or volatility is None else base_ofi * volatility
            )
        skew = values.get("surface.front_skew_ew_innovation")
        if "interaction.front_skew_innovation_x_ofi_w10_d10" in values:
            values["interaction.front_skew_innovation_x_ofi_w10_d10"] = (
                None if base_ofi is None or skew is None else base_ofi * skew
            )
        availability = {
            name: stamp if value is not None else None for name, value in values.items()
        }
        observation_id = (
            f"{source.dataset_id}:{row.instrument_id}:{row.event_type}:"
            f"{row.connection_id}:{row.connection_epoch}:{row.receive_sequence}"
        )
        assert row.best_bid is not None and row.best_ask is not None
        feature = build_feature_observation(
            observation_id=observation_id,
            session_date=source.trading_date,
            anchor_ts_ns=stamp,
            connection_epoch=row.connection_epoch,
            registry=registry,
            source_dataset_id=source.dataset_id,
            source_sha256=source.source_identity_hash,
            instrument_id=row.instrument_id,
            channel=row.event_type,
            connection_id=row.connection_id,
            break_segment=segment,
            reference_midpoint=mid,
            tick_size=tick_by_instrument[row.instrument_id],
            spread_price=(
                float(row.best_ask - row.best_bid)
                if tick_by_instrument[row.instrument_id] is not None
                else None
            ),
            values=MappingProxyType(values),
            availability=MappingProxyType(availability),
        )
        features.append(feature)
        anchors.append(
            _AnchorPoint(
                stamp,
                mid,
                observation_id,
                row.instrument_id,
                row.event_type,
                row.connection_id,
                row.connection_epoch,
                segment,
            )
        )
        values_history.append((stamp, mid))
    _source_bytes_are_unchanged(source)
    return tuple(features), tuple(anchors)


def _instrument_is_applicable(instrument_id: str, declared: tuple[object, ...]) -> bool:
    normalized = {str(item).upper() for item in declared}
    if instrument_id.upper() in normalized:
        return True
    parts = instrument_id.upper().split(":")
    tags = {instrument_id.upper()}
    if len(parts) >= 5:
        symbol = parts[2]
        kind = parts[3]
        tags.add(f"{symbol}_{'FUTURES' if kind == 'FUTURE' else kind + 'S'}")
    return bool(tags & normalized)


def _exact_endpoint(
    by_stamp: Mapping[int, list[_AnchorPoint]],
    expected_ns: int,
    tolerance_ns: int,
) -> _AnchorPoint | None:
    if tolerance_ns < 0:
        raise ValueError("target endpoint tolerance cannot be negative")
    candidates = [
        point
        for stamp, points in by_stamp.items()
        if abs(int(stamp) - expected_ns) <= tolerance_ns
        for point in points
    ]
    if not candidates:
        return None
    distances = [abs(item.stamp_ns - expected_ns) for item in candidates]
    nearest = min(distances)
    winners = [
        item for item, distance in zip(candidates, distances, strict=True) if distance == nearest
    ]
    return winners[0] if len(winners) == 1 else None


def derive_research_dataset(
    sources: tuple[VerifiedResearchSource, ...],
    *,
    feature_registry: FrozenRegistry,
    target_registry: FrozenRegistry,
) -> DerivedResearchDataset:
    """Replay exact DAT bytes into target-blind features and separately frozen targets."""

    if not isinstance(sources, tuple):
        raise TypeError("canonical sources must be supplied as a frozen tuple")
    ordered = tuple(sorted(sources, key=lambda item: (item.trading_date, item.dataset_id)))
    if not sources or ordered != sources:
        raise ValueError("verified sources must be non-empty, unique, and chronologically sorted")
    if len({item.dataset_id for item in sources}) != len(sources):
        raise ValueError("duplicate canonical source dataset")
    all_features: list[FeatureObservation] = []
    all_targets: list[TargetObservation] = []
    all_rows: list[EvaluationRow] = []
    targets_raw = target_registry.payload.get("targets")
    if not isinstance(targets_raw, tuple):
        raise TypeError("target registry was not deeply frozen")
    for source in sources:
        _source_bytes_are_unchanged(source)
        source_features, anchor_points = _derive_source_features(source, feature_registry)
        all_features.extend(source_features)
        features_by_id = {item.observation_id: item for item in source_features}
        grouped_points: dict[tuple[str, str, str, int, int], list[_AnchorPoint]] = defaultdict(list)
        for point in anchor_points:
            grouped_points[
                (
                    point.instrument_id,
                    point.channel,
                    point.connection_id,
                    point.connection_epoch,
                    point.segment,
                )
            ].append(point)
        for points in grouped_points.values():
            by_stamp: dict[int, list[_AnchorPoint]] = defaultdict(list)
            for point in points:
                by_stamp[point.stamp_ns].append(point)
            for anchor in points:
                for raw in targets_raw:
                    if not isinstance(raw, MappingProxyType):
                        raise TypeError("target definition is not deeply frozen")
                    instruments = raw.get("instruments")
                    if not isinstance(instruments, tuple) or not instruments:
                        raise ValueError("target definition requires instrument applicability")
                    if not _instrument_is_applicable(anchor.instrument_id, instruments):
                        continue
                    gap_ns = round(float(raw["causal_gap_seconds"]) * 1_000_000_000)
                    horizon_ns = round(float(raw["horizon_seconds"]) * 1_000_000_000)
                    tolerance_ns = round(
                        float(raw.get("endpoint_tolerance_seconds", 0)) * 1_000_000_000
                    )
                    start_expected = anchor.stamp_ns + gap_ns
                    end_expected = start_expected + horizon_ns
                    start_point = _exact_endpoint(by_stamp, start_expected, tolerance_ns)
                    end_point = _exact_endpoint(by_stamp, end_expected, tolerance_ns)
                    value: float | None = None
                    availability_ts: int | None = None
                    if (
                        start_point is not None
                        and end_point is not None
                        and start_point.stamp_ns < end_point.stamp_ns
                    ):
                        availability_ts = end_point.stamp_ns
                        if target_registry.version == "microstructure_targets_v2":
                            constructor = str(raw.get("constructor", ""))
                            feature = features_by_id[anchor.observation_id]
                            horizon_seconds = int(float(raw["horizon_seconds"]))
                            path: list[float] = []
                            if constructor == "future_range_target":
                                for offset in range(horizon_seconds + 1):
                                    point = _exact_endpoint(
                                        by_stamp,
                                        start_expected + offset * 1_000_000_000,
                                        tolerance_ns,
                                    )
                                    if point is None:
                                        path = []
                                        break
                                    path.append(point.midpoint)
                            start_feature = features_by_id.get(start_point.observation_id)
                            end_feature = features_by_id.get(end_point.observation_id)
                            result = construct_v2_target(
                                constructor,
                                anchor=datetime.fromtimestamp(
                                    start_point.stamp_ns / 1_000_000_000, tz=UTC
                                ),
                                connection_epoch=anchor.connection_epoch,
                                horizon_seconds=horizon_seconds,
                                tick_size=feature.tick_size,
                                current_mid=start_point.midpoint,
                                future_mid=end_point.midpoint,
                                path_midpoints=path,
                                parity_pressure_value=feature.value_map.get(
                                    "parity.pressure.v1"
                                ),
                                current_spread_ticks=(
                                    None
                                    if start_feature is None
                                    else start_feature.value_map.get(
                                        "liquidity.spread_ticks.v1"
                                    )
                                ),
                                future_spread_ticks=(
                                    None
                                    if end_feature is None
                                    else end_feature.value_map.get(
                                        "liquidity.spread_ticks.v1"
                                    )
                                ),
                            )
                            value = result.value if result.handled else None
                            # ATM-IV and actual-futures-hedged option outcomes need synchronized
                            # cross-instrument state. Until that adapter exists they stay missing.
                        else:
                            value = end_point.midpoint / start_point.midpoint - 1.0
                    target = build_target_observation(
                        observation_id=anchor.observation_id,
                        session_date=source.trading_date,
                        anchor_ts_ns=anchor.stamp_ns,
                        target_id=str(raw["target_id"]),
                        value=value,
                        registry=target_registry,
                        source_dataset_id=source.dataset_id,
                        source_sha256=source.source_identity_hash,
                        instrument_id=anchor.instrument_id,
                        channel=anchor.channel,
                        connection_id=anchor.connection_id,
                        connection_epoch=anchor.connection_epoch,
                        break_segment=anchor.segment,
                        availability_ts_ns=availability_ts,
                        observed_start_ts_ns=(
                            None
                            if start_point is None or end_point is None
                            else start_point.stamp_ns
                        ),
                        observed_end_ts_ns=(
                            None if start_point is None or end_point is None else end_point.stamp_ns
                        ),
                    )
                    all_targets.append(target)
                    all_rows.append(EvaluationRow(features_by_id[anchor.observation_id], target))
        _source_bytes_are_unchanged(source)
    source_manifest = canonical_sha256([asdict(item) for item in sources])
    derivation_payload = {
        "source_manifest_hash": source_manifest,
        "feature_registry": (feature_registry.version, feature_registry.fingerprint_sha256),
        "target_registry": (target_registry.version, target_registry.fingerprint_sha256),
        "feature_run_hash": feature_run_hash(all_features),
        "target_hashes": [item.target_run_hash for item in all_targets],
        "join_count": len(all_rows),
    }
    return DerivedResearchDataset(
        sources,
        feature_registry.version,
        feature_registry.fingerprint_sha256,
        target_registry.version,
        target_registry.fingerprint_sha256,
        tuple(all_features),
        tuple(all_targets),
        tuple(all_rows),
        source_manifest,
        canonical_sha256(derivation_payload),
        _factory_token=_DATASET_FACTORY_TOKEN,
    )
