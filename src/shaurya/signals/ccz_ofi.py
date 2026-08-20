"""Cont-Cucuringu-Zhang multi-level order flow imbalance.

Reference: Cont, Cucuringu & Zhang, *Cross-Impact of Order Flow Imbalance in Equity Markets*,
Quantitative Finance (2023); arXiv:2112.13213v4.  Equation numbers below are that paper's.

This module is the **single definition of order flow imbalance** in this repository.  It replaces
two earlier constructions that were not CCZ:

* the price-keyed innovation accumulated into a running sum across levels
  (``cumulative_by_depth[L] = sum over rank <= L``), which CCZ never do, and
* the disjoint-band flow divided by *that band's own* mean depth, whereas CCZ Eq. (3) divides
  every level by **one common** denominator so that relative cross-level magnitudes survive.

The level-one CKS (2014) event increment in :mod:`shaurya.signals.cks_l1_ofi` is CCZ Eq. (1)'s
base case and is retained unchanged.

Frozen specification: ``docs/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md`` (``D37``).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from shaurya.data.depth_thinning_analysis import BookState

SPECIFICATION_ID: Final = "D37 / CCZ-OFI-MIGRATION-2026-08-20"
DESIGN_DOCUMENT: Final = "docs/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md"
ESTIMATOR_NAME: Final = "CCZ"
CCZ_REFERENCE: Final = (
    "Cont, Cucuringu & Zhang (2023), Cross-Impact of Order Flow Imbalance in Equity Markets, "
    "Quantitative Finance; arXiv:2112.13213v4"
)

#: `EST-CCZ-06`.  ``M = 10`` is primary, matching CCZ.  No declared arm is dropped.
PRIMARY_LEVEL_COUNT: Final = 10
ROBUSTNESS_LEVEL_COUNTS: Final = (1, 5, 20, 200)
DECLARED_LEVEL_COUNTS: Final = (1, 5, 10, 20, 200)

#: `EST-CCZ-05`.  The four declared aggregation arms; the integrated arm is primary.
AGGREGATION_ARMS: Final = ("per_level_pi", "integrated", "simple_average", "best_level")
PRIMARY_AGGREGATION_ARM: Final = "integrated"

#: `EST-CCZ-03`.  Floor on ``Q^{M,h}`` in contracts so scaling cannot divide by ~zero.  Every
#: flooring event is recorded in diagnostics rather than silently absorbed.
MINIMUM_DEPTH_DENOMINATOR: Final = 1.0

#: `ID-CCZ-01`.  Stated, never patched around.  Must appear in every artifact and report.
ID_CCZ_01: Final = "ID-CCZ-01"
ID_CCZ_01_LIMITATION: Final = (
    "ID-CCZ-01: Dhan publishes book snapshots, not order-by-order messages. Faithful CCZ Eq. (2) "
    "compares the level-m price across consecutive states (rank-keyed), so a single best-quote "
    "move shifts every level's identity and one price change can register as order flow at many "
    "levels at once. The retired price-keyed design existed specifically to avoid this; faithful "
    "CCZ reintroduces it. This is a limitation of the estimand under snapshot data. It is "
    "documented, not silently corrected. Gross limit arrivals and gross cancellations remain "
    "unidentified (ID-01)."
)


def window_label(value: float) -> str:
    """Stable filename/feature-safe label for a horizon in seconds."""

    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def level_feature(window_seconds: float, level: int) -> str:
    """Raw per-level ``OFI^{m,h}`` (Eq. 2).  Carries no depth scaling by construction."""

    return f"ccz_ofi_w{window_label(window_seconds)}__level_{level}"


def denominator_feature(window_seconds: float, levels: int) -> str:
    """The single common depth denominator ``Q^{M,h}`` (Eq. 3) for a declared level count."""

    return f"ccz_qdepth_w{window_label(window_seconds)}__m{levels}"


def normalised_level_feature(window_seconds: float, level: int, levels: int) -> str:
    """Depth-scaled per-level ``ofi^{m,h} = OFI^{m,h} / Q^{M,h}`` (Eq. 3)."""

    return f"ccz_ofi_w{window_label(window_seconds)}__m{levels}__norm_level_{level}"


def integrated_feature(window_seconds: float, levels: int) -> str:
    """Integrated OFI ``ofi^{I,h}`` (Eq. 4).  Materialised at fit time, never pre-stored."""

    return f"ccz_ofi_w{window_label(window_seconds)}__m{levels}__integrated"


def average_feature(window_seconds: float, levels: int) -> str:
    """Simple average across levels — the CCZ Appendix A benchmark arm."""

    return f"ccz_ofi_w{window_label(window_seconds)}__m{levels}__average"


def best_level_feature(window_seconds: float) -> str:
    """Best-level-only arm (``m = 1``), the CKS (2014) baseline inside the CCZ family."""

    return f"ccz_ofi_w{window_label(window_seconds)}__best_level"


@dataclass(frozen=True, slots=True)
class CczLevelFlow:
    """`EST-CCZ-01`: rank-keyed per-level order flow for one book transition (Eq. 2 terms).

    ``bid_flow[m-1]`` is ``OF^{m,b}_n`` and ``ask_flow[m-1]`` is ``OF^{m,a}_n``.  ``order_flow`` is
    the Eq. (2) summand ``OF^{m,b}_n - OF^{m,a}_n``.  There is **no** sum over levels anywhere.
    """

    receive_ts_ns: int
    bid_flow: tuple[float, ...]
    ask_flow: tuple[float, ...]
    order_flow: tuple[float, ...]
    depth: tuple[float, ...]
    levels_covered: int
    invalid_reason: str | None = None


def _side_arrays(
    state: BookState, side: str, levels: int
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], np.ndarray[Any, np.dtype[np.float64]]]:
    ladder = state.bids if side == "bid" else state.asks
    prices = np.full(levels, np.nan, dtype=np.float64)
    quantities = np.zeros(levels, dtype=np.float64)
    usable = min(len(ladder), levels)
    for index in range(usable):
        price, quantity, _orders = ladder[index]
        prices[index] = float(price)
        quantities[index] = float(quantity)
    return prices, quantities


def _covered_levels(previous: BookState, current: BookState, levels: int) -> int:
    return min(len(previous.bids), len(previous.asks), len(current.bids), len(current.asks), levels)


def _bid_order_flow(
    old_price: np.ndarray[Any, np.dtype[np.float64]],
    old_quantity: np.ndarray[Any, np.dtype[np.float64]],
    new_price: np.ndarray[Any, np.dtype[np.float64]],
    new_quantity: np.ndarray[Any, np.dtype[np.float64]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """``OF^{m,b}_n`` exactly as in Eq. (2); NaN padding compares false on every branch."""

    improved = new_price > old_price
    unchanged = new_price == old_price
    return np.where(
        improved,
        new_quantity,
        np.where(unchanged, new_quantity - old_quantity, -new_quantity),
    )


def _ask_order_flow(
    old_price: np.ndarray[Any, np.dtype[np.float64]],
    old_quantity: np.ndarray[Any, np.dtype[np.float64]],
    new_price: np.ndarray[Any, np.dtype[np.float64]],
    new_quantity: np.ndarray[Any, np.dtype[np.float64]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """``OF^{m,a}_n`` exactly as in Eq. (2); the ask sign convention is the mirror of the bid."""

    retreated = new_price > old_price
    unchanged = new_price == old_price
    return np.where(
        retreated,
        -new_quantity,
        np.where(unchanged, new_quantity - old_quantity, new_quantity),
    )


def ccz_level_flow(
    previous: BookState,
    current: BookState,
    *,
    levels: int = PRIMARY_LEVEL_COUNT,
    invalid_reason: str | None = None,
) -> CczLevelFlow:
    """`EST-CCZ-01`: reference scalar implementation of the Eq. (2) per-level order flow.

    Rank-keyed: the level-``m`` price is compared across the two states.  Levels absent from
    either endpoint are reported as uncovered and contribute zero rather than a fabricated flow.
    """

    if levels < 1:
        raise ValueError("level count must be positive")
    if invalid_reason is not None:
        zeros = (0.0,) * levels
        return CczLevelFlow(current.receive_ts_ns, zeros, zeros, zeros, zeros, 0, invalid_reason)
    covered = _covered_levels(previous, current, levels)
    old_bid_price, old_bid_quantity = _side_arrays(previous, "bid", levels)
    new_bid_price, new_bid_quantity = _side_arrays(current, "bid", levels)
    old_ask_price, old_ask_quantity = _side_arrays(previous, "ask", levels)
    new_ask_price, new_ask_quantity = _side_arrays(current, "ask", levels)
    mask = np.arange(levels) < covered
    bid = np.where(
        mask,
        _bid_order_flow(old_bid_price, old_bid_quantity, new_bid_price, new_bid_quantity),
        0.0,
    )
    ask = np.where(
        mask,
        _ask_order_flow(old_ask_price, old_ask_quantity, new_ask_price, new_ask_quantity),
        0.0,
    )
    depth = np.where(mask, new_bid_quantity + new_ask_quantity, 0.0)
    return CczLevelFlow(
        receive_ts_ns=current.receive_ts_ns,
        bid_flow=tuple(float(value) for value in bid),
        ask_flow=tuple(float(value) for value in ask),
        order_flow=tuple(float(value) for value in bid - ask),
        depth=tuple(float(value) for value in depth),
        levels_covered=covered,
        invalid_reason=None,
    )


@dataclass(frozen=True, slots=True)
class CczWindow:
    """One evaluated ``(t-h, t]`` window at one declared level count ``M``."""

    levels: int
    window_seconds: float
    events: int
    raw: tuple[float, ...]
    denominator: float
    unfloored_denominator: float
    denominator_floored: bool
    normalised: tuple[float, ...]

    @property
    def simple_average(self) -> float:
        """CCZ Appendix A benchmark: the unweighted mean of the depth-scaled levels."""

        return float(sum(self.normalised) / len(self.normalised))

    @property
    def best_level(self) -> float:
        """CKS (2014) baseline inside the CCZ family: level one only."""

        return self.normalised[0]


class CczFlowSeries:
    """Prefix sums of per-level CCZ order flow and depth over one contiguous state sequence.

    Windows are half-open ``(t-h, t]`` in capture time, matching the rest of the repository.  A
    window that contains any refused transition, or that lacks full ``M``-level support on every
    contained event, is reported as unavailable rather than silently zero-filled.
    """

    __slots__ = (
        "_denominator_prefix",
        "_flow_prefix",
        "_invalid_prefix",
        "_level_counts",
        "_levels",
        "_support_prefix",
        "_timestamps",
        "_valid_prefix",
    )

    def __init__(
        self,
        *,
        timestamps: Sequence[int],
        flow_prefix: np.ndarray[Any, np.dtype[np.float64]],
        denominator_prefix: np.ndarray[Any, np.dtype[np.float64]],
        invalid_prefix: Sequence[int],
        valid_prefix: Sequence[int],
        support_prefix: Mapping[int, Sequence[int]],
        levels: int,
        level_counts: Sequence[int],
    ) -> None:
        self._timestamps = tuple(timestamps)
        self._flow_prefix = flow_prefix
        self._denominator_prefix = denominator_prefix
        self._invalid_prefix = tuple(invalid_prefix)
        self._valid_prefix = tuple(valid_prefix)
        self._support_prefix = {key: tuple(value) for key, value in support_prefix.items()}
        self._levels = levels
        self._level_counts = tuple(level_counts)

    @property
    def timestamps(self) -> tuple[int, ...]:
        return self._timestamps

    @property
    def levels(self) -> int:
        return self._levels

    @property
    def level_counts(self) -> tuple[int, ...]:
        return self._level_counts

    def __len__(self) -> int:
        return len(self._timestamps)

    @classmethod
    def from_states(
        cls,
        states: Sequence[BookState],
        *,
        level_counts: Sequence[int] = DECLARED_LEVEL_COUNTS,
        invalid_reasons: Sequence[str | None] | None = None,
    ) -> CczFlowSeries:
        """Build the prefix structure over ``len(states) - 1`` consecutive transitions."""

        counts = tuple(sorted({int(value) for value in level_counts}))
        if not counts or counts[0] < 1:
            raise ValueError("level counts must be positive")
        levels = counts[-1]
        transitions = max(len(states) - 1, 0)
        flow = np.zeros((transitions, levels), dtype=np.float64)
        depth_by_count = np.zeros((transitions, len(counts)), dtype=np.float64)
        timestamps: list[int] = []
        invalid = [0]
        valid = [0]
        support: dict[int, list[int]] = {count: [0] for count in counts}
        if invalid_reasons is not None and len(invalid_reasons) != transitions:
            raise ValueError("invalid_reasons must carry one entry per transition")
        index = np.arange(levels)
        previous_price: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
        previous_quantity: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
        for position in range(transitions):
            previous_state = states[position]
            current_state = states[position + 1]
            timestamps.append(current_state.receive_ts_ns)
            reason = None if invalid_reasons is None else invalid_reasons[position]
            if not previous_price:
                for side in ("bid", "ask"):
                    price, quantity = _side_arrays(previous_state, side, levels)
                    previous_price[side] = price
                    previous_quantity[side] = quantity
            current_price: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
            current_quantity: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
            for side in ("bid", "ask"):
                price, quantity = _side_arrays(current_state, side, levels)
                current_price[side] = price
                current_quantity[side] = quantity
            if reason is None:
                covered = _covered_levels(previous_state, current_state, levels)
                mask = index < covered
                bid = _bid_order_flow(
                    previous_price["bid"],
                    previous_quantity["bid"],
                    current_price["bid"],
                    current_quantity["bid"],
                )
                ask = _ask_order_flow(
                    previous_price["ask"],
                    previous_quantity["ask"],
                    current_price["ask"],
                    current_quantity["ask"],
                )
                flow[position] = np.where(mask, bid - ask, 0.0)
                level_depth = np.where(mask, current_quantity["bid"] + current_quantity["ask"], 0.0)
                cumulative_depth = np.cumsum(level_depth)
                for column, count in enumerate(counts):
                    depth_by_count[position, column] = cumulative_depth[count - 1]
            else:
                covered = 0
            invalid.append(invalid[-1] + int(reason is not None))
            valid.append(valid[-1] + int(reason is None))
            for count in counts:
                support[count].append(support[count][-1] + int(reason is None and covered >= count))
            previous_price = current_price
            previous_quantity = current_quantity
        flow_prefix = np.zeros((transitions + 1, levels), dtype=np.float64)
        np.cumsum(flow, axis=0, out=flow_prefix[1:])
        denominator_prefix = np.zeros((transitions + 1, len(counts)), dtype=np.float64)
        np.cumsum(depth_by_count, axis=0, out=denominator_prefix[1:])
        return cls(
            timestamps=timestamps,
            flow_prefix=flow_prefix,
            denominator_prefix=denominator_prefix,
            invalid_prefix=invalid,
            valid_prefix=valid,
            support_prefix=support,
            levels=levels,
            level_counts=counts,
        )

    def locate(self, start_ts_ns: int, end_position: int) -> int:
        """Left index of the half-open ``(start, end]`` window over transition timestamps."""

        return bisect_right(self._timestamps, start_ts_ns)

    def window(
        self,
        left: int,
        right: int,
        *,
        levels: int,
        window_seconds: float,
    ) -> CczWindow | None:
        """`EST-CCZ-02` and `EST-CCZ-03` for one window at one declared level count."""

        if levels not in self._level_counts:
            raise ValueError(f"level count {levels} was not declared for this series")
        if left >= right:
            return None
        if self._invalid_prefix[right] - self._invalid_prefix[left] != 0:
            return None
        events = self._valid_prefix[right] - self._valid_prefix[left]
        if events <= 0:
            return None
        supported = self._support_prefix[levels][right] - self._support_prefix[levels][left]
        if supported != events:
            return None
        raw = self._flow_prefix[right, :levels] - self._flow_prefix[left, :levels]
        column = self._level_counts.index(levels)
        depth_total = float(
            self._denominator_prefix[right, column] - self._denominator_prefix[left, column]
        )
        unfloored = depth_total / (2.0 * levels * events)
        denominator = max(unfloored, MINIMUM_DEPTH_DENOMINATOR)
        normalised = raw / denominator
        return CczWindow(
            levels=levels,
            window_seconds=window_seconds,
            events=events,
            raw=tuple(float(value) for value in raw),
            denominator=denominator,
            unfloored_denominator=unfloored,
            denominator_floored=unfloored < MINIMUM_DEPTH_DENOMINATOR,
            normalised=tuple(float(value) for value in normalised),
        )


@dataclass(frozen=True, slots=True)
class IntegratedWeights:
    """`EST-CCZ-04`: the first principal component of the multi-level normalised OFI vector.

    ``weights`` is ``w_1`` after the sign fix.  ``normalised_weights`` is ``w_1 / ||w_1||_1``,
    which is what Eq. (4) applies.  It is fitted on training rows only and applied unchanged out
    of sample; :func:`fit_integrated_weights` never sees a test row.
    """

    levels: int
    weights: tuple[float, ...]
    normalised_weights: tuple[float, ...]
    l1_norm: float
    explained_variance_ratio: float
    applied_sign: float
    dominant_level: int
    training_rows: int

    def project(
        self, matrix: np.ndarray[Any, np.dtype[np.float64]]
    ) -> np.ndarray[Any, np.dtype[np.float64]]:
        """Eq. (4): ``ofi^{I,h}_t = w_1^T ofi^{(h)}_t / ||w_1||_1`` on uncentred level vectors."""

        weights = np.asarray(self.normalised_weights, dtype=np.float64)
        design = np.asarray(matrix, dtype=np.float64).reshape(-1, self.levels)
        return design @ weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "levels": self.levels,
            "weights": list(self.weights),
            "normalised_weights": list(self.normalised_weights),
            "l1_norm": self.l1_norm,
            "explained_variance_ratio": self.explained_variance_ratio,
            "applied_sign": self.applied_sign,
            "dominant_level": self.dominant_level,
            "training_rows": self.training_rows,
            "fitted_on": "training_rows_only",
        }


def fit_integrated_weights(
    training_matrix: np.ndarray[Any, np.dtype[np.float64]],
) -> IntegratedWeights:
    """`EST-CCZ-04`: fit ``w_1`` by PCA on training rows of the normalised multi-level OFI.

    The component is obtained from the training covariance (mean-centred, as PCA requires) and is
    then applied to the **uncentred** level vector, which is what Eq. (4) states.  The sign is
    fixed so the dominant loading is positive and the applied sign is recorded.
    """

    matrix = np.asarray(training_matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError("integrated OFI needs at least two training rows and one level")
    levels = int(matrix.shape[1])
    centred = matrix - matrix.mean(axis=0)
    _left, singular, right = np.linalg.svd(centred, full_matrices=False)
    variance = singular**2
    total = float(variance.sum())
    explained = float(variance[0] / total) if total > 0.0 else 0.0
    component = np.asarray(right[0], dtype=np.float64)
    dominant = int(np.argmax(np.abs(component)))
    sign = -1.0 if component[dominant] < 0.0 else 1.0
    component = component * sign
    l1_norm = float(np.abs(component).sum())
    if l1_norm <= 0.0:
        raise ValueError("first principal component is degenerate")
    return IntegratedWeights(
        levels=levels,
        weights=tuple(float(value) for value in component),
        normalised_weights=tuple(float(value) / l1_norm for value in component),
        l1_norm=l1_norm,
        explained_variance_ratio=explained,
        applied_sign=sign,
        dominant_level=dominant + 1,
        training_rows=int(matrix.shape[0]),
    )


def aggregate_window(window: CczWindow, weights: IntegratedWeights | None) -> dict[str, float]:
    """`EST-CCZ-05`: the declared scalar aggregation arms for one evaluated window."""

    result = {
        "simple_average": window.simple_average,
        "best_level": window.best_level,
    }
    if weights is not None:
        if weights.levels != window.levels:
            raise ValueError("integrated weights were fitted at a different level count")
        vector = np.asarray(window.normalised, dtype=np.float64)
        result["integrated"] = float(weights.project(vector.reshape(1, -1))[0])
    return result


class CczFeatureSchema:
    """Shared, interned name/index table so per-anchor feature vectors stay compact."""

    __slots__ = ("_index", "_names")

    def __init__(self, names: Sequence[str]) -> None:
        ordered = tuple(dict.fromkeys(names))
        self._names = ordered
        self._index = {name: position for position, name in enumerate(ordered)}

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    def position(self, name: str) -> int | None:
        return self._index.get(name)

    def __len__(self) -> int:
        return len(self._names)


class CczFeatureVector(Mapping[str, float]):
    """A ``Mapping[str, float]`` backed by one dense array plus a presence mask.

    The multi-level arms declare up to ``200`` levels at five windows, so a plain per-anchor
    ``dict`` would dominate memory in the live dashboard.  This keeps the exact existing mapping
    interface — ``name in features`` and ``features[name]`` — at one float per declared feature.
    """

    __slots__ = ("_present", "_schema", "_values")

    def __init__(
        self,
        schema: CczFeatureSchema,
        values: np.ndarray[Any, np.dtype[np.float64]],
        present: np.ndarray[Any, np.dtype[np.bool_]],
    ) -> None:
        self._schema = schema
        self._values = values
        self._present = present

    @classmethod
    def build(cls, schema: CczFeatureSchema, values: Mapping[str, float]) -> CczFeatureVector:
        dense = np.zeros(len(schema), dtype=np.float64)
        present = np.zeros(len(schema), dtype=np.bool_)
        for name, value in values.items():
            position = schema.position(name)
            if position is None:
                raise KeyError(f"feature {name} is not declared in the schema")
            dense[position] = float(value)
            present[position] = True
        return cls(schema, dense, present)

    def __getitem__(self, key: str) -> float:
        position = self._schema.position(key)
        if position is None or not self._present[position]:
            raise KeyError(key)
        return float(self._values[position])

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        position = self._schema.position(key)
        return position is not None and bool(self._present[position])

    def __iter__(self) -> Iterator[str]:
        for position, name in enumerate(self._schema.names):
            if self._present[position]:
                yield name

    def __len__(self) -> int:
        return int(self._present.sum())


def ccz_metadata(
    *,
    level_counts: Sequence[int] = DECLARED_LEVEL_COUNTS,
    primary_levels: int = PRIMARY_LEVEL_COUNT,
    explained_variance_ratio: Any = None,
    aggregation_arms: Sequence[str] = AGGREGATION_ARMS,
    denominator_floor_events: Any = None,
) -> dict[str, Any]:
    """`VAL-CCZ-08`: the estimator block every CCZ artifact must carry.

    Every artifact produced from this estimator states the estimator name, the level count, the
    explained-variance ratio of the integrated arm, and the ``ID-CCZ-01`` limitation verbatim.
    """

    return {
        "estimator": ESTIMATOR_NAME,
        "estimator_reference": CCZ_REFERENCE,
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "equations": {
            "per_level_order_flow": "Eq. (2) base terms, rank-keyed",
            "level_ofi": "Eq. (2); no sum over levels",
            "depth_scaling": "Eq. (3); one common denominator Q^{M,h} across all M levels",
            "integrated": "Eq. (4); w_1 fitted on training rows only",
            "per_level_regressors": "Eq. (19) PI^[m]",
            "level_one_base_case": "Eq. (1) == CKS (2014), retained unchanged",
        },
        "primary_level_count": primary_levels,
        "declared_level_counts": list(level_counts),
        "aggregation_arms": list(aggregation_arms),
        "primary_aggregation_arm": PRIMARY_AGGREGATION_ARM,
        "depth_denominator_floor_contracts": MINIMUM_DEPTH_DENOMINATOR,
        "depth_denominator_floor_events": denominator_floor_events,
        "explained_variance_ratio": explained_variance_ratio,
        "cumulates_across_levels": False,
        "per_band_denominator": False,
        "limitation_id": ID_CCZ_01,
        "limitation": ID_CCZ_01_LIMITATION,
        "pre_migration_comparability": (
            "pre-migration price-keyed and per-band-normalised numbers are not comparable with "
            "these and must never be pooled without an explicit estimator column"
        ),
    }
