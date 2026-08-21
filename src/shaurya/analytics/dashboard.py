"""ANL-03 dashboard payload and HTML rendering.

Plotly is loaded in the browser from the CDN, exactly as Market Making's
`monday_v1/surface_dashboard.py` does, and Python only builds the JSON payload. That keeps
the module dependency-free, keeps the payload testable as plain data, and lets the same
payload feed a replay run and a live run without a second code path.

Harvested from `monday_v1/surface_dashboard.py`: the CDN script tag, the payload-embedded
render, and `uirevision` to hold the user's 3D camera across refreshes. Reconciled rather
than copied: the chart is a `Surface` over moneyness x maturity x implied volatility, the
health strip is driven by measured feed age, and every panel is read-only (D19).

ANL-05 (2026-08-19) redesigned the presentation only: a light/dark theme carried on CSS
custom properties, a monospace type scale, hairline rules in place of card borders, and
Aryan's muted slate/olive/brass/brick palette in place of Plotly's default brights. The
sustained-latency chart and the forward-source table were removed from the screen on
Aryan's explicit instruction; both remain fully present in `/api/state`, so nothing
measured was dropped, only two panels stopped being drawn. Every remaining number, label
and threshold is byte-for-byte the same field it was before.
"""

from __future__ import annotations

import json
from typing import Any

from shaurya.analytics.surface_feed import (
    FeedHealth,
    FeedStatus,
    StalenessPolicy,
    SurfaceEngine,
    SurfaceSnapshot,
)

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def _arbitrage_summary(snapshot: SurfaceSnapshot) -> dict[str, object]:
    if snapshot.arbitrage is None:
        return {
            "checked": False,
            "passed": None,
            "violation_count": 0,
            "headline": "no fit, so no arbitrage check",
            "violations": [],
        }
    raw_violations = snapshot.arbitrage.get("violations")
    violations: list[dict[str, Any]] = (
        [item for item in raw_violations if isinstance(item, dict)]
        if isinstance(raw_violations, list)
        else []
    )
    passed = bool(snapshot.arbitrage.get("passed"))
    kinds = sorted({str(item.get("kind")) for item in violations})
    headline = (
        "butterfly and calendar checks pass"
        if passed
        else f"ARBITRAGE VIOLATED: {len(violations)} point(s) — {', '.join(kinds)}"
    )
    return {
        "checked": True,
        "passed": passed,
        "violation_count": len(violations),
        "headline": headline,
        "butterfly_checked_points": snapshot.arbitrage.get("butterfly_checked_points"),
        "calendar_checked_points": snapshot.arbitrage.get("calendar_checked_points"),
        "calendar_required": snapshot.arbitrage.get("calendar_required"),
        "min_butterfly_density_factor": snapshot.arbitrage.get("min_butterfly_density_factor"),
        "min_calendar_total_variance_spread": snapshot.arbitrage.get(
            "min_calendar_total_variance_spread"
        ),
        "violations": violations[:40],
    }


def _diagnostics_summary(snapshot: SurfaceSnapshot) -> dict[str, object]:
    diagnostics = snapshot.diagnostics
    support = diagnostics.get("support")
    residuals = diagnostics.get("residuals_by_moneyness")
    stability = diagnostics.get("parameter_stability")
    optimizer = diagnostics.get("optimizer")
    return {
        "fit_status": diagnostics.get("fit_status"),
        "weighted_r_squared": diagnostics.get("weighted_r_squared"),
        "weighted_rmse_total_variance": diagnostics.get("weighted_rmse_total_variance"),
        "residuals_by_moneyness": residuals,
        "parameter_stability": stability,
        "optimizer": optimizer,
        "support": support,
        "input": diagnostics.get("input"),
        "interpolation_policy": diagnostics.get("interpolation_policy"),
    }


def _health_verdict(
    snapshot: SurfaceSnapshot,
    policy: StalenessPolicy,
    *,
    health: FeedHealth | None = None,
    fit_age_seconds: float | None = None,
) -> dict[str, object]:
    """Judge on a health reading taken *now*, not on the one frozen into the last fit."""

    health = health or snapshot.health
    reasons: list[str] = []
    if health.status is FeedStatus.DEAD:
        reasons.append(
            f"feed age {health.feed_age_seconds:.2f}s exceeds the "
            f"{policy.feed_dead_seconds:.1f}s dead threshold"
        )
    elif health.status is FeedStatus.SLOW:
        reasons.append(
            f"feed age {health.feed_age_seconds:.2f}s exceeds the "
            f"{policy.feed_slow_seconds:.1f}s slow threshold"
        )
    elif health.status is FeedStatus.NO_DATA:
        reasons.append("no packet has arrived on this connection")
    if snapshot.surface_is_stale:
        reasons.append(
            "surface age exceeds the dashboard's SUR-07 staleness threshold of "
            f"{policy.surface_staleness_seconds:.0f}s"
        )
    if fit_age_seconds is not None and fit_age_seconds > policy.fit_stale_seconds:
        reasons.append(
            f"no surface has been fitted for {fit_age_seconds:.1f}s, past the "
            f"{policy.fit_stale_seconds:.0f}s fit-staleness threshold"
        )
    if not snapshot.fit_ok:
        reasons.append(f"last fit failed: {snapshot.failure_reason}")
    return {
        "status": health.status.value,
        "surface_is_stale": snapshot.surface_is_stale,
        "fit_age_seconds": fit_age_seconds,
        "reasons": reasons,
    }


def _atm_summary(engine: SurfaceEngine) -> dict[str, Any]:
    """At-the-money implied vol per expiry, plus its change since the previous fitted frame.

    The change is matched by expiry, not by position: slices drop in and out of a live chain
    as quotes thin, so comparing the front slot against the front slot would occasionally
    difference two different expiries and print a jump that never happened. When the previous
    frame had no reading for that expiry the change is null rather than zero.
    """

    snapshot = engine.latest
    if snapshot is None or not snapshot.atm:
        return {"readings": [], "front": None}
    previous: dict[str, float] = {}
    for earlier in reversed(engine.history[:-1]):
        if earlier.fit_ok and earlier.atm:
            previous = {
                reading.expiry: reading.implied_volatility
                for reading in earlier.atm
                if reading.implied_volatility is not None
            }
            break
    readings: list[dict[str, Any]] = []
    for reading in snapshot.atm:
        prior = previous.get(reading.expiry)
        change = (
            reading.implied_volatility - prior
            if reading.implied_volatility is not None and prior is not None
            else None
        )
        readings.append({**reading.to_dict(), "change_since_previous_fit": change})
    return {"readings": readings, "front": readings[0] if readings else None}


