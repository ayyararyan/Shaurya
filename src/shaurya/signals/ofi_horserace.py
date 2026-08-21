"""Frozen exploratory predictor horse race `X-OFI-HORSERACE-DAT20-05`.

The module compares depth, static imbalance, identified signed trades, canonical CKS L1 OFI,
raw multi-level CCZ OFI, depth-scaled multi-level CCZ OFI, and a regularised combination.  It
uses only information available at each depth200 anchor and is permanently non-confirmatory.

`CCZ-IMPL-03` and `CCZ-IMPL-04`.  The multi-level families were migrated to Cont-Cucuringu-Zhang
(arXiv:2112.13213v4) under `D37 / CCZ-OFI-MIGRATION-2026-08-20`.  Two defects were removed:

* `M4` no longer consumes price-keyed flow accumulated across levels; it is CCZ Eq. (2) per level,
  with no sum over levels anywhere, and
* `M5` no longer divides each disjoint band by *that band's own* mean depth; it is CCZ Eq. (3),
  where a **single common** ``Q^{M,h}`` divides every level so relative cross-level magnitudes
  survive the scaling.

`M3` remains the level-one CKS (2014) event increment, which is CCZ Eq. (1)'s base case and the
best-level arm of `EST-CCZ-05`.  The remaining declared aggregation arms — Eq. (19) ``PI^[m]``,
the Eq. (4) integrated OFI, and the Appendix A simple average — are evaluated across every
declared level count by :func:`evaluate_ccz_aggregation_arms`.

Pre-migration and post-migration numbers are **not** comparable and must never be pooled without
an explicit estimator column.  The snapshot relabelling limitation `ID-CCZ-01` is carried in every
artifact this module produces.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from math import isfinite, log1p, sqrt
from typing import Any, Literal

import numpy as np
from scipy.stats import norm

from shaurya.data.depth_thinning_analysis import BookState, parse_receive_ts_ns
from shaurya.data.trade_direction import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION
from shaurya.signals.ccz_ofi import (
    DECLARED_LEVEL_COUNTS,
    PRIMARY_AGGREGATION_ARM,
    PRIMARY_LEVEL_COUNT,
    CczFeatureSchema,
    CczFeatureVector,
    CczFlowSeries,
    IntegratedWeights,
    average_feature,
    best_level_feature,
    ccz_metadata,
    denominator_feature,
    fit_integrated_weights,
    integrated_feature,
    level_feature,
    normalised_level_feature,
)
from shaurya.signals.cks_l1_ofi import cks_l1_transition
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EMBARGO_SECONDS,
    Observation,
    SplitIndex,
    _r_squared,
    build_depth20_mid_series,
    chronological_embargoed_split,
    estimate_mean,
    fit_ridge,
)
from shaurya.signals.deep_book_ofi import (
    CAUSAL_GAP_SECONDS,
    OFI_WINDOWS_SECONDS,
    _controls,
    _mid_return,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND
from shaurya.signals.effective_touch import (
    PRIMARY_EFFECTIVE_TOUCH_WINDOW,
    EffectiveTouchSeries,
    build_trade_prints,
)
from shaurya.signals.evaluation_metrics import (
    assert_companion_metrics,
    benjamini_yekutieli,
    metric_bundle,
    metric_metadata,
    past_mirror_verdict,
    per_tape_sign_check,
)
from shaurya.signals.microprice import (
    MicropriceState,
    StoikovMicropriceModel,
    build_stoikov_transitions,
    classify_state,
    fit_stoikov_microprice,
    microprice_metadata,
)
from shaurya.signals.reference_prices import (
    BASELINE_REFERENCE,
    REFERENCE_PRICE_LADDER,
    build_reference_price_paths,
    reference_price_coverage,
    touch_relative_metadata,
    touch_relative_microprice_tilt_ticks,
    touch_relative_queue_imbalance,
    touch_relative_state,
)

EXPLORATORY_SCAN_ID = "X-OFI-HORSERACE-DAT20-05"
CONFIRMATORY_ELIGIBLE = False
DESIGN_DOCUMENT = "docs/OFI-HORSERACE-SPEC-2026-08-19.md"
MIGRATION_DOCUMENT = "docs/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md"
TOUCH_METRICS_DOCUMENT = "docs/TOUCH-METRICS-SPEC-2026-08-20.md"
RETURN_HORIZONS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
CONDITIONAL_HORIZON_SECONDS = 30.0

#: `WINDOW-01`.  The same-window diagnostic grid, extended to 30 s and 60 s.  60 s is CCZ's
#: contemporaneous frequency ``h = 1 minute`` exactly, and is the only cell in this repository
#: directly comparable with their published numbers.  Predictor features are therefore built at
#: every one of these windows, not only at the five predictive windows.
SAME_WINDOW_SECONDS = (*OFI_WINDOWS_SECONDS, 30.0, 60.0)
#: `WINDOW-01`.  The CCZ comparison cell.
CCZ_CONTEMPORANEOUS_WINDOW_SECONDS = 60.0

#: `WINDOW-02`.  CCZ's published contemporaneous R-squared, promoted from a footnote to a gate.
CCZ_PUBLISHED_BEST_LEVEL_IN_SAMPLE_R2 = 0.7116
CCZ_PUBLISHED_BEST_LEVEL_OUT_OF_SAMPLE_R2 = 0.6464
CCZ_PUBLISHED_INTEGRATED_IN_SAMPLE_R2 = 0.8714

#: `TOUCH-04`.  Feature name prefix for the objects re-derived against the effective touch.
TOUCH_RELATIVE_PREFIX = "et_"
#: `MICRO-02`.  The `M8` regressor: the fitted Stoikov fair-value tilt, in ticks.
STOIKOV_FEATURE = "stoikov_adjustment_ticks"

#: `EST-CCZ-06`.  ``M = 10`` is primary; ``M in {1, 5, 20, 200}`` are declared robustness arms.
CCZ_LEVEL_COUNTS = DECLARED_LEVEL_COUNTS
CCZ_PRIMARY_LEVELS = PRIMARY_LEVEL_COUNT

#: `EST-CCZ-05`.  The scalar aggregation arms evaluated at every declared level count.
CCZ_SCALAR_ARMS = ("integrated", "simple_average", "best_level")
CCZ_AGGREGATION_ARMS = ("per_level_pi", *CCZ_SCALAR_ARMS)

RIDGE_ALPHAS = (0.0, 0.01, 0.1, 1.0, 10.0, 100.0)
#: `MICRO-03`.  ``M7`` and ``M8`` enter as families, not controls.
MODEL_ORDER = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
#: `TOUCH-04`.  The book-derived families that are re-derived against the effective touch.
TOUCH_RELATIVE_MODELS = ("M1", "M5", "M7")
#: Families whose design matrix is wide enough to need the inner-CV ridge penalty.
REGULARISED_MODELS = ("M4", "M5", "M6", "ccz_per_level_pi")
MINIMUM_FIT_OBSERVATIONS = 20
MINIMUM_TRADE_PACKETS = 20
BASELINE_FEATURES = ("log1p_l1_depth", "spread_ticks")


def _label(value: float) -> str:
    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def ccz_raw_features(window: float, levels: int = CCZ_PRIMARY_LEVELS) -> tuple[str, ...]:
    """`EST-CCZ-02`: raw ``OFI^{m,h}`` for each level, entered separately, never cumulated."""

    return tuple(level_feature(window, level) for level in range(1, levels + 1))


def ccz_normalised_features(window: float, levels: int = CCZ_PRIMARY_LEVELS) -> tuple[str, ...]:
    """`EST-CCZ-03`: ``ofi^{m,h}`` for each level, all divided by one common ``Q^{M,h}``."""

    return tuple(normalised_level_feature(window, level, levels) for level in range(1, levels + 1))


def cks_feature(window: float) -> str:
    return f"cks_ofi_w{_label(window)}"


def cks_pressure_feature(window: float) -> str:
    return f"cks_pressure_w{_label(window)}"


def trade_feature(window: float) -> str:
    return f"signed_trade_imbalance_w{_label(window)}"


def normalised_trade_feature(window: float) -> str:
    return f"normalised_trade_imbalance_w{_label(window)}"


def touch_relative_feature(name: str) -> str:
    """`TOUCH-04`: the name of ``name`` re-derived against the effective touch."""

    return f"{TOUCH_RELATIVE_PREFIX}{name}"


def touch_relative_normalised_features(
    window: float, levels: int = CCZ_PRIMARY_LEVELS
) -> tuple[str, ...]:
    return tuple(touch_relative_feature(name) for name in ccz_normalised_features(window, levels))


@dataclass(frozen=True, slots=True)
class TradeSeries:
    timestamps: tuple[int, ...]
    signed_prefix: tuple[float, ...]
    absolute_prefix: tuple[float, ...]
    schema_packets: int
    qualified_packets: int
    excluded_missing_classifier_version: int
    excluded_wrong_classifier_version: int
    excluded_missing_alignment_version: int
    excluded_wrong_alignment_version: int
    excluded_coalesced: int
    excluded_degraded_or_unclassified: int

    @property
    def identified(self) -> bool:
        return self.schema_packets > 0 and self.qualified_packets >= MINIMUM_TRADE_PACKETS

    def window(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        left = bisect_right(self.timestamps, start_ns)
        right = bisect_right(self.timestamps, end_ns)
        return (
            self.signed_prefix[right] - self.signed_prefix[left],
            self.absolute_prefix[right] - self.absolute_prefix[left],
        )


def build_trade_series(rows: Sequence[Mapping[str, Any]]) -> TradeSeries:
    """Build capture-time signed executed-volume innovations; never infer an absent sign."""

    values: list[tuple[int, float, float]] = []
    schema_packets = 0
    missing_classifier = 0
    wrong_classifier = 0
    missing_alignment = 0
    wrong_alignment = 0
    coalesced = 0
    degraded = 0
    for row in rows:
        if row.get("event_type") != "full" or row.get("cumulative_volume_increment") is None:
            continue
        if not any(
            key in row
            for key in (
                "trade_side",
                "trade_classifier_version",
                "trade_alignment_version",
                "trade_classification_degraded",
                "trade_coalesced",
            )
        ):
            continue
        schema_packets += 1
        increment = float(row["cumulative_volume_increment"])
        if increment <= 0:
            continue
        classifier_version = row.get("trade_classifier_version")
        if classifier_version is None:
            missing_classifier += 1
            continue
        if classifier_version != TRADE_CLASSIFIER_VERSION:
            wrong_classifier += 1
            continue
        alignment_version = row.get("trade_alignment_version")
        if alignment_version is None:
            missing_alignment += 1
            continue
        if alignment_version != TRADE_ALIGNMENT_VERSION:
            wrong_alignment += 1
            continue
        if row.get("trade_coalesced"):
            coalesced += 1
            continue
        side = row.get("trade_side")
        if row.get("trade_classification_degraded") or side not in {"buy", "sell"}:
            degraded += 1
            continue
        quantity = row.get("last_quantity")
        stamp = row.get("receive_ts")
        if quantity is None or not isinstance(stamp, str):
            degraded += 1
            continue
        absolute_quantity = float(quantity)
        if not isfinite(absolute_quantity) or absolute_quantity <= 0:
            degraded += 1
            continue
        values.append(
            (
                parse_receive_ts_ns(stamp),
                absolute_quantity if side == "buy" else -absolute_quantity,
                absolute_quantity,
            )
        )
    values.sort()
    signed = [0.0]
    absolute_prefix = [0.0]
    for _, signed_value, absolute_value in values:
        signed.append(signed[-1] + signed_value)
        absolute_prefix.append(absolute_prefix[-1] + absolute_value)
    return TradeSeries(
        timestamps=tuple(value[0] for value in values),
        signed_prefix=tuple(signed),
        absolute_prefix=tuple(absolute_prefix),
        schema_packets=schema_packets,
        qualified_packets=len(values),
        excluded_missing_classifier_version=missing_classifier,
        excluded_wrong_classifier_version=wrong_classifier,
        excluded_missing_alignment_version=missing_alignment,
        excluded_wrong_alignment_version=wrong_alignment,
        excluded_coalesced=coalesced,
        excluded_degraded_or_unclassified=degraded,
    )


@dataclass(frozen=True, slots=True)
class HorseRaceObservation:
    tape_index: int
    run_id: str
    receive_ts_ns: int
    features: Mapping[str, float]
    future_ticks: Mapping[float, float]
    past_ticks: Mapping[float, float]
    same_window_ticks: Mapping[float, float]
    window_start_ts_ns: Mapping[float, int]
    connection_epoch: int = 1
    #: `TOUCH-03`.  Returns under each reference price in the ladder, keyed reference -> horizon.
    #: ``displayed_mid`` duplicates ``future_ticks``/``past_ticks`` so the baseline stays exactly
    #: the status quo object and post-D38 cells remain comparable with the 11:30 horse race.
    reference_future_ticks: Mapping[str, Mapping[float, float]] = field(default_factory=dict)
    reference_past_ticks: Mapping[str, Mapping[float, float]] = field(default_factory=dict)
    reference_same_window_ticks: Mapping[str, Mapping[float, float]] = field(default_factory=dict)
    #: `MICRO-02`.  The discrete Stoikov state at this anchor; the adjustment itself cannot be a
    #: build-time feature because the chain may only be fitted on training rows.
    microprice_state: str | None = None


class _FeatureOverlay(Mapping[str, float]):
    """A read-only overlay adding split-dependent columns to an interned feature vector.

    `MICRO-02` forbids fitting the Stoikov chain on anything but training rows, so its regressor
    cannot exist when the feature vector is built.  Presenting it as an overlay keeps every design
    matrix, collinearity and support code path working against a plain ``Mapping[str, float]``.
    """

    __slots__ = ("_base", "_extra")

    def __init__(self, base: Mapping[str, float], extra: Mapping[str, float]) -> None:
        self._base = base
        self._extra = dict(extra)

    def __getitem__(self, key: str) -> float:
        if key in self._extra:
            return self._extra[key]
        return self._base[key]

    def __contains__(self, key: object) -> bool:
        return key in self._extra or key in self._base

    def __iter__(self) -> Iterator[str]:
        yield from self._base
        yield from (key for key in self._extra if key not in self._base)

    def __len__(self) -> int:
        return len(self._base) + sum(1 for key in self._extra if key not in self._base)


def ccz_feature_schema(level_counts: Sequence[int] = CCZ_LEVEL_COUNTS) -> CczFeatureSchema:
    """Declare every feature name once so per-anchor vectors stay dense and interned.

    The ``M = 200`` arm alone declares one thousand per-level names across five windows, so a
    plain per-anchor ``dict`` would dominate live-dashboard memory.  The schema is shared.
    """

    counts = tuple(sorted({int(value) for value in level_counts}))
    names: list[str] = [
        *BASELINE_FEATURES,
        "l1_queue_imbalance",
        "microprice_tilt_ticks",
        touch_relative_feature("l1_queue_imbalance"),
        touch_relative_feature("microprice_tilt_ticks"),
    ]
    # `WINDOW-01`: features are built at every same-window cell, not only at the five predictive
    # windows, because the 60 s CCZ comparison cell needs a 60 s predictor as well as a 60 s
    # return.
    for window in SAME_WINDOW_SECONDS:
        names.extend(
            (
                cks_feature(window),
                cks_pressure_feature(window),
                trade_feature(window),
                normalised_trade_feature(window),
                best_level_feature(window),
            )
        )
        names.extend(level_feature(window, level) for level in range(1, counts[-1] + 1))
        for count in counts:
            names.append(denominator_feature(window, count))
            names.append(average_feature(window, count))
        for count in counts:
            names.extend(ccz_normalised_features(window, count))
            names.extend(touch_relative_normalised_features(window, count))
    return CczFeatureSchema(names)


def build_horserace_observations(
    *,
    depth200_states: Sequence[BookState],
    depth20_states: Sequence[BookState],
    rows: Sequence[Mapping[str, Any]],
    tape_index: int,
    run_id: str,
    level_counts: Sequence[int] = CCZ_LEVEL_COUNTS,
    effective_touch_window_seconds: float = PRIMARY_EFFECTIVE_TOUCH_WINDOW,
    response_horizons: Sequence[float] | None = None,
    retain_unlabelled: bool = False,
    anchor_grid_seconds: float | None = None,
    anchor_start_ts_ns: int | None = None,
    anchor_end_ts_ns: int | None = None,
) -> tuple[list[HorseRaceObservation], dict[str, Any]]:
    """Construct all predictors and responses at one common causal anchor clock.

    `TOUCH-03` adds the reference-price ladder on the response side and `TOUCH-04` the
    effective-touch re-derivation on the predictor side, both at the same anchors as everything
    else, so a cell under one reference price is comparable with the same cell under another.
    """

    counts = tuple(sorted({int(value) for value in level_counts}))
    if CCZ_PRIMARY_LEVELS not in counts:
        raise ValueError("the primary CCZ level count must be declared")
    default_horizons = (*RETURN_HORIZONS_SECONDS, CONDITIONAL_HORIZON_SECONDS)
    requested_horizons = (
        tuple(float(value) for value in response_horizons) if response_horizons is not None else ()
    )
    if response_horizons is not None and (
        not requested_horizons
        or any(not isfinite(value) or value <= 0.0 for value in requested_horizons)
    ):
        raise ValueError("response horizons must be finite and strictly positive")
    if anchor_grid_seconds is not None and (
        not isfinite(anchor_grid_seconds) or anchor_grid_seconds <= 0.0
    ):
        raise ValueError("anchor grid must be finite and strictly positive")
    if (
        anchor_start_ts_ns is not None
        and anchor_end_ts_ns is not None
        and anchor_end_ts_ns < anchor_start_ts_ns
    ):
        raise ValueError("anchor end must not precede anchor start")
    all_horizons = tuple(sorted({*default_horizons, *requested_horizons}))
    schema = ccz_feature_schema(counts)
    failures: dict[str, Any] = {
        "invalid_transition": 0,
        "incomplete_history": 0,
        "unusable_state": 0,
        "no_response_anchor": 0,
        "no_future_coverage": 0,
        "ccz_depth_denominator_floored": 0,
        "ccz_level_support_missing": {str(count): 0 for count in counts},
        "effective_touch_undefined_anchors": 0,
    }
    trades = build_trade_series(rows)
    # `TOUCH-02`/`TOUCH-04`.  Every observed print, including the ones the DAT-14 quote rule could
    # not sign, so the exclusion accounting stays visible; only signed prints reach the estimator.
    prints = build_trade_prints(rows)
    touch_series = EffectiveTouchSeries(
        prints.prints, window_seconds=effective_touch_window_seconds
    )
    failures["trade_support"] = {
        "schema_packets": trades.schema_packets,
        "qualified_packets": trades.qualified_packets,
        "excluded_missing_classifier_version": trades.excluded_missing_classifier_version,
        "excluded_wrong_classifier_version": trades.excluded_wrong_classifier_version,
        "excluded_missing_alignment_version": trades.excluded_missing_alignment_version,
        "excluded_wrong_alignment_version": trades.excluded_wrong_alignment_version,
        "excluded_coalesced": trades.excluded_coalesced,
        "excluded_degraded_or_unclassified": trades.excluded_degraded_or_unclassified,
        "identified": trades.identified,
    }
    if len(depth200_states) < 2:
        return [], failures
    cks = [
        cks_l1_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    reasons = [transition.invalid_reason for transition in cks]
    series = CczFlowSeries.from_states(
        depth200_states, level_counts=counts, invalid_reasons=reasons
    )
    # `TOUCH-04`.  The same CCZ machinery on a book re-keyed to tick-distance bands measured
    # outward from the effective touch at each state's own timestamp.  Where the touch is
    # undefined the state is refused, and its transition is marked invalid, which propagates as
    # missing through the identical code path rather than as a displayed-touch fallback.
    touch_states: list[BookState] = []
    touch_reasons: list[str | None] = []
    for position, state in enumerate(depth200_states):
        rekeyed = touch_relative_state(
            state, touch_series.at(state.receive_ts_ns), levels=counts[-1]
        )
        if rekeyed is None:
            failures["effective_touch_undefined_anchors"] += 1
            touch_states.append(state)
            if position > 0:
                touch_reasons.append("effective_touch_undefined")
            continue
        touch_states.append(rekeyed)
        if position > 0:
            touch_reasons.append(reasons[position - 1])
    for index, reason in enumerate(reasons):
        if reason is not None:
            touch_reasons[index] = reason
    touch_flow = CczFlowSeries.from_states(
        touch_states, level_counts=counts, invalid_reasons=touch_reasons
    )
    stamps = [transition.receive_ts_ns for transition in cks]
    invalid_prefix = [0]
    cks_prefix = [0.0]
    l1_depth_prefix = [0.0]
    count_prefix = [0]
    for transition in cks:
        valid = transition.invalid_reason is None
        invalid_prefix.append(invalid_prefix[-1] + int(not valid))
        failures["invalid_transition"] += int(not valid)
        cks_prefix.append(cks_prefix[-1] + (transition.event if valid else 0.0))
        l1_depth_prefix.append(
            l1_depth_prefix[-1] + (transition.half_total_depth if valid else 0.0)
        )
        count_prefix.append(count_prefix[-1] + int(valid))
    mid_series = build_depth20_mid_series(depth20_states)
    # `TOUCH-03`.  The ladder is built over the depth20 clock (and, for the effective touch, over
    # the depth20 publication timestamps) so every reference price is sampled on one common clock
    # and the four cells stay comparable.
    reference_anchors = [state.receive_ts_ns for state in depth20_states]
    reference_paths = build_reference_price_paths(
        depth20_states=depth20_states,
        prints=prints.prints,
        effective_touch=touch_series,
        anchors=reference_anchors,
    )
    observations: list[HorseRaceObservation] = []
    gap_ns = int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
    # The warm-up gate stays at the longest *predictive* window.  `WINDOW-01`'s 30 s and 60 s
    # cells are diagnostic: an anchor without 60 s of history simply has no 60 s feature, and the
    # common-sample rule then drops it from that cell alone.  Lengthening the global warm-up
    # instead would discard predictive observations to serve a diagnostic.
    longest_ns = int(max(OFI_WINDOWS_SECONDS) * NANOSECONDS_PER_SECOND)
    grid_ns = (
        None
        if anchor_grid_seconds is None
        else int(round(anchor_grid_seconds * NANOSECONDS_PER_SECOND))
    )
    last_anchor_bucket: tuple[int, int] | None = None
    for position, (state, transition) in enumerate(zip(depth200_states[1:], cks, strict=True)):
        if transition.invalid_reason is not None:
            continue
        if state.receive_ts_ns - depth200_states[0].receive_ts_ns < longest_ns:
            failures["incomplete_history"] += 1
            continue
        if anchor_start_ts_ns is not None and state.receive_ts_ns < anchor_start_ts_ns:
            continue
        if anchor_end_ts_ns is not None and state.receive_ts_ns > anchor_end_ts_ns:
            continue
        if grid_ns is not None:
            bucket = (state.connection_epoch, state.receive_ts_ns // grid_ns)
            if bucket == last_anchor_bucket:
                continue
            last_anchor_bucket = bucket
        controls = _controls(state)
        if controls is None or not state.bids or not state.asks:
            failures["unusable_state"] += 1
            continue
        bid_quantity = state.bids[0][1]
        ask_quantity = state.asks[0][1]
        total_l1 = bid_quantity + ask_quantity
        if total_l1 <= 0:
            failures["unusable_state"] += 1
            continue
        features: dict[str, float] = {
            "spread_ticks": controls["spread_ticks"],
            "microprice_tilt_ticks": controls["microprice_tilt_ticks"],
            "log1p_l1_depth": log1p(total_l1),
            "l1_queue_imbalance": (bid_quantity - ask_quantity) / total_l1,
        }
        # `TOUCH-04`.  Missing where the touch is undefined; the common-sample intersection then
        # drops the anchor from the touch-relative arms only, leaving the displayed arms intact.
        touch_here = touch_series.at(state.receive_ts_ns)
        touch_imbalance = touch_relative_queue_imbalance(state, touch_here)
        if touch_imbalance is not None:
            features[touch_relative_feature("l1_queue_imbalance")] = touch_imbalance
        touch_tilt = touch_relative_microprice_tilt_ticks(state, touch_here)
        if touch_tilt is not None:
            features[touch_relative_feature("microprice_tilt_ticks")] = touch_tilt
        window_starts: dict[float, int] = {}
        complete = True
        for window in SAME_WINDOW_SECONDS:
            predictive = window in OFI_WINDOWS_SECONDS
            start = state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND)
            left = bisect_right(stamps, start)
            right = position + 1
            if left >= right or invalid_prefix[right] - invalid_prefix[left] != 0:
                if not predictive:
                    continue
                complete = False
                break
            covered = count_prefix[right] - count_prefix[left]
            if covered <= 0:
                if not predictive:
                    continue
                complete = False
                break
            cks_value = cks_prefix[right] - cks_prefix[left]
            mean_l1_half_depth = (l1_depth_prefix[right] - l1_depth_prefix[left]) / covered
            features[cks_feature(window)] = cks_value
            features[cks_pressure_feature(window)] = cks_value / max(mean_l1_half_depth, 1.0)
            signed_trade, absolute_trade = trades.window(start, state.receive_ts_ns)
            features[trade_feature(window)] = signed_trade
            if absolute_trade > 0:
                features[normalised_trade_feature(window)] = signed_trade / absolute_trade
            primary = None
            for count in counts:
                evaluated = series.window(left, right, levels=count, window_seconds=window)
                if evaluated is None:
                    failures["ccz_level_support_missing"][str(count)] += 1
                    continue
                if evaluated.denominator_floored:
                    failures["ccz_depth_denominator_floored"] += 1
                features[denominator_feature(window, count)] = evaluated.denominator
                features[average_feature(window, count)] = evaluated.simple_average
                for level, raw_value in enumerate(evaluated.raw, start=1):
                    features[level_feature(window, level)] = raw_value
                for level, scaled in enumerate(evaluated.normalised, start=1):
                    features[normalised_level_feature(window, level, count)] = scaled
                touch_evaluated = touch_flow.window(
                    left, right, levels=count, window_seconds=window
                )
                if touch_evaluated is not None:
                    for level, scaled in enumerate(touch_evaluated.normalised, start=1):
                        features[
                            touch_relative_feature(normalised_level_feature(window, level, count))
                        ] = scaled
                if count == CCZ_PRIMARY_LEVELS:
                    primary = evaluated
                    features[best_level_feature(window)] = evaluated.best_level
            if primary is None:
                if not predictive:
                    continue
                complete = False
                break
            window_starts[window] = stamps[left]
        if not complete:
            failures["incomplete_history"] += 1
            continue
        response_anchor = state.receive_ts_ns + gap_ns
        if not retain_unlabelled and mid_series.as_of(response_anchor) is None:
            failures["no_response_anchor"] += 1
            continue
        future: dict[float, float] = {}
        past: dict[float, float] = {}
        for horizon in all_horizons:
            horizon_ns = int(horizon * NANOSECONDS_PER_SECOND)
            value = _mid_return(mid_series, response_anchor, response_anchor + horizon_ns)
            if value is not None:
                future[horizon] = value
            mirror = _mid_return(mid_series, state.receive_ts_ns - horizon_ns, state.receive_ts_ns)
            if mirror is not None:
                past[horizon] = mirror
        if not retain_unlabelled and not any(
            horizon in future for horizon in RETURN_HORIZONS_SECONDS
        ):
            failures["no_future_coverage"] += 1
            continue
        same: dict[float, float] = {}
        for window in SAME_WINDOW_SECONDS:
            value = _mid_return(
                mid_series,
                state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND),
                state.receive_ts_ns,
            )
            if value is not None:
                same[window] = value
        reference_future: dict[str, dict[float, float]] = {}
        reference_past: dict[str, dict[float, float]] = {}
        reference_same: dict[str, dict[float, float]] = {}
        for name, path in reference_paths.items():
            forward: dict[float, float] = {}
            mirror_map: dict[float, float] = {}
            for horizon in all_horizons:
                horizon_ns = int(horizon * NANOSECONDS_PER_SECOND)
                value = path.return_ticks(response_anchor, response_anchor + horizon_ns)
                if value is not None:
                    forward[horizon] = value
                mirrored = path.return_ticks(state.receive_ts_ns - horizon_ns, state.receive_ts_ns)
                if mirrored is not None:
                    mirror_map[horizon] = mirrored
            window_map: dict[float, float] = {}
            for window in SAME_WINDOW_SECONDS:
                value = path.return_ticks(
                    state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND),
                    state.receive_ts_ns,
                )
                if value is not None:
                    window_map[window] = value
            reference_future[name] = forward
            reference_past[name] = mirror_map
            reference_same[name] = window_map
        observations.append(
            HorseRaceObservation(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=state.receive_ts_ns,
                features=CczFeatureVector.build(schema, features),
                future_ticks=future,
                past_ticks=past,
                same_window_ticks=same,
                window_start_ts_ns=window_starts,
                connection_epoch=state.connection_epoch,
                reference_future_ticks=reference_future,
                reference_past_ticks=reference_past,
                reference_same_window_ticks=reference_same,
                microprice_state=(
                    state_key.key
                    if (
                        state_key := classify_state(
                            bid_quantity=float(bid_quantity),
                            ask_quantity=float(ask_quantity),
                            spread_ticks=controls["spread_ticks"],
                        )
                    )
                    is not None
                    else None
                ),
            )
        )
    failures["reference_price_coverage"] = reference_price_coverage(reference_paths)
    failures["effective_touch_window_seconds"] = effective_touch_window_seconds
    return observations, failures


def as_normal_observation(observation: HorseRaceObservation) -> Observation:
    return Observation(
        tape_index=observation.tape_index,
        run_id=observation.run_id,
        receive_ts_ns=observation.receive_ts_ns,
        time_bucket="mid_afternoon",
        features=observation.features,
        future_ticks=observation.future_ticks,
        past_ticks=observation.past_ticks,
        contemporaneous_ticks={},
    )


def assert_no_lookahead(observations: Sequence[HorseRaceObservation]) -> None:
    for observation in observations:
        for window, start in observation.window_start_ts_ns.items():
            if start <= observation.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND):
                raise AssertionError(
                    "predictor window included an event at/before its open boundary"
                )
            if start > observation.receive_ts_ns:
                raise AssertionError("predictor window starts in the future")


def model_features(
    model: str,
    window: float,
    *,
    trade_identified: bool,
    basis: str = "displayed",
    stoikov_available: bool = False,
) -> tuple[str, ...]:
    """Feature sets for the frozen horse race, with the multi-level families now CCZ.

    ``M4`` is CCZ Eq. (2) per level and ``M5`` is CCZ Eq. (3) per level under one common
    denominator.  Neither cumulates across levels and neither uses a per-band denominator.
    ``M3`` is the level-one CKS increment, which is Eq. (1)'s base case.  `MICRO-03` adds ``M7``,
    the size-weighted microprice, and ``M8``, the Stoikov iterated fair value, as families.

    ``basis`` selects `TOUCH-04`'s re-derivation.  Under ``"effective_touch"`` the three book
    objects the specification names — multi-level OFI, level-one queue imbalance and the
    microprice — are replaced by their effective-touch counterparts.  Families that carry no
    book-derived regressor are unchanged by the basis and are reported as such rather than
    silently duplicated.
    """

    if basis not in {"displayed", "effective_touch"}:
        raise ValueError(f"unknown predictor basis {basis}")
    baseline = BASELINE_FEATURES
    raw = ccz_raw_features(window, CCZ_PRIMARY_LEVELS)
    normalised = ccz_normalised_features(window, CCZ_PRIMARY_LEVELS)
    imbalance = "l1_queue_imbalance"
    tilt = "microprice_tilt_ticks"
    if basis == "effective_touch":
        normalised = touch_relative_normalised_features(window, CCZ_PRIMARY_LEVELS)
        imbalance = touch_relative_feature(imbalance)
        tilt = touch_relative_feature(tilt)
    specifications = {
        "M0": baseline,
        "M1": (*baseline, imbalance),
        "M2": (*baseline, trade_feature(window)) if trade_identified else (),
        "M3": (*baseline, cks_feature(window)),
        "M4": (*baseline, *raw),
        "M5": (*baseline, *normalised),
        "M6": (
            *baseline,
            imbalance,
            *((trade_feature(window),) if trade_identified else ()),
            cks_feature(window),
            *raw,
            *normalised,
        ),
        "M7": (*baseline, tilt),
        # `M8` is blocked exactly as `M2` is when its object is unidentified: the Stoikov chain
        # has to be fitted on a split, so before that fit the arm has no regressor at all and is
        # reported blocked rather than silently dropped from the grid.
        "M8": (*baseline, STOIKOV_FEATURE) if stoikov_available else (),
    }
    if model not in specifications:
        raise ValueError(f"unknown model {model}")
    return specifications[model]


def stoikov_is_available(observations: Sequence[HorseRaceObservation]) -> bool:
    """`MICRO-02`: whether the split-dependent ``M8`` regressor has been overlaid yet."""

    return any(STOIKOV_FEATURE in observation.features for observation in observations)


def basis_changes_model(model: str) -> bool:
    """`TOUCH-04`: whether swapping the reference basis changes this family's regressors at all."""

    return model in {"M1", "M5", "M6", "M7"}


