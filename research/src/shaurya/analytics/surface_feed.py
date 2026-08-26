"""ANL-03 surface engine: tape rows in, labelled surface snapshots out.

Read-only by construction (D19). The engine consumes `CON-01` tape rows from either a
DAT-05 replay or one live Dhan connection, refits the `SUR-02` eSSVI surface on a cadence,
smooths it with `SUR-07`'s temporal smoother, and emits a snapshot carrying the `CON-03`
frame, the `SUR-05` arbitrage report, the `SUR-06` diagnostics, the per-expiry forward
choice, and feed-health measurements.

Nothing here filters points, widens tolerances, or retries a fit to make the surface look
clean: a failed fit and a failed arbitrage check are both first-class snapshot states.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST, nse_equity_derivatives_close

from shaurya.analytics.forward import ForwardSelection, select_forwards
from shaurya.analytics.mispricing import (
    InstrumentMetadata,
    MispricingPolicy,
    SurfaceMispricingDetector,
)
from shaurya.research_contracts.surface import SurfaceFrame
from shaurya.surfaces.base import EvaluationStatus, SurfaceFitRequest, SurfaceUse
from shaurya.surfaces.essvi import ESSVISurface, SurfaceCalibrationError
from shaurya.surfaces.state import ESSVITemporalSmoother, staleness_measurement

SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


class FeedStatus(StrEnum):
    """Feed liveness verdict under the measured Quote/Full cadence (DAT-16)."""

    LIVE = "live"
    SLOW = "slow"
    DEAD = "dead"
    NO_DATA = "no_data"


@dataclass(frozen=True, slots=True)
class StalenessPolicy:
    """Thresholds calibrated to DAT-16's measured cadence, not to taste.

    DAT-16 measured the Quote/Full channel at roughly 1.2-1.7 updates per second per liquid
    instrument, with per-instrument gap p95 near 1,140 ms. Aggregate feed age across a
    subscribed chain is therefore normally far below one second, and a few hundred
    milliseconds is healthy rather than faulty. The dead threshold is set where a liquid
    chain has demonstrably stopped: two seconds is more than 1.75x the single-instrument p95
    gap, so on a universe of dozens of instruments it cannot be produced by ordinary gaps.
    The 2026-08-19 live run measured aggregate feed age at p50 4.7 ms and p95 30.8 ms across
    452 instruments, so the 1 s / 2 s thresholds sit far above ordinary variation.

    ``surface_staleness_seconds`` is a different measurement and is calibrated separately:
    `ESSVISurface.surface_timestamp` is the *oldest* contributing quote, so on a wide chain
    surface age tracks how sparsely the deepest wing quotes, not how current the fit is. The
    same live run measured it at p50 200 s and p95 421 s. `SUR-07` leaves this threshold to
    the consuming strategy; this dashboard supplies one above the measured p95 and reports
    fit age separately as the "is this picture current" signal.
    """

    feed_slow_seconds: float = 1.0
    feed_dead_seconds: float = 2.0
    instrument_slow_seconds: float = 3.0
    instrument_dead_seconds: float = 6.0
    surface_staleness_seconds: float = 480.0
    fit_stale_seconds: float = 20.0
    rate_window_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not 0 < self.feed_slow_seconds < self.feed_dead_seconds:
            raise ValueError("feed thresholds must satisfy 0 < slow < dead")
        if not 0 < self.instrument_slow_seconds < self.instrument_dead_seconds:
            raise ValueError("instrument thresholds must satisfy 0 < slow < dead")
        if self.surface_staleness_seconds <= 0 or self.rate_window_seconds <= 0:
            raise ValueError("surface staleness and rate windows must be positive")
        if self.fit_stale_seconds <= 0:
            raise ValueError("fit staleness threshold must be positive")

    def to_dict(self) -> dict[str, float]:
        return {
            "feed_slow_seconds": self.feed_slow_seconds,
            "feed_dead_seconds": self.feed_dead_seconds,
            "instrument_slow_seconds": self.instrument_slow_seconds,
            "instrument_dead_seconds": self.instrument_dead_seconds,
            "surface_staleness_seconds": self.surface_staleness_seconds,
            "fit_stale_seconds": self.fit_stale_seconds,
            "rate_window_seconds": self.rate_window_seconds,
        }


@dataclass(frozen=True, slots=True)
class FeedHealth:
    """Everything needed to see that the feed died, not just that the surface looks fine."""

    status: FeedStatus
    observation_timestamp: datetime
    last_update_timestamp: datetime | None
    feed_age_seconds: float | None
    worst_instrument_age_seconds: float | None
    worst_instrument_id: str | None
    stale_instrument_count: int
    tracked_instrument_count: int
    packets_per_second: float
    rows_total: int
    reconnect_count: int
    connection_epoch: int

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "observation_timestamp": self.observation_timestamp.isoformat(),
            "last_update_timestamp": (
                self.last_update_timestamp.isoformat() if self.last_update_timestamp else None
            ),
            "feed_age_seconds": self.feed_age_seconds,
            "worst_instrument_age_seconds": self.worst_instrument_age_seconds,
            "worst_instrument_id": self.worst_instrument_id,
            "stale_instrument_count": self.stale_instrument_count,
            "tracked_instrument_count": self.tracked_instrument_count,
            "packets_per_second": self.packets_per_second,
            "rows_total": self.rows_total,
            "reconnect_count": self.reconnect_count,
            "connection_epoch": self.connection_epoch,
        }


@dataclass(frozen=True, slots=True)
class SurfaceGrid:
    """A fixed-axis evaluation grid. Unsupported cells stay null; nothing is filled in."""

    log_moneyness: tuple[float, ...]
    maturity_days: tuple[float, ...]
    expiry_labels: tuple[str, ...]
    implied_volatility: tuple[tuple[float | None, ...], ...]
    unsupported_cells: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "log_moneyness": list(self.log_moneyness),
            "maturity_days": list(self.maturity_days),
            "expiry_labels": list(self.expiry_labels),
            "implied_volatility": [list(row) for row in self.implied_volatility],
            "unsupported_cells": self.unsupported_cells,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class MarketPoint:
    """One observed option mid expressed in the surface's own coordinates."""

    instrument_id: str
    expiry: str
    log_moneyness: float
    maturity_days: float
    implied_volatility: float

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "expiry": self.expiry,
            "log_moneyness": self.log_moneyness,
            "maturity_days": self.maturity_days,
            "implied_volatility": self.implied_volatility,
        }