def build_payload(engine: SurfaceEngine, *, title: str, source: str) -> dict[str, Any]:
    """Build the whole dashboard payload from the engine's current state."""

    now = engine.current_time()
    live_health = engine.sample_health(now) if now is not None else None
    snapshot = engine.latest
    trace = engine.latency_trace()
    policy = engine.policy
    if snapshot is None:
        return {
            "title": title,
            "source": source,
            "read_only": True,
            "policy": policy.to_dict(),
            "snapshot": None,
            "history_length": 0,
            "trace": trace,
            "live_health": live_health.to_dict() if live_health else None,
            "fit_age_seconds": None,
            "health_verdict": {
                "status": FeedStatus.NO_DATA.value,
                "surface_is_stale": True,
                "reasons": ["the engine has not produced a snapshot yet"],
            },
            "atm": {"readings": [], "front": None},
            "arbitrage": {
                "checked": False,
                "passed": None,
                "violation_count": 0,
                "headline": "no fit yet",
                "violations": [],
            },
            "diagnostics": {},
            "mispricing": {
                "status": "unavailable",
                "reasons": ["the engine has not produced a surface fit yet"],
                "policy": engine.mispricing_policy.to_dict(),
                "active": [],
                "recent": [],
                "eligible_contract_count": 0,
                "statistically_tested_count": 0,
                "outside_band_count": 0,
                "fdr_significant_count": 0,
                "exact_confirmed_count": 0,
                "pending_count": 0,
            },
        }
    fit_age = engine.fit_age_seconds(now) if now is not None else None
    return {
        "title": title,
        "source": source,
        "read_only": True,
        "policy": policy.to_dict(),
        "snapshot": snapshot.to_dict(),
        "history_length": len(engine.history),
        "trace": trace,
        "live_health": live_health.to_dict() if live_health else None,
        "fit_age_seconds": fit_age,
        "health_verdict": _health_verdict(
            snapshot, policy, health=live_health, fit_age_seconds=fit_age
        ),
        "atm": _atm_summary(engine),
        "arbitrage": _arbitrage_summary(snapshot),
        "diagnostics": _diagnostics_summary(snapshot),
        "mispricing": snapshot.mispricing,
    }


def build_history_payload(engine: SurfaceEngine, index: int) -> dict[str, Any]:
    """One historical snapshot, so the session can be looked back across."""

    history = engine.history
    if not history:
        raise IndexError("no snapshots recorded yet")
    bounded = max(0, min(index, len(history) - 1))
    snapshot = history[bounded]
    return {
        "index": bounded,
        "history_length": len(history),
        "snapshot": snapshot.to_dict(),
        "atm": {
            "readings": [
                {**reading.to_dict(), "change_since_previous_fit": None} for reading in snapshot.atm
            ],
            "front": (
                {**snapshot.atm[0].to_dict(), "change_since_previous_fit": None}
                if snapshot.atm
                else None
            ),
        },
        "arbitrage": _arbitrage_summary(snapshot),
        "diagnostics": _diagnostics_summary(snapshot),
        "mispricing": snapshot.mispricing,
        "health_verdict": _health_verdict(snapshot, engine.policy),
    }


_THEME_JS = """
const THEMES = {
  light: {
    ink: '#1d1f22', ink2: '#575a5f', ink3: '#8b8d90',
    rule: '#dcd8ce', surface: '#f4f2ec', panel: '#faf8f2',
    slate: '#46586b', brass: '#b5851f', brick: '#8f3327', sage: '#5b7a52',
    point: '#2b2d31',
    ivRamp: ['#e2e6ea', '#c3ccd4', '#a2afbb', '#8291a1', '#647688', '#4a5c6e', '#364656'],
    violRamp: ['#f0e2d6', '#e0c3ac', '#cd9f83', '#b87c60', '#a05c45', '#843f2e', '#672c1f'],
  },
  dark: {
    ink: '#e6e2d8', ink2: '#a4a29a', ink3: '#76746e',
    rule: '#2d3137', surface: '#17191c', panel: '#1c1f23',
    slate: '#8199b0', brass: '#d3a44a', brick: '#c05c46', sage: '#8faa7c',
    point: '#ded9cf',
    ivRamp: ['#232c35', '#33404c', '#465768', '#5d7183', '#7b8fa1', '#9cadbc', '#bfccd7'],
    violRamp: ['#33211a', '#4a3025', '#664234', '#855747', '#a4705c', '#c08d75', '#d5ab92'],
  },
};

// Escalation is carried by a glyph and a word as well as a hue, so a colour-blind
// reader never depends on the hue alone (dataviz: status is never colour-only).
const STATUS_GLYPH = {live: '\\u25CF', slow: '\\u25D0', dead: '\\u2715', no_data: '\\u25CB'};

function themeName() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function theme() {
  return THEMES[themeName()];
}

function applyTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  try { window.localStorage.setItem('anl03-theme', name); } catch (error) { /* private mode */ }
  const button = document.getElementById('themeToggle');
  button.textContent = name === 'dark' ? '\\u25D1 LIGHT' : '\\u25D0 DARK';
  button.setAttribute('aria-label', 'switch to ' + (name === 'dark' ? 'light' : 'dark') + ' mode');
}

function toggleTheme() {
  applyTheme(themeName() === 'dark' ? 'light' : 'dark');
  if (lastPayload) render(lastPayload);
}

function initTheme() {
  let stored = null;
  try { stored = window.localStorage.getItem('anl03-theme'); } catch (error) { stored = null; }
  if (stored !== 'light' && stored !== 'dark') {
    stored = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark' : 'light';
  }
  applyTheme(stored);
}

function rampToScale(ramp) {
  return ramp.map((hex, index) => [index / (ramp.length - 1), hex]);
}

// The camera is held here rather than left to `uirevision` alone. `Plotly.react` is handed
// an explicit camera on every refresh (the axis ranges move as the session widens them), and
// an explicit camera in the layout wins over the retained one — so the view would snap back
// to the default once a second while the surface is live. Capturing the viewer's own camera
// off `plotly_relayout` and feeding it straight back makes zoom, pan and rotate survive every
// update until they press RESET.
const DEFAULT_CAMERA = {eye: {x: 1.16, y: 1.16, z: 0.88}};
let cameraState = null;
let sceneDragMode = 'turntable';
let surfaceWired = false;

function wireSurface(holder) {
  if (surfaceWired || typeof holder.on !== 'function') return;
  surfaceWired = true;
  holder.on('plotly_relayout', (event) => {
    const camera = event['scene.camera'];
    if (camera && camera.eye) cameraState = camera;
  });
}

function setDragMode(mode) {
  sceneDragMode = mode;
  document.querySelectorAll('[data-drag]').forEach((button) => {
    button.classList.toggle('on', button.getAttribute('data-drag') === mode);
  });
  if (lastPayload) renderSurface(stabiliseAxes(lastPayload));
}

function resetView() {
  cameraState = null;
  if (lastPayload) renderSurface(stabiliseAxes(lastPayload));
}
"""