def _returns(
    observation: HorseRaceObservation,
    source: Literal["future", "past"],
    reference: str = BASELINE_REFERENCE,
) -> Mapping[float, float]:
    """`TOUCH-03`: the return map under one reference price.

    The displayed-mid baseline reads the original ``future_ticks``/``past_ticks`` fields so the
    status quo cell is byte-identical to the pre-D38 object and remains comparable with the 11:30
    horse race; the other three read the ladder.
    """

    if reference == BASELINE_REFERENCE:
        return observation.future_ticks if source == "future" else observation.past_ticks
    ladder = (
        observation.reference_future_ticks
        if source == "future"
        else observation.reference_past_ticks
    )
    return ladder.get(reference, {})


def _target(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    horizon: float,
    source: Literal["future", "past"],
    reference: str = BASELINE_REFERENCE,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [_returns(observations[position], source, reference)[horizon] for position in positions],
        dtype=np.float64,
    )


def _design(
    observations: Sequence[HorseRaceObservation], positions: Sequence[int], names: Sequence[str]
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [[observations[position].features[name] for name in names] for position in positions],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


def _has_features(observation: HorseRaceObservation, names: Sequence[str]) -> bool:
    return all(
        name in observation.features and isfinite(float(observation.features[name]))
        for name in names
    )


def _positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    horizon: float,
    source: Literal["future", "past"],
    *,
    names: Sequence[str] = (),
    reference: str = BASELINE_REFERENCE,
) -> tuple[int, ...]:
    return tuple(
        position
        for position in candidates
        if horizon in _returns(observations[position], source, reference)
        and _has_features(observations[position], names)
    )