@dataclass(frozen=True, slots=True)
class AtmReading:
    """The fitted surface read exactly at k = 0 — at the money on the chosen forward.

    This is an **estimated** object, not an observed one: it is the SUR-01 fit (after SUR-07
    smoothing, when smoothing applied) evaluated at log-moneyness zero, so it inherits that
    fit's labels and moves whenever the forward moves, even if no option reprinted. It is
    read exactly at zero rather than picked off the display grid, so it stays correct under
    a grid whose points do not straddle the money. When the slice cannot support the money
    the volatility is null and `reason` says why; nothing is filled in.
    """

    expiry: str
    maturity_days: float
    implied_volatility: float | None
    status: str
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "expiry": self.expiry,
            "maturity_days": self.maturity_days,
            "implied_volatility": self.implied_volatility,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SurfaceSnapshot:
    """One dashboard-ready observation of the whole chain: fit or explicit failure."""

    sequence: int
    fit_timestamp: datetime
    fit_duration_seconds: float
    fit_ok: bool
    failure_reason: str | None
    health: FeedHealth
    forwards: ForwardSelection
    frame: SurfaceFrame | None
    grid: SurfaceGrid | None
    market_points: tuple[MarketPoint, ...]
    atm: tuple[AtmReading, ...]
    arbitrage: dict[str, object] | None
    diagnostics: dict[str, object]
    mispricing: dict[str, object]
    surface_age_seconds: float | None
    surface_is_stale: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "fit_timestamp": self.fit_timestamp.isoformat(),
            "fit_duration_seconds": self.fit_duration_seconds,
            "fit_ok": self.fit_ok,
            "failure_reason": self.failure_reason,
            "health": self.health.to_dict(),
            "forwards": self.forwards.to_dict(),
            "grid": self.grid.to_dict() if self.grid else None,
            "market_points": [point.to_dict() for point in self.market_points],
            "atm": [reading.to_dict() for reading in self.atm],
            "arbitrage": self.arbitrage,
            "diagnostics": self.diagnostics,
            "mispricing": self.mispricing,
            "surface_age_seconds": self.surface_age_seconds,
            "surface_is_stale": self.surface_is_stale,
            "frame": self.frame.model_dump(mode="json") if self.frame else None,
        }