def _chart_script() -> str:
    return """
const fmt = (value, digits) => (value === null || value === undefined || Number.isNaN(value))
  ? '\\u2014' : Number(value).toFixed(digits);

function statusColour(status) {
  const t = theme();
  if (status === 'slow') return t.brass;
  if (status === 'live') return t.ink;
  return t.brick;
}

function renderHealth(payload) {
  const t = theme();
  const snapshot = payload.snapshot;
  const verdict = payload.health_verdict;
  const rail = document.getElementById('healthStrip');
  rail.className = 'rail ' + verdict.status;
  const health = payload.live_health || (snapshot ? snapshot.health : null);
  const feedAge = health ? health.feed_age_seconds : null;
  const feedColour = feedAge === null ? t.brick
    : (feedAge >= payload.policy.feed_dead_seconds ? t.brick
      : (feedAge >= payload.policy.feed_slow_seconds ? t.brass : null));
  const fitAge = payload.fit_age_seconds;
  const fitColour = (fitAge !== null && fitAge !== undefined
    && fitAge > payload.policy.fit_stale_seconds) ? t.brick : null;
  const surfaceColour = snapshot && snapshot.surface_is_stale ? t.brick : null;
  const tiles = [
    ['feed', (STATUS_GLYPH[verdict.status] || '') + ' ' + verdict.status.replace('_', ' ')
      .toUpperCase(), statusColour(verdict.status)],
    ['feed age', health ? fmt(feedAge, 3) + ' s' : '\\u2014', feedColour],
    ['fit age', fmt(fitAge, 2) + ' s', fitColour],
    ['surface age', snapshot ? fmt(snapshot.surface_age_seconds, 2) + ' s' : '\\u2014',
      surfaceColour],
    ['packets / s', health ? fmt(health.packets_per_second, 1) : '\\u2014', null],
    ['reconnects', health ? health.reconnect_count : '\\u2014', null],
    ['worst instrument age',
      health ? fmt(health.worst_instrument_age_seconds, 2) + ' s' : '\\u2014', null],
    ['last update ist', health && health.last_update_timestamp
      ? health.last_update_timestamp.slice(11, 23) : 'NEVER', null],
    ['browser clock', new Date().toLocaleTimeString('en-GB'), null],
  ];
  rail.innerHTML = tiles.map(([label, value, colour]) => (
    '<div class="cell"><div class="cell-label">' + label + '</div>' +
    '<div class="cell-value"' + (colour ? ' style="color:' + colour + '"' : '') + '>' +
    value + '</div></div>'
  )).join('');
  const reasons = document.getElementById('healthReasons');
  reasons.className = verdict.reasons.length ? 'notes alert' : 'notes';
  reasons.innerHTML = verdict.reasons.length
    ? verdict.reasons.map((reason) => '<li>' + reason + '</li>').join('')
    : '<li>feed live, surface fresh, last fit converged</li>';
}

function renderSurface(payload) {
  const t = theme();
  const snapshot = payload.snapshot;
  const holder = document.getElementById('surfaceChart');
  if (!snapshot || !snapshot.grid) {
    Plotly.purge(holder);
    holder.innerHTML = '<div class="empty">NO SURFACE \\u2014 ' +
      ((snapshot && snapshot.failure_reason) || 'no fit yet') + '</div>';
    return;
  }
  const grid = snapshot.grid;
  const arb = payload.arbitrage;
  const violated = arb.passed === false;
  // One hue, monotone in lightness, in both states; the hue itself carries the SUR-05
  // verdict and the banner states it in words.
  const ramp = violated ? t.violRamp : t.ivRamp;
  const traces = [{
    type: 'surface',
    x: grid.log_moneyness,
    y: grid.maturity_days,
    z: grid.implied_volatility,
    colorscale: rampToScale(ramp),
    connectgaps: false,
    showscale: true,
    opacity: 0.98,
    contours: {z: {highlight: true, highlightcolor: t.ink3, highlightwidth: 1}},
    colorbar: {
      title: {text: 'IV', font: {size: 10, color: t.ink3}},
      thickness: 8, len: 0.5, x: 0.97, xpad: 0, outlinewidth: 0,
      ticks: 'outside', ticklen: 3, tickfont: {size: 9, color: t.ink3},
    },
    hovertemplate: 'k %{x:.4f}<br>T %{y:.2f} d<br>IV %{z:.4f}<extra></extra>',
  }];
  if (snapshot.market_points && snapshot.market_points.length) {
    traces.push({
      type: 'scatter3d',
      mode: 'markers',
      x: snapshot.market_points.map((p) => p.log_moneyness),
      y: snapshot.market_points.map((p) => p.maturity_days),
      z: snapshot.market_points.map((p) => p.implied_volatility),
      marker: {size: 2.2, color: t.point, opacity: 0.85},
      name: 'fitted at quoted strikes',
      hovertemplate: '%{text}<extra></extra>',
      text: snapshot.market_points.map((p) => p.instrument_id),
    });
  }
  // The SUR-05 violating points, placed where they actually occur rather than only
  // listed in the table below.
  const violations = (arb.violations || []).filter(
    (v) => v.log_moneyness !== null && v.log_moneyness !== undefined
      && v.maturity_years !== null && v.maturity_years !== undefined);
  if (violations.length) {
    traces.push({
      type: 'scatter3d',
      mode: 'markers',
      x: violations.map((v) => v.log_moneyness),
      y: violations.map((v) => v.maturity_years * 365.0),
      z: violations.map(() => payload.axis_iv_max),
      marker: {size: 5, color: t.brick, symbol: 'diamond', line: {width: 0}},
      name: 'SUR-05 violation',
      hovertemplate: '%{text}<extra></extra>',
      text: violations.map((v) => v.kind + ' violation'),
    });
  }
  const axis = (title) => ({
    title: {text: title, font: {size: 10, color: t.ink3}},
    tickfont: {size: 9, color: t.ink3},
    gridcolor: t.rule, zerolinecolor: t.rule, linecolor: t.rule,
    backgroundcolor: t.panel, showbackground: true,
  });
  const layout = {
    margin: {l: 0, r: 0, t: 0, b: 0},
    showlegend: false,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {family: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: t.ink2},
    uirevision: 'anl03-surface-camera',
    hoverlabel: {bgcolor: t.panel, bordercolor: t.rule,
      font: {color: t.ink, size: 11,
        family: 'ui-monospace, SFMono-Regular, Menlo, monospace'}},
    scene: {
      xaxis: Object.assign(axis('log-moneyness k'), {range: [
        Math.min.apply(null, grid.log_moneyness),
        Math.max.apply(null, grid.log_moneyness)]}),
      yaxis: Object.assign(axis('maturity (days)'), {range: [0, payload.axis_maturity_max]}),
      zaxis: Object.assign(axis('implied vol'),
        {range: [payload.axis_iv_min, payload.axis_iv_max]}),
      aspectmode: 'cube',
      dragmode: sceneDragMode,
      camera: cameraState || DEFAULT_CAMERA,
    },
  };
  Plotly.react(holder, traces, layout, {
    displaylogo: false, responsive: true, scrollZoom: true,
    modeBarButtonsToRemove: ['toImage'],
  }).then(() => wireSurface(holder));
}

function renderAtm(payload) {
  const atm = payload.atm || {readings: [], front: null};
  const band = document.getElementById('atmBand');
  const front = atm.front;
  const pct = (value) => (value === null || value === undefined)
    ? '\\u2014' : (value * 100).toFixed(3);
  if (!front || front.implied_volatility === null
      || front.implied_volatility === undefined) {
    band.innerHTML = '<div class="atm-head">ATM IV<span>k = 0</span></div>' +
      '<div class="atm-hero">\\u2014<em>%</em></div>' +
      '<div class="atm-why">' + ((front && front.reason) || 'no fitted slice at the money')
      + '</div>';
    return;
  }
  const change = front.change_since_previous_fit;
  const moved = change !== null && change !== undefined;
  const arrow = !moved ? '\\u00B7'
    : (change > 0 ? '\\u25B2' : (change < 0 ? '\\u25BC' : '\\u00B7'));
  // Direction is a glyph and a sign, never a hue: a rising ATM vol is not "good" and a
  // falling one is not "bad", so the status palette must not be borrowed for it.
  const delta = !moved ? 'first fit'
    : arrow + ' ' + (change > 0 ? '+' : '') + (change * 100).toFixed(3) + ' pp';
  const others = (atm.readings || []).slice(1).map((reading) => (
    '<div class="atm-other"><b>' + pct(reading.implied_volatility) + '<em>%</em></b>' +
    '<span>' + reading.expiry + ' \\u00B7 ' + reading.maturity_days.toFixed(1) + ' d</span></div>'
  )).join('');
  band.innerHTML =
    '<div class="atm-head">ATM IV<span>k = 0 \\u00B7 fitted, not observed</span></div>' +
    '<div class="atm-hero" title="' + front.implied_volatility + '">' +
      pct(front.implied_volatility) + '<em>%</em></div>' +
    '<div class="atm-meta"><div class="atm-delta">' + delta + '</div>' +
      '<div class="atm-expiry">' + front.expiry + ' \\u00B7 ' +
      front.maturity_days.toFixed(1) + ' d \\u00B7 ' + front.status + '</div></div>' +
    '<div class="atm-others">' + others + '</div>';
}

function renderArbitrage(payload) {
  const arb = payload.arbitrage;
  const banner = document.getElementById('arbBanner');
  banner.className = 'banner ' + (arb.passed === false ? 'bad' :
    (arb.passed === true ? 'ok' : 'unknown'));
  const glyph = arb.passed === false ? '\\u2715' : (arb.passed === true ? '\\u2713' : '\\u25CB');
  banner.textContent = glyph + '  SUR-05 ' + arb.headline;
  const rows = (arb.violations || []).map((v) => (
    '<tr><td>' + v.kind + '</td><td class="num">' + fmt(v.log_moneyness, 4) +
    '</td><td class="num">' + fmt(v.maturity_years, 5) + '</td><td class="num">' +
    fmt(v.value, 8) + '</td><td class="num">' + fmt(v.threshold, 8) + '</td></tr>'
  )).join('');
  document.getElementById('arbBody').innerHTML = rows ||
    '<tr><td colspan="5" class="muted">no violating points</td></tr>';
  document.getElementById('arbCounts').innerHTML = [
    ['butterfly points checked', arb.butterfly_checked_points ?? '\\u2014'],
    ['calendar points checked', arb.calendar_checked_points ?? '\\u2014'],
    ['min butterfly density factor', fmt(arb.min_butterfly_density_factor, 6)],
    ['min calendar total-variance spread', fmt(arb.min_calendar_total_variance_spread, 8)],
  ].map(([k, v]) => '<span><i>' + k + '</i> ' + v + '</span>').join('');
}

function renderDiagnostics(payload) {
  const d = payload.diagnostics || {};
  const snapshot = payload.snapshot;
  const bits = [
    ['fit status', d.fit_status ?? '\\u2014'],
    ['weighted R\\u00B2', fmt(d.weighted_r_squared, 5)],
    ['weighted RMSE (total variance)', fmt(d.weighted_rmse_total_variance, 8)],
    ['fit duration', snapshot ? fmt(snapshot.fit_duration_seconds, 3) + ' s' : '\\u2014'],
    ['max |\\u0394parameter| vs previous frame',
      d.parameter_stability
        ? fmt(d.parameter_stability.max_absolute_parameter_change, 6) : '\\u2014'],
    ['unsupported grid cells',
      snapshot && snapshot.grid ? snapshot.grid.unsupported_cells : '\\u2014'],
  ];
  document.getElementById('diagBody').innerHTML = bits.map(([k, v]) => (
    '<tr><td>' + k + '</td><td class="num">' + v + '</td></tr>')).join('');
  const residuals = d.residuals_by_moneyness || {};
  document.getElementById('residualBody').innerHTML = Object.keys(residuals).map((bucket) => {
    const item = residuals[bucket];
    return '<tr><td>' + bucket + '</td><td class="num">' + (item.count ?? '\\u2014') +
      '</td><td class="num">' + fmt(item.mean_total_variance_residual, 8) +
      '</td><td class="num">' + fmt(item.max_abs_total_variance_residual, 8) + '</td></tr>';
  }).join('') || '<tr><td colspan="4" class="muted">no residual buckets</td></tr>';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function renderMispricing(payload) {
  const monitor = payload.mispricing || {active: [], recent: [], reasons: []};
  const policy = monitor.policy || {};
  const summary = document.getElementById('mispricingSummary');
  const bits = [
    ['state', monitor.status || 'unavailable'],
    ['eligible', monitor.eligible_contract_count ?? 0],
    ['tested', monitor.statistically_tested_count ?? 0],
    ['outside band', monitor.outside_band_count ?? 0],
    ['FDR 1%', monitor.fdr_significant_count ?? 0],
    ['exact confirmed', monitor.exact_confirmed_count ?? 0],
    ['reference warming', monitor.reference_warming_count ?? 0],
    ['reference unstable', monitor.reference_unstable_count ?? 0],
    ['reference window', (policy.reference_stability_frames ?? '\u2014') + ' frames'],
    ['IV tolerance', fmt(policy.reference_max_iv_range_points, 2) + ' pp'],
    ['pending', monitor.pending_count ?? 0],
    ['active', (monitor.active || []).length],
    ['invalidated', (monitor.recent || []).filter((item) => item.status === 'invalidated').length],
  ];
  summary.innerHTML = bits.map(([label, value]) => (
    '<span><i>' + label + '</i> ' + escapeHtml(value) + '</span>')).join('');
  const notes = (monitor.reasons || []).join(' \u00b7 ');
  document.getElementById('mispricingNotes').textContent = notes ||
    'fresh strike-held-out reference surface; no confirmed dislocation';

  const row = (episode, recent) => {
    const market = episode.direction === 'cheap' ? episode.observed_ask : episode.observed_bid;
    const executableIv = episode.direction === 'cheap'
      ? episode.observed_ask_iv : episode.observed_bid_iv;
    const trace = episode.gap_close_trace || {};
    const words = (value) => String(value || '').replaceAll('_', ' ');
    const signed = (value) => value === null || value === undefined
      ? '\u2014' : ((Number(value) > 0 ? '+' : '') + fmt(value, 2));
    const clock = recent
      ? ((episode.corrected_at || episode.last_observed_at || '').slice(11, 19))
      : ((episode.first_seen_at || '').slice(11, 19));
    const outcome = recent
      ? (episode.status === 'corrected'
        ? (words(trace.attribution || episode.correction_driver || 'corrected') +
          (trace.closure_gate ? ' \u00b7 ' + words(trace.closure_gate) : ''))
        : episode.status === 'invalidated'
        ? ('invalidated \u00b7 ' + words(trace.attribution || 'reference changed') +
          (trace.closure_gate ? ' \u00b7 ' + words(trace.closure_gate) : ''))
        : 'censored: ' + (episode.censor_reason || 'unavailable'))
      : ('live \u00b7 ' + (episode.reference_stable ? 'stable reference' :
          words(episode.reference_stability_reason || 'reference warming')));
    return '<tr>' +
      '<td title="' + escapeHtml(episode.instrument_id) + '">' +
        escapeHtml(episode.expiry + ' ' + episode.strike + ' ' + episode.option_type) + '</td>' +
      '<td class="' + escapeHtml(episode.direction) + '">' +
        escapeHtml(episode.direction) + '</td>' +
      '<td class="num">' + fmt(market, 2) + '</td>' +
      '<td class="num">' + fmt(episode.fair_price, 2) + '</td>' +
      '<td class="num">[' + fmt(episode.fair_lower, 2) + ', ' +
        fmt(episode.fair_upper, 2) + ']</td>' +
      '<td class="num">' + fmt(Number(executableIv) * 100, 3) + '</td>' +
      '<td class="num">' + fmt(Number(episode.fair_iv) * 100, 3) + '</td>' +
      '<td class="num">[' + fmt(Number(episode.fair_iv_lower) * 100, 3) + ', ' +
        fmt(Number(episode.fair_iv_upper) * 100, 3) + ']</td>' +
      '<td class="num">' + fmt(episode.model_uncertainty_iv_points, 3) + '</td>' +
      '<td class="num">' + fmt(episode.total_uncertainty_iv_points, 3) + '</td>' +
      '<td class="num">' + escapeHtml(episode.residual_history_count) + ' / ' +
        fmt(episode.residual_effective_sample_size, 1) + '</td>' +
      '<td class="num">' + fmt(episode.raw_smoothed_iv_gap_points, 3) + '</td>' +
      '<td class="num">' + fmt(episode.reference_iv_range_points, 3) + '</td>' +
      '<td>' + escapeHtml(episode.reference_stable ? 'yes' :
        words(episode.reference_stability_reason || 'no')) + '</td>' +
      '<td class="num">' + fmt(episode.gross_iv_edge_points, 3) + '</td>' +
      '<td class="num">' + fmt(episode.net_edge_ticks, 2) + '</td>' +
      '<td class="num">' + fmt(episode.net_edge_per_lot, 2) + '</td>' +
      '<td class="num">' + fmt(trace.delta_hedged_net_per_lot, 2) + '</td>' +
      '<td class="num">' + fmt(episode.quote_age_seconds, 2) + ' s</td>' +
      '<td class="num">' + escapeHtml(clock) + '</td>' +
      '<td class="num">' + fmt(episode.duration_seconds, 1) + ' s</td>' +
      '<td class="num">' + fmt(trace.entry_iv_gap_points, 3) + '</td>' +
      '<td class="num">' + fmt(trace.target_correction_required_iv_points, 3) + '</td>' +
      '<td class="num">' + signed(trace.target_iv_contribution_points) + '</td>' +
      '<td class="num">' + signed(trace.reference_iv_contribution_points) + '</td>' +
      '<td class="num">' + signed(trace.iv_gap_closed_points) + '</td>' +
      '<td>' + escapeHtml(outcome) + '</td></tr>';
  };
  document.getElementById('mispricingActiveBody').innerHTML =
    (monitor.active || []).map((episode) => row(episode, false)).join('') ||
    '<tr><td colspan="27" class="muted">no confirmed active stable dislocation</td></tr>';
  document.getElementById('mispricingRecentBody').innerHTML =
    (monitor.recent || []).map((episode) => row(episode, true)).join('') ||
    '<tr><td colspan="27" class="muted">' +
      'no corrected, invalidated, or censored episodes yet</td></tr>';
}

function render(payload) {
  document.getElementById('sourceLabel').textContent = payload.source;
  renderHealth(payload);
  renderAtm(payload);
  renderSurface(payload);
  renderArbitrage(payload);
  renderDiagnostics(payload);
  renderMispricing(payload);
  const slider = document.getElementById('historySlider');
  const live = document.getElementById('liveToggle').checked;
  if (live) {
    slider.max = Math.max(0, payload.history_length - 1);
    slider.value = slider.max;
  }
  document.getElementById('historyLabel').textContent = payload.history_length
    ? 'frame ' + (Number(slider.value) + 1) + ' / ' + payload.history_length +
      (payload.snapshot ? '  \\u00B7  ' + payload.snapshot.fit_timestamp.slice(11, 19) + ' IST'
        : '')
    : 'no frames yet';
}

function stabiliseAxes(payload) {
  const snapshot = payload.snapshot;
  if (!snapshot || !snapshot.grid) return payload;
  const flat = [];
  snapshot.grid.implied_volatility.forEach((row) => row.forEach((value) => {
    if (value !== null && value !== undefined) flat.push(value);
  }));
  if (flat.length) {
    const lo = Math.min.apply(null, flat);
    const hi = Math.max.apply(null, flat);
    axisState.ivMin = axisState.ivMin === null ? lo : Math.min(axisState.ivMin, lo);
    axisState.ivMax = axisState.ivMax === null ? hi : Math.max(axisState.ivMax, hi);
  }
  const maxMaturity = Math.max.apply(null, snapshot.grid.maturity_days);
  axisState.maturityMax = axisState.maturityMax === null
    ? maxMaturity : Math.max(axisState.maturityMax, maxMaturity);
  payload.axis_iv_min = Math.max(0, (axisState.ivMin ?? 0) - 0.02);
  payload.axis_iv_max = (axisState.ivMax ?? 1) + 0.02;
  payload.axis_maturity_max = (axisState.maturityMax ?? 30) * 1.05;
  return payload;
}

async function refresh() {
  const live = document.getElementById('liveToggle').checked;
  try {
    const response = await fetch(live ? '/api/state'
      : '/api/history?index=' + document.getElementById('historySlider').value);
    const body = await response.json();
    if (!live) {
      lastPayload = Object.assign({}, lastPayload, body);
      render(stabiliseAxes(lastPayload));
    } else {
      lastPayload = body;
      render(stabiliseAxes(body));
    }
  } catch (error) {
    document.getElementById('healthReasons').className = 'notes alert';
    document.getElementById('healthReasons').innerHTML =
      '<li>dashboard cannot reach its own server: ' + error + '</li>';
  }
}
"""


