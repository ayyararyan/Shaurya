"""D51 causal registry and construction layer for the ten-second futures-mid experiment.

This module deliberately stops before preprocessing, clustering, fitting or selection.  It
consumes the canonical OFI, LOB and eSSVI feature objects and records when every value became
available.  The frozen design is ``docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md``.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from shaurya.data.depth_thinning_analysis import BookState
from shaurya.signals.ccz_ofi import average_feature
from shaurya.signals.ofi_horserace import HorseRaceObservation
from shaurya.signals.surface_futures_predictive import (
    EXPIRIES,
    QUALITY_NUMERIC_NAMES,
    SURFACE_LEVEL_NAMES,
    TERM_NAMES,
    FrameDraft,
    lob_features,
    surface_feature,
    term_feature,
)

SPECIFICATION_ID: Final = "D51-10S-FEATURE-SELECTION-2026-08-21"
SPECIFICATION_VERSION: Final = "1.0.0"
DESIGN_DOCUMENT: Final = "docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md"
REGISTRY_VERSION: Final = "d51-feature-registry-v1"
TARGET_REGISTRY_VERSION: Final = "d51-target-registry-v1"
CONFIRMATORY_ELIGIBLE: Final = False
EVIDENCE_LABEL: Final = "exploratory_screening_today_only"

NANOSECONDS_PER_SECOND: Final = 1_000_000_000
CAUSAL_GAP_SECONDS: Final = 0.5
TARGET_HORIZON_SECONDS: Final = 10.0
TARGET_START_OFFSET_SECONDS: Final = CAUSAL_GAP_SECONDS
TARGET_END_OFFSET_SECONDS: Final = CAUSAL_GAP_SECONDS + TARGET_HORIZON_SECONDS
TARGET_NAME: Final = "future_displayed_mid_return_10s_after_0p5s_gap_ticks"
TICK_SIZE_RUPEES: Final = 0.05

PRICE_LAG_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
OFI_WINDOWS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
OFI_DEPTHS: Final = (1, 5, 10, 20, 50, 100, 200)
OFI_GRADIENTS: Final = ((5, 20), (20, 200))
SURFACE_EW_ALPHA: Final = 0.2
MAX_BOOK_AGE_SECONDS: Final = 1.0

FeatureFamily = Literal[
    "price_path",
    "book_liquidity",
    "ofi",
    "surface",
    "surface_quality",
    "time_regime",
    "interaction",
]
ObjectCategory = Literal["deterministically_derived", "estimated", "proxy"]


def _label(value: float) -> str:
    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def price_lag_feature(seconds: float) -> str:
    return f"price__displayed_mid_return_lag_{_label(seconds)}s_ticks"


def ofi_gradient_feature(window: float, near_depth: int, far_depth: int) -> str:
    return f"ofi__w{_label(window)}__average_m{near_depth}_minus_m{far_depth}"


def surface_innovation_feature(name: str) -> str:
    return f"{name}__ew_innovation_alpha_0p2"


BOOK_FEATURE_NAMES: Final = (
    "lob__spread_ticks",
    "lob__microprice_tilt_ticks",
    "lob__l1_total_quantity",
    "lob__log1p_l1_total_quantity",
    *(f"lob__quantity_imbalance_l{level}" for level in range(1, 6)),
    *(f"lob__order_count_imbalance_l{level}" for level in range(1, 6)),
    "lob__quantity_imbalance_cum1",
    "lob__quantity_imbalance_cum5",
    "lob__bid_total_quantity_5",
    "lob__ask_total_quantity_5",
    "lob__log1p_bid_total_quantity_5",
    "lob__log1p_ask_total_quantity_5",
    "lob__order_count_imbalance_cum5",
    "lob__bid_average_order_size_proxy_5",
    "lob__ask_average_order_size_proxy_5",
    "lob__average_order_size_log_ratio_proxy_5",
    "lob__bid_slope",
    "lob__bid_curvature",
    "lob__ask_slope",
    "lob__ask_curvature",
    "lob__slope_asymmetry_ask_minus_bid",
    "lob__curvature_asymmetry_ask_minus_bid",
)

TIME_REGIME_FEATURE_NAMES: Final = (
    "regime__minutes_from_open",
    "regime__minutes_to_close",
    "regime__session_phase_sin",
    "regime__session_phase_cos",
    "regime__abs_lag_return_10s_per_sqrt_second",
    "regime__spread_ticks",
    "regime__log1p_l1_depth",
)

INTERACTION_FEATURE_NAMES: Final = (
    "interaction__ofi_w10_m10_x_spread",
    "interaction__ofi_w10_m10_x_inverse_l1_depth",
    "interaction__ofi_w10_m10_x_lagged_move_scale",
    "interaction__front_atm_skew_ew_innovation_x_ofi_w10_m10",
)


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    family: FeatureFamily
    category: ObjectCategory
    source: str
    timing_rule: str
    construction: str
    requirement_id: str


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    name: str
    category: Literal["deterministically_derived"]
    units: Literal["futures_ticks"]
    reference_price: Literal["displayed_bbo_mid"]
    causal_gap_seconds: float
    horizon_seconds: float
    source: str
    requirement_id: str


@dataclass(frozen=True, slots=True)
class FeatureTargetRegistry:
    version: str
    target_version: str
    features: tuple[FeatureDefinition, ...]
    targets: tuple[TargetDefinition, ...]

    def __post_init__(self) -> None:
        feature_names = [item.name for item in self.features]
        target_names = [item.name for item in self.targets]
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("feature registry contains duplicate names")
        if len(target_names) != len(set(target_names)):
            raise ValueError("target registry contains duplicate names")
        if set(feature_names) & set(target_names):
            raise ValueError("feature and target registry names overlap")

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.features)


@dataclass(frozen=True, slots=True)
class FeatureSelectionRow:
    anchor_ts_ns: int
    connection_epoch: int
    target_start_ts_ns: int
    target_end_ts_ns: int
    target_ticks: float
    feature_values: Mapping[str, float | None]
    feature_available_ts_ns: Mapping[str, int | None]
    registry_version: str = REGISTRY_VERSION
    evidence_label: str = EVIDENCE_LABEL

    def __post_init__(self) -> None:
        if self.target_start_ts_ns <= self.anchor_ts_ns:
            raise ValueError("target must start strictly after its feature anchor")
        if self.target_end_ts_ns <= self.target_start_ts_ns:
            raise ValueError("target endpoint must follow target start")
        if set(self.feature_values) != set(self.feature_available_ts_ns):
            raise ValueError("feature values and availability maps must have identical names")
        for name, value in self.feature_values.items():
            available = self.feature_available_ts_ns[name]
            if value is not None and available is None:
                raise ValueError(f"non-missing feature {name} has no availability timestamp")
            if available is not None and available > self.anchor_ts_ns:
                raise ValueError(f"feature {name} is available after its anchor")


@dataclass(frozen=True, slots=True)
class FeatureConstructionResult:
    registry: FeatureTargetRegistry
    rows: tuple[FeatureSelectionRow, ...]
    diagnostics: Mapping[str, int | str | bool]


def _surface_level_names() -> tuple[str, ...]:
    result: list[str] = []
    for expiry in EXPIRIES:
        for name in SURFACE_LEVEL_NAMES:
            result.append(surface_feature(expiry, name))
    for earlier, later in zip(EXPIRIES, EXPIRIES[1:], strict=False):
        for name in TERM_NAMES:
            result.append(term_feature(earlier, later, name))
    return tuple(result)


SURFACE_BASE_NAMES: Final = _surface_level_names()
SURFACE_ECONOMIC_NAMES: Final = (
    *SURFACE_BASE_NAMES,
    *(f"{name}__delta_1f" for name in SURFACE_BASE_NAMES),
    *(f"{name}__velocity_per_second" for name in SURFACE_BASE_NAMES),
    *(surface_innovation_feature(name) for name in SURFACE_BASE_NAMES),
)


def build_registry() -> FeatureTargetRegistry:
    """Return the complete immutable D51 v1 feature and target catalog."""

    definitions: list[FeatureDefinition] = []

    def add(
        name: str,
        family: FeatureFamily,
        category: ObjectCategory,
        source: str,
        timing_rule: str,
        construction: str,
        requirement_id: str,
    ) -> None:
        definitions.append(
            FeatureDefinition(
                name,
                family,
                category,
                source,
                timing_rule,
                construction,
                requirement_id,
            )
        )

    for seconds in PRICE_LAG_SECONDS:
        add(
            price_lag_feature(seconds),
            "price_path",
            "deterministically_derived",
            "HorseRaceObservation.past_ticks",
            f"displayed-mid move ending at anchor over trailing {seconds}s",
            "canonical past-return map; no future endpoint",
            "D51-X-PRICE-01",
        )
    for name in BOOK_FEATURE_NAMES:
        add(
            name,
            "book_liquidity",
            "proxy" if "proxy" in name else "deterministically_derived",
            "surface_futures_predictive.lob_features(BookState)",
            "latest usable same-epoch book as of anchor",
            "canonical five-level LOB constructor",
            "D51-X-BOOK-01",
        )
    for window in OFI_WINDOWS_SECONDS:
        for depth in OFI_DEPTHS:
            add(
                average_feature(window, depth),
                "ofi",
                "deterministically_derived",
                "HorseRaceObservation.features / canonical CCZ",
                f"CCZ window ends at anchor; trailing {window}s",
                f"CCZ Appendix-A average at M={depth} with common depth denominator",
                "D51-X-OFI-01",
            )
        for near, far in OFI_GRADIENTS:
            add(
                ofi_gradient_feature(window, near, far),
                "ofi",
                "deterministically_derived",
                "registered canonical CCZ averages",
                f"both CCZ windows end at anchor; trailing {window}s",
                f"M={near} average minus M={far} average",
                "D51-X-OFI-01",
            )
    for name in SURFACE_ECONOMIC_NAMES:
        add(
            name,
            "surface",
            "estimated" if "ew_innovation" not in name else "deterministically_derived",
            "canonical FrameDraft.economic and past-state EW transform",
            "latest same-epoch surface frame as of anchor",
            "canonical eSSVI observable/change/velocity or strictly past-state EW innovation",
            "D51-X-SURF-01",
        )
    for name in QUALITY_NUMERIC_NAMES:
        add(
            name,
            "surface_quality",
            "deterministically_derived",
            "canonical FrameDraft.quality_numeric",
            "quality attached to latest same-epoch surface frame as of anchor",
            "pass through finite diagnostic; missing remains missing",
            "D51-X-SURF-01",
        )
    for name in TIME_REGIME_FEATURE_NAMES:
        add(
            name,
            "time_regime",
            "deterministically_derived",
            "anchor/session bounds and lagged price/book state",
            "known at anchor",
            "declared deterministic regime transform",
            "D51-X-REGIME-01",
        )
    for name in INTERACTION_FEATURE_NAMES:
        add(
            name,
            "interaction",
            "deterministically_derived",
            "predeclared component features",
            "maximum availability time of non-missing components",
            "product of named economic components; missing propagates",
            "D51-X-INT-01",
        )
    target = TargetDefinition(
        TARGET_NAME,
        "deterministically_derived",
        "futures_ticks",
        "displayed_bbo_mid",
        CAUSAL_GAP_SECONDS,
        TARGET_HORIZON_SECONDS,
        "HorseRaceObservation.future_ticks[10.0]",
        "D51-OBJ-01",
    )
    return FeatureTargetRegistry(
        REGISTRY_VERSION, TARGET_REGISTRY_VERSION, tuple(definitions), (target,)
    )


def _finite(value: object) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _surface_frames_with_innovations(
    frames: Sequence[FrameDraft],
) -> tuple[tuple[FrameDraft, Mapping[str, float | None]], ...]:
    """Attach innovations against EW state from strictly earlier frames."""

    means_by_epoch: dict[int, dict[str, float]] = {}
    result: list[tuple[FrameDraft, Mapping[str, float | None]]] = []
    for frame in sorted(frames, key=lambda item: (item.receive_ts_ns, item.sequence)):
        means = means_by_epoch.setdefault(frame.connection_epoch, {})
        innovations: dict[str, float | None] = {}
        for name in SURFACE_BASE_NAMES:
            value = _finite(frame.economic.get(name))
            previous = means.get(name)
            innovations[surface_innovation_feature(name)] = (
                None if value is None or previous is None else value - previous
            )
            if value is not None:
                means[name] = (
                    value
                    if previous is None
                    else SURFACE_EW_ALPHA * value + (1.0 - SURFACE_EW_ALPHA) * previous
                )
        result.append((frame, innovations))
    return tuple(result)


def _same_epoch_as_of_book(
    books: Sequence[BookState], anchor_ts_ns: int, connection_epoch: int
) -> BookState | None:
    ordered = sorted(books, key=lambda item: item.receive_ts_ns)
    timestamps = [item.receive_ts_ns for item in ordered]
    position = bisect_right(timestamps, anchor_ts_ns) - 1
    if position < 0:
        return None
    state = ordered[position]
    age = (anchor_ts_ns - state.receive_ts_ns) / NANOSECONDS_PER_SECOND
    if state.connection_epoch != connection_epoch or age > MAX_BOOK_AGE_SECONDS:
        return None
    return state


def _same_epoch_as_of_surface(
    frames: Sequence[tuple[FrameDraft, Mapping[str, float | None]]],
    anchor_ts_ns: int,
    connection_epoch: int,
) -> tuple[FrameDraft, Mapping[str, float | None]] | None:
    timestamps = [item[0].receive_ts_ns for item in frames]
    position = bisect_right(timestamps, anchor_ts_ns) - 1
    if position < 0:
        return None
    frame = frames[position]
    return frame if frame[0].connection_epoch == connection_epoch else None


def _put(
    values: dict[str, float | None],
    availability: dict[str, int | None],
    name: str,
    value: object,
    available_ts_ns: int | None,
) -> None:
    finite = _finite(value)
    values[name] = finite
    availability[name] = available_ts_ns if finite is not None else None


def _product(
    values: Mapping[str, float | None],
    availability: Mapping[str, int | None],
    left: str,
    right: str,
) -> tuple[float | None, int | None]:
    left_value, right_value = values[left], values[right]
    left_time, right_time = availability[left], availability[right]
    if left_value is None or right_value is None or left_time is None or right_time is None:
        return None, None
    return left_value * right_value, max(left_time, right_time)


def build_feature_selection_rows(
    *,
    observations: Sequence[HorseRaceObservation],
    books: Sequence[BookState],
    surface_frames: Sequence[FrameDraft],
    session_open_ts_ns: int,
    session_close_ts_ns: int,
) -> FeatureConstructionResult:
    """Construct D51 rows without fitting, imputing, scaling or selecting anything."""

    if session_close_ts_ns <= session_open_ts_ns:
        raise ValueError("session close must follow session open")
    registry = build_registry()
    enriched_surface = _surface_frames_with_innovations(surface_frames)
    feature_names = registry.feature_names
    rows: list[FeatureSelectionRow] = []
    missing_target = 0
    missing_book = 0
    missing_surface = 0
    session_length = session_close_ts_ns - session_open_ts_ns

    for observation in sorted(observations, key=lambda item: item.receive_ts_ns):
        target = _finite(observation.future_ticks.get(TARGET_HORIZON_SECONDS))
        if target is None:
            missing_target += 1
            continue
        anchor = observation.receive_ts_ns
        values: dict[str, float | None] = dict.fromkeys(feature_names)
        availability: dict[str, int | None] = dict.fromkeys(feature_names)

        for seconds in PRICE_LAG_SECONDS:
            _put(
                values,
                availability,
                price_lag_feature(seconds),
                observation.past_ticks.get(seconds),
                anchor,
            )

        book = _same_epoch_as_of_book(books, anchor, observation.connection_epoch)
        book_values = lob_features(book) if book is not None else None
        if book_values is None:
            missing_book += 1
        for name in BOOK_FEATURE_NAMES:
            _put(
                values,
                availability,
                name,
                None if book_values is None else book_values.get(name),
                None if book is None else book.receive_ts_ns,
            )

        for window in OFI_WINDOWS_SECONDS:
            for depth in OFI_DEPTHS:
                source_name = average_feature(window, depth)
                _put(
                    values,
                    availability,
                    source_name,
                    observation.features.get(source_name),
                    anchor,
                )
            for near, far in OFI_GRADIENTS:
                near_name = average_feature(window, near)
                far_name = average_feature(window, far)
                gradient_name = ofi_gradient_feature(window, near, far)
                near_value, far_value = values[near_name], values[far_name]
                _put(
                    values,
                    availability,
                    gradient_name,
                    None
                    if near_value is None or far_value is None
                    else near_value - far_value,
                    anchor,
                )

        surface = _same_epoch_as_of_surface(
            enriched_surface, anchor, observation.connection_epoch
        )
        if surface is None:
            missing_surface += 1
        frame = surface[0] if surface is not None else None
        innovations = surface[1] if surface is not None else {}
        for name in SURFACE_ECONOMIC_NAMES:
            source_value = (
                innovations.get(name)
                if "__ew_innovation_" in name
                else (None if frame is None else frame.economic.get(name))
            )
            _put(
                values,
                availability,
                name,
                source_value,
                None if frame is None else frame.receive_ts_ns,
            )
        for name in QUALITY_NUMERIC_NAMES:
            _put(
                values,
                availability,
                name,
                None if frame is None else frame.quality_numeric.get(name),
                None if frame is None else frame.receive_ts_ns,
            )

        minutes_from_open = (anchor - session_open_ts_ns) / (60 * NANOSECONDS_PER_SECOND)
        minutes_to_close = (session_close_ts_ns - anchor) / (60 * NANOSECONDS_PER_SECOND)
        phase = 2.0 * math.pi * (anchor - session_open_ts_ns) / session_length
        lag_10 = values[price_lag_feature(10.0)]
        regime_values = {
            "regime__minutes_from_open": minutes_from_open,
            "regime__minutes_to_close": minutes_to_close,
            "regime__session_phase_sin": math.sin(phase),
            "regime__session_phase_cos": math.cos(phase),
            "regime__abs_lag_return_10s_per_sqrt_second": (
                None if lag_10 is None else abs(lag_10) / math.sqrt(10.0)
            ),
            "regime__spread_ticks": values["lob__spread_ticks"],
            "regime__log1p_l1_depth": values["lob__log1p_l1_total_quantity"],
        }
        for name, value in regime_values.items():
            source_time = (
                book.receive_ts_ns
                if name in {"regime__spread_ticks", "regime__log1p_l1_depth"}
                and book is not None
                else anchor
            )
            _put(values, availability, name, value, source_time)

        ofi_name = average_feature(10.0, 10)
        interaction_inputs = (
            (
                "interaction__ofi_w10_m10_x_spread",
                ofi_name,
                "regime__spread_ticks",
            ),
            (
                "interaction__ofi_w10_m10_x_lagged_move_scale",
                ofi_name,
                "regime__abs_lag_return_10s_per_sqrt_second",
            ),
            (
                "interaction__front_atm_skew_ew_innovation_x_ofi_w10_m10",
                surface_innovation_feature(surface_feature(EXPIRIES[0], "atm_skew")),
                ofi_name,
            ),
        )
        for name, left, right in interaction_inputs:
            value, interaction_time = _product(values, availability, left, right)
            _put(values, availability, name, value, interaction_time)
        depth_value = values["lob__l1_total_quantity"]
        inverse_name = "interaction__ofi_w10_m10_x_inverse_l1_depth"
        if depth_value is None or depth_value <= 0.0:
            _put(values, availability, inverse_name, None, None)
        else:
            ofi_value = values[ofi_name]
            ofi_time = availability[ofi_name]
            depth_time = availability["lob__l1_total_quantity"]
            _put(
                values,
                availability,
                inverse_name,
                None if ofi_value is None else ofi_value / depth_value,
                None
                if ofi_value is None or ofi_time is None or depth_time is None
                else max(ofi_time, depth_time),
            )

        start = anchor + int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
        end = start + int(TARGET_HORIZON_SECONDS * NANOSECONDS_PER_SECOND)
        rows.append(
            FeatureSelectionRow(
                anchor,
                observation.connection_epoch,
                start,
                end,
                target,
                values,
                availability,
            )
        )

    diagnostics: dict[str, int | str | bool] = {
        "input_observations": len(observations),
        "constructed_rows": len(rows),
        "missing_target_rows": missing_target,
        "rows_without_book_features": missing_book,
        "rows_without_surface_features": missing_surface,
        "registry_feature_count": len(feature_names),
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "evidence_label": EVIDENCE_LABEL,
    }
    return FeatureConstructionResult(registry, tuple(rows), diagnostics)
