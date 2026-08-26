from __future__ import annotations

from shaurya.signals.ofi_horserace import HorseRaceObservation
from shaurya.signals.surface_futures_predictive import SurfacePredictiveObservation
from shaurya.signals.surface_ofi_reconciliation import join_displayed_surface

SECOND = 1_000_000_000


def _surface(seconds: int, *, epoch: int = 1, sequence: int = 1) -> SurfacePredictiveObservation:
    return SurfacePredictiveObservation(
        sequence=sequence,
        receive_ts_ns=seconds * SECOND,
        connection_epoch=epoch,
        economic={"surface__x": float(sequence)},
        quality_numeric={},
        quality_categorical={},
        lob={},
        ofi={},
        y_future_ticks=0.0,
        y_past_ticks=0.0,
        y_same_ticks=0.0,
        target_start_age_seconds=0.0,
        target_end_age_seconds=0.0,
        surface_age_seconds=0.0,
        smoothing_status="smoothed",
    )


def _horse(seconds: int, *, epoch: int = 1) -> HorseRaceObservation:
    return HorseRaceObservation(
        tape_index=0,
        run_id="run",
        receive_ts_ns=seconds * SECOND,
        features={"spread_ticks": 1.0},
        future_ticks={5.0: 2.0},
        past_ticks={5.0: -1.0},
        same_window_ticks={5.0: 1.0},
        window_start_ts_ns={1.0: (seconds - 1) * SECOND},
        connection_epoch=epoch,
    )


def test_surface_join_is_strictly_past_only_and_uses_latest_displayed_frame() -> None:
    joined, records, failures = join_displayed_surface(
        [_horse(15)], [_surface(10, sequence=1), _surface(14, sequence=2), _surface(16, sequence=3)]
    )
    assert len(joined) == len(records) == 1
    assert joined[0].features["surface__x"] == 2.0
    assert records[0].surface_ts_ns == 14 * SECOND
    assert records[0].carry_age_seconds == 1.0
    assert failures == {
        "no_prior_surface": 0,
        "cross_epoch_surface": 0,
        "stale_surface_frame": 0,
    }


def test_surface_join_refuses_no_prior_stale_and_cross_epoch_frames() -> None:
    horses = [_horse(5), _horse(20), _horse(30, epoch=2)]
    surfaces = [_surface(10), _surface(21)]
    joined, records, failures = join_displayed_surface(horses, surfaces, max_carry_seconds=6.0)
    assert not joined and not records
    assert failures == {
        "no_prior_surface": 1,
        "cross_epoch_surface": 1,
        "stale_surface_frame": 1,
    }
