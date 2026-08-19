"""ANL-03 tests: forward choice, feed-death visibility, read-only server, payload shape."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from shaurya.analytics.dashboard import build_history_payload, build_payload, render_html
from shaurya.analytics.forward import ForwardMethod, select_forwards
from shaurya.analytics.server import DashboardState, serve_in_background
from shaurya.analytics.surface_feed import (
    FeedStatus,
    StalenessPolicy,
    SurfaceEngine,
    default_log_moneyness_grid,
    expiry_timestamp,
)
from shaurya.analytics.universe import select_chain_universe
from shaurya.contracts.categories import ObjectCategory
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.contracts.timing import IST
from shaurya.surfaces.essvi import ESSVISurface, black76_price

VALUATION = datetime(2026, 8, 19, 11, 0, tzinfo=IST)
NEAR = date(2026, 8, 25)
FAR = date(2026, 9, 29)
FORWARDS = {NEAR: 24_100.0, FAR: 24_250.0}
PARAMETERS = {NEAR: (0.0009, -0.32, 0.022), FAR: (0.0040, -0.28, 0.038)}
SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


def test_expiry_close_is_date_versioned_at_the_2026_extension_boundary() -> None:
    assert expiry_timestamp(date(2026, 8, 2)) == datetime(
        2026, 8, 2, 15, 30, tzinfo=IST
    )
    assert expiry_timestamp(date(2026, 8, 3)) == datetime(
        2026, 8, 3, 15, 40, tzinfo=IST
    )


def _row(
    *,
    instrument_id: str,
    bid: float,
    ask: float,
    sequence: int,
    receive_ts: datetime,
    connection_epoch: int = 1,
) -> TapeRow:
    return TapeRow(
        run_id="sha-20260819T053000.000000Z-anl03test",
        receive_sequence=sequence,
        connection_epoch=connection_epoch,
        source="synthetic_anl03_fixture",
        event_type="full",
        instrument_id=instrument_id,
        broker_security_id=str(50_000 + sequence),
        exchange_segment="NSE_FNO",
        receive_ts=receive_ts,
        raw_message_size_bytes=162,
        update_side="both",
        bids=(DepthLevel(bid, 150, 2),),
        asks=(DepthLevel(ask, 175, 3),),
    )


def _chain(
    *,
    valuation: datetime = VALUATION,
    include_near_future: bool = True,
    include_far_future: bool = True,
) -> list[TapeRow]:
    rows: list[TapeRow] = []
    sequence = 1
    for expiry, forward in FORWARDS.items():
        theta, rho, psi = PARAMETERS[expiry]
        maturity = (expiry_timestamp(expiry) - valuation).total_seconds() / SECONDS_PER_YEAR
        for log_moneyness in (-0.06, -0.045, -0.03, -0.015, 0.0, 0.015, 0.03, 0.045, 0.06):
            strike = round(forward * math.exp(log_moneyness) / 50.0) * 50.0
            actual_k = math.log(strike / forward)
            variance = ESSVISurface.total_variance(actual_k, theta=theta, rho=rho, psi=psi)
            volatility = math.sqrt(variance / maturity)
            for is_call in (True, False):
                mid = black76_price(
                    forward=forward,
                    strike=strike,
                    maturity_years=maturity,
                    volatility=volatility,
                    risk_free_rate=0.0,
                    is_call=is_call,
                )
                half = max(0.05, mid * 0.002)
                rows.append(
                    _row(
                        instrument_id=(
                            f"NSE:NSE_FNO:NIFTY:option:{expiry.isoformat()}:"
                            f"{strike:.8f}:{'CE' if is_call else 'PE'}"
                        ),
                        bid=max(0.05, mid - half),
                        ask=mid + half,
                        sequence=sequence,
                        receive_ts=valuation - timedelta(milliseconds=400),
                    )
                )
                sequence += 1
    for expiry, include in ((NEAR, include_near_future), (FAR, include_far_future)):
        if not include:
            continue
        forward = FORWARDS[expiry]
        rows.append(
            _row(
                instrument_id=f"NSE:NSE_FNO:NIFTY:future:{expiry.isoformat()}",
                bid=forward - 0.5,
                ask=forward + 0.5,
                sequence=sequence,
                receive_ts=valuation - timedelta(milliseconds=200),
            )
        )
        sequence += 1
    return rows


def _engine(*, wall_clock: bool = False, **overrides: object) -> SurfaceEngine:
    policy = StalenessPolicy(**overrides)  # type: ignore[arg-type]
    return SurfaceEngine(
        run_id="sha-20260819T053000.000000Z-anl03test",
        surface_id="anl03-test",
        expiries=(NEAR, FAR),
        log_moneyness_grid=default_log_moneyness_grid(half_width=0.06, points=13),
        policy=policy,
        fit_interval_seconds=5.0,
        wall_clock=wall_clock,
    )


def _maturities(valuation: datetime) -> dict[date, float]:
    return {
        expiry: (expiry_timestamp(expiry) - valuation).total_seconds() / SECONDS_PER_YEAR
        for expiry in FORWARDS
    }


def test_traded_future_is_preferred_and_labelled_with_its_construction() -> None:
    selection = select_forwards(
        rows=_chain(),
        expiries=[NEAR, FAR],
        maturity_years_by_expiry=_maturities(VALUATION),
    )
    by_expiry = {choice.expiry: choice for choice in selection.choices}
    assert by_expiry[NEAR].method is ForwardMethod.TRADED_FUTURE
    assert by_expiry[NEAR].forward == pytest.approx(FORWARDS[NEAR], abs=1e-9)
    label = by_expiry[NEAR].label
    assert label.category is ObjectCategory.DERIVED
    assert "traded future" in (label.construction or "")
    assert label.assumptions


def test_put_call_parity_is_used_and_labelled_when_no_future_exists() -> None:
    selection = select_forwards(
        rows=_chain(include_near_future=False),
        expiries=[NEAR, FAR],
        maturity_years_by_expiry=_maturities(VALUATION),
    )
    by_expiry = {choice.expiry: choice for choice in selection.choices}
    assert by_expiry[NEAR].method is ForwardMethod.PUT_CALL_PARITY
    assert by_expiry[NEAR].forward == pytest.approx(FORWARDS[NEAR], rel=5e-4)
    assert by_expiry[NEAR].parity_strike is not None
    assert by_expiry[NEAR].parity_candidate_strikes >= 5
    assert "put-call parity" in (by_expiry[NEAR].label.construction or "")
    assert any("no traded future" in item for item in by_expiry[NEAR].label.limitations)


def test_an_expiry_with_no_forward_source_is_reported_not_guessed() -> None:
    selection = select_forwards(
        rows=[],
        expiries=[NEAR],
        maturity_years_by_expiry=_maturities(VALUATION),
    )
    assert selection.choices == ()
    assert selection.unresolved[0][0] == NEAR
    assert "no traded future" in selection.unresolved[0][1]


def test_a_fit_carries_arbitrage_diagnostics_and_a_stable_grid() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    snapshot = engine.fit(VALUATION)
    assert snapshot.fit_ok, snapshot.failure_reason
    assert snapshot.arbitrage is not None
    assert snapshot.arbitrage["butterfly_checked_points"]
    assert "weighted_r_squared" in snapshot.diagnostics
    assert snapshot.grid is not None
    assert snapshot.grid.log_moneyness == engine.log_moneyness_grid
    assert len(snapshot.grid.implied_volatility) == 2
    assert snapshot.frame is not None
    assert snapshot.frame.surface_id == "anl03-test"


def test_unsupported_grid_cells_stay_null_rather_than_being_filled() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.log_moneyness_grid = default_log_moneyness_grid(half_width=0.9, points=9)
    snapshot = engine.fit(VALUATION)
    assert snapshot.grid is not None
    assert snapshot.grid.unsupported_cells > 0
    assert any(value is None for row in snapshot.grid.implied_volatility for value in row)
    assert snapshot.grid.reasons


def test_a_fit_without_rows_fails_visibly_instead_of_being_skipped() -> None:
    engine = _engine()
    snapshot = engine.fit(VALUATION)
    assert not snapshot.fit_ok
    assert snapshot.failure_reason
    assert snapshot.surface_is_stale
    assert snapshot.grid is None


def test_feed_status_follows_the_measured_cadence_thresholds() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    # DAT-16: a few hundred milliseconds is the normal Quote/Full cadence, not a fault.
    assert engine.health(VALUATION).status is FeedStatus.LIVE
    assert engine.health(VALUATION + timedelta(seconds=1.2)).status is FeedStatus.SLOW
    assert engine.health(VALUATION + timedelta(seconds=3)).status is FeedStatus.DEAD


def test_a_dead_feed_is_visible_even_though_the_last_surface_still_renders() -> None:
    """The guarded failure mode: a dead feed quietly showing the last good surface."""

    engine = _engine(wall_clock=True)
    # Every packet and the fit itself are 45 seconds old; nothing has arrived since.
    stale_valuation = datetime.now(tz=IST) - timedelta(seconds=45)
    for row in _chain(valuation=stale_valuation):
        engine.ingest(row)
    snapshot = engine.fit(stale_valuation)
    assert snapshot.fit_ok, snapshot.failure_reason
    health = engine.health(datetime.now(tz=IST))
    assert health.status is FeedStatus.DEAD
    assert health.feed_age_seconds is not None and health.feed_age_seconds > 40
    payload = build_payload(engine, title="t", source="s")
    verdict = payload["health_verdict"]
    assert verdict["status"] == FeedStatus.DEAD.value
    assert any("feed age" in reason for reason in verdict["reasons"])
    assert any("no surface has been fitted" in reason for reason in verdict["reasons"])
    assert payload["snapshot"]["grid"] is not None


def test_reconnects_are_counted_from_the_connection_epoch() -> None:
    engine = _engine()
    engine.ingest(
        _row(
            instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
            bid=1.0,
            ask=2.0,
            sequence=1,
            receive_ts=VALUATION,
            connection_epoch=1,
        )
    )
    assert engine.health(VALUATION).reconnect_count == 0
    engine.ingest(
        _row(
            instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
            bid=1.0,
            ask=2.0,
            sequence=2,
            receive_ts=VALUATION,
            connection_epoch=3,
        )
    )
    assert engine.health(VALUATION).reconnect_count == 2


def test_health_is_sampled_between_fits_so_the_trace_keeps_moving() -> None:
    engine = _engine(wall_clock=True)
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    build_payload(engine, title="t", source="s")
    build_payload(engine, title="t", source="s")
    trace = engine.latency_trace()
    assert len(trace["health_sample_timestamps"]) >= 2
    assert len(trace["timestamps"]) == 1


def test_history_lets_the_session_be_looked_back_across() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    engine.fit(VALUATION + timedelta(seconds=5))
    payload = build_history_payload(engine, 0)
    assert payload["index"] == 0
    assert payload["history_length"] == 2
    assert payload["snapshot"]["sequence"] == 1
    assert build_history_payload(engine, 99)["index"] == 1


def test_rendered_html_is_self_contained_and_declares_itself_read_only() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    html = render_html(build_payload(engine, title="ANL-03 test", source="fixture"))
    assert "cdn.plot.ly" in html
    assert "type: 'surface'" in html
    assert "uirevision" in html
    assert "READ-ONLY" in html
    assert "SUR-05 ARBITRAGE" in html
    assert "SUR-06 DIAGNOSTICS" in html


def test_the_server_serves_state_and_refuses_every_write_method() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    state = DashboardState(engine, title="ANL-03 test", source="fixture")
    server, _ = serve_in_background(state, host="127.0.0.1", port=0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert response.status == 200
            assert b"READ-ONLY" in response.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as response:
            body = json.loads(response.read())
        assert body["read_only"] is True
        assert body["snapshot"]["fit_ok"] is True
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/state", data=b"{}", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code in {405, 501}
    finally:
        server.shutdown()
        server.server_close()


def test_the_universe_interleaves_expiries_so_a_ceiling_truncates_wings() -> None:
    mappings = [
        DhanInstrumentMapping(
            instrument=InstrumentId(
                exchange="NSE",
                segment=ExchangeSegment.NSE_FNO,
                underlying="NIFTY",
                kind=InstrumentKind.OPTION,
                expiry=expiry,
                strike=Decimal(strike),
                option_type=option_type,
            ),
            security_id=str(70_000 + index),
            exchange_segment=ExchangeSegment.NSE_FNO,
            trading_symbol=f"NIFTY-{expiry}-{strike}-{option_type.value}",
            lot_size=75,
            tick_size_paise=None,
            as_of_date=date(2026, 8, 19),
            source="fixture",
        )
        for index, (expiry, strike, option_type) in enumerate(
            (expiry, strike, option_type)
            for expiry in (NEAR, FAR)
            for strike in (23_900, 24_000, 24_100, 24_200)
            for option_type in (OptionType.CALL, OptionType.PUT)
        )
    ]
    universe = select_chain_universe(
        mappings,
        underlying="NIFTY",
        expiries=[NEAR, FAR],
        spot_reference=24_100.0,
        strike_window_fraction=0.06,
        max_options=4,
    )
    assert len(universe.options) == 4
    assert {option.instrument.expiry for option in universe.options} == {NEAR, FAR}
    assert all(
        abs(float(option.instrument.strike or 0) - 24_100.0) <= 100.0
        for option in universe.options
    )


def test_staleness_policy_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="slow < dead"):
        StalenessPolicy(feed_slow_seconds=3.0, feed_dead_seconds=1.0)


# --- ANL-05: the presentation redesign -------------------------------------------------
#
# These guard the *shell*, not the model. The rule Aryan set for ANL-05 is that layout,
# typography and colour may change and measured fields may not, so the tests below pin the
# fields that must survive any future restyle, and pin exactly the two panels he asked to
# have removed so a later edit cannot quietly put a third one back or take a fourth away.


def _rendered_shell() -> str:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    return render_html(build_payload(engine, title="ANL-03 test", source="fixture"))


def test_the_shell_carries_both_themes_and_a_toggle() -> None:
    html = _rendered_shell()
    assert 'data-theme="light"' in html
    assert ':root[data-theme="dark"]' in html
    assert "prefers-color-scheme: dark" in html
    assert "function toggleTheme()" in html
    assert "anl03-theme" in html  # the choice persists across refreshes
    # Both Plotly palettes must be present, or one mode would render with the other's ramp.
    assert "ivRamp" in html and "violRamp" in html
    assert html.count("ivRamp:") == 2 and html.count("violRamp:") == 2


def test_the_shell_is_monospace_and_uses_the_approved_muted_palette() -> None:
    html = _rendered_shell()
    assert "ui-monospace" in html and "JetBrains Mono" in html and "Consolas" in html
    for muted in ("#46586b", "#b5851f", "#8f3327", "#5b7a52"):  # light slate/brass/brick/sage
        assert muted in html
    for muted in ("#8199b0", "#d3a44a", "#c05c46", "#8faa7c"):  # the dark steps
        assert muted in html
    for bright in ("Viridis", "Hot", "#c0221c", "#1a7a34", "#1f4e9c"):  # the old defaults
        assert bright not in html


def test_status_is_never_carried_by_colour_alone() -> None:
    html = _rendered_shell()
    assert "STATUS_GLYPH" in html
    for glyph in ("\\u25CF", "\\u25D0", "\\u2715", "\\u25CB"):  # live, slow, dead, no data
        assert glyph in html


def test_only_the_latency_and_forward_panels_were_removed() -> None:
    html = _rendered_shell()
    for gone in ("latencyChart", "renderTrace", "forwardBody", "forwardUnresolved",
                 "SUSTAINED LATENCY", "FORWARD SOURCE"):
        assert gone not in html
    for kept in ("healthStrip", "healthReasons", "arbBanner", "arbCounts", "arbBody",
                 "diagBody", "residualBody", "surfaceChart", "historySlider", "liveToggle"):
        assert kept in html


def test_removing_the_two_panels_did_not_remove_the_measurements() -> None:
    """The panels stopped being drawn; the fields behind them still reach `/api/state`."""

    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    payload = build_payload(engine, title="ANL-03 test", source="fixture")
    trace = payload["trace"]
    assert trace["timestamps"] and trace["fit_duration_seconds"]
    assert trace["health_sample_feed_age_seconds"]
    assert trace["surface_age_seconds"]
    forwards = payload["snapshot"]["forwards"]
    assert forwards["choices"], "the forward per expiry is still resolved and still published"
    assert forwards["choices"][0]["method"]
    assert forwards["choices"][0]["label"]["category"]


def test_every_health_and_diagnostic_field_is_still_on_screen() -> None:
    html = _rendered_shell()
    for label in ("feed age", "fit age", "surface age", "packets / s", "reconnects",
                  "worst instrument age", "last update ist", "browser clock"):
        assert label in html
    for label in ("fit status", "weighted RMSE (total variance)", "fit duration",
                  "unsupported grid cells", "butterfly points checked",
                  "calendar points checked", "min butterfly density factor",
                  "min calendar total-variance spread"):
        assert label in html
    assert "feed_dead_seconds" in html and "feed_slow_seconds" in html
    assert "fit_stale_seconds" in html and "surface_staleness_seconds" in html


def test_sur05_violations_are_placed_on_the_surface_as_well_as_tabulated() -> None:
    html = _rendered_shell()
    assert "SUR-05 violation" in html
    assert "symbol: 'diamond'" in html


# --- ANL-05 follow-ups: free navigation, and ATM IV as a live hero number ---------------


def test_atm_is_read_at_k_zero_and_matches_the_surface_the_dashboard_plots() -> None:
    """The hero number must be the same object as the cell the surface draws at k = 0."""

    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    snapshot = engine.fit(VALUATION)
    assert snapshot.atm, "a converged fit must produce an at-the-money reading"
    grid = snapshot.grid
    assert grid is not None
    k_zero = grid.log_moneyness.index(0.0)
    for reading in snapshot.atm:
        from_grid = grid.implied_volatility[grid.expiry_labels.index(reading.expiry)][k_zero]
        assert reading.implied_volatility == pytest.approx(from_grid, abs=1e-12)
        assert reading.maturity_days > 0
        assert reading.status
    # Front expiry first, so the hero is always the nearest maturity.
    assert [reading.maturity_days for reading in snapshot.atm] == sorted(
        reading.maturity_days for reading in snapshot.atm
    )


def test_a_failed_fit_reports_no_atm_rather_than_a_stale_one() -> None:
    engine = _engine()
    snapshot = engine.fit(VALUATION)
    assert not snapshot.fit_ok
    assert snapshot.atm == ()
    payload = build_payload(engine, title="ANL-03 test", source="fixture")
    assert payload["atm"]["front"] is None
    assert payload["atm"]["readings"] == []


def test_the_atm_change_is_matched_by_expiry_and_is_null_on_the_first_fit() -> None:
    engine = _engine()
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    first = build_payload(engine, title="t", source="s")["atm"]["front"]
    assert first["change_since_previous_fit"] is None, "nothing to difference against yet"

    engine.fit(VALUATION + timedelta(seconds=6))
    payload = build_payload(engine, title="t", source="s")
    previous = {
        reading.expiry: reading.implied_volatility
        for reading in engine.history[-2].atm
    }
    for reading in payload["atm"]["readings"]:
        expected = reading["implied_volatility"] - previous[reading["expiry"]]
        assert reading["change_since_previous_fit"] == pytest.approx(expected, abs=1e-15)


def test_the_shell_shows_atm_big_and_states_what_it_is() -> None:
    html = _rendered_shell()
    assert 'id="atmBand"' in html and "renderAtm" in html
    assert "font-size:44px" in html  # the hero, not another table row
    assert "k = 0" in html
    assert "fitted, not observed" in html  # it is estimated; the shell says so
    assert "change_since_previous_fit" in html
    # Direction is a glyph, never a status hue: a rising ATM vol is not "good".
    assert "\\u25B2" in html and "\\u25BC" in html


def test_the_camera_survives_a_refresh_and_the_view_can_be_driven() -> None:
    html = _rendered_shell()
    assert "cameraState" in html and "plotly_relayout" in html
    assert "cameraState || DEFAULT_CAMERA" in html, "the held camera must win over the default"
    assert "scrollZoom: true" in html
    for mode in ("turntable", "pan", "zoom"):
        assert f'data-drag="{mode}"' in html
    assert "function resetView()" in html
    assert "dragmode: sceneDragMode" in html