def _inner_folds(
    observations: Sequence[HorseRaceObservation], train_positions: Sequence[int]
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    by_tape: dict[int, list[int]] = {}
    for position in train_positions:
        by_tape.setdefault(observations[position].tape_index, []).append(position)
    folds: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    embargo_ns = int((max(RETURN_HORIZONS_SECONDS) + CAUSAL_GAP_SECONDS) * NANOSECONDS_PER_SECOND)
    for fraction in (0.5, 0.65, 0.8):
        inner_train: list[int] = []
        validation: list[int] = []
        for positions in by_tape.values():
            ordered = sorted(positions, key=lambda item: observations[item].receive_ts_ns)
            cut = max(1, int(len(ordered) * fraction))
            boundary = observations[ordered[cut - 1]].receive_ts_ns
            validation_end = min(len(ordered), cut + max(1, len(ordered) // 10))
            inner_train.extend(ordered[:cut])
            validation.extend(
                item
                for item in ordered[cut:validation_end]
                if observations[item].receive_ts_ns > boundary + embargo_ns
            )
        if len(inner_train) >= MINIMUM_FIT_OBSERVATIONS and validation:
            folds.append((tuple(inner_train), tuple(validation)))
    return tuple(folds)


def select_ridge_alpha(
    observations: Sequence[HorseRaceObservation],
    train_positions: Sequence[int],
    *,
    names: Sequence[str],
    horizon: float,
    source: Literal["future", "past"],
    reference: str = BASELINE_REFERENCE,
) -> tuple[float, tuple[dict[str, float], ...]]:
    """Select penalty entirely inside training by three deterministic expanding folds."""

    scores: dict[float, list[float]] = {alpha: [] for alpha in RIDGE_ALPHAS}
    folds = _inner_folds(observations, train_positions)
    for inner_train, validation in folds:
        raw_train = _target(observations, inner_train, horizon, source, reference)
        raw_validation = _target(observations, validation, horizon, source, reference)
        drift = float(raw_train.mean())
        design_train = _design(observations, inner_train, names)
        design_validation = _design(observations, validation, names)
        for alpha in RIDGE_ALPHAS:
            fit = fit_ridge(design_train, raw_train - drift, feature_names=names, penalty=alpha)
            residual = raw_validation - drift - fit.predict(design_validation)
            scores[alpha].append(float(np.mean(residual**2)))
    mean_scores = {
        alpha: (float(np.mean(values)) if values else float("inf"))
        for alpha, values in scores.items()
    }
    selected = min(RIDGE_ALPHAS, key=lambda alpha: (mean_scores[alpha], alpha))
    if not isfinite(mean_scores[selected]):
        selected = RIDGE_ALPHAS[0]
    diagnostics = tuple(
        {
            "alpha": alpha,
            "mean_validation_mse": mean_scores[alpha],
            "folds": float(len(scores[alpha])),
        }
        for alpha in RIDGE_ALPHAS
    )
    return selected, diagnostics


@dataclass(frozen=True, slots=True)
class FittedScore:
    payload: Mapping[str, Any]
    errors: tuple[float, ...]
    predictions: tuple[float, ...]
    target_drift: float
    fit: Any


def _fit_score(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    test: Sequence[int],
    *,
    model: str,
    names: Sequence[str],
    horizon: float,
    source: Literal["future", "past"],
    reference: str = BASELINE_REFERENCE,
) -> FittedScore:
    raw_train = _target(observations, train, horizon, source, reference)
    raw_test = _target(observations, test, horizon, source, reference)
    drift = float(raw_train.mean())
    train_target = raw_train - drift
    test_target = raw_test - drift
    train_design = _design(observations, train, names)
    test_design = _design(observations, test, names)
    regularised = model in REGULARISED_MODELS
    alpha, cv = (
        select_ridge_alpha(
            observations,
            train,
            names=names,
            horizon=horizon,
            source=source,
            reference=reference,
        )
        if regularised
        else (0.0, ())
    )
    fit = fit_ridge(train_design, train_target, feature_names=names, penalty=alpha)
    fitted = fit.predict(train_design)
    predicted = fit.predict(test_design)
    in_sample = _r_squared(train_target, fitted, np.zeros(train_target.shape, dtype=np.float64))
    degrees = len(train) - len(names) - 1
    adjusted = (
        None
        if in_sample is None or degrees <= 0
        else 1.0 - (1.0 - in_sample) * (len(train) - 1) / degrees
    )
    residual = test_target - predicted
    coefficients = {name: float(fit.coefficients[index]) for index, name in enumerate(names)}
    raw_coefficients = {
        name: float(fit.coefficients[index] / fit.scale[index]) for index, name in enumerate(names)
    }
    payload: dict[str, Any] = {
        "status": "estimated",
        "features": list(names),
        "train_n": len(train),
        "test_n": len(test),
        "in_sample_r2": in_sample,
        "in_sample_adjusted_r2": adjusted,
        "oos_r2_training_mean": _r_squared(
            test_target, predicted, np.zeros(test_target.shape, dtype=np.float64)
        ),
        "rmse_ticks": sqrt(float(np.mean(residual**2))),
        "mae_ticks": float(np.mean(np.abs(residual))),
        "target_training_mean_ticks": drift,
        "selected_alpha": alpha,
        "inner_cv": cv,
        "coefficients_ticks_per_training_sd": coefficients,
        "raw_coefficients_ticks_per_unit": raw_coefficients,
        "training_standardisation": {
            "centre": {name: float(fit.centre[index]) for index, name in enumerate(names)},
            "scale": {name: float(fit.scale[index]) for index, name in enumerate(names)},
            "source": "training_only",
        },
    }
    return FittedScore(
        payload=payload,
        errors=tuple(float(value) for value in residual**2),
        predictions=tuple(float(value) for value in predicted),
        target_drift=drift,
        fit=fit,
    )


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _per_tape_scores(
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    *,
    horizon: float,
    source: Literal["future", "past"],
    score: FittedScore,
    baseline: FittedScore,
    reference: str = BASELINE_REFERENCE,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tape in sorted({observations[position].tape_index for position in test}):
        selection = [
            index
            for index, position in enumerate(test)
            if observations[position].tape_index == tape
        ]
        positions = [test[index] for index in selection]
        target = _target(observations, positions, horizon, source, reference) - score.target_drift
        predicted = np.asarray([score.predictions[index] for index in selection])
        baseline_predicted = np.asarray([baseline.predictions[index] for index in selection])
        benchmark = np.zeros(target.shape, dtype=np.float64)
        current_r2 = _r_squared(target, predicted, benchmark)
        baseline_r2 = _r_squared(target, baseline_predicted, benchmark)
        result[str(tape)] = {
            "test_n": len(positions),
            "oos_r2_training_mean": current_r2,
            "incremental_oos_r2_over_m0": _difference(current_r2, baseline_r2),
            "rmse_ticks": sqrt(float(np.mean((target - predicted) ** 2))),
            "mae_ticks": float(np.mean(np.abs(target - predicted))),
        }
    return result


def _direction_by_tape(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    *,
    names: Sequence[str],
    model: str,
    horizon: float,
    source: Literal["future", "past"],
    alpha: float,
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    baseline = {"log1p_l1_depth", "spread_ticks"}
    for tape in sorted({observations[position].tape_index for position in train}):
        positions = [position for position in train if observations[position].tape_index == tape]
        if len(positions) < len(names) + 3:
            result[str(tape)] = None
            continue
        target = _target(observations, positions, horizon, source)
        design = _design(observations, positions, names)
        fit = fit_ridge(design, target - target.mean(), feature_names=names, penalty=alpha)
        family_indices = [index for index, name in enumerate(names) if name not in baseline]
        if not family_indices:
            result[str(tape)] = None
            continue
        if len(family_indices) == 1:
            result[str(tape)] = float(fit.coefficients[family_indices[0]])
            continue
        standardised = (design - fit.centre) / fit.scale
        contribution = standardised[:, family_indices] @ fit.coefficients[family_indices]
        covariance = float(np.mean((contribution - contribution.mean()) * (target - target.mean())))
        result[str(tape)] = covariance
    return result


def _level_contribution_diagnostics(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    test: Sequence[int],
    *,
    names: Sequence[str],
    model: Literal["M4", "M5"],
    horizon: float,
    source: Literal["future", "past"],
    score: FittedScore,
) -> dict[str, Any]:
    """Decompose a fitted Ridge family into auditable per-CCZ-level held-out contributions.

    Levels are reported individually because CCZ never cumulate; a level's contribution here is
    that level's own flow, not a running total through it.
    """

    family = ccz_raw_features(0.0) if model == "M4" else ccz_normalised_features(0.0)
    suffix = tuple(name.split("__", 1)[1] for name in family)
    feature_indices = [
        index
        for index, name in enumerate(names)
        if name.startswith("ccz_ofi_") and name.split("__", 1)[-1] in suffix
    ]
    test_design = _design(observations, test, names)
    standardised_test = (test_design - score.fit.centre) / score.fit.scale
    tape_fits: dict[int, Any] = {}
    for tape in sorted({observations[position].tape_index for position in train}):
        positions = [position for position in train if observations[position].tape_index == tape]
        if len(positions) < len(names) + 3:
            continue
        target = _target(observations, positions, horizon, source)
        tape_fits[tape] = fit_ridge(
            _design(observations, positions, names),
            target - target.mean(),
            feature_names=names,
            penalty=float(score.payload["selected_alpha"]),
        )

    rows: list[dict[str, Any]] = []
    for level, feature_index in enumerate(feature_indices, start=1):
        feature = names[feature_index]
        contribution = standardised_test[:, feature_index] * score.fit.coefficients[feature_index]
        per_tape: dict[str, Any] = {}
        tape_coefficients: list[float] = []
        for tape in sorted({observations[position].tape_index for position in test}):
            selection = np.asarray(
                [observations[position].tape_index == tape for position in test], dtype=bool
            )
            tape_fit = tape_fits.get(tape)
            coefficient = None if tape_fit is None else float(tape_fit.coefficients[feature_index])
            if coefficient is not None:
                tape_coefficients.append(coefficient)
            values = contribution[selection]
            per_tape[str(tape)] = {
                "test_n": int(selection.sum()),
                "coefficient_ticks_per_tape_training_sd": coefficient,
                "mean_test_contribution_ticks": float(values.mean()) if len(values) else None,
                "mean_absolute_test_contribution_ticks": (
                    float(np.mean(np.abs(values))) if len(values) else None
                ),
            }
        signs = [int(value > 0) - int(value < 0) for value in tape_coefficients]
        rows.append(
            {
                "level": level,
                "feature": feature,
                "train_n": len(train),
                "test_n": len(test),
                "coefficient_ticks_per_pooled_training_sd": float(
                    score.fit.coefficients[feature_index]
                ),
                "raw_coefficient_ticks_per_unit": float(
                    score.fit.coefficients[feature_index] / score.fit.scale[feature_index]
                ),
                "mean_test_contribution_ticks": float(contribution.mean()),
                "mean_absolute_test_contribution_ticks": float(np.mean(np.abs(contribution))),
                "rms_test_contribution_ticks": sqrt(float(np.mean(contribution**2))),
                "coefficient_sign_stable_across_tapes": (
                    len(signs) == len(per_tape)
                    and len(signs) >= 2
                    and len(set(signs)) == 1
                    and signs[0] != 0
                ),
                "per_tape": per_tape,
            }
        )
    return {
        "definition": (
            "held-out contribution = pooled Ridge coefficient (ticks per pooled training SD) "
            "times the feature standardised by pooled training centre/scale; per-tape "
            "coefficient stability refits the same selected alpha on each tape's training rows; "
            "levels are individual CCZ levels, never cumulative through a depth cutoff"
        ),
        "levels": rows,
    }


def _inference(
    baseline: FittedScore,
    score: FittedScore,
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    *,
    horizon: float,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    differential = [left - right for left, right in zip(baseline.errors, score.errors, strict=True)]
    estimate = estimate_mean(
        differential,
        [observations[position].receive_ts_ns for position in test],
        [observations[position].tape_index for position in test],
        overlap_seconds=horizon + CAUSAL_GAP_SECONDS,
        replicates=replicates,
        seed=seed,
    )
    return {**asdict(estimate), "naive_inference_valid": False}


def _support_by_tape(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    horizon: float,
    source: Literal["future", "past"],
    names: Sequence[str] = (),
    reference: str = BASELINE_REFERENCE,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for tape in sorted({observation.tape_index for observation in observations}):

        def count(candidates: Sequence[int], tape_index: int = tape) -> int:
            return sum(
                observations[position].tape_index == tape_index
                and horizon in _returns(observations[position], source, reference)
                and _has_features(observations[position], names)
                for position in candidates
            )

        result[str(tape)] = {
            "total_n": sum(
                observation.tape_index == tape
                and horizon in _returns(observation, source, reference)
                and _has_features(observation, names)
                for observation in observations
            ),
            "train_n": count(split.train),
            "embargoed_n": count(split.embargoed),
            "test_n": count(split.test),
        }
    return result


def _collinearity(
    observations: Sequence[HorseRaceObservation], train: Sequence[int], names: Sequence[str]
) -> dict[str, float | None]:
    if len(names) < 2:
        return {"max_absolute_correlation": None, "condition_number": None, "max_vif": None}
    design = _design(observations, train, names)
    scale = design.std(axis=0)
    active = scale > 0
    if active.sum() < 2:
        return {"max_absolute_correlation": 0.0, "condition_number": None, "max_vif": None}
    standardised = (design[:, active] - design[:, active].mean(axis=0)) / scale[active]
    correlation = np.corrcoef(standardised, rowvar=False)
    off_diagonal = correlation - np.eye(correlation.shape[0])
    inverse = np.linalg.pinv(correlation)
    return {
        "max_absolute_correlation": float(np.max(np.abs(off_diagonal))),
        "condition_number": float(np.linalg.cond(standardised)),
        "max_vif": float(np.max(np.diag(inverse))),
    }


def fit_stoikov_for_split(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    reference: str = BASELINE_REFERENCE,
) -> StoikovMicropriceModel:
    """`MICRO-02` / `VAL-MICRO-01`: fit the Stoikov chain on training rows only.

    The chain steps on mid changes, so the mid path is taken from the reference price under
    evaluation and the transitions are those whose mid change *resolves* strictly before the
    training boundary.  A transition straddling the boundary would carry a held-out mid move into
    the fit, so it is dropped here and refused again inside :func:`fit_stoikov_microprice`.
    """

    if not split.train:
        raise ValueError("a Stoikov fit needs at least one training row")
    boundary = max(observations[position].receive_ts_ns for position in split.train) + 1
    samples: list[tuple[int, float, MicropriceState | None]] = []
    for position in sorted(split.train, key=lambda item: observations[item].receive_ts_ns):
        observation = observations[position]
        mid = _reference_level(observation, reference)
        if mid is None:
            continue
        samples.append((observation.receive_ts_ns, mid, _state_from_key(observation)))
    transitions = [
        transition
        for transition in build_stoikov_transitions(samples)
        if transition.resolved_ts_ns < boundary
    ]
    return fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=boundary)


def _state_from_key(observation: HorseRaceObservation) -> MicropriceState | None:
    key = observation.microprice_state
    if key is None:
        return None
    imbalance, _, spread = key.partition("_")
    return MicropriceState(imbalance_bucket=int(imbalance[1:]), spread_bucket=int(spread[1:]))


def _reference_level(observation: HorseRaceObservation, reference: str) -> float | None:
    """A local price level for the Stoikov chain, reconstructed from the same-window return.

    The observation carries returns, not levels, so the chain is stepped on a cumulative path
    built from the shortest same-window return.  Only *changes* of the path enter the estimator,
    so an arbitrary origin is harmless; what matters is that two anchors sharing a mid produce the
    same value, which a cumulative path preserves.
    """

    same = (
        observation.same_window_ticks
        if reference == BASELINE_REFERENCE
        else observation.reference_same_window_ticks.get(reference, {})
    )
    shortest = min(SAME_WINDOW_SECONDS)
    value = same.get(shortest)
    return None if value is None else float(value)


def with_stoikov_feature(
    observations: Sequence[HorseRaceObservation],
    model: StoikovMicropriceModel,
) -> list[HorseRaceObservation]:
    """`MICRO-02`: overlay the fitted adjustment as the ``M8`` regressor, applied unchanged.

    Anchors whose state was never estimated get **no** value, so the common-sample intersection
    drops them from ``M8`` alone rather than imputing a zero tilt.
    """

    augmented: list[HorseRaceObservation] = []
    for observation in observations:
        adjustment = model.adjustment(_state_from_key(observation))
        augmented.append(
            observation
            if adjustment is None
            else replace(
                observation,
                features=_FeatureOverlay(observation.features, {STOIKOV_FEATURE: adjustment}),
            )
        )
    return augmented


def cell_metrics(
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    *,
    score: FittedScore,
    horizon: float,
    source: Literal["future", "past"],
    reference: str,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """`METRIC-04`: the companion metric bundle for one cell, on its own held-out rows.

    The predictions are the cell's own out-of-sample predictions and the realised values its own
    drift-adjusted targets, so `VAL-METRIC-01` holds by construction rather than by convention.
    """

    realised = _target(observations, test, horizon, source, reference) - score.target_drift
    spreads = [float(observations[position].features["spread_ticks"]) for position in test]
    bundle = metric_bundle(
        list(score.predictions),
        [float(value) for value in realised],
        spread_ticks=spreads,
        tapes=[observations[position].tape_index for position in test],
        mean_block_length=8.0,
        replicates=replicates,
        seed=seed,
    )
    bundle["per_tape_sign_check"] = per_tape_sign_check(
        {
            str(tape): _correlation_for_tape(observations, test, score, realised, tape)
            for tape in sorted({observations[position].tape_index for position in test})
        },
        label="pearson_information_coefficient",
    )
    return bundle


def _correlation_for_tape(
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    score: FittedScore,
    realised: np.ndarray[Any, np.dtype[np.float64]],
    tape: int,
) -> float | None:
    selection = [
        index for index, position in enumerate(test) if observations[position].tape_index == tape
    ]
    if len(selection) < 3:
        return None
    predicted = np.asarray([score.predictions[index] for index in selection], dtype=np.float64)
    actual = realised[selection]
    if float(np.std(predicted)) <= 0.0 or float(np.std(actual)) <= 0.0:
        return None
    return float(np.corrcoef(predicted, actual)[0, 1])


def evaluate_cells(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    horizons: Sequence[float],
    source: Literal["future", "past"],
    trade_identified: bool,
    replicates: int,
    seed: int,
    reference: str = BASELINE_REFERENCE,
    basis: str = "displayed",
) -> list[dict[str, Any]]:
    """`TOUCH-03`: one full grid under one reference price and one predictor basis.

    Both sides of the regression move together: ``reference`` selects the return the cell is
    scored against and ``basis`` selects whether the book-derived regressors are measured against
    the displayed level one or against the effective touch.
    """

    rows: list[dict[str, Any]] = []
    stoikov_available = stoikov_is_available(observations)
    for horizon in horizons:
        for window in OFI_WINDOWS_SECONDS:
            feature_sets = {
                model: model_features(
                    model,
                    window,
                    trade_identified=trade_identified,
                    basis=basis,
                    stoikov_available=stoikov_available,
                )
                for model in MODEL_ORDER
            }
            common_names = tuple(
                dict.fromkeys(
                    name
                    for model in MODEL_ORDER
                    for name in feature_sets[model]
                    if feature_sets[model]
                )
            )
            train = _positions(
                observations, split.train, horizon, source, names=common_names, reference=reference
            )
            test = _positions(
                observations, split.test, horizon, source, names=common_names, reference=reference
            )
            embargoed = _positions(
                observations,
                split.embargoed,
                horizon,
                source,
                names=common_names,
                reference=reference,
            )
            total = _positions(
                observations,
                tuple(range(len(observations))),
                horizon,
                source,
                names=common_names,
                reference=reference,
            )
            support_by_tape = _support_by_tape(
                observations,
                split,
                horizon=horizon,
                source=source,
                names=common_names,
                reference=reference,
            )
            if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
                raise ValueError(
                    f"insufficient common support at h1={window}, h2={horizon}, "
                    f"reference={reference}, basis={basis}"
                )
            scores: dict[str, FittedScore] = {}
            for model in MODEL_ORDER:
                names = feature_sets[model]
                if not names:
                    rows.append(
                        {
                            "source": source,
                            "reference_price": reference,
                            "predictor_basis": basis,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "model": model,
                            "status": (
                                "blocked_unfitted_stoikov_chain"
                                if model == "M8"
                                else "blocked_unidentified_signed_trades"
                            ),
                            "total_n": len(total),
                            "train_n": len(train),
                            "embargoed_n": len(embargoed),
                            "test_n": len(test),
                            "support_by_tape": support_by_tape,
                        }
                    )
                    continue
                model_total = _positions(
                    observations,
                    tuple(range(len(observations))),
                    horizon,
                    source,
                    names=names,
                    reference=reference,
                )
                model_train = _positions(
                    observations, split.train, horizon, source, names=names, reference=reference
                )
                model_embargoed = _positions(
                    observations,
                    split.embargoed,
                    horizon,
                    source,
                    names=names,
                    reference=reference,
                )
                model_test = _positions(
                    observations, split.test, horizon, source, names=names, reference=reference
                )
                model_specific_support = {
                    "total_n": len(model_total),
                    "train_n": len(model_train),
                    "embargoed_n": len(model_embargoed),
                    "test_n": len(model_test),
                    "support_by_tape": _support_by_tape(
                        observations,
                        split,
                        horizon=horizon,
                        source=source,
                        names=names,
                        reference=reference,
                    ),
                }
                score = _fit_score(
                    observations,
                    train,
                    test,
                    model=model,
                    names=names,
                    horizon=horizon,
                    source=source,
                    reference=reference,
                )
                scores[model] = score
                baseline = scores["M0"]
                payload = dict(score.payload)
                current_r2 = payload["oos_r2_training_mean"]
                baseline_r2 = baseline.payload["oos_r2_training_mean"]
                payload.update(
                    {
                        "source": source,
                        "reference_price": reference,
                        "predictor_basis": basis,
                        "basis_changes_this_model": basis_changes_model(model),
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                        "model": model,
                        "total_n": len(total),
                        "embargoed_n": len(embargoed),
                        "support_by_tape": support_by_tape,
                        "common_sample_feature_count": len(common_names),
                        "model_specific_support_before_common_intersection": (
                            model_specific_support
                        ),
                        "support_loss_to_common_sample": {
                            "total_n": len(model_total) - len(total),
                            "train_n": len(model_train) - len(train),
                            "embargoed_n": len(model_embargoed) - len(embargoed),
                            "test_n": len(model_test) - len(test),
                        },
                        "incremental_oos_r2_over_m0": _difference(current_r2, baseline_r2),
                        "incremental_oos_r2_over_prior_model": (
                            _difference(current_r2, scores["M4"].payload["oos_r2_training_mean"])
                            if model == "M5"
                            else _difference(
                                current_r2, scores["M5"].payload["oos_r2_training_mean"]
                            )
                            if model == "M6"
                            else _difference(current_r2, baseline_r2)
                            if model == "M1"
                            else None
                        ),
                        "per_tape": _per_tape_scores(
                            observations,
                            test,
                            horizon=horizon,
                            source=source,
                            score=score,
                            baseline=baseline,
                            reference=reference,
                        ),
                        "direction_by_tape": _direction_by_tape(
                            observations,
                            train,
                            names=names,
                            model=model,
                            horizon=horizon,
                            source=source,
                            alpha=float(payload["selected_alpha"]),
                        ),
                        "collinearity": _collinearity(observations, train, names[2:]),
                        # `METRIC-04`: R2 never travels alone.
                        "metrics": cell_metrics(
                            observations,
                            test,
                            score=score,
                            horizon=horizon,
                            source=source,
                            reference=reference,
                            replicates=replicates,
                            seed=seed + 7_000_000 + int(horizon * 1000) + int(window * 100),
                        ),
                    }
                )
                if model in {"M4", "M5"}:
                    payload["level_contribution_diagnostics"] = _level_contribution_diagnostics(
                        observations,
                        train,
                        test,
                        names=names,
                        model="M4" if model == "M4" else "M5",
                        horizon=horizon,
                        source=source,
                        score=score,
                    )
                if model != "M0":
                    payload["error_improvement_inference_over_m0"] = _inference(
                        baseline,
                        score,
                        observations,
                        test,
                        horizon=horizon,
                        seed=seed + int(horizon * 1000) + int(window * 100) + int(model[1]),
                        replicates=replicates,
                    )
                rows.append(payload)
    return rows


def evaluate_same_window(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    trade_identified: bool,
    basis: str = "displayed",
    reference: str = BASELINE_REFERENCE,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """`WINDOW-01`/`WINDOW-02`: the contemporaneous grid, now a replication gate.

    Two things change from the descriptive predecessor.  The grid runs to 30 s and 60 s
    (`WINDOW-01`), and 60 s is CCZ's ``h = 1 minute`` exactly, which makes it the only cell in this
    repository directly comparable with their published figures.  And the cell stops being
    ``descriptive_only``: it carries in-sample and out-of-sample R2 side by side with CCZ's
    published 71.16% / 64.64% best-level and 87.14% integrated numbers, and records the **gap**
    explicitly rather than leaving a reader to infer it (`WINDOW-02`).

    A contemporaneous R2 is not a forecast and never becomes one.  It measures how much of the
    same-window price move the same-window order flow explains, which is a construction
    diagnostic; that is carried on every row.
    """

    rows: list[dict[str, Any]] = []
    stoikov_available = stoikov_is_available(observations)
    for window in SAME_WINDOW_SECONDS:
        feature_sets = {
            model: model_features(
                model,
                window,
                trade_identified=trade_identified,
                basis=basis,
                stoikov_available=stoikov_available,
            )
            for model in MODEL_ORDER
        }
        common_names = tuple(
            dict.fromkeys(
                name for model in MODEL_ORDER for name in feature_sets[model] if feature_sets[model]
            )
        )

        def _rows(
            candidates: Sequence[int],
            window: float = window,
            required: Sequence[str] = common_names,
        ) -> tuple[int, ...]:
            return tuple(
                position
                for position in candidates
                if window in _same_window_returns(observations[position], reference)
                and _has_features(observations[position], required)
            )

        train = _rows(split.train)
        test = _rows(split.test)
        for model in MODEL_ORDER:
            names = feature_sets[model]
            blocked = (
                not names
                or len(train) < MINIMUM_FIT_OBSERVATIONS
                or len(test) < MINIMUM_FIT_OBSERVATIONS
            )
            if blocked:
                rows.append(
                    {
                        "h1_seconds": window,
                        "model": model,
                        "reference_price": reference,
                        "predictor_basis": basis,
                        "is_ccz_comparison_cell": window == CCZ_CONTEMPORANEOUS_WINDOW_SECONDS,
                        "train_n": len(train),
                        "test_n": len(test),
                        "status": (
                            "blocked_unfitted_stoikov_chain"
                            if model == "M8" and not names
                            else "blocked_unidentified_signed_trades"
                            if not names
                            else "insufficient_support"
                        ),
                    }
                )
                continue
            design_train = _design(observations, train, names)
            design_test = _design(observations, test, names)
            raw_train = np.asarray(
                [_same_window_returns(observations[p], reference)[window] for p in train],
                dtype=np.float64,
            )
            raw_test = np.asarray(
                [_same_window_returns(observations[p], reference)[window] for p in test],
                dtype=np.float64,
            )
            drift = float(raw_train.mean())
            alpha = 0.0 if model not in REGULARISED_MODELS else 1.0
            fit = fit_ridge(design_train, raw_train - drift, feature_names=names, penalty=alpha)
            fitted = fit.predict(design_train)
            prediction = fit.predict(design_test)
            zeros_train = np.zeros(raw_train.shape, dtype=np.float64)
            zeros_test = np.zeros(raw_test.shape, dtype=np.float64)
            in_sample = _r_squared(raw_train - drift, fitted, zeros_train)
            out_of_sample = _r_squared(raw_test - drift, prediction, zeros_test)
            row: dict[str, Any] = {
                "h1_seconds": window,
                "model": model,
                "status": "estimated",
                "reference_price": reference,
                "predictor_basis": basis,
                "is_ccz_comparison_cell": window == CCZ_CONTEMPORANEOUS_WINDOW_SECONDS,
                "contemporaneous_not_a_forecast": True,
                "features": list(names),
                "train_n": len(train),
                "test_n": len(test),
                "in_sample_r2": in_sample,
                "oos_r2": out_of_sample,
                "oos_r2_training_mean": out_of_sample,
                "selected_alpha": alpha,
                "metrics": metric_bundle(
                    [float(value) for value in prediction],
                    [float(value) for value in raw_test - drift],
                    spread_ticks=[
                        float(observations[position].features["spread_ticks"]) for position in test
                    ],
                    tapes=[observations[position].tape_index for position in test],
                    replicates=replicates,
                    seed=seed + int(window * 100),
                ),
            }
            row["ccz_replication_gap"] = _ccz_replication_gap(model, in_sample, out_of_sample)
            rows.append(row)
    return rows


def _same_window_returns(
    observation: HorseRaceObservation, reference: str = BASELINE_REFERENCE
) -> Mapping[float, float]:
    if reference == BASELINE_REFERENCE:
        return observation.same_window_ticks
    return observation.reference_same_window_ticks.get(reference, {})


def _ccz_replication_gap(
    model: str, in_sample: float | None, out_of_sample: float | None
) -> dict[str, Any]:
    """`WINDOW-02`: the distance from CCZ's published contemporaneous figures, recorded not implied.

    ``M3`` is the level-one CKS increment, which is CCZ's best-level arm; ``M5`` is the
    depth-scaled multi-level object, whose published comparator is the integrated in-sample
    figure.  Every other family has no published counterpart and says so rather than borrowing one.
    """

    published_in_sample: float | None = None
    published_out_of_sample: float | None = None
    comparator = "none_published"
    if model == "M3":
        published_in_sample = CCZ_PUBLISHED_BEST_LEVEL_IN_SAMPLE_R2
        published_out_of_sample = CCZ_PUBLISHED_BEST_LEVEL_OUT_OF_SAMPLE_R2
        comparator = "ccz_best_level"
    elif model == "M5":
        published_in_sample = CCZ_PUBLISHED_INTEGRATED_IN_SAMPLE_R2
        comparator = "ccz_integrated"
    return {
        "requirement": "WINDOW-02",
        "comparator": comparator,
        "published_in_sample_r2": published_in_sample,
        "published_out_of_sample_r2": published_out_of_sample,
        "observed_in_sample_r2": in_sample,
        "observed_out_of_sample_r2": out_of_sample,
        "in_sample_gap": (
            None
            if published_in_sample is None or in_sample is None
            else in_sample - published_in_sample
        ),
        "out_of_sample_gap": (
            None
            if published_out_of_sample is None or out_of_sample is None
            else out_of_sample - published_out_of_sample
        ),
        "note": (
            "CCZ measure US equities where level one is the touch and spreads are about one tick; "
            "ID-CKS-02 and TOUCH-01 establish that neither holds on this feed, so a gap is as "
            "likely to be a level-one identification failure as an absence of information"
        ),
    }


def evaluate_same_window_by_depth(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    reference: str = BASELINE_REFERENCE,
    level_counts: Sequence[int] = CCZ_LEVEL_COUNTS,
    arms: Sequence[str] = CCZ_SCALAR_ARMS,
) -> list[dict[str, Any]]:
    """`WINDOW-03`: the contemporaneous R2 at every window **and every declared depth** ``M``.

    :func:`evaluate_same_window` varies the model family at the primary level count; this varies
    the level count itself, which is what "at every depth" means for a CCZ object.  The scalar
    aggregation arms are used because ``PI^[M]`` at ``M = 200`` is a two-hundred-regressor
    contemporaneous fit and would be reporting its own degrees of freedom.

    The integrated arm's weights are fitted on training rows only, exactly as `EST-CCZ-04`
    requires, and a depth with no support at a window is emitted as data-insufficient rather than
    dropped: `EST-CCZ-06` retires no declared arm.
    """

    rows: list[dict[str, Any]] = []
    counts = tuple(sorted({int(value) for value in level_counts}))
    for window in SAME_WINDOW_SECONDS:
        for levels in counts:
            design = build_ccz_arm_design(
                observations, tuple(range(len(observations))), window=window, levels=levels
            )
            train = [
                design.index[position]
                for position in split.train
                if position in design.index
                and window in _same_window_returns(observations[position], reference)
            ]
            test = [
                design.index[position]
                for position in split.test
                if position in design.index
                and window in _same_window_returns(observations[position], reference)
            ]
            weights = (
                fit_integrated_weights(design.normalised[np.asarray(train, dtype=np.intp)])
                if len(train) >= MINIMUM_FIT_OBSERVATIONS
                else None
            )
            for arm in arms:
                if (
                    len(train) < MINIMUM_FIT_OBSERVATIONS
                    or len(test) < MINIMUM_FIT_OBSERVATIONS
                    or (arm == "integrated" and weights is None)
                ):
                    rows.append(
                        {
                            "requirement": "WINDOW-03",
                            "h1_seconds": window,
                            "levels": levels,
                            "arm": arm,
                            "reference_price": reference,
                            "status": "data_insufficient",
                            "train_n": len(train),
                            "test_n": len(test),
                            "is_ccz_comparison_cell": (
                                window == CCZ_CONTEMPORANEOUS_WINDOW_SECONDS
                            ),
                        }
                    )
                    continue
                columns_train, names = _arm_columns(design, arm, weights, train)
                columns_test, _ = _arm_columns(design, arm, weights, test)
                selected_train = np.asarray(train, dtype=np.intp)
                selected_test = np.asarray(test, dtype=np.intp)
                matrix_train = np.hstack([design.baseline[selected_train], columns_train])
                matrix_test = np.hstack([design.baseline[selected_test], columns_test])
                feature_names = (*BASELINE_FEATURES, *names)
                target_train = np.asarray(
                    [
                        _same_window_returns(observations[position], reference)[window]
                        for position in split.train
                        if position in design.index
                        and window in _same_window_returns(observations[position], reference)
                    ],
                    dtype=np.float64,
                )
                target_test = np.asarray(
                    [
                        _same_window_returns(observations[position], reference)[window]
                        for position in split.test
                        if position in design.index
                        and window in _same_window_returns(observations[position], reference)
                    ],
                    dtype=np.float64,
                )
                drift = float(target_train.mean())
                fit = fit_ridge(
                    matrix_train,
                    target_train - drift,
                    feature_names=feature_names,
                    penalty=0.0 if arm != "per_level_pi" else 1.0,
                )
                in_sample = _r_squared(
                    target_train - drift,
                    fit.predict(matrix_train),
                    np.zeros(target_train.shape, dtype=np.float64),
                )
                out_of_sample = _r_squared(
                    target_test - drift,
                    fit.predict(matrix_test),
                    np.zeros(target_test.shape, dtype=np.float64),
                )
                rows.append(
                    {
                        "requirement": "WINDOW-03",
                        "h1_seconds": window,
                        "levels": levels,
                        "arm": arm,
                        "reference_price": reference,
                        "status": "estimated",
                        "contemporaneous_not_a_forecast": True,
                        "is_ccz_comparison_cell": window == CCZ_CONTEMPORANEOUS_WINDOW_SECONDS,
                        "train_n": len(train),
                        "test_n": len(test),
                        "in_sample_r2": in_sample,
                        "oos_r2": out_of_sample,
                        "explained_variance_ratio": (
                            weights.explained_variance_ratio if weights is not None else None
                        ),
                        "ccz_replication_gap": _ccz_replication_gap_for_arm(
                            arm, in_sample, out_of_sample
                        ),
                    }
                )
    return rows


def _ccz_replication_gap_for_arm(
    arm: str, in_sample: float | None, out_of_sample: float | None
) -> dict[str, Any]:
    """`WINDOW-02` for the depth grid, where the arm rather than the family names the comparator."""

    model = {"best_level": "M3", "integrated": "M5"}.get(arm, "M0")
    payload = _ccz_replication_gap(model, in_sample, out_of_sample)
    payload["arm"] = arm
    return payload


def depth_r2_curve(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`WINDOW-03`: one R2-versus-window curve per depth and arm, with the plateau visible."""

    curves: list[dict[str, Any]] = []
    keys = sorted(
        {(int(row["levels"]), str(row["arm"]), str(row.get("reference_price"))) for row in rows}
    )
    for levels, arm, reference in keys:
        selected = {
            float(row["h1_seconds"]): row
            for row in rows
            if int(row["levels"]) == levels
            and row["arm"] == arm
            and row.get("reference_price") == reference
        }
        windows = sorted(selected)
        values = [selected[window].get("oos_r2") for window in windows]
        estimated = [
            (window, value)
            for window, value in zip(windows, values, strict=True)
            if value is not None
        ]
        peak = max(estimated, key=lambda item: item[1]) if estimated else None
        ordered = [value for _, value in estimated]
        curves.append(
            {
                "requirement": "WINDOW-03",
                "levels": levels,
                "arm": arm,
                "reference_price": reference,
                "windows_seconds": windows,
                "oos_r2": values,
                "in_sample_r2": [selected[window].get("in_sample_r2") for window in windows],
                "estimated_cells": len(estimated),
                "peak_window_seconds": peak[0] if peak else None,
                "peak_oos_r2": peak[1] if peak else None,
                "monotone_increasing": (
                    all(
                        later >= earlier
                        for earlier, later in zip(ordered, ordered[1:], strict=False)
                    )
                    if len(estimated) > 1
                    else None
                ),
                "still_climbing_at_the_ceiling": (
                    bool(peak[0] == max(windows)) if peak and windows else None
                ),
            }
        )
    return curves


def same_window_curve(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`WINDOW-03`: the R2-versus-window curve, so a plateau or its absence is directly visible.

    The 11:30 curve was monotone increasing and still climbing at the 10 s ceiling, which is
    exactly the shape that cannot be read without seeing where it stops.  One row per model per
    reference basis, carrying the ordered window axis and whether the curve ever turned over.
    """

    curves: list[dict[str, Any]] = []
    keys = sorted(
        {
            (
                str(row.get("model")),
                str(row.get("reference_price")),
                str(row.get("predictor_basis")),
            )
            for row in rows
        }
    )
    for model, reference, basis in keys:
        selected = {
            float(row["h1_seconds"]): row
            for row in rows
            if row.get("model") == model
            and row.get("reference_price") == reference
            and row.get("predictor_basis") == basis
        }
        windows = sorted(selected)
        values = [selected[window].get("oos_r2") for window in windows]
        estimated = [
            (window, value)
            for window, value in zip(windows, values, strict=True)
            if value is not None
        ]
        peak = max(estimated, key=lambda item: item[1]) if estimated else None
        ordered = [value for _, value in estimated]
        monotone = all(
            later >= earlier for earlier, later in zip(ordered, ordered[1:], strict=False)
        )
        curves.append(
            {
                "requirement": "WINDOW-03",
                "model": model,
                "reference_price": reference,
                "predictor_basis": basis,
                "windows_seconds": windows,
                "oos_r2": values,
                "in_sample_r2": [selected[window].get("in_sample_r2") for window in windows],
                "estimated_cells": len(estimated),
                "peak_window_seconds": peak[0] if peak else None,
                "peak_oos_r2": peak[1] if peak else None,
                "monotone_increasing": monotone if len(estimated) > 1 else None,
                "still_climbing_at_the_ceiling": (
                    bool(peak[0] == max(windows)) if peak and windows else None
                ),
            }
        )
    return curves


def evaluate_normalised_subarms(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    source: Literal["future", "past"],
    trade_identified: bool,
    replicates: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Evaluate the two frozen normalised robustness sub-arms outside the primary ranking."""

    rows: list[dict[str, Any]] = []
    baseline_names = ("log1p_l1_depth", "spread_ticks")
    for horizon in RETURN_HORIZONS_SECONDS:
        for window in OFI_WINDOWS_SECONDS:
            subarms = (
                ("M2b_normalised_trade", normalised_trade_feature(window), trade_identified),
                ("M3b_depth_normalised_cks", cks_pressure_feature(window), True),
            )
            for label, feature, available in subarms:
                if not available:
                    rows.append(
                        {
                            "source": source,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "subarm": label,
                            "status": "blocked_unidentified_signed_trades",
                        }
                    )
                    continue
                names = (*baseline_names, feature)
                train = _positions(observations, split.train, horizon, source, names=names)
                test = _positions(observations, split.test, horizon, source, names=names)
                embargoed = _positions(observations, split.embargoed, horizon, source, names=names)
                total = _positions(
                    observations,
                    tuple(range(len(observations))),
                    horizon,
                    source,
                    names=names,
                )
                support_by_tape = _support_by_tape(
                    observations, split, horizon=horizon, source=source, names=names
                )
                if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
                    rows.append(
                        {
                            "source": source,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "subarm": label,
                            "status": "data_insufficient_feature_support",
                            "total_n": len(total),
                            "train_n": len(train),
                            "embargoed_n": len(embargoed),
                            "test_n": len(test),
                            "support_by_tape": support_by_tape,
                        }
                    )
                    continue
                baseline = _fit_score(
                    observations,
                    train,
                    test,
                    model="M0",
                    names=baseline_names,
                    horizon=horizon,
                    source=source,
                )
                score = _fit_score(
                    observations,
                    train,
                    test,
                    model="M3",
                    names=names,
                    horizon=horizon,
                    source=source,
                )
                rows.append(
                    {
                        "source": source,
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "subarm": label,
                        "status": "estimated",
                        "total_n": len(total),
                        "train_n": len(train),
                        "embargoed_n": len(embargoed),
                        "test_n": len(test),
                        "support_by_tape": support_by_tape,
                        "in_sample_r2": score.payload["in_sample_r2"],
                        "in_sample_adjusted_r2": score.payload["in_sample_adjusted_r2"],
                        "oos_r2_training_mean": score.payload["oos_r2_training_mean"],
                        "incremental_oos_r2_over_m0": _difference(
                            score.payload["oos_r2_training_mean"],
                            baseline.payload["oos_r2_training_mean"],
                        ),
                        "coefficient_ticks_per_training_sd": score.payload[
                            "coefficients_ticks_per_training_sd"
                        ][feature],
                        "raw_coefficient_ticks_per_unit": score.payload[
                            "raw_coefficients_ticks_per_unit"
                        ][feature],
                        "rmse_ticks": score.payload["rmse_ticks"],
                        "mae_ticks": score.payload["mae_ticks"],
                        "selected_alpha": score.payload["selected_alpha"],
                        "training_standardisation": score.payload["training_standardisation"],
                        "per_tape": _per_tape_scores(
                            observations,
                            test,
                            horizon=horizon,
                            source=source,
                            score=score,
                            baseline=baseline,
                        ),
                        "direction_by_tape": _direction_by_tape(
                            observations,
                            train,
                            names=names,
                            model=label,
                            horizon=horizon,
                            source=source,
                            alpha=0.0,
                        ),
                        "error_improvement_inference_over_m0": _inference(
                            baseline,
                            score,
                            observations,
                            test,
                            horizon=horizon,
                            seed=(
                                seed
                                + int(horizon * 1000)
                                + int(window * 100)
                                + (20_000 if label.startswith("M2b") else 30_000)
                                + (0 if source == "future" else 1_000_000)
                            ),
                            replicates=replicates,
                        ),
                    }
                )
    return rows


@dataclass(frozen=True, slots=True)
class CczArmDesign:
    """Materialised CCZ level block for one ``(window, M)`` cell.

    ``normalised[:, m-1]`` is ``ofi^{m,h} = OFI^{m,h} / Q^{M,h}``.  It is derived from the stored
    raw level flow and the stored single common denominator rather than pre-stored per level, so
    every declared level count shares exactly one denominator by construction.
    """

    window: float
    levels: int
    positions: tuple[int, ...]
    index: Mapping[int, int]
    baseline: np.ndarray[Any, np.dtype[np.float64]]
    normalised: np.ndarray[Any, np.dtype[np.float64]]
    average: np.ndarray[Any, np.dtype[np.float64]]
    best_level: np.ndarray[Any, np.dtype[np.float64]]


def build_ccz_arm_design(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    *,
    window: float,
    levels: int,
) -> CczArmDesign:
    """Collect every candidate anchor that has complete ``M``-level CCZ support."""

    raw_names = ccz_raw_features(window, levels)
    denominator_name = denominator_feature(window, levels)
    required = (*BASELINE_FEATURES, denominator_name, *raw_names)
    positions = tuple(
        position for position in candidates if _has_features(observations[position], required)
    )
    baseline = _design(observations, positions, BASELINE_FEATURES)
    raw = _design(observations, positions, raw_names)
    denominator = _design(observations, positions, (denominator_name,)).reshape(-1, 1)
    normalised = raw / denominator
    average = normalised.mean(axis=1) if levels else np.zeros(len(positions), dtype=np.float64)
    best = normalised[:, 0] if levels else np.zeros(len(positions), dtype=np.float64)
    return CczArmDesign(
        window=window,
        levels=levels,
        positions=positions,
        index={position: row for row, position in enumerate(positions)},
        baseline=baseline,
        normalised=normalised,
        average=average,
        best_level=best,
    )


def _arm_columns(
    design: CczArmDesign,
    arm: str,
    weights: IntegratedWeights | None,
    rows: Sequence[int],
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], tuple[str, ...]]:
    selected = np.asarray(rows, dtype=np.intp)
    if arm == "per_level_pi":
        return design.normalised[selected], ccz_normalised_features(design.window, design.levels)
    if arm == "simple_average":
        return (
            design.average[selected].reshape(-1, 1),
            (average_feature(design.window, design.levels),),
        )
    if arm == "best_level":
        return (
            design.best_level[selected].reshape(-1, 1),
            (best_level_feature(design.window),),
        )
    if arm == "integrated":
        if weights is None:
            raise ValueError("the integrated arm needs weights fitted on training rows")
        projected = weights.project(design.normalised[selected]).reshape(-1, 1)
        return projected, (integrated_feature(design.window, design.levels),)
    raise ValueError(f"unknown CCZ aggregation arm {arm}")


def _ccz_arm_design_matrix(
    design: CczArmDesign,
    arm: str,
    weights: IntegratedWeights | None,
    rows: Sequence[int],
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], tuple[str, ...]]:
    columns, names = _arm_columns(design, arm, weights, rows)
    selected = np.asarray(rows, dtype=np.intp)
    return np.hstack([design.baseline[selected], columns]), (*BASELINE_FEATURES, *names)


def _select_alpha_for_arm(
    observations: Sequence[HorseRaceObservation],
    design: CczArmDesign,
    train_positions: Sequence[int],
    *,
    arm: str,
    weights: IntegratedWeights | None,
    horizon: float,
    source: Literal["future", "past"],
) -> float:
    """Choose the ridge penalty inside training only, on the same expanding folds as the race."""

    if arm not in REGULARISED_MODELS and arm != "per_level_pi":
        return 0.0
    scores: dict[float, list[float]] = {alpha: [] for alpha in RIDGE_ALPHAS}
    for inner_train, validation in _inner_folds(observations, train_positions):
        inner_rows = [
            design.index[position] for position in inner_train if position in design.index
        ]
        validation_rows = [
            design.index[position] for position in validation if position in design.index
        ]
        if len(inner_rows) < MINIMUM_FIT_OBSERVATIONS or not validation_rows:
            continue
        inner_positions = [design.positions[row] for row in inner_rows]
        validation_positions = [design.positions[row] for row in validation_rows]
        raw_train = _target(observations, inner_positions, horizon, source)
        raw_validation = _target(observations, validation_positions, horizon, source)
        drift = float(raw_train.mean())
        train_design, names = _ccz_arm_design_matrix(design, arm, weights, inner_rows)
        validation_design, _ = _ccz_arm_design_matrix(design, arm, weights, validation_rows)
        for alpha in RIDGE_ALPHAS:
            fit = fit_ridge(train_design, raw_train - drift, feature_names=names, penalty=alpha)
            residual = raw_validation - drift - fit.predict(validation_design)
            scores[alpha].append(float(np.mean(residual**2)))
    means = {
        alpha: (float(np.mean(values)) if values else float("inf"))
        for alpha, values in scores.items()
    }
    selected = min(RIDGE_ALPHAS, key=lambda alpha: (means[alpha], alpha))
    return selected if isfinite(means[selected]) else RIDGE_ALPHAS[0]


def evaluate_ccz_aggregation_arms(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    source: Literal["future", "past"] = "future",
    level_counts: Sequence[int] = CCZ_LEVEL_COUNTS,
    horizons: Sequence[float] = RETURN_HORIZONS_SECONDS,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """`EST-CCZ-04`, `EST-CCZ-05`, `EST-CCZ-06`: every declared arm at every declared ``M``.

    ``w_1`` for the integrated arm is fitted on **training rows only** and applied unchanged out
    of sample; the explained-variance ratio and the applied sign are reported for every fit.  No
    declared arm is dropped: an arm without complete level support is emitted with an explicit
    data-insufficient status rather than omitted.
    """

    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        for window in OFI_WINDOWS_SECONDS:
            for levels in sorted({int(value) for value in level_counts}):
                design = build_ccz_arm_design(
                    observations, tuple(range(len(observations))), window=window, levels=levels
                )
                available = set(design.positions)
                train = tuple(
                    position
                    for position in _positions(observations, split.train, horizon, source)
                    if position in available
                )
                test = tuple(
                    position
                    for position in _positions(observations, split.test, horizon, source)
                    if position in available
                )
                common = {
                    "source": source,
                    "estimator": "CCZ",
                    "h1_seconds": window,
                    "h2_seconds": horizon,
                    "levels": levels,
                    "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                    "train_n": len(train),
                    "test_n": len(test),
                }
                if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
                    rows.extend(
                        {**common, "arm": arm, "status": "data_insufficient_level_support"}
                        for arm in CCZ_AGGREGATION_ARMS
                    )
                    continue
                train_rows = [design.index[position] for position in train]
                test_rows = [design.index[position] for position in test]
                weights = fit_integrated_weights(design.normalised[np.asarray(train_rows)])
                baseline = _fit_score(
                    observations,
                    train,
                    test,
                    model="M0",
                    names=BASELINE_FEATURES,
                    horizon=horizon,
                    source=source,
                )
                for arm in CCZ_AGGREGATION_ARMS:
                    alpha = _select_alpha_for_arm(
                        observations,
                        design,
                        train,
                        arm=arm,
                        weights=weights,
                        horizon=horizon,
                        source=source,
                    )
                    train_design, names = _ccz_arm_design_matrix(design, arm, weights, train_rows)
                    test_design, _ = _ccz_arm_design_matrix(design, arm, weights, test_rows)
                    raw_train = _target(observations, train, horizon, source)
                    raw_test = _target(observations, test, horizon, source)
                    drift = float(raw_train.mean())
                    fit = fit_ridge(
                        train_design, raw_train - drift, feature_names=names, penalty=alpha
                    )
                    predicted = fit.predict(test_design)
                    target = raw_test - drift
                    benchmark = np.zeros(target.shape, dtype=np.float64)
                    arm_r2 = _r_squared(target, predicted, benchmark)
                    errors = tuple(float(value) for value in (target - predicted) ** 2)
                    estimate = estimate_mean(
                        [left - right for left, right in zip(baseline.errors, errors, strict=True)],
                        [observations[position].receive_ts_ns for position in test],
                        [observations[position].tape_index for position in test],
                        overlap_seconds=horizon + CAUSAL_GAP_SECONDS,
                        replicates=replicates,
                        seed=seed
                        + int(horizon * 1000)
                        + int(window * 100)
                        + levels * 7
                        + CCZ_AGGREGATION_ARMS.index(arm),
                    )
                    rows.append(
                        {
                            **common,
                            "arm": arm,
                            "status": "estimated",
                            "primary_arm": arm == PRIMARY_AGGREGATION_ARM,
                            "primary_level_count": levels == CCZ_PRIMARY_LEVELS,
                            "features": list(names),
                            "selected_alpha": alpha,
                            "oos_r2_training_mean": arm_r2,
                            "baseline_oos_r2_training_mean": (
                                baseline.payload["oos_r2_training_mean"]
                            ),
                            "incremental_oos_r2_over_m0": _difference(
                                arm_r2, baseline.payload["oos_r2_training_mean"]
                            ),
                            "rmse_ticks": sqrt(float(np.mean((target - predicted) ** 2))),
                            "coefficients_ticks_per_training_sd": {
                                name: float(fit.coefficients[index])
                                for index, name in enumerate(names)
                            },
                            "integrated_weights": (
                                weights.to_dict() if arm == "integrated" else None
                            ),
                            "explained_variance_ratio": weights.explained_variance_ratio,
                            "error_improvement_inference_over_m0": {
                                **asdict(estimate),
                                "naive_inference_valid": False,
                            },
                        }
                    )
    return rows


def evaluate_combined_ablations(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    trade_identified: bool,
) -> list[dict[str, Any]]:
    """Leave each predictor family out of M6 and score the held-out loss of fit."""

    rows: list[dict[str, Any]] = []
    for horizon in RETURN_HORIZONS_SECONDS:
        for window in OFI_WINDOWS_SECONDS:
            full_names = model_features("M6", window, trade_identified=trade_identified)
            train = _positions(observations, split.train, horizon, "future", names=full_names)
            test = _positions(observations, split.test, horizon, "future", names=full_names)
            full = _fit_score(
                observations,
                train,
                test,
                model="M6",
                names=full_names,
                horizon=horizon,
                source="future",
            )
            families: dict[str, set[str]] = {
                "M1_static_queue": {"l1_queue_imbalance"},
                "M2_signed_trades": {trade_feature(window)} if trade_identified else set(),
                "M3_cks_l1": {cks_feature(window)},
                "M4_ccz_raw_per_level_ofi": set(ccz_raw_features(window, CCZ_PRIMARY_LEVELS)),
                "M5_ccz_depth_scaled_per_level_ofi": set(
                    ccz_normalised_features(window, CCZ_PRIMARY_LEVELS)
                ),
            }
            for family, excluded in families.items():
                if not excluded:
                    rows.append(
                        {
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "excluded_family": family,
                            "status": "blocked_unidentified_signed_trades",
                        }
                    )
                    continue
                reduced_names = tuple(name for name in full_names if name not in excluded)
                reduced = _fit_score(
                    observations,
                    train,
                    test,
                    model="M6",
                    names=reduced_names,
                    horizon=horizon,
                    source="future",
                )
                rows.append(
                    {
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "excluded_family": family,
                        "status": "estimated",
                        "full_m6_oos_r2": full.payload["oos_r2_training_mean"],
                        "without_family_oos_r2": reduced.payload["oos_r2_training_mean"],
                        "family_incremental_oos_r2": _difference(
                            full.payload["oos_r2_training_mean"],
                            reduced.payload["oos_r2_training_mean"],
                        ),
                        "full_alpha": full.payload["selected_alpha"],
                        "reduced_alpha": reduced.payload["selected_alpha"],
                    }
                )
    return rows


def feature_intensity_table(
    observations: Sequence[HorseRaceObservation], *, trade_identified: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in OFI_WINDOWS_SECONDS:
        names = [
            "l1_queue_imbalance",
            cks_feature(window),
            cks_pressure_feature(window),
        ]
        if trade_identified:
            names.extend((trade_feature(window), normalised_trade_feature(window)))
        names.extend(best_level_feature(window) for _ in (0,))
        names.extend(average_feature(window, count) for count in CCZ_LEVEL_COUNTS)
        names.extend(ccz_raw_features(window, CCZ_PRIMARY_LEVELS))
        names.extend(ccz_normalised_features(window, CCZ_PRIMARY_LEVELS))
        for name in names:
            values = np.asarray(
                [
                    observation.features[name]
                    for observation in observations
                    if name in observation.features
                ]
            )
            rows.append(
                {
                    "h1_seconds": window,
                    "feature": name,
                    "n": len(values),
                    "missing_n": len(observations) - len(values),
                    "mean": float(values.mean()) if len(values) else None,
                    "standard_deviation": float(values.std()) if len(values) else None,
                    "mean_absolute": float(np.mean(np.abs(values))) if len(values) else None,
                    "zero_share": float(np.mean(values == 0.0)) if len(values) else None,
                }
            )
    return rows


def compact_support_table(
    primary_rows: Sequence[Mapping[str, Any]],
    normalised_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten common and model-specific support for compact artifact export."""

    result: list[dict[str, Any]] = []
    for category, rows, label_key in (
        ("primary", primary_rows, "model"),
        ("normalised_subarm", normalised_rows, "subarm"),
    ):
        for row in rows:
            support_by_tape = row.get("support_by_tape", {})
            model_support = row.get("model_specific_support_before_common_intersection", {})
            support_loss = row.get("support_loss_to_common_sample", {})
            result.append(
                {
                    "source": row.get("source"),
                    "category": category,
                    "label": row.get(label_key),
                    "h1_seconds": row.get("h1_seconds"),
                    "h2_seconds": row.get("h2_seconds"),
                    "status": row.get("status"),
                    "common_total_n": row.get("total_n"),
                    "common_train_n": row.get("train_n"),
                    "common_embargoed_n": row.get("embargoed_n"),
                    "common_test_n": row.get("test_n"),
                    "tape_0_test_n": support_by_tape.get("0", {}).get("test_n"),
                    "tape_1_test_n": support_by_tape.get("1", {}).get("test_n"),
                    "model_specific_total_n": model_support.get("total_n"),
                    "model_specific_train_n": model_support.get("train_n"),
                    "model_specific_embargoed_n": model_support.get("embargoed_n"),
                    "model_specific_test_n": model_support.get("test_n"),
                    "loss_to_common_total_n": support_loss.get("total_n"),
                    "loss_to_common_train_n": support_loss.get("train_n"),
                    "loss_to_common_embargoed_n": support_loss.get("embargoed_n"),
                    "loss_to_common_test_n": support_loss.get("test_n"),
                }
            )
    return result


def resolve_30_second_gate(
    future: Sequence[Mapping[str, Any]], past: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply the frozen four-condition gate mechanically to h2=10 non-combined models."""

    past_index = {
        (row.get("h1_seconds"), row.get("h2_seconds"), row.get("model")): row for row in past
    }
    candidates: list[dict[str, Any]] = []
    for model in ("M1", "M2", "M3", "M4", "M5"):
        model_rows = [
            row
            for row in future
            if row.get("model") == model
            and row.get("h2_seconds") == 10.0
            and row.get("status") == "estimated"
        ]
        if not model_rows:
            candidates.append({"model": model, "status": "unavailable", "all_conditions": False})
            continue
        row = max(
            model_rows,
            key=lambda item: (
                float(item.get("incremental_oos_r2_over_m0") or -float("inf")),
                -float(item["h1_seconds"]),
            ),
        )
        past_row = past_index[(row["h1_seconds"], row["h2_seconds"], model)]
        per_tape = row["per_tape"]
        directions = [value for value in row["direction_by_tape"].values() if value is not None]
        conditions = {
            "pooled_increment_strictly_positive": float(row["incremental_oos_r2_over_m0"]) > 0,
            "per_tape_increment_non_negative": all(
                value["incremental_oos_r2_over_m0"] is not None
                and value["incremental_oos_r2_over_m0"] >= 0
                for value in per_tape.values()
            ),
            "direction_stable_across_tapes": len(directions) == len(per_tape)
            and len(directions) >= 2
            and all(value > 0 for value in directions)
            or len(directions) >= 2
            and all(value < 0 for value in directions),
            "future_increment_stronger_than_past_mirror": (
                float(row["incremental_oos_r2_over_m0"])
                > float(past_row["incremental_oos_r2_over_m0"])
            ),
        }
        candidates.append(
            {
                "model": model,
                "h1_seconds": row["h1_seconds"],
                "future_incremental_oos_r2_over_m0": row["incremental_oos_r2_over_m0"],
                "past_incremental_oos_r2_over_m0": past_row["incremental_oos_r2_over_m0"],
                "conditions": conditions,
                "all_conditions": all(conditions.values()),
            }
        )
    passing = [candidate for candidate in candidates if candidate.get("all_conditions")]
    return {
        "gate_passed": bool(passing),
        "passing_candidates": passing,
        "evaluated_candidates": candidates,
        "same_window_cannot_open_gate": True,
        "combined_model_cannot_open_gate": True,
    }


def compact_rankings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for horizon in RETURN_HORIZONS_SECONDS:
        eligible = [
            row
            for row in rows
            if row.get("h2_seconds") == horizon
            and row.get("status") == "estimated"
            and row.get("model") != "M0"
        ]
        ordered = sorted(
            eligible,
            key=lambda row: (
                -(float(row.get("incremental_oos_r2_over_m0") or -float("inf"))),
                MODEL_ORDER.index(str(row["model"])),
                float(row["h1_seconds"]),
            ),
        )
        for rank, row in enumerate(ordered, start=1):
            result.append(
                {
                    "h2_seconds": horizon,
                    "rank": rank,
                    "model": row["model"],
                    "h1_seconds": row["h1_seconds"],
                    "oos_r2": row["oos_r2_training_mean"],
                    "incremental_oos_r2_over_m0": row["incremental_oos_r2_over_m0"],
                    "per_tape_increment": {
                        tape: payload["incremental_oos_r2_over_m0"]
                        for tape, payload in row["per_tape"].items()
                    },
                }
            )
    return result


@dataclass(frozen=True, slots=True)
class HorseRaceTapeInput:
    tape_index: int
    run_id: str
    instrument_id: str
    tape_sha256: str
    observations: tuple[HorseRaceObservation, ...]
    depth200_publications: int
    depth20_publications: int
    observed_seconds: float
    failures: Mapping[str, Any]


def build_horserace_artifact(
    tapes: Sequence[HorseRaceTapeInput],
    *,
    code_commit: str | None,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    observations = [observation for tape in tapes for observation in tape.observations]
    if not observations:
        raise ValueError("at least one horse-race observation is required")
    assert_no_lookahead(observations)
    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=EMBARGO_SECONDS,
    )
    # `MICRO-02` / `VAL-MICRO-01`: fit the Stoikov chain on this split's training rows only, then
    # overlay its adjustment as the M8 regressor and apply it unchanged out of sample.
    stoikov = fit_stoikov_for_split(observations, split)
    observations = with_stoikov_feature(observations, stoikov)
    trade_identified = all(
        bool(
            tape.failures.get("trade_support", {}).get("qualified_packets", 0)
            >= MINIMUM_TRADE_PACKETS
        )
        for tape in tapes
    )
    future = evaluate_cells(
        observations,
        split,
        horizons=RETURN_HORIZONS_SECONDS,
        source="future",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed,
    )
    past = evaluate_cells(
        observations,
        split,
        horizons=RETURN_HORIZONS_SECONDS,
        source="past",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 10_000_000,
    )
    normalised_future = evaluate_normalised_subarms(
        observations,
        split,
        source="future",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 30_000_000,
    )
    normalised_past = evaluate_normalised_subarms(
        observations,
        split,
        source="past",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 40_000_000,
    )
    ablations = evaluate_combined_ablations(observations, split, trade_identified=trade_identified)
    ccz_arms = evaluate_ccz_aggregation_arms(
        observations,
        split,
        source="future",
        replicates=replicates,
        seed=seed + 50_000_000,
    )
    ccz_arms_past = evaluate_ccz_aggregation_arms(
        observations,
        split,
        source="past",
        replicates=replicates,
        seed=seed + 60_000_000,
    )
    explained = {
        f"w{_label(float(row['h1_seconds']))}__m{row['levels']}": row["explained_variance_ratio"]
        for row in ccz_arms
        if row.get("status") == "estimated"
    }
    floored = 0
    for tape in tapes:
        value = tape.failures.get("ccz_depth_denominator_floored")
        if isinstance(value, int):
            floored += value
    gate = resolve_30_second_gate(future, past)
    conditional: list[dict[str, Any]] = []
    if gate["gate_passed"]:
        conditional = evaluate_cells(
            observations,
            split,
            horizons=(CONDITIONAL_HORIZON_SECONDS,),
            source="future",
            trade_identified=trade_identified,
            replicates=replicates,
            seed=seed + 20_000_000,
        )
    intensity = feature_intensity_table(observations, trade_identified=trade_identified)
    support = compact_support_table([*future, *past], [*normalised_future, *normalised_past])
    # `WINDOW-01`/`WINDOW-02`: the contemporaneous grid is now a replication gate, and it runs
    # under every reference price so the CCZ comparison cell is not tied to the displayed mid.
    same_window: list[dict[str, Any]] = []
    for reference in REFERENCE_PRICE_LADDER:
        for basis in ("displayed", "effective_touch"):
            same_window.extend(
                evaluate_same_window(
                    observations,
                    split,
                    trade_identified=trade_identified,
                    basis=basis,
                    reference=reference,
                    replicates=replicates,
                    seed=seed + 80_000_000,
                )
            )
    # `TOUCH-03`/`TOUCH-04`: the predictive grid re-run under each reference price on both sides
    # of the regression.  The displayed-mid, displayed-basis cell is the status quo baseline and
    # is already in ``future``; the remaining combinations are the ladder.
    ladder_future: list[dict[str, Any]] = []
    ladder_past: list[dict[str, Any]] = []
    ladder_failures: list[dict[str, Any]] = []
    for index, reference in enumerate(REFERENCE_PRICE_LADDER):
        for basis_index, basis in enumerate(("displayed", "effective_touch")):
            if reference == BASELINE_REFERENCE and basis == "displayed":
                continue
            offset = 90_000_000 + index * 1_000_000 + basis_index * 100_000
            try:
                ladder_future.extend(
                    evaluate_cells(
                        observations,
                        split,
                        horizons=RETURN_HORIZONS_SECONDS,
                        source="future",
                        trade_identified=trade_identified,
                        replicates=replicates,
                        seed=seed + offset,
                        reference=reference,
                        basis=basis,
                    )
                )
                ladder_past.extend(
                    evaluate_cells(
                        observations,
                        split,
                        horizons=RETURN_HORIZONS_SECONDS,
                        source="past",
                        trade_identified=trade_identified,
                        replicates=replicates,
                        seed=seed + offset + 50_000,
                        reference=reference,
                        basis=basis,
                    )
                )
            except ValueError as error:
                # A reference price with too little common support is recorded as an uncovered
                # cell set, never silently omitted from the ladder (`VAL-TOUCH-03`).
                ladder_failures.append(
                    {
                        "reference_price": reference,
                        "predictor_basis": basis,
                        "status": "insufficient_common_support",
                        "detail": str(error),
                    }
                )
    all_future = [*future, *ladder_future]
    all_past = [*past, *ladder_past]
    # `METRIC-04` / `VAL-METRIC-02`: refuse the artifact if any cell reports an R2 alone.
    for row in (*all_future, *all_past, *same_window):
        assert_companion_metrics(
            row,
            label=(
                f"{row.get('source', 'same_window')}:{row.get('reference_price')}:"
                f"{row.get('predictor_basis')}:{row.get('model')}"
                f"@h1={row.get('h1_seconds')},h2={row.get('h2_seconds')}"
            ),
        )
    # `WINDOW-03`: the same contemporaneous grid at every declared CCZ depth, so the curve can be
    # read per level count rather than only at the primary M = 10.
    depth_grid: list[dict[str, Any]] = []
    for reference in REFERENCE_PRICE_LADDER:
        depth_grid.extend(evaluate_same_window_by_depth(observations, split, reference=reference))
    mirror = _past_mirror_table(all_future, all_past)
    return {
        "schema_version": 3,
        "scan_id": EXPLORATORY_SCAN_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "design_document": DESIGN_DOCUMENT,
        "migration_document": MIGRATION_DOCUMENT,
        "ccz": ccz_metadata(
            level_counts=CCZ_LEVEL_COUNTS,
            primary_levels=CCZ_PRIMARY_LEVELS,
            explained_variance_ratio=explained,
            denominator_floor_events=floored,
        ),
        "code_commit": code_commit,
        "tapes": [
            {
                "tape_index": tape.tape_index,
                "run_id": tape.run_id,
                "instrument_id": tape.instrument_id,
                "tape_sha256": tape.tape_sha256,
                "observations": len(tape.observations),
                "depth200_publications": tape.depth200_publications,
                "depth20_publications": tape.depth20_publications,
                "observed_seconds": tape.observed_seconds,
                "failures": tape.failures,
            }
            for tape in tapes
        ],
        "sample": {
            "observations": len(observations),
            "train_n": len(split.train),
            "embargoed_n": len(split.embargoed),
            "test_n": len(split.test),
            "split_boundaries": split.boundaries,
            "trade_model_identified": trade_identified,
            "common_sample_models": list(MODEL_ORDER),
        },
        "axes": {
            "h1_seconds": OFI_WINDOWS_SECONDS,
            "h2_seconds": RETURN_HORIZONS_SECONDS,
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "models": MODEL_ORDER,
            "ccz_level_counts": CCZ_LEVEL_COUNTS,
            "ccz_primary_levels": CCZ_PRIMARY_LEVELS,
            "ccz_aggregation_arms": CCZ_AGGREGATION_ARMS,
            "ridge_alphas": RIDGE_ALPHAS,
        },
        "future_cells": future,
        "past_mirror_cells": past,
        "reference_price_ladder_future_cells": ladder_future,
        "reference_price_ladder_past_cells": ladder_past,
        "reference_price_ladder_uncovered": ladder_failures,
        "same_window_diagnostic": same_window,
        "same_window_r2_curve": same_window_curve(same_window),
        "same_window_by_depth": depth_grid,
        "same_window_depth_r2_curve": depth_r2_curve(depth_grid),
        "past_mirror_table": mirror,
        "rankings": compact_rankings(future),
        "reference_price_rankings": compact_rankings(ladder_future),
        "normalised_subarms_future": normalised_future,
        "normalised_subarms_past": normalised_past,
        "combined_ablations": ablations,
        "ccz_aggregation_arms_future": ccz_arms,
        "ccz_aggregation_arms_past": ccz_arms_past,
        "feature_intensity": intensity,
        "support_table": support,
        "gate_30_seconds": gate,
        "conditional_30_second_cells": conditional,
        "multiplicity": {
            "ccz_aggregation_arm_cells_per_direction": len(ccz_arms),
            "future_ranked_cells": len(future),
            "past_mirror_cells": len(past),
            "same_window_diagnostic_cells": 5 * len(MODEL_ORDER),
            "normalised_subarm_cells_per_direction": len(normalised_future),
            "combined_ablation_cells": len(ablations),
            "naive_iid_inference_valid": False,
        },
        "touch_metrics_document": TOUCH_METRICS_DOCUMENT,
        "metrics": metric_metadata(),
        "microprice": {**microprice_metadata(), "stoikov_model": stoikov.to_dict()},
        "touch_relative": touch_relative_metadata(),
        "reference_prices": {
            "requirement": "TOUCH-03",
            "ladder": list(REFERENCE_PRICE_LADDER),
            "baseline_reference": BASELINE_REFERENCE,
            "predictor_bases": ["displayed", "effective_touch"],
            "applied_on_both_sides_of_the_regression": True,
            "uncovered_combinations": len(ladder_failures),
        },
        "window_extension": {
            "requirement": "WINDOW-01",
            "same_window_seconds": list(SAME_WINDOW_SECONDS),
            "ccz_comparison_window_seconds": CCZ_CONTEMPORANEOUS_WINDOW_SECONDS,
            "published_best_level_in_sample_r2": CCZ_PUBLISHED_BEST_LEVEL_IN_SAMPLE_R2,
            "published_best_level_out_of_sample_r2": CCZ_PUBLISHED_BEST_LEVEL_OUT_OF_SAMPLE_R2,
            "published_integrated_in_sample_r2": CCZ_PUBLISHED_INTEGRATED_IN_SAMPLE_R2,
            "promoted_from_descriptive_only": True,
        },
        "evidence_level": "Level 3 machinery; exploratory empirical content only",
    }


def _past_mirror_table(
    future: Sequence[Mapping[str, Any]], past: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """`METRIC-05`: every metric compared with its own past mirror, with a BY-adjusted family.

    A cell whose headline improves while the past mirror reproduces the improvement is reported
    as **failing**, because a predictor cannot have information about the past.
    """

    index = {
        (
            row.get("reference_price"),
            row.get("predictor_basis"),
            row.get("h1_seconds"),
            row.get("h2_seconds"),
            row.get("model"),
        ): row
        for row in past
    }
    rows: list[dict[str, Any]] = []
    for row in future:
        if row.get("status") != "estimated":
            continue
        key = (
            row.get("reference_price"),
            row.get("predictor_basis"),
            row.get("h1_seconds"),
            row.get("h2_seconds"),
            row.get("model"),
        )
        mirrored = index.get(key)
        metrics = row.get("metrics") or {}
        mirror_metrics = (mirrored or {}).get("metrics") or {}
        pearson = (metrics.get("information_coefficient") or {}).get("pearson") or {}
        mirror_pearson = (mirror_metrics.get("information_coefficient") or {}).get("pearson") or {}
        rows.append(
            {
                "reference_price": key[0],
                "predictor_basis": key[1],
                "h1_seconds": key[2],
                "h2_seconds": key[3],
                "model": key[4],
                "oos_r2": past_mirror_verdict(
                    future_value=row.get("oos_r2_training_mean"),
                    past_value=(mirrored or {}).get("oos_r2_training_mean"),
                    label="oos_r2_training_mean",
                ),
                # An IC's sign is a direction, not a quality: a past-return IC of -0.3 is as
                # much of a warning as +0.3, so this one comparison is two-sided.
                "information_coefficient": past_mirror_verdict(
                    future_value=pearson.get("estimate"),
                    past_value=mirror_pearson.get("estimate"),
                    label="pearson_information_coefficient",
                    two_sided=True,
                ),
                "per_tape_sign_check": metrics.get("per_tape_sign_check"),
                "_pearson_p": _bootstrap_p_value(pearson),
            }
        )
    raw_p = [row.pop("_pearson_p") for row in rows]
    adjusted = benjamini_yekutieli(raw_p)
    for row, unadjusted, value in zip(rows, raw_p, adjusted, strict=True):
        row["pearson_bootstrap_p_value"] = unadjusted
        row["benjamini_yekutieli_q_value"] = value
        row["family_size"] = len(rows)
    return rows


def _bootstrap_p_value(block: Mapping[str, Any]) -> float | None:
    """Two-sided normal-approximation p from the stationary block-bootstrap standard error.

    The bootstrap standard error is the only dependence-aware precision the IC block carries, so
    it is the one this family is ordered on.  It is an approximation and is labelled as one; the
    Benjamini-Yekutieli adjustment then controls the FDR across the family without assuming the
    cells are positively dependent.
    """

    estimate = block.get("estimate")
    standard_error = block.get("standard_error")
    if estimate is None or standard_error is None or standard_error <= 0.0:
        return None
    return float(2.0 * norm.sf(abs(float(estimate) / float(standard_error))))
