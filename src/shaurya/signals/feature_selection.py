"""D51 causal registry and construction layer for the ten-second futures-mid experiment.

This module deliberately stops before preprocessing, clustering, fitting or selection.  It
consumes the canonical OFI, LOB and eSSVI feature objects and records when every value became
available.  The frozen design is ``docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

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
SPECIFICATION_VERSION: Final = "1.1.0"
DESIGN_DOCUMENT: Final = "docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md"
REGISTRY_VERSION: Final = "d51-feature-registry-v1"
TARGET_REGISTRY_VERSION: Final = "d51-target-registry-v1"
CONFIRMATORY_ELIGIBLE: Final = False
EVIDENCE_LABEL: Final = "exploratory_screening_today_only"
GATE_ARTIFACT_VERSION: Final = "d51-quality-gates-v1"

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


GateReason = Literal[
    "schema_missing_feature",
    "schema_extra_feature",
    "registry_version_mismatch",
    "invalid_target",
    "invalid_target_geometry",
    "missing_value",
    "missing_availability",
    "future_availability",
    "stale_availability",
    "range_violation",
    "surface_quality_missing",
    "surface_marked_stale",
    "surface_fit_below_minimum",
    "surface_support_below_minimum",
    "surface_arbitrage_failed",
    "insufficient_training_coverage",
    "near_constant_training_feature",
    "exact_duplicate_training_feature",
    "affine_duplicate_training_feature",
]


@dataclass(frozen=True, slots=True)
class SurfaceQualityGate:
    """Predeclared causal surface acceptance policy; it is never fitted on outcomes."""

    maximum_age_seconds: float = 480.0
    minimum_weighted_r_squared: float = 0.0
    minimum_used_quote_count: float = 1.0
    minimum_expiry_quote_count: float = 1.0
    minimum_expiry_support_width: float = 0.0
    require_arbitrage_passed: bool = True
    reject_stale_flag: bool = True

    def __post_init__(self) -> None:
        thresholds = (
            self.maximum_age_seconds,
            self.minimum_used_quote_count,
            self.minimum_expiry_quote_count,
            self.minimum_expiry_support_width,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in thresholds):
            raise ValueError("surface age/support thresholds must be finite and non-negative")
        if not math.isfinite(self.minimum_weighted_r_squared):
            raise ValueError("surface fit threshold must be finite")


@dataclass(frozen=True, slots=True)
class FeatureQualityGateConfig:
    """Frozen engineering gates; train-derived checks use only ``training_row_indices``."""

    minimum_training_coverage: float = 0.5
    near_constant_absolute_tolerance: float = 1e-12
    affine_duplicate_absolute_tolerance: float = 1e-12
    maximum_age_seconds_by_family: Mapping[str, float] | None = None
    surface: SurfaceQualityGate = SurfaceQualityGate()

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_training_coverage <= 1.0:
            raise ValueError("minimum training coverage must lie in [0, 1]")
        if self.near_constant_absolute_tolerance < 0.0:
            raise ValueError("near-constant tolerance must be non-negative")
        if self.affine_duplicate_absolute_tolerance < 0.0:
            raise ValueError("affine-duplicate tolerance must be non-negative")
        if self.maximum_age_seconds_by_family is not None and any(
            not math.isfinite(value) or value < 0.0
            for value in self.maximum_age_seconds_by_family.values()
        ):
            raise ValueError("family age thresholds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class GateFinding:
    reason: GateReason
    feature_name: str | None
    row_index: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class TrainingFeatureDiagnostic:
    feature_name: str
    finite_count: int
    training_row_count: int
    coverage: float
    minimum: float | None
    maximum: float | None
    retained: bool


@dataclass(frozen=True, slots=True)
class GatedFeatureRow:
    """Gate view of one source row; source values are preserved and never zero-filled."""

    source_row_index: int
    row_valid: bool
    feature_values: Mapping[str, float | None]
    missing_indicators: Mapping[str, bool]
    validity_indicators: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class FeatureQualityGateArtifact:
    version: str
    specification_id: str
    registry_version: str
    config: FeatureQualityGateConfig
    maximum_age_seconds_by_family: Mapping[str, float]
    input_fingerprint_sha256: str
    training_row_indices: tuple[int, ...]
    eligible_features: tuple[str, ...]
    excluded_features: tuple[str, ...]
    findings: tuple[GateFinding, ...]
    training_diagnostics: tuple[TrainingFeatureDiagnostic, ...]
    rows: tuple[GatedFeatureRow, ...]
    reason_counts: Mapping[str, int]


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
                    None if near_value is None or far_value is None else near_value - far_value,
                    anchor,
                )

        surface = _same_epoch_as_of_surface(enriched_surface, anchor, observation.connection_epoch)
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
                if name in {"regime__spread_ticks", "regime__log1p_l1_depth"} and book is not None
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


def _default_maximum_age_by_family() -> Mapping[str, float]:
    return {"book_liquidity": MAX_BOOK_AGE_SECONDS, "surface": 480.0}


def _feature_in_range(name: str, value: float) -> bool:
    """Apply only deterministic domain/schema ranges, not empirically chosen winsorisation."""

    zero_one = name.startswith("quality__") and name in {
        "quality__surface_is_stale",
        "quality__is_temporally_smoothed",
        "quality__smoothing_reset",
        "quality__raw_unsmoothed",
        "quality__arbitrage_passed",
    }
    if zero_one and value not in {0.0, 1.0}:
        return False
    if name in {"regime__session_phase_sin", "regime__session_phase_cos"}:
        return -1.0 - 1e-12 <= value <= 1.0 + 1e-12
    explicitly_nonnegative = name in {
        "lob__spread_ticks",
        "lob__l1_total_quantity",
        "lob__log1p_l1_total_quantity",
        "lob__bid_total_quantity_5",
        "lob__ask_total_quantity_5",
        "lob__log1p_bid_total_quantity_5",
        "lob__log1p_ask_total_quantity_5",
        "lob__bid_average_order_size_proxy_5",
        "lob__ask_average_order_size_proxy_5",
        "regime__minutes_from_open",
        "regime__minutes_to_close",
        "regime__abs_lag_return_10s_per_sqrt_second",
        "regime__spread_ticks",
        "regime__log1p_l1_depth",
    }
    nonnegative_quality_tokens = (
        "weighted_rmse",
        "quote_count",
        "used_quote_count",
        "support_width",
        "age_seconds",
        "duration_seconds",
        "packets_per_second",
        "reconnect_count",
        "stale_instrument_count",
        "smoothing_component_count",
    )
    quality_nonnegative = name.startswith("quality__") and any(
        token in name for token in nonnegative_quality_tokens
    )
    return not ((explicitly_nonnegative or quality_nonnegative) and value < 0.0)


def _surface_quality_failures(
    values: Mapping[str, float | None], policy: SurfaceQualityGate
) -> tuple[tuple[GateReason, str], ...]:
    required = (
        "quality__surface_age_seconds",
        "quality__weighted_r_squared",
        "quality__used_quote_count",
        "quality__surface_is_stale",
        "quality__arbitrage_passed",
        *tuple(
            f"quality__{expiry.isoformat()}__{suffix}"
            for expiry in EXPIRIES
            for suffix in ("quote_count", "support_width")
        ),
    )
    missing = tuple(name for name in required if values.get(name) is None)
    if missing:
        return (("surface_quality_missing", ",".join(missing)),)
    failures: list[tuple[GateReason, str]] = []
    age = cast(float, values["quality__surface_age_seconds"])
    r_squared = cast(float, values["quality__weighted_r_squared"])
    used_quotes = cast(float, values["quality__used_quote_count"])
    stale = cast(float, values["quality__surface_is_stale"])
    arbitrage = cast(float, values["quality__arbitrage_passed"])
    if age > policy.maximum_age_seconds:
        failures.append(("stale_availability", f"surface age {age} > {policy.maximum_age_seconds}"))
    if policy.reject_stale_flag and stale != 0.0:
        failures.append(("surface_marked_stale", f"surface stale flag={stale}"))
    if r_squared < policy.minimum_weighted_r_squared:
        failures.append(
            (
                "surface_fit_below_minimum",
                f"weighted R2 {r_squared} < {policy.minimum_weighted_r_squared}",
            )
        )
    if used_quotes < policy.minimum_used_quote_count:
        failures.append(
            (
                "surface_support_below_minimum",
                f"used quotes {used_quotes} < {policy.minimum_used_quote_count}",
            )
        )
    for expiry in EXPIRIES:
        prefix = f"quality__{expiry.isoformat()}"
        quote_count = cast(float, values[f"{prefix}__quote_count"])
        support_width = cast(float, values[f"{prefix}__support_width"])
        if quote_count < policy.minimum_expiry_quote_count:
            failures.append(
                (
                    "surface_support_below_minimum",
                    f"{expiry} quote count {quote_count} < {policy.minimum_expiry_quote_count}",
                )
            )
        if support_width < policy.minimum_expiry_support_width:
            failures.append(
                (
                    "surface_support_below_minimum",
                    f"{expiry} support {support_width} < {policy.minimum_expiry_support_width}",
                )
            )
    if policy.require_arbitrage_passed and arbitrage != 1.0:
        failures.append(("surface_arbitrage_failed", f"arbitrage flag={arbitrage}"))
    return tuple(failures)


def _input_fingerprint(
    result: FeatureConstructionResult, training_row_indices: tuple[int, ...]
) -> str:
    def canonical(value: float | None) -> float | str | None:
        if value is None or math.isfinite(value):
            return value
        if math.isnan(value):
            return "nonfinite:nan"
        return "nonfinite:+inf" if value > 0.0 else "nonfinite:-inf"

    payload = {
        "registry_version": result.registry.version,
        "training_row_indices": training_row_indices,
        "rows": [
            {
                "anchor": row.anchor_ts_ns,
                "epoch": row.connection_epoch,
                "target_start": row.target_start_ts_ns,
                "target_end": row.target_end_ts_ns,
                "target": canonical(row.target_ticks),
                "values": sorted(
                    (name, canonical(_finite(value)) if _finite(value) is not None else None)
                    for name, value in row.feature_values.items()
                ),
                "availability": sorted(row.feature_available_ts_ns.items()),
            }
            for row in result.rows
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _affine_duplicate(left: Sequence[float], right: Sequence[float], tolerance: float) -> bool:
    if len(left) < 3 or len(left) != len(right):
        return False
    pivot = next(
        (index for index in range(1, len(left)) if abs(left[index] - left[0]) > tolerance),
        None,
    )
    if pivot is None:
        return False
    slope = (right[pivot] - right[0]) / (left[pivot] - left[0])
    intercept = right[0] - slope * left[0]
    if abs(slope) <= tolerance:
        return False
    scale = max(1.0, *(abs(value) for value in right))
    return all(
        abs(observed - (slope * source + intercept)) <= tolerance * scale
        for source, observed in zip(left, right, strict=True)
    )


def apply_feature_quality_gates(
    result: FeatureConstructionResult,
    *,
    training_row_indices: Sequence[int],
    config: FeatureQualityGateConfig | None = None,
) -> FeatureQualityGateArtifact:
    """Audit D51 rows and learn coverage/constancy/redundancy on training rows only.

    This function does not impute, scale, cluster, fit or inspect target association. Invalid
    values become ``None`` in the gate view, with separate missingness and validity flags.
    """

    policy = config or FeatureQualityGateConfig()
    training = tuple(sorted(set(training_row_indices)))
    if not training:
        raise ValueError("at least one training row index is required")
    if training[0] < 0 or training[-1] >= len(result.rows):
        raise IndexError("training row index is outside constructed rows")
    registry_names = result.registry.feature_names
    registry_set = set(registry_names)
    definitions = {item.name: item for item in result.registry.features}
    maximum_age = dict(_default_maximum_age_by_family())
    if policy.maximum_age_seconds_by_family is not None:
        maximum_age.update(policy.maximum_age_seconds_by_family)

    findings: list[GateFinding] = []
    hard_excluded: set[str] = set()
    valid_source_rows: list[bool] = []
    row_values: list[dict[str, float | None]] = []
    row_validity: list[dict[str, bool]] = []
    for row_index, row in enumerate(result.rows):
        row_is_valid = True
        value_names = set(row.feature_values)
        availability_names = set(row.feature_available_ts_ns)
        if value_names != registry_set or availability_names != registry_set:
            row_is_valid = False
        for name in sorted(registry_set - value_names):
            hard_excluded.add(name)
            findings.append(GateFinding("schema_missing_feature", name, row_index, "value absent"))
        for name in sorted(value_names - registry_set):
            findings.append(
                GateFinding("schema_extra_feature", name, row_index, "unregistered value")
            )
        for name in sorted(registry_set - availability_names):
            findings.append(
                GateFinding("schema_missing_feature", name, row_index, "availability absent")
            )
        for name in sorted(availability_names - registry_set):
            findings.append(
                GateFinding("schema_extra_feature", name, row_index, "unregistered availability")
            )
        if row.registry_version != result.registry.version:
            row_is_valid = False
            findings.append(
                GateFinding(
                    "registry_version_mismatch",
                    None,
                    row_index,
                    f"row={row.registry_version}; registry={result.registry.version}",
                )
            )
        if not math.isfinite(row.target_ticks):
            row_is_valid = False
            findings.append(GateFinding("invalid_target", None, row_index, "target is non-finite"))
        expected_start = row.anchor_ts_ns + int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
        expected_end = expected_start + int(TARGET_HORIZON_SECONDS * NANOSECONDS_PER_SECOND)
        if row.target_start_ts_ns != expected_start or row.target_end_ts_ns != expected_end:
            row_is_valid = False
            findings.append(
                GateFinding("invalid_target_geometry", None, row_index, "target offsets differ")
            )

        gated: dict[str, float | None] = {}
        valid: dict[str, bool] = {}
        for name in registry_names:
            raw = row.feature_values.get(name)
            available = row.feature_available_ts_ns.get(name)
            value = _finite(raw)
            is_valid = value is not None
            if value is None:
                findings.append(GateFinding("missing_value", name, row_index, "missing/non-finite"))
            elif available is None:
                is_valid = False
                hard_excluded.add(name)
                findings.append(
                    GateFinding(
                        "missing_availability",
                        name,
                        row_index,
                        "finite value has no timestamp",
                    )
                )
            elif available > row.anchor_ts_ns:
                is_valid = False
                hard_excluded.add(name)
                findings.append(
                    GateFinding(
                        "future_availability",
                        name,
                        row_index,
                        f"available {available} > anchor {row.anchor_ts_ns}",
                    )
                )
            elif not _feature_in_range(name, value):
                is_valid = False
                findings.append(GateFinding("range_violation", name, row_index, f"value={value}"))
            else:
                age_limit = maximum_age.get(definitions[name].family)
                if age_limit is not None:
                    age = (row.anchor_ts_ns - available) / NANOSECONDS_PER_SECOND
                    if age > age_limit:
                        is_valid = False
                        findings.append(
                            GateFinding(
                                "stale_availability",
                                name,
                                row_index,
                                f"age {age} > {age_limit}",
                            )
                        )
            gated[name] = value if is_valid else None
            valid[name] = is_valid

        surface_failures = _surface_quality_failures(gated, policy.surface)
        if surface_failures:
            for reason, detail in surface_failures:
                findings.append(GateFinding(reason, None, row_index, detail))
            for name in registry_names:
                if definitions[name].family == "surface":
                    gated[name] = None
                    valid[name] = False
        row_values.append(gated)
        row_validity.append(valid)
        valid_source_rows.append(row_is_valid)

    excluded: set[str] = set(hard_excluded)
    diagnostics: list[TrainingFeatureDiagnostic] = []
    training_vectors: dict[str, tuple[float | None, ...]] = {}
    for name in registry_names:
        vector = tuple(row_values[index][name] for index in training)
        training_vectors[name] = vector
        finite = tuple(value for value in vector if value is not None)
        coverage = len(finite) / len(training)
        retained = True
        if not finite or coverage < policy.minimum_training_coverage:
            retained = False
            excluded.add(name)
            findings.append(
                GateFinding(
                    "insufficient_training_coverage",
                    name,
                    None,
                    f"coverage {coverage} < {policy.minimum_training_coverage}",
                )
            )
        elif finite and max(finite) - min(finite) <= policy.near_constant_absolute_tolerance:
            retained = False
            excluded.add(name)
            findings.append(
                GateFinding(
                    "near_constant_training_feature",
                    name,
                    None,
                    f"range {max(finite) - min(finite)}",
                )
            )
        diagnostics.append(
            TrainingFeatureDiagnostic(
                name,
                len(finite),
                len(training),
                coverage,
                min(finite) if finite else None,
                max(finite) if finite else None,
                retained,
            )
        )

    candidates = [name for name in registry_names if name not in excluded]
    for position, name in enumerate(candidates):
        if name in excluded:
            continue
        left_vector = training_vectors[name]
        for other in candidates[position + 1 :]:
            if other in excluded:
                continue
            right_vector = training_vectors[other]
            if tuple(value is None for value in left_vector) != tuple(
                value is None for value in right_vector
            ):
                continue
            left = tuple(value for value in left_vector if value is not None)
            right = tuple(value for value in right_vector if value is not None)
            if left == right:
                excluded.add(other)
                findings.append(
                    GateFinding(
                        "exact_duplicate_training_feature",
                        other,
                        None,
                        f"duplicates canonical representative {name}",
                    )
                )
            elif _affine_duplicate(left, right, policy.affine_duplicate_absolute_tolerance):
                excluded.add(other)
                findings.append(
                    GateFinding(
                        "affine_duplicate_training_feature",
                        other,
                        None,
                        f"affine duplicate of canonical representative {name}",
                    )
                )

    gated_rows: list[GatedFeatureRow] = []
    for index, values in enumerate(row_values):
        validity = {
            name: row_validity[index][name] and name not in excluded for name in registry_names
        }
        gate_values = {name: values[name] if validity[name] else None for name in registry_names}
        gated_rows.append(
            GatedFeatureRow(
                index,
                valid_source_rows[index],
                gate_values,
                {
                    name: _finite(result.rows[index].feature_values.get(name)) is None
                    for name in registry_names
                },
                validity,
            )
        )
    eligible = tuple(name for name in registry_names if name not in excluded)
    reason_counts: dict[str, int] = {}
    for finding in findings:
        reason_counts[finding.reason] = reason_counts.get(finding.reason, 0) + 1
    retained_lookup = set(eligible)
    final_diagnostics = tuple(
        TrainingFeatureDiagnostic(
            item.feature_name,
            item.finite_count,
            item.training_row_count,
            item.coverage,
            item.minimum,
            item.maximum,
            item.feature_name in retained_lookup,
        )
        for item in diagnostics
    )
    return FeatureQualityGateArtifact(
        GATE_ARTIFACT_VERSION,
        SPECIFICATION_ID,
        result.registry.version,
        policy,
        maximum_age,
        _input_fingerprint(result, training),
        training,
        eligible,
        tuple(name for name in registry_names if name in excluded),
        tuple(findings),
        final_diagnostics,
        tuple(gated_rows),
        reason_counts,
    )
