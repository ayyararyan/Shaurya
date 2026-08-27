"""Microprice arms — `D38 / TOUCH-METRICS-2026-08-20`, section D.

The imbalance-weighted microprice has sat in this repository since the first order-flow scan as
the unused control ``microprice_tilt_ticks``.  It has never been raced.  `MICRO-01` promotes it to
a named arm, `M7`, and `MICRO-02` adds the estimator it is usually compared against.

* `MICRO-01` :func:`simple_microprice` and :func:`microprice_tilt_ticks` — the one-line
  size-weighted average, ``(q_a P_b + q_b P_a) / (q_a + q_b)``.  It is a *deterministically
  derived* quantity: no model is fitted, and it is a weighted average of two displayed prices, so
  it can never leave the displayed quote.
* `MICRO-02` :func:`fit_stoikov_microprice` — Stoikov (2018), *The Micro-Price: A High Frequency
  Estimator of Future Prices*, Quantitative Finance.  The fair value is the mid plus the expected
  total future mid move conditional on the current ``(imbalance, spread)`` state, obtained by
  iterating the Markov chain of states observed at successive mid changes:

  ``G1[s] = E[dM | state s]``, ``B[s, s'] = P(state at the next mid change = s' | state s)``,
  ``G_inf = (I - B)^-1 G1``, ``microprice = mid + G_inf[state]``.

  It is an **estimated** object.  The chain is fitted on training rows only and applied unchanged
  out of sample; :func:`fit_stoikov_microprice` refuses any sample at or after the declared
  training boundary, which is what `VAL-MICRO-01` asserts.

Both enter ``MODEL_ORDER`` as families rather than controls (`MICRO-03`) and inherit the full
section B metric set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any, Final

import numpy as np

from shaurya.signals.deep_book_ofi import FUTURES_TICK_SIZE

SPECIFICATION_ID: Final = "D38 / TOUCH-METRICS-2026-08-20"
DESIGN_DOCUMENT: Final = "research/docs/legacy/TOUCH-METRICS-SPEC-2026-08-20.md"
STOIKOV_REFERENCE: Final = (
    "Stoikov (2018), The Micro-Price: A High Frequency Estimator of Future Prices, "
    "Quantitative Finance 18(12)"
)

#: `MICRO-02`.  Number of equal-width buckets the signed queue imbalance ``(q_b - q_a)/(q_b + q_a)``
#: is discretised into over ``[-1, 1]``.  Stoikov uses ten on US equities; the chain must be
#: estimable on a few thousand mid changes, so ten is kept.
IMBALANCE_BUCKETS: Final = 10

#: `MICRO-02`.  Upper edges of the spread buckets, in ticks.  Stoikov's original grid is one and
#: two ticks; on this feed the median displayed spread is tens of ticks (`ID-CKS-02`), so the grid
#: is widened rather than collapsing every observation into one state.  The final bucket is open.
SPREAD_BUCKET_EDGES_TICKS: Final = (10.0, 30.0, 60.0, 100.0, 150.0)

#: `MICRO-02`.  A state carrying fewer transitions than this is not estimated; its adjustment is
#: emitted as missing rather than as a noisy point estimate or a silent zero.
MINIMUM_TRANSITIONS_PER_STATE: Final = 10

ID_MICRO_01: Final = "ID-MICRO-01"
ID_MICRO_01_LIMITATION: Final = (
    "ID-MICRO-01: the Stoikov chain is estimated on displayed level-one queues. Where the "
    "displayed level one is not the touch (ID-CKS-02, ID-TOUCH-01) the imbalance state variable "
    "measures the outermost displayed band, not touch depth, so the fitted adjustment is a "
    "conditional expectation given a mis-located state rather than given the true touch state."
)


# ------------------------------------------------------------------------------------ MICRO-01


def simple_microprice(
    *, bid: float, bid_quantity: float, ask: float, ask_quantity: float
) -> float | None:
    """`MICRO-01`: the size-weighted average of the two displayed touch prices."""

    total = bid_quantity + ask_quantity
    if not (bid < ask) or total <= 0 or not isfinite(total):
        return None
    return (ask_quantity * bid + bid_quantity * ask) / total


def microprice_tilt_ticks(
    *, bid: float, bid_quantity: float, ask: float, ask_quantity: float
) -> float | None:
    """`MICRO-01`: the simple microprice expressed as a tilt away from the mid, in ticks."""

    value = simple_microprice(
        bid=bid, bid_quantity=bid_quantity, ask=ask, ask_quantity=ask_quantity
    )
    if value is None:
        return None
    return (value - (bid + ask) / 2.0) / FUTURES_TICK_SIZE


def queue_imbalance(bid_quantity: float, ask_quantity: float) -> float | None:
    total = bid_quantity + ask_quantity
    if total <= 0 or not isfinite(total):
        return None
    return (bid_quantity - ask_quantity) / total


# ------------------------------------------------------------------------------------ MICRO-02


def imbalance_bucket(imbalance: float, *, buckets: int = IMBALANCE_BUCKETS) -> int:
    """Map signed imbalance on ``[-1, 1]`` to ``0 .. buckets-1``, clamped at both ends."""

    if buckets < 1:
        raise ValueError("at least one imbalance bucket is required")
    position = int((imbalance + 1.0) / 2.0 * buckets)
    return min(max(position, 0), buckets - 1)


def spread_bucket(
    spread_ticks: float, *, edges: Sequence[float] = SPREAD_BUCKET_EDGES_TICKS
) -> int:
    """Map a displayed spread in ticks to ``0 .. len(edges)``; the final bucket is open."""

    for index, edge in enumerate(edges):
        if spread_ticks < edge:
            return index
    return len(edges)


@dataclass(frozen=True, slots=True)
class MicropriceState:
    """`MICRO-02`: the discrete state the Stoikov chain conditions on."""

    imbalance_bucket: int
    spread_bucket: int

    @property
    def key(self) -> str:
        return f"i{self.imbalance_bucket}_s{self.spread_bucket}"


def classify_state(
    *,
    bid_quantity: float,
    ask_quantity: float,
    spread_ticks: float,
    buckets: int = IMBALANCE_BUCKETS,
    edges: Sequence[float] = SPREAD_BUCKET_EDGES_TICKS,
) -> MicropriceState | None:
    imbalance = queue_imbalance(bid_quantity, ask_quantity)
    if imbalance is None or not isfinite(spread_ticks) or spread_ticks < 0:
        return None
    return MicropriceState(
        imbalance_bucket=imbalance_bucket(imbalance, buckets=buckets),
        spread_bucket=spread_bucket(spread_ticks, edges=edges),
    )


@dataclass(frozen=True, slots=True)
class StoikovTransition:
    """One observed step of the chain: a state, the mid move that ended it, and the next state.

    ``receive_ts_ns`` is the timestamp of the **origin** state.  ``resolved_ts_ns`` is when the mid
    actually moved.  Both are carried so the training-boundary guard can require that the whole
    transition, not merely its origin, lies inside training.
    """

    receive_ts_ns: int
    resolved_ts_ns: int
    state: MicropriceState
    mid_change_ticks: float
    next_state: MicropriceState


class StoikovLeakage(ValueError):
    """`VAL-MICRO-01`: a transition at or after the training boundary reached the fit."""


@dataclass(frozen=True, slots=True)
class StoikovMicropriceModel:
    """`MICRO-02`: the fitted chain, applied unchanged out of sample."""

    adjustment_ticks: Mapping[str, float]
    state_counts: Mapping[str, int]
    estimated_states: tuple[str, ...]
    dropped_states: tuple[str, ...]
    transitions: int
    training_upper_bound_ts_ns: int
    imbalance_buckets: int
    spread_edges_ticks: tuple[float, ...]
    converged: bool
    spectral_radius: float | None

    def adjustment(self, state: MicropriceState | None) -> float | None:
        """The fair-value tilt in ticks, or missing where the state was never estimated."""

        if state is None:
            return None
        return self.adjustment_ticks.get(state.key)

    def fair_value_ticks(self, state: MicropriceState | None, mid: float) -> float | None:
        value = self.adjustment(state)
        return None if value is None else mid + value * FUTURES_TICK_SIZE

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": "MICRO-02",
            "specification_id": SPECIFICATION_ID,
            "reference": STOIKOV_REFERENCE,
            "object_category": "estimated",
            "fitted_on": "training_rows_only",
            "training_upper_bound_ts_ns": self.training_upper_bound_ts_ns,
            "transitions": self.transitions,
            "imbalance_buckets": self.imbalance_buckets,
            "spread_edges_ticks": list(self.spread_edges_ticks),
            "minimum_transitions_per_state": MINIMUM_TRANSITIONS_PER_STATE,
            "estimated_states": list(self.estimated_states),
            "dropped_states_insufficient_support": list(self.dropped_states),
            "state_counts": dict(self.state_counts),
            "adjustment_ticks": dict(self.adjustment_ticks),
            "converged": self.converged,
            "spectral_radius": self.spectral_radius,
            "limitation_id": ID_MICRO_01,
            "limitation": ID_MICRO_01_LIMITATION,
        }


def build_stoikov_transitions(
    samples: Sequence[tuple[int, float, MicropriceState | None]],
) -> list[StoikovTransition]:
    """Pair each observation with the **next** observation whose mid differs from its own.

    ``samples`` is ``(receive_ts_ns, mid, state)`` in time order.  A run of observations sharing
    one mid all resolve to the same next mid change, which is Stoikov's construction: the chain
    steps on mid changes, not on publications.
    """

    ordered = list(samples)
    transitions: list[StoikovTransition] = []
    pending: list[tuple[int, float, MicropriceState]] = []
    for stamp, mid, state in ordered:
        if not isfinite(mid):
            continue
        while pending and pending[0][1] != mid:
            origin_ts, origin_mid, origin_state = pending.pop(0)
            if state is None:
                continue
            transitions.append(
                StoikovTransition(
                    receive_ts_ns=origin_ts,
                    resolved_ts_ns=stamp,
                    state=origin_state,
                    mid_change_ticks=(mid - origin_mid) / FUTURES_TICK_SIZE,
                    next_state=state,
                )
            )
        if state is not None:
            pending.append((stamp, mid, state))
    return transitions


def fit_stoikov_microprice(
    transitions: Sequence[StoikovTransition],
    *,
    training_upper_bound_ts_ns: int,
    imbalance_buckets: int = IMBALANCE_BUCKETS,
    spread_edges_ticks: Sequence[float] = SPREAD_BUCKET_EDGES_TICKS,
    minimum_transitions: int = MINIMUM_TRANSITIONS_PER_STATE,
) -> StoikovMicropriceModel:
    """`MICRO-02` / `VAL-MICRO-01`: fit the iterated chain on training transitions only.

    Every transition must be **fully** resolved before ``training_upper_bound_ts_ns`` — a
    transition whose origin is in training but whose mid change lands in the test period would
    carry held-out information into the fit, so it is refused rather than trimmed.
    """

    for transition in transitions:
        if transition.resolved_ts_ns >= training_upper_bound_ts_ns:
            raise StoikovLeakage(
                "a Stoikov transition resolved at or after the training boundary "
                f"({transition.resolved_ts_ns} >= {training_upper_bound_ts_ns})"
            )
    counts: dict[str, int] = {}
    for transition in transitions:
        counts[transition.state.key] = counts.get(transition.state.key, 0) + 1
    estimated = tuple(sorted(key for key, count in counts.items() if count >= minimum_transitions))
    dropped = tuple(sorted(key for key, count in counts.items() if count < minimum_transitions))
    if not estimated:
        return StoikovMicropriceModel(
            adjustment_ticks={},
            state_counts=counts,
            estimated_states=(),
            dropped_states=dropped,
            transitions=len(transitions),
            training_upper_bound_ts_ns=training_upper_bound_ts_ns,
            imbalance_buckets=imbalance_buckets,
            spread_edges_ticks=tuple(spread_edges_ticks),
            converged=False,
            spectral_radius=None,
        )
    index = {key: position for position, key in enumerate(estimated)}
    size = len(estimated)
    g1 = np.zeros(size, dtype=np.float64)
    origin_counts = np.zeros(size, dtype=np.float64)
    transition_counts = np.zeros((size, size), dtype=np.float64)
    for transition in transitions:
        origin = index.get(transition.state.key)
        if origin is None:
            continue
        origin_counts[origin] += 1.0
        g1[origin] += transition.mid_change_ticks
        destination = index.get(transition.next_state.key)
        if destination is not None:
            transition_counts[origin, destination] += 1.0
    g1 = g1 / np.maximum(origin_counts, 1.0)
    # Divide by the *origin* count, not by the row total: a transition that lands in a dropped
    # state leaks probability out of the chain, which is what makes it sub-stochastic and the
    # inverse finite.  Renormalising onto the surviving states would put the destination back
    # somewhere it was never observed to go, and would make the chain stochastic and the inverse
    # singular.
    chain = transition_counts / np.maximum(origin_counts, 1.0)[:, None]
    spectral_radius = float(np.max(np.abs(np.linalg.eigvals(chain)))) if size else 0.0
    converged = spectral_radius < 1.0 - 1e-9
    # A sub-stochastic chain has (I - B) invertible.  If it is not, fall back to the one-step
    # expectation rather than inverting a singular operator, and record that it did not converge.
    adjustment = np.linalg.solve(np.eye(size, dtype=np.float64) - chain, g1) if converged else g1
    return StoikovMicropriceModel(
        adjustment_ticks={key: float(adjustment[index[key]]) for key in estimated},
        state_counts=counts,
        estimated_states=estimated,
        dropped_states=dropped,
        transitions=len(transitions),
        training_upper_bound_ts_ns=training_upper_bound_ts_ns,
        imbalance_buckets=imbalance_buckets,
        spread_edges_ticks=tuple(spread_edges_ticks),
        converged=converged,
        spectral_radius=spectral_radius,
    )


def microprice_metadata() -> dict[str, Any]:
    """The block every artifact carrying a microprice arm must publish."""

    return {
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "simple_microprice": {
            "requirement": "MICRO-01",
            "definition": "(q_ask * bid + q_bid * ask) / (q_bid + q_ask)",
            "object_category": "deterministically_derived",
            "arm": "M7",
        },
        "stoikov_microprice": {
            "requirement": "MICRO-02",
            "reference": STOIKOV_REFERENCE,
            "definition": "mid + G_inf[state], G_inf = (I - B)^-1 G1 over (imbalance, spread)",
            "object_category": "estimated",
            "fitted_on": "training_rows_only",
            "arm": "M8",
        },
        "limitation_id": ID_MICRO_01,
        "limitation": ID_MICRO_01_LIMITATION,
    }