_STYLE = """
:root {
  --ink:#1d1f22; --ink-2:#575a5f; --ink-3:#8b8d90;
  --rule:#dcd8ce; --rule-soft:#e8e4da;
  --bg:#f4f2ec; --panel:#faf8f2;
  --slate:#46586b; --brass:#b5851f; --brick:#8f3327; --sage:#5b7a52;
  color-scheme:light;
}
:root[data-theme="dark"] {
  --ink:#e6e2d8; --ink-2:#a4a29a; --ink-3:#76746e;
  --rule:#2d3137; --rule-soft:#24272b;
  --bg:#17191c; --panel:#1c1f23;
  --slate:#8199b0; --brass:#d3a44a; --brick:#c05c46; --sage:#8faa7c;
  color-scheme:dark;
}
* { box-sizing:border-box; }
html, body {
  margin:0; background:var(--bg); color:var(--ink);
  font-family:ui-monospace, SFMono-Regular, "SF Mono", "JetBrains Mono", "IBM Plex Mono",
    Menlo, Consolas, "Liberation Mono", monospace;
  font-size:12.5px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums;
}
body { display:flex; flex-direction:column; height:100vh; overflow:hidden; }

header {
  display:flex; align-items:center; gap:14px;
  padding:11px 18px 10px; border-bottom:1px solid var(--rule); flex:none;
}
h1 { font-size:12.5px; font-weight:600; letter-spacing:.06em; margin:0; }
header .spacer { flex:1; }
.stamp {
  font-size:9.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-3);
}
.stamp b { font-weight:600; color:var(--ink-2); }
button {
  font:inherit; font-size:9.5px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-2); background:none; border:1px solid var(--rule);
  padding:3px 9px; cursor:pointer;
}
button:hover { border-color:var(--ink-3); color:var(--ink); }

.rail {
  display:flex; flex-wrap:wrap; flex:none;
  border-bottom:1px solid var(--rule); border-left:3px solid transparent;
  padding:9px 18px 10px; gap:0;
}
.rail.slow { border-left-color:var(--brass); }
.rail.dead, .rail.no_data { border-left-color:var(--brick); }
.cell { padding:0 18px; border-left:1px solid var(--rule-soft); }
.cell:first-child { padding-left:0; border-left:none; }
.cell-label {
  font-size:9px; letter-spacing:.15em; text-transform:uppercase; color:var(--ink-3);
  white-space:nowrap;
}
.cell-value { font-size:15px; line-height:1.35; white-space:nowrap; }

.atm {
  display:flex; align-items:center; gap:26px; flex:none;
  padding:12px 18px 13px; border-bottom:1px solid var(--rule);
}
.atm-head {
  font-size:9px; letter-spacing:.17em; text-transform:uppercase; color:var(--ink-3);
  display:flex; flex-direction:column; gap:2px; white-space:nowrap;
}
.atm-head span { letter-spacing:.1em; opacity:.75; text-transform:none; }
.atm-hero {
  font-size:44px; line-height:1; letter-spacing:-.01em; color:var(--ink);
  font-variant-numeric:tabular-nums; white-space:nowrap;
}
.atm-hero em { font-size:15px; font-style:normal; color:var(--ink-3); margin-left:5px; }
.atm-meta { display:flex; flex-direction:column; gap:3px; white-space:nowrap; }
.atm-delta { font-size:13px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
.atm-expiry { font-size:9px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--ink-3); }
.atm-why { font-size:11px; color:var(--brick); }
.atm-others { display:flex; gap:22px; margin-left:auto; }
.atm-other { display:flex; flex-direction:column; gap:2px; text-align:right;
  white-space:nowrap; }
.atm-other b { font-size:17px; font-weight:400; color:var(--ink-2);
  font-variant-numeric:tabular-nums; }
.atm-other b em { font-size:9px; font-style:normal; color:var(--ink-3); margin-left:3px; }
.atm-other span { font-size:9px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-3); }

.viewmodes { display:flex; gap:0; margin-left:auto; }
.viewmodes button { border-right-width:0; }
.viewmodes button:last-child { border-right-width:1px; }
.viewmodes button.on { color:var(--ink); border-color:var(--ink-3);
  background:var(--panel); }

.notes { margin:0; padding:7px 18px 8px; list-style:none;
  border-bottom:1px solid var(--rule); flex:none; color:var(--ink-3); font-size:11px; }
.notes.alert { color:var(--brick); border-left:3px solid var(--brick); }
.notes li::before { content:'\\2014\\00a0\\00a0'; color:var(--ink-3); }

.banner {
  flex:none; padding:8px 18px; font-size:11.5px; letter-spacing:.04em;
  border-bottom:1px solid var(--rule); border-left:3px solid transparent;
}
.banner.ok { color:var(--sage); border-left-color:var(--sage); }
.banner.bad { color:var(--brick); border-left-color:var(--brick); font-weight:600; }
.banner.unknown { color:var(--ink-3); border-left-color:var(--rule); }

main {
  flex:1; min-height:0; display:grid;
  grid-template-columns:minmax(460px, 1.5fr) minmax(380px, 1fr);
}
.stage { display:flex; flex-direction:column; min-width:0;
  border-right:1px solid var(--rule); }
#surfaceChart { flex:1; min-height:0; }
.aside { overflow-y:auto; padding:14px 18px 22px; }
.aside section + section { margin-top:22px; }

.sec { display:flex; align-items:center; gap:10px; margin:0 0 9px; }
.sec h2 {
  font-size:9.5px; font-weight:600; letter-spacing:.17em; text-transform:uppercase;
  color:var(--ink-3); margin:0; white-space:nowrap;
}
.sec::after { content:''; flex:1; height:1px; background:var(--rule); }

.controls {
  display:flex; align-items:center; gap:14px; flex:none;
  padding:9px 18px 10px; border-top:1px solid var(--rule);
  font-size:9.5px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-3);
}
.controls label { display:flex; align-items:center; gap:6px; cursor:pointer; }
.controls input[type=checkbox] { accent-color:var(--slate); margin:0; }
input[type=range] {
  flex:1; accent-color:var(--slate); height:2px; background:var(--rule);
  -webkit-appearance:none; appearance:none;
}
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance:none; width:9px; height:14px; background:var(--slate); cursor:pointer;
}

.kv { display:flex; flex-wrap:wrap; gap:4px 20px; color:var(--ink-3);
  font-size:10.5px; margin-bottom:9px; }
.kv i { font-style:normal; letter-spacing:.1em; text-transform:uppercase; font-size:9px; }
.kv span { color:var(--ink-2); }

table { border-collapse:collapse; width:100%; }
th, td { text-align:left; padding:3px 10px 3px 0; font-size:11px;
  border-bottom:1px solid var(--rule-soft); }
td.num, th.num { text-align:right; padding-right:0; }
th { color:var(--ink-3); font-weight:500; font-size:9px; letter-spacing:.13em;
  text-transform:uppercase; border-bottom-color:var(--rule); }
td { color:var(--ink-2); }
tr:last-child td { border-bottom:none; }
.muted { color:var(--ink-3); }
.cheap { color:var(--sage); font-weight:600; }
.rich { color:var(--brick); font-weight:600; }
.empty { display:flex; height:100%; align-items:center; justify-content:center;
  color:var(--brick); letter-spacing:.1em; font-size:11px; }

.mispricing-panel {
  flex:none; height:340px; min-height:220px; overflow:auto;
  border-top:1px solid var(--rule); background:var(--panel); padding:11px 18px 16px;
}
.mispricing-head { display:flex; align-items:baseline; gap:14px; margin-bottom:4px; }
.mispricing-head h2 {
  margin:0; font-size:10px; letter-spacing:.16em; text-transform:uppercase;
}
.mispricing-head p { margin:0; color:var(--ink-3); font-size:9.5px; }
.mispricing-notes { color:var(--ink-3); font-size:10px; margin:0 0 8px; }
.mispricing-tables { display:grid; grid-template-columns:1fr; gap:14px; }
.mispricing-table { min-width:0; overflow-x:auto; }
.mispricing-table h3 {
  margin:0 0 5px; color:var(--ink-3); font-size:9px; font-weight:600;
  letter-spacing:.14em; text-transform:uppercase;
}
.mispricing-table table { min-width:2500px; }
.mispricing-table th, .mispricing-table td { white-space:nowrap; }

@media (max-width:1080px) {
  body { height:auto; overflow:auto; }
  main { grid-template-columns:1fr; }
  .stage { border-right:none; border-bottom:1px solid var(--rule); }
  #surfaceChart { height:60vh; }
  .mispricing-panel { height:auto; max-height:none; }
  .mispricing-tables { grid-template-columns:1fr; }
}
"""


