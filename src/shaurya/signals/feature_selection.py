"""D51 causal feature-selection foundation for the ten-second futures-mid experiment.

Steps 1--2 construct and quality-gate canonical OFI, LOB and eSSVI features.  Step 3 reduces
correlated features using training rows only. Step 4 supplies a transparent elastic-net baseline
and a deterministic shallow boosted-tree challenger. It deliberately stops before importance,
stability selection, fold construction or empirical evaluation. The frozen design is
``docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

import numpy as np
from numpy.typing import NDArray
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata

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
SPECIFICATION_VERSION: Final = "1.3.0"
DESIGN_DOCUMENT: Final = "docs/D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md"
REGISTRY_VERSION: Final = "d51-feature-registry-v1"
TARGET_REGISTRY_VERSION: Final = "d51-target-registry-v1"
CONFIRMATORY_ELIGIBLE: Final = False
EVIDENCE_LABEL: Final = "exploratory_screening_today_only"
GATE_ARTIFACT_VERSION: Final = "d51-quality-gates-v1"
CORRELATION_ARTIFACT_VERSION: Final = "d51-correlation-reduction-v1"
PREDICTIVE_MODEL_ARTIFACT_VERSION: Final = "d51-predictive-model-v1"
CORRELATION_SENSITIVITY_THRESHOLDS: Final = (0.85, 0.90, 0.95)
PRIMARY_CORRELATION_THRESHOLD: Final = 0.90

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


PairStatus = Literal["estimated", "insufficient_pairs", "zero_rank_variance"]
ClusterRepresentation = Literal["representative", "first_pc"]


@dataclass(frozen=True, slots=True)
class CorrelationReductionConfig:
    """Predeclared Step-3 policy; no field may be selected using outcomes."""

    minimum_pair_count: int = 3
    sensitivity_thresholds: tuple[float, ...] = CORRELATION_SENSITIVITY_THRESHOLDS
    primary_threshold: float = PRIMARY_CORRELATION_THRESHOLD
    representation: ClusterRepresentation = "representative"
    measurement_quality_by_feature: Mapping[str, float] | None = None
    minimum_pca_complete_rows: int = 3

    def __post_init__(self) -> None:
        if self.minimum_pair_count < 2:
            raise ValueError("minimum pair support must be at least two")
        if self.sensitivity_thresholds != CORRELATION_SENSITIVITY_THRESHOLDS:
            raise ValueError("D51 sensitivity thresholds are frozen at 0.85/0.90/0.95")
        if self.primary_threshold != PRIMARY_CORRELATION_THRESHOLD:
            raise ValueError("D51 primary threshold is frozen at 0.90")
        if self.minimum_pca_complete_rows < 2:
            raise ValueError("minimum PCA complete rows must be at least two")
        if self.measurement_quality_by_feature is not None and any(
            not math.isfinite(value) for value in self.measurement_quality_by_feature.values()
        ):
            raise ValueError("measurement-quality scores must be finite")


@dataclass(frozen=True, slots=True)
class PairwiseSpearmanDiagnostic:
    left_feature: str
    right_feature: str
    pair_count: int
    rho: float | None
    distance: float
    status: PairStatus


@dataclass(frozen=True, slots=True)
class ClusterDefinition:
    cluster_id: str
    members: tuple[str, ...]
    representative: str
    representative_measurement_quality: float
    representative_training_coverage: float


@dataclass(frozen=True, slots=True)
class CorrelationClusterMap:
    absolute_correlation_threshold: float
    distance_cut: float
    clusters: tuple[ClusterDefinition, ...]


@dataclass(frozen=True, slots=True)
class FirstPCTransform:
    cluster_id: str
    members: tuple[str, ...]
    center: tuple[float, ...]
    loadings: tuple[float, ...]
    complete_training_row_count: int
    sign_anchor_feature: str
    sign_convention: str = "largest_absolute_loading_positive_then_lexical_feature"


@dataclass(frozen=True, slots=True)
class CorrelatedFeatureReductionArtifact:
    version: str
    specification_id: str
    specification_version: str
    registry_version: str
    source_gate_version: str
    config: CorrelationReductionConfig
    training_row_indices: tuple[int, ...]
    training_input_fingerprint_sha256: str
    eligible_input_features: tuple[str, ...]
    pairwise_diagnostics: tuple[PairwiseSpearmanDiagnostic, ...]
    sensitivity_maps: tuple[CorrelationClusterMap, ...]
    primary_map: CorrelationClusterMap
    first_pc_transforms: tuple[FirstPCTransform, ...]
    importance_unit: Literal["cluster"] = "cluster"


@dataclass(frozen=True, slots=True)
class ReducedFeatureRow:
    """Apply-only cluster view. Missing members remain explicit and are never zero-filled."""

    source_row_index: int
    values: Mapping[str, float | None]
    missing_indicators: Mapping[str, bool]
    validity_indicators: Mapping[str, bool]


ModelInputRow = Mapping[str, float | None] | ReducedFeatureRow
ModelKind = Literal[
    "zero_return_baseline",
    "training_mean_baseline",
    "state_linear_baseline",
    "elastic_net",
    "shallow_gradient_boosting",
]


ELASTIC_NET_CONFIG_GRID: Final = tuple(
    (alpha, l1_ratio)
    for alpha in (0.0001, 0.001, 0.01, 0.1, 1.0)
    for l1_ratio in (0.1, 0.5, 0.9, 1.0)
)
BOOSTED_TREE_CONFIG_GRID: Final = tuple(
    (maximum_depth, maximum_leaves, learning_rate, minimum_leaf_size)
    for maximum_depth, maximum_leaves in ((1, 2), (2, 4), (3, 8))
    for learning_rate in (0.03, 0.05, 0.1)
    for minimum_leaf_size in (10, 25, 50)
)


@dataclass(frozen=True, slots=True)
class ModelTransform:
    """Train-fitted feature transform; missing values are never interpreted as economic zero."""

    input_features: tuple[str, ...]
    output_features: tuple[str, ...]
    medians: tuple[float, ...]
    centers: tuple[float, ...]
    scales: tuple[float, ...]
    training_row_count: int


@dataclass(frozen=True, slots=True)
class ElasticNetConfig:
    alpha: float = 0.01
    l1_ratio: float = 0.5
    maximum_iterations: int = 10_000
    tolerance: float = 1e-10

    def __post_init__(self) -> None:
        if (self.alpha, self.l1_ratio) not in ELASTIC_NET_CONFIG_GRID:
            raise ValueError("elastic-net alpha/l1 ratio must come from the frozen grid")
        if self.maximum_iterations < 1 or self.tolerance <= 0.0:
            raise ValueError("elastic-net iteration limit and tolerance must be positive")


@dataclass(frozen=True, slots=True)
class ElasticNetModel:
    version: str
    transform: ModelTransform
    config: ElasticNetConfig
    intercept: float
    coefficients: tuple[float, ...]
    iterations: int
    converged: bool
    model_kind: Literal["elastic_net"] = "elastic_net"


@dataclass(frozen=True, slots=True)
class BoostedTreeConfig:
    maximum_depth: int = 2
    maximum_leaves: int = 4
    learning_rate: float = 0.05
    minimum_leaf_size: int = 10
    maximum_estimators: int = 200
    threshold_candidates: int = 31
    early_stopping_patience: int = 20
    early_stopping_minimum_improvement: float = 0.0

    def __post_init__(self) -> None:
        grid_key = (
            self.maximum_depth,
            self.maximum_leaves,
            self.learning_rate,
            self.minimum_leaf_size,
        )
        if grid_key not in BOOSTED_TREE_CONFIG_GRID:
            raise ValueError("boosted-tree structural parameters must come from the frozen grid")
        if self.maximum_estimators < 1 or self.threshold_candidates < 1:
            raise ValueError("estimator and threshold-candidate counts must be positive")
        if self.early_stopping_patience < 1:
            raise ValueError("early-stopping patience must be positive")
        if self.early_stopping_minimum_improvement < 0.0:
            raise ValueError("early-stopping minimum improvement must be non-negative")


@dataclass(frozen=True, slots=True)
class RegressionTreeNode:
    value: float
    feature_index: int | None = None
    threshold: float | None = None
    left: RegressionTreeNode | None = None
    right: RegressionTreeNode | None = None

    @property
    def is_leaf(self) -> bool:
        return self.feature_index is None


@dataclass(frozen=True, slots=True)
class ShallowGradientBoostingModel:
    version: str
    transform: ModelTransform
    config: BoostedTreeConfig
    intercept: float
    trees: tuple[RegressionTreeNode, ...]
    best_iteration: int
    validation_loss_by_iteration: tuple[float, ...]
    model_kind: Literal["shallow_gradient_boosting"] = "shallow_gradient_boosting"


@dataclass(frozen=True, slots=True)
class ConstantBaselineModel:
    value: float
    model_kind: Literal["zero_return_baseline", "training_mean_baseline"]


@dataclass(frozen=True, slots=True)
class StateLinearBaselineModel:
    transform: ModelTransform
    intercept: float
    coefficients: tuple[float, ...]
    ridge_penalty: float
    model_kind: Literal["state_linear_baseline"] = "state_linear_baseline"


PredictiveModel = (
    ElasticNetModel
    | ShallowGradientBoostingModel
    | ConstantBaselineModel
    | StateLinearBaselineModel
)


@dataclass(frozen=True, slots=True)
class PredictionResult:
    model_kind: ModelKind
    predictions: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    observation_count: int
    mean_squared_error: float
    mean_absolute_error: float
    r_squared_vs_zero: float | None
    r_squared_vs_training_mean: float | None
    pearson_correlation: float | None
    directional_accuracy: float


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


def _training_feature_vector(
    artifact: FeatureQualityGateArtifact, feature_name: str
) -> tuple[float | None, ...]:
    return tuple(
        artifact.rows[index].feature_values.get(feature_name)
        if artifact.rows[index].row_valid
        and artifact.rows[index].validity_indicators.get(feature_name, False)
        else None
        for index in artifact.training_row_indices
    )


def _pairwise_spearman(
    left: Sequence[float | None],
    right: Sequence[float | None],
    *,
    minimum_pair_count: int,
) -> tuple[int, float | None, PairStatus]:
    paired = tuple(
        (left_value, right_value)
        for left_value, right_value in zip(left, right, strict=True)
        if left_value is not None and right_value is not None
    )
    if len(paired) < minimum_pair_count:
        return len(paired), None, "insufficient_pairs"
    left_ranks = np.asarray(rankdata([item[0] for item in paired], method="average"), dtype=float)
    right_ranks = np.asarray(rankdata([item[1] for item in paired], method="average"), dtype=float)
    left_centered = left_ranks - float(np.mean(left_ranks))
    right_centered = right_ranks - float(np.mean(right_ranks))
    denominator = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denominator == 0.0:
        return len(paired), None, "zero_rank_variance"
    rho = float(np.dot(left_centered, right_centered) / denominator)
    return len(paired), max(-1.0, min(1.0, rho)), "estimated"


def _training_reduction_fingerprint(
    artifact: FeatureQualityGateArtifact,
    feature_names: tuple[str, ...],
    config: CorrelationReductionConfig,
) -> str:
    payload = {
        "source_gate_version": artifact.version,
        "registry_version": artifact.registry_version,
        "training_row_indices": artifact.training_row_indices,
        "features": feature_names,
        "training_values": {
            name: _training_feature_vector(artifact, name) for name in feature_names
        },
        "config": {
            "minimum_pair_count": config.minimum_pair_count,
            "sensitivity_thresholds": config.sensitivity_thresholds,
            "primary_threshold": config.primary_threshold,
            "representation": config.representation,
            "measurement_quality_by_feature": sorted(
                (config.measurement_quality_by_feature or {}).items()
            ),
            "minimum_pca_complete_rows": config.minimum_pca_complete_rows,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _representative(
    members: tuple[str, ...],
    *,
    coverage_by_feature: Mapping[str, float],
    quality_by_feature: Mapping[str, float],
) -> str:
    """Choose by pre-outcome measurement quality, coverage, then lexical stable name."""

    return min(
        members,
        key=lambda name: (
            -quality_by_feature.get(name, 0.0),
            -coverage_by_feature[name],
            name,
        ),
    )


def _canonical_cluster_map(
    *,
    feature_names: tuple[str, ...],
    raw_labels: Sequence[int],
    threshold: float,
    coverage_by_feature: Mapping[str, float],
    quality_by_feature: Mapping[str, float],
) -> CorrelationClusterMap:
    grouped: dict[int, list[str]] = {}
    for name, label in zip(feature_names, raw_labels, strict=True):
        grouped.setdefault(int(label), []).append(name)
    clusters: list[ClusterDefinition] = []
    for names in grouped.values():
        members = tuple(sorted(names))
        representative = _representative(
            members,
            coverage_by_feature=coverage_by_feature,
            quality_by_feature=quality_by_feature,
        )
        clusters.append(
            ClusterDefinition(
                f"cluster__{representative}",
                members,
                representative,
                quality_by_feature.get(representative, 0.0),
                coverage_by_feature[representative],
            )
        )
    clusters.sort(key=lambda item: item.cluster_id)
    return CorrelationClusterMap(threshold, 1.0 - threshold, tuple(clusters))


def _fit_first_pc(
    cluster: ClusterDefinition,
    *,
    artifact: FeatureQualityGateArtifact,
    minimum_complete_rows: int,
) -> FirstPCTransform:
    members = cluster.members
    complete: list[list[float]] = []
    for row_index in artifact.training_row_indices:
        row = artifact.rows[row_index]
        values = [row.feature_values.get(name) for name in members]
        if row.row_valid and all(
            value is not None and row.validity_indicators.get(name, False)
            for name, value in zip(members, values, strict=True)
        ):
            complete.append([cast(float, value) for value in values])
    required = 1 if len(members) == 1 else minimum_complete_rows
    if len(complete) < required:
        raise ValueError(
            f"cluster {cluster.cluster_id} has {len(complete)} complete training rows; "
            f"requires {required} for first-PC fitting"
        )
    matrix = np.asarray(complete, dtype=float)
    center_array = np.mean(matrix, axis=0)
    if len(members) == 1:
        loading_array = np.asarray([1.0])
    else:
        centered = matrix - center_array
        if not np.any(centered):
            raise ValueError(f"cluster {cluster.cluster_id} has zero complete-case variance")
        _, _, right_vectors = np.linalg.svd(centered, full_matrices=False)
        loading_array = np.asarray(right_vectors[0], dtype=float)
    absolute = np.abs(loading_array)
    anchor_index = int(np.argmax(absolute))
    if loading_array[anchor_index] < 0.0:
        loading_array = -loading_array
    return FirstPCTransform(
        cluster.cluster_id,
        members,
        tuple(float(value) for value in center_array),
        tuple(float(value) for value in loading_array),
        len(complete),
        members[anchor_index],
    )


def fit_correlated_feature_reduction(
    artifact: FeatureQualityGateArtifact,
    *,
    config: CorrelationReductionConfig | None = None,
) -> CorrelatedFeatureReductionArtifact:
    """Fit deterministic correlation clusters from the gate's declared training rows only.

    Targets and held-out row values are neither accepted as arguments nor read. Pairwise missing
    observations are dropped only for that pair. A pair below the explicit support floor receives
    distance one and therefore cannot merge at any frozen sensitivity cut.
    """

    policy = config or CorrelationReductionConfig()
    feature_names = tuple(sorted(artifact.eligible_features))
    if not feature_names:
        raise ValueError("at least one gate-eligible feature is required")
    quality = dict(policy.measurement_quality_by_feature or {})
    unknown_quality = set(quality) - set(feature_names)
    if unknown_quality:
        raise ValueError(
            f"measurement quality supplied for ineligible features: {sorted(unknown_quality)}"
        )
    vectors = {name: _training_feature_vector(artifact, name) for name in feature_names}
    coverage = {
        name: sum(value is not None for value in vectors[name]) / len(artifact.training_row_indices)
        for name in feature_names
    }
    distances = np.zeros((len(feature_names), len(feature_names)), dtype=float)
    diagnostics: list[PairwiseSpearmanDiagnostic] = []
    for left_index, left_name in enumerate(feature_names):
        for right_index in range(left_index + 1, len(feature_names)):
            right_name = feature_names[right_index]
            pair_count, rho, status = _pairwise_spearman(
                vectors[left_name],
                vectors[right_name],
                minimum_pair_count=policy.minimum_pair_count,
            )
            distance = 1.0 if rho is None else 1.0 - abs(rho)
            distances[left_index, right_index] = distance
            distances[right_index, left_index] = distance
            diagnostics.append(
                PairwiseSpearmanDiagnostic(
                    left_name, right_name, pair_count, rho, distance, status
                )
            )

    if len(feature_names) == 1:
        raw_labels_by_threshold = {
            threshold: np.asarray([1], dtype=int)
            for threshold in policy.sensitivity_thresholds
        }
    else:
        condensed = squareform(distances, checks=True)
        hierarchy = linkage(condensed, method="average", optimal_ordering=False)
        raw_labels_by_threshold = {
            threshold: fcluster(hierarchy, t=1.0 - threshold, criterion="distance")
            for threshold in policy.sensitivity_thresholds
        }
    maps = tuple(
        _canonical_cluster_map(
            feature_names=feature_names,
            raw_labels=tuple(int(value) for value in raw_labels_by_threshold[threshold]),
            threshold=threshold,
            coverage_by_feature=coverage,
            quality_by_feature=quality,
        )
        for threshold in policy.sensitivity_thresholds
    )
    primary = next(
        cluster_map
        for cluster_map in maps
        if cluster_map.absolute_correlation_threshold == policy.primary_threshold
    )
    pc_transforms = (
        tuple(
            _fit_first_pc(
                cluster,
                artifact=artifact,
                minimum_complete_rows=policy.minimum_pca_complete_rows,
            )
            for cluster in primary.clusters
        )
        if policy.representation == "first_pc"
        else ()
    )
    return CorrelatedFeatureReductionArtifact(
        CORRELATION_ARTIFACT_VERSION,
        SPECIFICATION_ID,
        SPECIFICATION_VERSION,
        artifact.registry_version,
        artifact.version,
        policy,
        artifact.training_row_indices,
        _training_reduction_fingerprint(artifact, feature_names, policy),
        feature_names,
        tuple(diagnostics),
        maps,
        primary,
        pc_transforms,
    )


def apply_correlated_feature_reduction(
    artifact: CorrelatedFeatureReductionArtifact,
    rows: Sequence[GatedFeatureRow],
) -> tuple[ReducedFeatureRow, ...]:
    """Apply the frozen representative or first-PC map without refitting any state."""

    pc_by_cluster = {item.cluster_id: item for item in artifact.first_pc_transforms}
    reduced: list[ReducedFeatureRow] = []
    for row in rows:
        values: dict[str, float | None] = {}
        missing: dict[str, bool] = {}
        validity: dict[str, bool] = {}
        for cluster in artifact.primary_map.clusters:
            if artifact.config.representation == "representative":
                source = cluster.representative
                value = row.feature_values.get(source)
                is_valid = (
                    row.row_valid
                    and value is not None
                    and row.validity_indicators.get(source, False)
                )
                values[cluster.cluster_id] = value if is_valid else None
                missing[cluster.cluster_id] = row.missing_indicators.get(source, value is None)
                validity[cluster.cluster_id] = is_valid
                continue
            transform = pc_by_cluster[cluster.cluster_id]
            source_values = [row.feature_values.get(name) for name in transform.members]
            is_valid = row.row_valid and all(
                value is not None and row.validity_indicators.get(name, False)
                for name, value in zip(transform.members, source_values, strict=True)
            )
            values[cluster.cluster_id] = (
                float(
                    np.dot(
                        np.asarray([cast(float, value) for value in source_values])
                        - np.asarray(transform.center),
                        np.asarray(transform.loadings),
                    )
                )
                if is_valid
                else None
            )
            missing[cluster.cluster_id] = any(
                row.missing_indicators.get(name, value is None)
                for name, value in zip(transform.members, source_values, strict=True)
            )
            validity[cluster.cluster_id] = is_valid
        reduced.append(ReducedFeatureRow(row.source_row_index, values, missing, validity))
    return tuple(reduced)


def _model_row_values(row: ModelInputRow) -> Mapping[str, float | None]:
    return row.values if isinstance(row, ReducedFeatureRow) else row


def _validate_targets(targets: Sequence[float], expected_rows: int) -> NDArray[np.float64]:
    if len(targets) != expected_rows or expected_rows == 0:
        raise ValueError("targets must be non-empty and match the supplied rows")
    array = np.asarray(targets, dtype=float)
    if array.ndim != 1 or not np.all(np.isfinite(array)):
        raise ValueError("targets must be a finite one-dimensional sequence")
    return array


def fit_model_transform(
    rows: Sequence[ModelInputRow], *, feature_names: Sequence[str]
) -> ModelTransform:
    """Fit median-imputation, missing indicators, centering and scaling on training rows only."""

    names = tuple(feature_names)
    if not rows or not names:
        raise ValueError("training rows and feature names must be non-empty")
    if len(names) != len(set(names)):
        raise ValueError("model feature names must be unique")
    raw = np.full((len(rows), len(names)), np.nan, dtype=float)
    for row_index, row in enumerate(rows):
        values = _model_row_values(row)
        for column, name in enumerate(names):
            value = _finite(values.get(name))
            if value is not None:
                raw[row_index, column] = value
    medians: list[float] = []
    for column, name in enumerate(names):
        finite = raw[np.isfinite(raw[:, column]), column]
        if finite.size == 0:
            raise ValueError(f"training feature {name} has no finite values")
        medians.append(float(np.median(finite)))
    missing = ~np.isfinite(raw)
    imputed = np.where(missing, np.asarray(medians)[None, :], raw)
    design = np.concatenate((imputed, missing.astype(float)), axis=1)
    centers = np.mean(design, axis=0)
    scales = np.std(design, axis=0)
    scales = np.where(scales > 0.0, scales, 1.0)
    output_names = (*names, *(f"missing__{name}" for name in names))
    return ModelTransform(
        names,
        tuple(output_names),
        tuple(medians),
        tuple(float(value) for value in centers),
        tuple(float(value) for value in scales),
        len(rows),
    )


def apply_model_transform(
    transform: ModelTransform, rows: Sequence[ModelInputRow]
) -> NDArray[np.float64]:
    """Apply saved training state. Held-out rows cannot refit medians, centers or scales."""

    raw = np.full((len(rows), len(transform.input_features)), np.nan, dtype=float)
    for row_index, row in enumerate(rows):
        values = _model_row_values(row)
        for column, name in enumerate(transform.input_features):
            value = _finite(values.get(name))
            if value is not None:
                raw[row_index, column] = value
    missing = ~np.isfinite(raw)
    imputed = np.where(missing, np.asarray(transform.medians)[None, :], raw)
    design = np.concatenate((imputed, missing.astype(float)), axis=1)
    transformed = (design - np.asarray(transform.centers)) / np.asarray(transform.scales)
    if not np.all(np.isfinite(transformed)):
        raise ValueError("model transform produced non-finite values")
    return np.asarray(transformed, dtype=float)


def fit_elastic_net(
    training_rows: Sequence[ModelInputRow],
    training_targets: Sequence[float],
    *,
    feature_names: Sequence[str],
    config: ElasticNetConfig | None = None,
) -> ElasticNetModel:
    """Fit deterministic cyclic-coordinate elastic net without removing correlated columns."""

    policy = config or ElasticNetConfig()
    target = _validate_targets(training_targets, len(training_rows))
    transform = fit_model_transform(training_rows, feature_names=feature_names)
    design = apply_model_transform(transform, training_rows)
    centered_target = target - float(np.mean(target))
    coefficients = np.zeros(design.shape[1], dtype=float)
    prediction = np.zeros(len(target), dtype=float)
    converged = False
    iterations = 0
    for _iteration in range(1, policy.maximum_iterations + 1):
        iterations = _iteration
        maximum_change = 0.0
        for column in range(design.shape[1]):
            values = design[:, column]
            residual_without_column = centered_target - prediction + values * coefficients[column]
            correlation = float(np.dot(values, residual_without_column) / len(target))
            threshold = policy.alpha * policy.l1_ratio
            shrunk = math.copysign(max(abs(correlation) - threshold, 0.0), correlation)
            denominator = float(np.dot(values, values) / len(target)) + policy.alpha * (
                1.0 - policy.l1_ratio
            )
            updated = shrunk / denominator if denominator > 0.0 else 0.0
            change = updated - coefficients[column]
            if change != 0.0:
                prediction += values * change
                coefficients[column] = updated
                maximum_change = max(maximum_change, abs(change))
        if maximum_change <= policy.tolerance:
            converged = True
            break
    return ElasticNetModel(
        PREDICTIVE_MODEL_ARTIFACT_VERSION,
        transform,
        policy,
        float(np.mean(target)),
        tuple(float(value) for value in coefficients),
        iterations,
        converged,
    )


@dataclass(slots=True)
class _TreeLeaf:
    node_id: int
    indices: NDArray[np.int64]
    depth: int


def _threshold_grid(
    design: NDArray[np.float64], candidates: int
) -> tuple[tuple[float, ...], ...]:
    probabilities = np.arange(1, candidates + 1, dtype=float) / (candidates + 1)
    return tuple(
        tuple(float(value) for value in np.unique(np.quantile(design[:, column], probabilities)))
        for column in range(design.shape[1])
    )


def _best_leaf_split(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    leaf: _TreeLeaf,
    thresholds: tuple[tuple[float, ...], ...],
    minimum_leaf_size: int,
) -> tuple[float, int, float, NDArray[np.int64], NDArray[np.int64]] | None:
    indices = leaf.indices
    if len(indices) < 2 * minimum_leaf_size:
        return None
    values = target[indices]
    parent_sse = float(np.sum((values - np.mean(values)) ** 2))
    best: tuple[float, int, float, NDArray[np.int64], NDArray[np.int64]] | None = None
    for feature_index, candidates in enumerate(thresholds):
        column = design[indices, feature_index]
        for threshold in candidates:
            left_mask = column <= threshold
            left = indices[left_mask]
            right = indices[~left_mask]
            if len(left) < minimum_leaf_size or len(right) < minimum_leaf_size:
                continue
            left_values = target[left]
            right_values = target[right]
            child_sse = float(
                np.sum((left_values - np.mean(left_values)) ** 2)
                + np.sum((right_values - np.mean(right_values)) ** 2)
            )
            gain = parent_sse - child_sse
            candidate = (gain, feature_index, threshold, left, right)
            if best is None or gain > best[0] + 1e-15 or (
                abs(gain - best[0]) <= 1e-15
                and (feature_index, threshold) < (best[1], best[2])
            ):
                best = candidate
    return best if best is not None and best[0] > 0.0 else None


def _fit_regression_tree(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    *,
    thresholds: tuple[tuple[float, ...], ...],
    config: BoostedTreeConfig,
) -> RegressionTreeNode:
    leaves: dict[int, _TreeLeaf] = {0: _TreeLeaf(0, np.arange(len(target)), 0)}
    children: dict[int, tuple[int, float, int, int]] = {}
    next_id = 1
    while len(leaves) < config.maximum_leaves:
        choices: list[
            tuple[
                float,
                int,
                int,
                float,
                NDArray[np.int64],
                NDArray[np.int64],
            ]
        ] = []
        for leaf_id, leaf in sorted(leaves.items()):
            if leaf.depth >= config.maximum_depth:
                continue
            split = _best_leaf_split(
                design, target, leaf, thresholds, config.minimum_leaf_size
            )
            if split is not None:
                gain, feature_index, threshold, left, right = split
                choices.append((gain, leaf_id, feature_index, threshold, left, right))
        if not choices:
            break
        gain, leaf_id, feature_index, threshold, left, right = min(
            choices, key=lambda item: (-item[0], item[1], item[2], item[3])
        )
        del gain
        parent = leaves.pop(leaf_id)
        left_id, right_id = next_id, next_id + 1
        next_id += 2
        leaves[left_id] = _TreeLeaf(left_id, left, parent.depth + 1)
        leaves[right_id] = _TreeLeaf(right_id, right, parent.depth + 1)
        children[leaf_id] = (feature_index, threshold, left_id, right_id)

    def freeze(node_id: int) -> RegressionTreeNode:
        if node_id in leaves:
            indices = leaves[node_id].indices
            return RegressionTreeNode(float(np.mean(target[indices])))
        feature_index, threshold, left_id, right_id = children[node_id]
        return RegressionTreeNode(
            0.0,
            feature_index,
            threshold,
            freeze(left_id),
            freeze(right_id),
        )

    return freeze(0)


def _predict_tree_row(node: RegressionTreeNode, row: NDArray[np.float64]) -> float:
    current = node
    while not current.is_leaf:
        assert current.feature_index is not None and current.threshold is not None
        assert current.left is not None and current.right is not None
        current = current.left if row[current.feature_index] <= current.threshold else current.right
    return current.value


def _predict_tree(
    node: RegressionTreeNode, design: NDArray[np.float64]
) -> NDArray[np.float64]:
    return np.asarray([_predict_tree_row(node, row) for row in design], dtype=float)


def fit_shallow_gradient_boosting(
    training_rows: Sequence[ModelInputRow],
    training_targets: Sequence[float],
    *,
    feature_names: Sequence[str],
    config: BoostedTreeConfig | None = None,
    validation_rows: Sequence[ModelInputRow] | None = None,
    validation_targets: Sequence[float] | None = None,
) -> ShallowGradientBoostingModel:
    """Fit deterministic shallow boosted trees; validation may select only tree count."""

    policy = config or BoostedTreeConfig()
    train_target = _validate_targets(training_targets, len(training_rows))
    if (validation_rows is None) != (validation_targets is None):
        raise ValueError("validation rows and targets must be supplied together")
    transform = fit_model_transform(training_rows, feature_names=feature_names)
    train_design = apply_model_transform(transform, training_rows)
    validation_design = (
        apply_model_transform(transform, validation_rows) if validation_rows is not None else None
    )
    if validation_rows is not None:
        assert validation_targets is not None
        validation_target = _validate_targets(validation_targets, len(validation_rows))
    else:
        validation_target = None
    thresholds = _threshold_grid(train_design, policy.threshold_candidates)
    intercept = float(np.mean(train_target))
    train_prediction = np.full(len(train_target), intercept, dtype=float)
    validation_prediction = (
        np.full(len(validation_target), intercept, dtype=float)
        if validation_target is not None
        else None
    )
    trees: list[RegressionTreeNode] = []
    validation_losses: list[float] = []
    best_iteration = 0
    best_loss = (
        float(np.mean((validation_target - intercept) ** 2))
        if validation_target is not None
        else math.inf
    )
    stale_rounds = 0
    for _ in range(policy.maximum_estimators):
        tree = _fit_regression_tree(
            train_design,
            train_target - train_prediction,
            thresholds=thresholds,
            config=policy,
        )
        trees.append(tree)
        train_prediction += policy.learning_rate * _predict_tree(tree, train_design)
        if validation_target is None or validation_prediction is None or validation_design is None:
            best_iteration = len(trees)
            continue
        validation_prediction += policy.learning_rate * _predict_tree(tree, validation_design)
        loss = float(np.mean((validation_target - validation_prediction) ** 2))
        validation_losses.append(loss)
        if loss < best_loss - policy.early_stopping_minimum_improvement:
            best_loss = loss
            best_iteration = len(trees)
            stale_rounds = 0
        else:
            stale_rounds += 1
            if stale_rounds >= policy.early_stopping_patience:
                break
    if validation_target is not None:
        trees = trees[:best_iteration]
    return ShallowGradientBoostingModel(
        PREDICTIVE_MODEL_ARTIFACT_VERSION,
        transform,
        policy,
        intercept,
        tuple(trees),
        best_iteration,
        tuple(validation_losses),
    )


def zero_return_baseline() -> ConstantBaselineModel:
    return ConstantBaselineModel(0.0, "zero_return_baseline")


def fit_training_mean_baseline(training_targets: Sequence[float]) -> ConstantBaselineModel:
    target = _validate_targets(training_targets, len(training_targets))
    return ConstantBaselineModel(float(np.mean(target)), "training_mean_baseline")


def fit_state_linear_baseline(
    training_rows: Sequence[ModelInputRow],
    training_targets: Sequence[float],
    *,
    state_feature_names: Sequence[str],
    ridge_penalty: float = 1e-6,
) -> StateLinearBaselineModel:
    """Fit a small declared-state ridge baseline using the same train-only missing transform."""

    if ridge_penalty < 0.0 or not math.isfinite(ridge_penalty):
        raise ValueError("ridge penalty must be finite and non-negative")
    target = _validate_targets(training_targets, len(training_rows))
    transform = fit_model_transform(training_rows, feature_names=state_feature_names)
    design = apply_model_transform(transform, training_rows)
    centered_target = target - float(np.mean(target))
    gram = design.T @ design + ridge_penalty * np.eye(design.shape[1])
    coefficients = np.linalg.solve(gram, design.T @ centered_target)
    return StateLinearBaselineModel(
        transform,
        float(np.mean(target)),
        tuple(float(value) for value in coefficients),
        ridge_penalty,
    )


def predict_model(model: PredictiveModel, rows: Sequence[ModelInputRow]) -> PredictionResult:
    """Common deterministic prediction contract for baselines and both model classes."""

    if isinstance(model, ConstantBaselineModel):
        predictions = np.full(len(rows), model.value, dtype=float)
    else:
        design = apply_model_transform(model.transform, rows)
        if isinstance(model, ShallowGradientBoostingModel):
            predictions = np.full(len(rows), model.intercept, dtype=float)
            for tree in model.trees:
                predictions += model.config.learning_rate * _predict_tree(tree, design)
        else:
            predictions = model.intercept + design @ np.asarray(model.coefficients)
    if not np.all(np.isfinite(predictions)):
        raise ValueError("model produced non-finite predictions")
    return PredictionResult(model.model_kind, tuple(float(value) for value in predictions))


def regression_metrics(
    targets: Sequence[float],
    predictions: Sequence[float],
    *,
    training_mean: float,
) -> RegressionMetrics:
    target = _validate_targets(targets, len(predictions))
    predicted = np.asarray(predictions, dtype=float)
    if predicted.ndim != 1:
        raise ValueError("predictions must be one-dimensional")
    if not math.isfinite(training_mean) or not np.all(np.isfinite(predicted)):
        raise ValueError("predictions and training mean must be finite")
    errors = target - predicted
    squared_error = float(np.sum(errors**2))
    zero_error = float(np.sum(target**2))
    mean_error = float(np.sum((target - training_mean) ** 2))
    target_centered = target - float(np.mean(target))
    predicted_centered = predicted - float(np.mean(predicted))
    denominator = float(np.linalg.norm(target_centered) * np.linalg.norm(predicted_centered))
    correlation = (
        float(np.dot(target_centered, predicted_centered) / denominator)
        if denominator > 0.0
        else None
    )
    return RegressionMetrics(
        len(target),
        float(np.mean(errors**2)),
        float(np.mean(np.abs(errors))),
        1.0 - squared_error / zero_error if zero_error > 0.0 else None,
        1.0 - squared_error / mean_error if mean_error > 0.0 else None,
        correlation,
        float(np.mean(np.sign(target) == np.sign(predicted))),
    )


def _transform_to_dict(transform: ModelTransform) -> dict[str, object]:
    return {
        "input_features": transform.input_features,
        "output_features": transform.output_features,
        "medians": transform.medians,
        "centers": transform.centers,
        "scales": transform.scales,
        "training_row_count": transform.training_row_count,
    }


def _transform_from_dict(payload: Mapping[str, object]) -> ModelTransform:
    return ModelTransform(
        tuple(cast(Sequence[str], payload["input_features"])),
        tuple(cast(Sequence[str], payload["output_features"])),
        tuple(float(value) for value in cast(Sequence[float], payload["medians"])),
        tuple(float(value) for value in cast(Sequence[float], payload["centers"])),
        tuple(float(value) for value in cast(Sequence[float], payload["scales"])),
        int(cast(int, payload["training_row_count"])),
    )


def _tree_to_dict(node: RegressionTreeNode) -> dict[str, object]:
    if node.is_leaf:
        return {"value": node.value}
    assert node.feature_index is not None and node.threshold is not None
    assert node.left is not None and node.right is not None
    return {
        "value": node.value,
        "feature_index": node.feature_index,
        "threshold": node.threshold,
        "left": _tree_to_dict(node.left),
        "right": _tree_to_dict(node.right),
    }


def _tree_from_dict(payload: Mapping[str, object]) -> RegressionTreeNode:
    if "feature_index" not in payload:
        return RegressionTreeNode(float(cast(float, payload["value"])))
    return RegressionTreeNode(
        float(cast(float, payload["value"])),
        int(cast(int, payload["feature_index"])),
        float(cast(float, payload["threshold"])),
        _tree_from_dict(cast(Mapping[str, object], payload["left"])),
        _tree_from_dict(cast(Mapping[str, object], payload["right"])),
    )


def predictive_model_to_json(model: PredictiveModel) -> str:
    """Serialize the complete apply-only state with stable, sorted JSON keys."""

    payload: dict[str, object] = {"model_kind": model.model_kind}
    if isinstance(model, ConstantBaselineModel):
        payload["value"] = model.value
    elif isinstance(model, ElasticNetModel):
        payload.update(
            version=model.version,
            transform=_transform_to_dict(model.transform),
            config={
                "alpha": model.config.alpha,
                "l1_ratio": model.config.l1_ratio,
                "maximum_iterations": model.config.maximum_iterations,
                "tolerance": model.config.tolerance,
            },
            intercept=model.intercept,
            coefficients=model.coefficients,
            iterations=model.iterations,
            converged=model.converged,
        )
    elif isinstance(model, StateLinearBaselineModel):
        payload.update(
            transform=_transform_to_dict(model.transform),
            intercept=model.intercept,
            coefficients=model.coefficients,
            ridge_penalty=model.ridge_penalty,
        )
    else:
        payload.update(
            version=model.version,
            transform=_transform_to_dict(model.transform),
            config={
                "maximum_depth": model.config.maximum_depth,
                "maximum_leaves": model.config.maximum_leaves,
                "learning_rate": model.config.learning_rate,
                "minimum_leaf_size": model.config.minimum_leaf_size,
                "maximum_estimators": model.config.maximum_estimators,
                "threshold_candidates": model.config.threshold_candidates,
                "early_stopping_patience": model.config.early_stopping_patience,
                "early_stopping_minimum_improvement": (
                    model.config.early_stopping_minimum_improvement
                ),
            },
            intercept=model.intercept,
            trees=tuple(_tree_to_dict(tree) for tree in model.trees),
            best_iteration=model.best_iteration,
            validation_loss_by_iteration=model.validation_loss_by_iteration,
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def predictive_model_from_json(encoded: str) -> PredictiveModel:
    payload = cast(Mapping[str, object], json.loads(encoded))
    kind = payload.get("model_kind")
    if kind in ("zero_return_baseline", "training_mean_baseline"):
        return ConstantBaselineModel(
            float(cast(float, payload["value"])),
            kind,
        )
    transform = _transform_from_dict(cast(Mapping[str, object], payload["transform"]))
    if kind == "elastic_net":
        config_payload = cast(Mapping[str, object], payload["config"])
        elastic_config = ElasticNetConfig(
            alpha=float(cast(float, config_payload["alpha"])),
            l1_ratio=float(cast(float, config_payload["l1_ratio"])),
            maximum_iterations=int(cast(int, config_payload["maximum_iterations"])),
            tolerance=float(cast(float, config_payload["tolerance"])),
        )
        return ElasticNetModel(
            str(payload["version"]),
            transform,
            elastic_config,
            float(cast(float, payload["intercept"])),
            tuple(float(value) for value in cast(Sequence[float], payload["coefficients"])),
            int(cast(int, payload["iterations"])),
            bool(payload["converged"]),
        )
    if kind == "state_linear_baseline":
        return StateLinearBaselineModel(
            transform,
            float(cast(float, payload["intercept"])),
            tuple(float(value) for value in cast(Sequence[float], payload["coefficients"])),
            float(cast(float, payload["ridge_penalty"])),
        )
    if kind == "shallow_gradient_boosting":
        config_payload = cast(Mapping[str, object], payload["config"])
        boosted_config = BoostedTreeConfig(
            maximum_depth=int(cast(int, config_payload["maximum_depth"])),
            maximum_leaves=int(cast(int, config_payload["maximum_leaves"])),
            learning_rate=float(cast(float, config_payload["learning_rate"])),
            minimum_leaf_size=int(cast(int, config_payload["minimum_leaf_size"])),
            maximum_estimators=int(cast(int, config_payload["maximum_estimators"])),
            threshold_candidates=int(cast(int, config_payload["threshold_candidates"])),
            early_stopping_patience=int(
                cast(int, config_payload["early_stopping_patience"])
            ),
            early_stopping_minimum_improvement=float(
                cast(float, config_payload["early_stopping_minimum_improvement"])
            ),
        )
        return ShallowGradientBoostingModel(
            str(payload["version"]),
            transform,
            boosted_config,
            float(cast(float, payload["intercept"])),
            tuple(
                _tree_from_dict(item)
                for item in cast(Sequence[Mapping[str, object]], payload["trees"])
            ),
            int(cast(int, payload["best_iteration"])),
            tuple(
                float(value)
                for value in cast(Sequence[float], payload["validation_loss_by_iteration"])
            ),
        )
    raise ValueError(f"unknown predictive model kind: {kind!r}")