def expiry_timestamp(expiry: date) -> datetime:
    """Return the date-versioned NSE F&O close on the option's expiry date."""

    return datetime.combine(expiry, nse_equity_derivatives_close(expiry), tzinfo=IST)


def _option_expiry(instrument_id: str) -> date | None:
    parts = instrument_id.split(":")
    if len(parts) != 7 or parts[3].lower() != "option":
        return None
    try:
        return date.fromisoformat(parts[4])
    except ValueError:
        return None


def _option_strike(instrument_id: str) -> float | None:
    parts = instrument_id.split(":")
    if len(parts) != 7:
        return None
    try:
        return float(parts[5])
    except ValueError:
        return None


@dataclass
class SurfaceEngine:
    """Stateful chain-to-surface engine driven by tape rows.

    ``run_id`` and ``surface_id`` identify the emitted `CON-03` frames. ``expiries`` fixes
    the maturity axis for the whole session so the 3D view does not re-scale on every fit.
    """

    run_id: str
    surface_id: str
    expiries: tuple[date, ...]
    log_moneyness_grid: tuple[float, ...]
    policy: StalenessPolicy = field(default_factory=StalenessPolicy)
    fit_interval_seconds: float = 5.0
    risk_free_rate: float = 0.0
    min_quotes_per_slice: int = 5
    history_limit: int = 720
    health_sample_limit: int = 3600
    wall_clock: bool = True
    smoother: ESSVITemporalSmoother = field(default_factory=ESSVITemporalSmoother)
    mispricing_policy: MispricingPolicy = field(default_factory=MispricingPolicy)
    instrument_metadata: dict[str, InstrumentMetadata] = field(default_factory=dict)

    _latest: dict[str, TapeRow] = field(default_factory=dict, init=False, repr=False)
    _recent_receipts: deque[datetime] = field(default_factory=deque, init=False, repr=False)
    _history: list[SurfaceSnapshot] = field(default_factory=list, init=False, repr=False)
    _rows_total: int = field(default=0, init=False)
    _last_row_timestamp: datetime | None = field(default=None, init=False)
    _connection_epoch: int = field(default=0, init=False)
    _max_connection_epoch: int = field(default=0, init=False)
    _sequence: int = field(default=0, init=False)
    _last_fit_timestamp: datetime | None = field(default=None, init=False)
    _health_samples: deque[FeedHealth] = field(default_factory=deque, init=False, repr=False)
    _previous_surface: ESSVISurface | None = field(default=None, init=False, repr=False)
    _mispricing_detector: SurfaceMispricingDetector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.expiries:
            raise ValueError("at least one expiry is required")
        if len(self.log_moneyness_grid) < 2:
            raise ValueError("the log-moneyness grid needs at least two points")
        if self.fit_interval_seconds <= 0:
            raise ValueError("fit_interval_seconds must be positive")
        self.expiries = tuple(sorted(set(self.expiries)))
        self._mispricing_detector = SurfaceMispricingDetector(
            policy=self.mispricing_policy,
            instrument_metadata=self.instrument_metadata,
            min_quotes_per_slice=self.min_quotes_per_slice,
        )

    @property
    def history(self) -> tuple[SurfaceSnapshot, ...]:
        return tuple(self._history)

    @property
    def latest(self) -> SurfaceSnapshot | None:
        return self._history[-1] if self._history else None

    def current_time(self) -> datetime | None:
        """The engine's clock: the wall clock when live, tape time when replaying.

        Replay must not compare tape timestamps against the wall clock, or every replayed
        surface would read as hours stale.
        """

        if self.wall_clock:
            return datetime.now(tz=IST)
        if self._last_fit_timestamp is None:
            return self._last_row_timestamp
        if self._last_row_timestamp is None:
            return self._last_fit_timestamp
        return max(self._last_row_timestamp, self._last_fit_timestamp)

    def fit_age_seconds(self, now: datetime) -> float | None:
        if self._last_fit_timestamp is None:
            return None
        return (now - self._last_fit_timestamp).total_seconds()

    def sample_health(self, now: datetime) -> FeedHealth:
        """Record a health reading independently of fits.

        A dead feed produces no fits, so a trace built only from fits would simply stop and
        leave the last good reading on screen forever. That is the exact failure mode this
        dashboard exists to make visible, so health is sampled on every dashboard read.
        """

        health = self.health(now)
        self._health_samples.append(health)
        while len(self._health_samples) > self.health_sample_limit:
            self._health_samples.popleft()
        return health

    @property
    def health_samples(self) -> tuple[FeedHealth, ...]:
        return tuple(self._health_samples)

    def ingest(self, row: TapeRow) -> None:
        """Absorb one tape row. Only two-sided option and future books matter here."""

        self._rows_total += 1
        receive = row.receive_ts.astimezone(IST)
        if self._last_row_timestamp is None or receive > self._last_row_timestamp:
            self._last_row_timestamp = receive
        self._recent_receipts.append(receive)
        self._connection_epoch = row.connection_epoch
        self._max_connection_epoch = max(self._max_connection_epoch, row.connection_epoch)
        incumbent = self._latest.get(row.instrument_id)
        if incumbent is None or (row.receive_ts, row.receive_sequence) > (
            incumbent.receive_ts,
            incumbent.receive_sequence,
        ):
            self._latest[row.instrument_id] = row

    def _trim_rate_window(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.policy.rate_window_seconds)
        while self._recent_receipts and self._recent_receipts[0] < cutoff:
            self._recent_receipts.popleft()

    def health(self, now: datetime) -> FeedHealth:
        self._trim_rate_window(now)
        feed_age: float | None = None
        if self._last_row_timestamp is not None:
            feed_age = (now - self._last_row_timestamp).total_seconds()
        worst_age: float | None = None
        worst_id: str | None = None
        stale_instruments = 0
        for instrument_id, row in self._latest.items():
            age = (now - row.receive_ts.astimezone(IST)).total_seconds()
            if age >= self.policy.instrument_slow_seconds:
                stale_instruments += 1
            if worst_age is None or age > worst_age:
                worst_age = age
                worst_id = instrument_id
        if feed_age is None:
            status = FeedStatus.NO_DATA
        elif feed_age >= self.policy.feed_dead_seconds:
            status = FeedStatus.DEAD
        elif feed_age >= self.policy.feed_slow_seconds:
            status = FeedStatus.SLOW
        else:
            status = FeedStatus.LIVE
        return FeedHealth(
            status=status,
            observation_timestamp=now,
            last_update_timestamp=self._last_row_timestamp,
            feed_age_seconds=feed_age,
            worst_instrument_age_seconds=worst_age,
            worst_instrument_id=worst_id,
            stale_instrument_count=stale_instruments,
            tracked_instrument_count=len(self._latest),
            packets_per_second=len(self._recent_receipts) / self.policy.rate_window_seconds,
            rows_total=self._rows_total,
            reconnect_count=max(self._max_connection_epoch - 1, 0),
            connection_epoch=self._connection_epoch,
        )

    def due_for_fit(self, now: datetime) -> bool:
        if self._last_fit_timestamp is None:
            return True
        return (now - self._last_fit_timestamp).total_seconds() >= self.fit_interval_seconds

    def _maturities(self, now: datetime) -> dict[date, float]:
        return {
            expiry: (expiry_timestamp(expiry) - now).total_seconds() / SECONDS_PER_YEAR
            for expiry in self.expiries
        }

    def _grid(self, surface: ESSVISurface, maturities: dict[date, float]) -> SurfaceGrid:
        """Evaluate on the surface's own fitted maturities.

        `ESSVISurface.evaluate` matches an exact maturity to within 1e-10 years, and the
        SUR-07 smoother blends slices whose maturities came from earlier valuation times, so
        recomputing a maturity from the clock would miss the exact match and silently demote
        every row to maturity interpolation.
        """

        reasons: set[str] = set()
        rows: list[tuple[float | None, ...]] = []
        unsupported = 0
        maturity_days: list[float] = []
        labels: list[str] = []
        fitted = {item.expiry: item.maturity_years for item in surface.slices}
        for expiry in self.expiries:
            maturity = fitted.get(expiry, maturities[expiry])
            if expiry not in fitted:
                reasons.add(f"{expiry.isoformat()} has no fitted slice in this frame")
            maturity_days.append(maturity * 365.0)
            labels.append(expiry.isoformat())
            row: list[float | None] = []
            for log_moneyness in self.log_moneyness_grid:
                evaluation = surface.evaluate(
                    log_moneyness=log_moneyness, maturity_years=maturity
                )
                if evaluation.status is EvaluationStatus.DATA_INSUFFICIENT:
                    unsupported += 1
                    if evaluation.reason:
                        reasons.add(evaluation.reason)
                    row.append(None)
                else:
                    row.append(evaluation.implied_volatility)
            rows.append(tuple(row))
        return SurfaceGrid(
            log_moneyness=self.log_moneyness_grid,
            maturity_days=tuple(maturity_days),
            expiry_labels=tuple(labels),
            implied_volatility=tuple(rows),
            unsupported_cells=unsupported,
            reasons=tuple(sorted(reasons)),
        )

    def _atm(
        self, surface: ESSVISurface, maturities: dict[date, float]
    ) -> tuple[AtmReading, ...]:
        """Evaluate at k = 0 on each fitted maturity, the same way `_grid` does.

        The maturity comes from the fitted slice, not from the clock, for the reason given
        in `_grid`: recomputing it would miss `ESSVISurface.evaluate`'s exact-maturity match
        and quietly demote a fitted reading to an interpolated one.
        """

        fitted = {item.expiry: item.maturity_years for item in surface.slices}
        readings: list[AtmReading] = []
        for expiry in self.expiries:
            maturity = fitted.get(expiry, maturities[expiry])
            evaluation = surface.evaluate(log_moneyness=0.0, maturity_years=maturity)
            readings.append(
                AtmReading(
                    expiry=expiry.isoformat(),
                    maturity_days=maturity * 365.0,
                    implied_volatility=evaluation.implied_volatility,
                    status=str(evaluation.status),
                    reason=(
                        evaluation.reason
                        if expiry in fitted
                        else f"{expiry.isoformat()} has no fitted slice in this frame"
                    ),
                )
            )
        return tuple(sorted(readings, key=lambda item: item.maturity_days))

    def _market_points(
        self, surface: ESSVISurface, forwards: ForwardSelection, maturities: dict[date, float]
    ) -> tuple[MarketPoint, ...]:
        forward_by_expiry = forwards.forward_by_expiry
        fitted_maturities = {item.expiry: item.maturity_years for item in surface.slices}
        points: list[MarketPoint] = []
        for instrument_id, row in self._latest.items():
            expiry = _option_expiry(instrument_id)
            strike = _option_strike(instrument_id)
            if expiry is None or strike is None or expiry not in forward_by_expiry:
                continue
            maturity = maturities.get(expiry)
            if maturity is None or maturity <= 0:
                continue
            bid = row.best_bid
            ask = row.best_ask
            if bid is None or ask is None or bid <= 0 or ask < bid:
                continue
            log_moneyness = math.log(strike / forward_by_expiry[expiry])
            evaluation = surface.evaluate(
                log_moneyness=log_moneyness,
                maturity_years=fitted_maturities.get(expiry, maturity),
            )
            if evaluation.status is EvaluationStatus.DATA_INSUFFICIENT:
                continue
            fitted = evaluation.implied_volatility
            if fitted is None:
                continue
            points.append(
                MarketPoint(
                    instrument_id=instrument_id,
                    expiry=expiry.isoformat(),
                    log_moneyness=log_moneyness,
                    maturity_days=maturity * 365.0,
                    implied_volatility=fitted,
                )
            )
        return tuple(points)

    def _record(self, snapshot: SurfaceSnapshot) -> SurfaceSnapshot:
        self._history.append(snapshot)
        if len(self._history) > self.history_limit:
            del self._history[0 : len(self._history) - self.history_limit]
        return snapshot

    def _smooth(self, raw: ESSVISurface, now: datetime) -> tuple[ESSVISurface, str]:
        """Apply SUR-07 smoothing, and report rather than hide when it cannot apply.

        The smoother's contract is strict on purpose: it refuses a non-increasing surface
        timestamp, a changed instrument scope, or a changed expiry set. All three occur
        legitimately on a live chain — `ESSVISurface.surface_timestamp` is the *oldest*
        contributing quote, so two consecutive fits can share it when a wing instrument has
        not reprinted, and slices drop in and out as quotes thin. When that happens the
        dashboard shows the raw fit and says so; it never silently pretends the surface was
        smoothed.
        """

        try:
            return self.smoother.update(raw, observation_timestamp=now), "smoothed"
        except ValueError as error:
            reason = str(error)
            if "scope" in reason or "expiry set" in reason:
                self.smoother.reset()
                try:
                    return (
                        self.smoother.update(raw, observation_timestamp=now),
                        f"reset_then_smoothed: {reason}",
                    )
                except ValueError as retry_error:  # pragma: no cover - defensive
                    return raw, f"raw_after_reset_failure: {retry_error}"
            return raw, f"raw_unsmoothed: {reason}"

    def fit(self, now: datetime) -> SurfaceSnapshot:
        """Refit and emit one snapshot. A failure is emitted, never swallowed."""

        started = time.monotonic()
        self._last_fit_timestamp = now
        self._sequence += 1
        health = self.health(now)
        maturities = self._maturities(now)
        usable_expiries = [
            expiry for expiry in self.expiries if maturities[expiry] > 0
        ]
        rows = tuple(
            row
            for row in self._latest.values()
            if row.receive_ts.astimezone(IST) <= now
        )
        forwards = select_forwards(
            rows=rows,
            expiries=usable_expiries,
            maturity_years_by_expiry=maturities,
            risk_free_rate=self.risk_free_rate,
        )

        def failure(reason: str) -> SurfaceSnapshot:
            mispricing = self._mispricing_detector.unavailable(
                now, f"base_surface_unavailable: {reason}"
            )
            return self._record(
                SurfaceSnapshot(
                    sequence=self._sequence,
                    fit_timestamp=now,
                    fit_duration_seconds=time.monotonic() - started,
                    fit_ok=False,
                    failure_reason=reason,
                    health=health,
                    forwards=forwards,
                    frame=None,
                    grid=None,
                    market_points=(),
                    atm=(),
                    arbitrage=None,
                    diagnostics={"fit_status": "failed", "reason": reason},
                    mispricing=mispricing.to_dict(),
                    surface_age_seconds=None,
                    surface_is_stale=True,
                )
            )

        if not rows:
            return failure("no tape rows have arrived yet")
        if not forwards.choices:
            return failure("no expiry resolved a forward from a future or from put-call parity")
        forward_by_expiry = forwards.forward_by_expiry
        request = SurfaceFitRequest(
            tape_rows=rows,
            valuation_timestamp=now,
            forward_by_expiry=forward_by_expiry,
            expiry_timestamp_by_expiry={
                expiry: expiry_timestamp(expiry) for expiry in forward_by_expiry
            },
            risk_free_rate=self.risk_free_rate,
            min_quotes_per_slice=self.min_quotes_per_slice,
            previous_surface=self._previous_surface,
        )
        try:
            raw = ESSVISurface.fit(request)
        except (SurfaceCalibrationError, ValueError) as error:
            return failure(f"{type(error).__name__}: {error}")
        self._previous_surface = raw
        smoothed, smoothing_status = self._smooth(raw, now)
        smoothed.assert_ready_for(SurfaceUse.RESEARCH)
        frame = smoothed.to_frame(
            run_id=self.run_id,
            surface_id=self.surface_id,
            decision_timestamp=now,
            staleness_threshold_seconds=self.policy.surface_staleness_seconds,
        )
        surface_age = float(frame.surface_age_seconds)
        grid = self._grid(smoothed, maturities)
        diagnostics: dict[str, object] = {
            diagnostic.name: diagnostic.value for diagnostic in smoothed.diagnostics
        }
        diagnostics["temporal_smoothing"] = {
            "status": smoothing_status,
            "is_temporally_smoothed": smoothed.is_temporally_smoothed,
        }
        arbitrage = smoothed.arb_check()
        mispricing = self._mispricing_detector.evaluate(
            rows=rows,
            expiries=self.expiries,
            now=now,
            risk_free_rate=self.risk_free_rate,
            base_fit_age_seconds=0.0,
            base_arbitrage_passed=arbitrage.passed,
        )
        return self._record(
            SurfaceSnapshot(
                sequence=self._sequence,
                fit_timestamp=now,
                fit_duration_seconds=time.monotonic() - started,
                fit_ok=True,
                failure_reason=None,
                health=health,
                forwards=forwards,
                frame=frame,
                grid=grid,
                market_points=self._market_points(smoothed, forwards, maturities),
                atm=self._atm(smoothed, maturities),
                arbitrage=arbitrage.to_dict(),
                diagnostics=diagnostics,
                mispricing=mispricing.to_dict(),
                surface_age_seconds=surface_age,
                surface_is_stale=staleness_measurement(
                    age_seconds=surface_age,
                    threshold_seconds=self.policy.surface_staleness_seconds,
                ),
            )
        )

    def latency_trace(self) -> dict[str, list[Any]]:
        """Session-long traces: an instantaneous readout hides its own tails."""

        gaps: list[float | None] = []
        previous: datetime | None = None
        for snapshot in self._history:
            gaps.append(
                None if previous is None else (snapshot.fit_timestamp - previous).total_seconds()
            )
            previous = snapshot.fit_timestamp
        return {
            "fit_gap_seconds": gaps,
            "health_sample_timestamps": [
                sample.observation_timestamp.isoformat() for sample in self._health_samples
            ],
            "health_sample_feed_age_seconds": [
                sample.feed_age_seconds for sample in self._health_samples
            ],
            "health_sample_worst_instrument_age_seconds": [
                sample.worst_instrument_age_seconds for sample in self._health_samples
            ],
            "timestamps": [snapshot.fit_timestamp.isoformat() for snapshot in self._history],
            "feed_age_seconds": [
                snapshot.health.feed_age_seconds for snapshot in self._history
            ],
            "worst_instrument_age_seconds": [
                snapshot.health.worst_instrument_age_seconds for snapshot in self._history
            ],
            "surface_age_seconds": [
                snapshot.surface_age_seconds for snapshot in self._history
            ],
            "fit_duration_seconds": [
                snapshot.fit_duration_seconds for snapshot in self._history
            ],
            "packets_per_second": [
                snapshot.health.packets_per_second for snapshot in self._history
            ],
            "fit_ok": [snapshot.fit_ok for snapshot in self._history],
            "arbitrage_passed": [
                bool(snapshot.arbitrage["passed"]) if snapshot.arbitrage else None
                for snapshot in self._history
            ],
        }


def default_log_moneyness_grid(
    *, half_width: float = 0.08, points: int = 33
) -> tuple[float, ...]:
    """A fixed grid; the axis must not move just because the market did."""

    if half_width <= 0 or points < 2:
        raise ValueError("half_width must be positive and points at least two")
    step = (2.0 * half_width) / (points - 1)
    return tuple(-half_width + step * index for index in range(points))


def replay_rows(rows: Iterable[TapeRow], engine: SurfaceEngine) -> Sequence[SurfaceSnapshot]:
    """Drive the engine off a retained tape in tape time (DAT-05 replay)."""

    produced: list[SurfaceSnapshot] = []
    for row in rows:
        engine.ingest(row)
        stamp = row.receive_ts.astimezone(IST)
        if engine.due_for_fit(stamp):
            produced.append(engine.fit(stamp))
    return produced