_BODY = """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<script src="__PLOTLY__"></script>
<style>__STYLE__</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="stamp"><b>READ-ONLY</b> &middot; D19 watching only, never places or influences
    an order</span>
  <span class="spacer"></span>
  <span class="stamp" id="sourceLabel"></span>
  <button id="themeToggle" type="button" onclick="toggleTheme()">&#9686; DARK</button>
</header>
<div class="rail" id="healthStrip"></div>
<div class="atm" id="atmBand"></div>
<ul class="notes" id="healthReasons"></ul>
<div class="banner" id="arbBanner"></div>
<main>
  <div class="stage">
    <div id="surfaceChart"></div>
    <div class="controls">
      <label><input type="checkbox" id="liveToggle" checked onchange="refresh()" /> live</label>
      <input type="range" id="historySlider" min="0" max="0" value="0"
        oninput="document.getElementById('liveToggle').checked=false; refresh()" />
      <span id="historyLabel"></span>
      <span class="viewmodes">
        <button type="button" data-drag="turntable" class="on"
          onclick="setDragMode('turntable')" title="drag to rotate">rotate</button>
        <button type="button" data-drag="pan"
          onclick="setDragMode('pan')" title="drag to pan across the surface">pan</button>
        <button type="button" data-drag="zoom"
          onclick="setDragMode('zoom')" title="drag a box to zoom; the wheel always zooms"
          >zoom</button>
        <button type="button" onclick="resetView()" title="back to the default camera"
          >reset</button>
      </span>
    </div>
  </div>
  <div class="aside">
    <section>
      <div class="sec"><h2>SUR-05 ARBITRAGE</h2></div>
      <div class="kv" id="arbCounts"></div>
      <table><thead><tr><th>kind</th><th class="num">k</th><th class="num">T (y)</th>
        <th class="num">value</th><th class="num">threshold</th></tr></thead>
        <tbody id="arbBody"></tbody></table>
    </section>
    <section>
      <div class="sec"><h2>SUR-06 DIAGNOSTICS</h2></div>
      <table><tbody id="diagBody"></tbody></table>
    </section>
    <section>
      <div class="sec"><h2>Residuals by moneyness</h2></div>
      <table><thead><tr><th>bucket</th><th class="num">n</th>
        <th class="num">mean residual</th><th class="num">max |residual|</th></tr></thead>
        <tbody id="residualBody"></tbody></table>
    </section>
  </div>
</main>
<section class="mispricing-panel" id="mispricingPanel">
  <div class="mispricing-head">
    <h2>Stable held-out executable-IV dislocations</h2>
    <p>read-only research monitor &middot; 60 s causal surface smoothing &middot;
      continuous past-only IV uncertainty &middot; exact held-out check
      &middot; frozen-entry IV correction &middot; frozen-delta markout proxy</p>
  </div>
  <div class="kv" id="mispricingSummary"></div>
  <p class="mispricing-notes" id="mispricingNotes"></p>
  <div class="mispricing-tables">
    <div class="mispricing-table">
      <h3>Active confirmed</h3>
      <table><thead><tr><th>contract</th><th>side</th><th class="num">market</th>
        <th class="num">fair</th><th class="num">fair band</th>
        <th class="num">exec IV %</th><th class="num">fair IV %</th>
        <th class="num">fair IV band %</th><th class="num">model u pp</th>
        <th class="num">total u pp</th><th class="num">neigh / eff n</th>
        <th class="num">raw-smooth pp</th><th class="num">stability range pp</th>
        <th>reference stable</th><th class="num">gross IV pp</th>
        <th class="num">net ticks</th><th class="num">net / lot</th>
        <th class="num" title="frozen-entry-delta executable-quote proxy"
          >delta hedge net / lot</th>
        <th class="num">quote age</th><th class="num">first seen</th>
        <th class="num">duration</th>
        <th class="num" title="executable-IV gap at confirmation">entry gap pp</th>
        <th class="num" title="target executable-IV movement required after costs"
          >target required pp</th>
        <th class="num" title="positive means target executable IV closed the gap"
          >target \u0394 pp</th>
        <th class="num" title="positive means held-out reference IV closed the gap"
          >reference \u0394 pp</th>
        <th class="num" title="target plus reference IV contributions">gap closed pp</th>
        <th>closure trace</th></tr></thead>
        <tbody id="mispricingActiveBody"></tbody></table>
    </div>
    <div class="mispricing-table">
      <h3>Recently corrected / invalidated / censored</h3>
      <table><thead><tr><th>contract</th><th>side</th><th class="num">market</th>
        <th class="num">fair</th><th class="num">fair band</th>
        <th class="num">exec IV %</th><th class="num">fair IV %</th>
        <th class="num">fair IV band %</th><th class="num">model u pp</th>
        <th class="num">total u pp</th><th class="num">neigh / eff n</th>
        <th class="num">raw-smooth pp</th><th class="num">stability range pp</th>
        <th>reference stable</th><th class="num">gross IV pp</th>
        <th class="num">net ticks</th><th class="num">net / lot</th>
        <th class="num" title="frozen-entry-delta executable-quote proxy"
          >delta hedge net / lot</th>
        <th class="num">quote age</th><th class="num">closed</th>
        <th class="num">duration</th>
        <th class="num" title="executable-IV gap at confirmation">entry gap pp</th>
        <th class="num" title="target executable-IV movement required after costs"
          >target required pp</th>
        <th class="num" title="positive means target executable IV closed the gap"
          >target \u0394 pp</th>
        <th class="num" title="positive means held-out reference IV closed the gap"
          >reference \u0394 pp</th>
        <th class="num" title="target plus reference IV contributions">gap closed pp</th>
        <th>closure trace</th></tr></thead>
        <tbody id="mispricingRecentBody"></tbody></table>
    </div>
  </div>
</section>
<script>
const axisState = {ivMin: null, ivMax: null, maturityMax: null};
let lastPayload = __PAYLOAD__;
__THEME_JS__
__CHART_JS__
initTheme();
render(stabiliseAxes(lastPayload));
setInterval(refresh, __REFRESH_MS__);
</script>
</body>
</html>
"""


def render_html(payload: dict[str, Any], *, refresh_ms: int = 1000) -> str:
    """Render the read-only dashboard shell with an embedded first payload.

    Placeholders rather than an f-string: the CSS and JS are full of braces, and doubling
    every one of them to survive an f-string is how a stylesheet silently rots.
    """

    payload_json = json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")
    return (
        _BODY.replace("__STYLE__", _STYLE)
        .replace("__PLOTLY__", PLOTLY_CDN)
        .replace("__THEME_JS__", _THEME_JS)
        .replace("__CHART_JS__", _chart_script())
        .replace("__REFRESH_MS__", str(refresh_ms))
        .replace("__PAYLOAD__", payload_json)
        .replace("__TITLE__", str(payload["title"]))
    )
