"""ANL-03 dashboard payload and HTML rendering.

Plotly is loaded in the browser from the CDN, exactly as Market Making's
`monday_v1/surface_dashboard.py` does, and Python only builds the JSON payload. That keeps
the module dependency-free, keeps the payload testable as plain data, and lets the same
payload feed a replay run and a live run without a second code path.

Harvested from `monday_v1/surface_dashboard.py`: the CDN script tag, the payload-embedded
render, and `uirevision` to hold the user's 3D camera across refreshes. Reconciled rather
than copied: the chart is a `Surface` over moneyness x maturity x implied volatility, the
health strip is driven by measured feed age, and every panel is read-only (D19).
"""

from __future__ import annotations

import json
from typing import Any

from shaurya.analytics.surface_feed import (
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
        "min_butterfly_density_factor": snapshot.arbitrage.get(
            "min_butterfly_density_factor"
        ),
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


def _health_verdict(snapshot: SurfaceSnapshot, policy: StalenessPolicy) -> dict[str, object]:
    health = snapshot.health
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
    if not snapshot.fit_ok:
        reasons.append(f"last fit failed: {snapshot.failure_reason}")
    return {
        "status": health.status.value,
        "surface_is_stale": snapshot.surface_is_stale,
        "reasons": reasons,
    }


def build_payload(engine: SurfaceEngine, *, title: str, source: str) -> dict[str, Any]:
    """Build the whole dashboard payload from the engine's current state."""

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
            "health_verdict": {
                "status": FeedStatus.NO_DATA.value,
                "surface_is_stale": True,
                "reasons": ["the engine has not produced a snapshot yet"],
            },
            "arbitrage": {
                "checked": False,
                "passed": None,
                "violation_count": 0,
                "headline": "no fit yet",
                "violations": [],
            },
            "diagnostics": {},
        }
    return {
        "title": title,
        "source": source,
        "read_only": True,
        "policy": policy.to_dict(),
        "snapshot": snapshot.to_dict(),
        "history_length": len(engine.history),
        "trace": trace,
        "health_verdict": _health_verdict(snapshot, policy),
        "arbitrage": _arbitrage_summary(snapshot),
        "diagnostics": _diagnostics_summary(snapshot),
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
        "arbitrage": _arbitrage_summary(snapshot),
        "diagnostics": _diagnostics_summary(snapshot),
        "health_verdict": _health_verdict(snapshot, engine.policy),
    }


def _chart_script() -> str:
    return """
const fmt = (value, digits) => (value === null || value === undefined || Number.isNaN(value))
  ? '--' : Number(value).toFixed(digits);

function statusColour(status) {
  if (status === 'live') return '#1a7a34';
  if (status === 'slow') return '#b8860b';
  return '#c0221c';
}

function renderHealth(payload) {
  const snapshot = payload.snapshot;
  const verdict = payload.health_verdict;
  const strip = document.getElementById('healthStrip');
  strip.className = 'health ' + verdict.status;
  const health = snapshot ? snapshot.health : null;
  const tiles = [
    ['FEED', verdict.status.toUpperCase(), statusColour(verdict.status)],
    ['FEED AGE', health ? fmt(health.feed_age_seconds, 3) + ' s' : '--', null],
    ['SURFACE AGE', snapshot ? fmt(snapshot.surface_age_seconds, 2) + ' s' : '--', null],
    ['PACKETS/S', health ? fmt(health.packets_per_second, 1) : '--', null],
    ['RECONNECTS', health ? health.reconnect_count : '--', null],
    ['WORST INSTRUMENT AGE',
      health ? fmt(health.worst_instrument_age_seconds, 2) + ' s' : '--', null],
    ['LAST UPDATE (IST)', health && health.last_update_timestamp
        ? health.last_update_timestamp.slice(11, 23) : 'NEVER', null],
    ['BROWSER CLOCK', new Date().toLocaleTimeString('en-GB'), null],
  ];
  strip.innerHTML = tiles.map(([label, value, colour]) => (
    '<div class="tile"><div class="tile-label">' + label + '</div>' +
    '<div class="tile-value"' + (colour ? ' style="color:' + colour + '"' : '') + '>' +
    value + '</div></div>'
  )).join('');
  document.getElementById('healthReasons').innerHTML = verdict.reasons.length
    ? verdict.reasons.map((reason) => '<li>' + reason + '</li>').join('')
    : '<li class="ok">feed live, surface fresh, last fit converged</li>';
}

function renderSurface(payload) {
  const snapshot = payload.snapshot;
  const holder = document.getElementById('surfaceChart');
  if (!snapshot || !snapshot.grid) {
    Plotly.purge(holder);
    holder.innerHTML = '<div class="failed">NO SURFACE — ' +
      ((snapshot && snapshot.failure_reason) || 'no fit yet') + '</div>';
    return;
  }
  const grid = snapshot.grid;
  const arb = payload.arbitrage;
  const colorscale = arb.passed === false ? 'Hot' : 'Viridis';
  const surfaceTrace = {
    type: 'surface',
    x: grid.log_moneyness,
    y: grid.maturity_days,
    z: grid.implied_volatility,
    colorscale: colorscale,
    connectgaps: false,
    showscale: true,
    colorbar: {title: 'IV', thickness: 12},
    hovertemplate: 'k=%{x:.4f}<br>T=%{y:.2f}d<br>IV=%{z:.4f}<extra></extra>',
  };
  const traces = [surfaceTrace];
  if (snapshot.market_points && snapshot.market_points.length) {
    traces.push({
      type: 'scatter3d',
      mode: 'markers',
      x: snapshot.market_points.map((p) => p.log_moneyness),
      y: snapshot.market_points.map((p) => p.maturity_days),
      z: snapshot.market_points.map((p) => p.implied_volatility),
      marker: {size: 2, color: '#111111'},
      name: 'fitted at quoted strikes',
      hovertemplate: '%{text}<extra></extra>',
      text: snapshot.market_points.map((p) => p.instrument_id),
    });
  }
  const layout = {
    margin: {l: 0, r: 0, t: 10, b: 0},
    showlegend: false,
    uirevision: 'anl03-surface-camera',
    scene: {
      xaxis: {title: 'log-moneyness k', range: [
        Math.min.apply(null, grid.log_moneyness),
        Math.max.apply(null, grid.log_moneyness)]},
      yaxis: {title: 'maturity (days)', range: [0, payload.axis_maturity_max]},
      zaxis: {title: 'implied vol', range: [payload.axis_iv_min, payload.axis_iv_max]},
      aspectmode: 'cube',
    },
  };
  Plotly.react(holder, traces, layout, {displaylogo: false, responsive: true});
}

function renderTrace(payload) {
  const trace = payload.trace;
  const holder = document.getElementById('latencyChart');
  const traces = [
    {x: trace.timestamps, y: trace.feed_age_seconds, name: 'feed age (s)',
     mode: 'lines', line: {width: 1.4, color: '#1f4e9c'}},
    {x: trace.timestamps, y: trace.surface_age_seconds, name: 'surface age (s)',
     mode: 'lines', line: {width: 1.4, color: '#b8860b'}},
    {x: trace.timestamps, y: trace.fit_duration_seconds, name: 'fit duration (s)',
     mode: 'lines', line: {width: 1.2, color: '#5a5a5a', dash: 'dot'}},
  ];
  const layout = {
    margin: {l: 46, r: 10, t: 6, b: 28},
    uirevision: 'anl03-latency-view',
    legend: {orientation: 'h', y: 1.18, font: {size: 10}},
    xaxis: {showgrid: false, type: 'date'},
    yaxis: {title: 'seconds', rangemode: 'tozero',
            zerolinecolor: '#dddddd', gridcolor: '#eeeeee'},
    shapes: [
      {type: 'line', xref: 'paper', x0: 0, x1: 1,
       y0: payload.policy.feed_dead_seconds, y1: payload.policy.feed_dead_seconds,
       line: {color: '#c0221c', width: 1, dash: 'dash'}},
      {type: 'line', xref: 'paper', x0: 0, x1: 1,
       y0: payload.policy.feed_slow_seconds, y1: payload.policy.feed_slow_seconds,
       line: {color: '#b8860b', width: 1, dash: 'dot'}},
    ],
  };
  Plotly.react(holder, traces, layout, {displaylogo: false, responsive: true});
}

function renderArbitrage(payload) {
  const arb = payload.arbitrage;
  const banner = document.getElementById('arbBanner');
  banner.className = 'arb ' + (arb.passed === false ? 'failed' :
    (arb.passed === true ? 'ok' : 'unknown'));
  banner.textContent = 'SUR-05 ' + arb.headline;
  const rows = (arb.violations || []).map((v) => (
    '<tr><td>' + v.kind + '</td><td>' + fmt(v.log_moneyness, 4) + '</td><td>' +
    fmt(v.maturity_years, 5) + '</td><td>' + fmt(v.value, 8) + '</td><td>' +
    fmt(v.threshold, 8) + '</td></tr>'
  )).join('');
  document.getElementById('arbBody').innerHTML = rows ||
    '<tr><td colspan="5" class="muted">no violating points</td></tr>';
  document.getElementById('arbCounts').textContent =
    'butterfly points checked ' + (arb.butterfly_checked_points ?? '--') +
    ' | calendar points checked ' + (arb.calendar_checked_points ?? '--') +
    ' | min butterfly density factor ' + fmt(arb.min_butterfly_density_factor, 6) +
    ' | min calendar total-variance spread ' + fmt(arb.min_calendar_total_variance_spread, 8);
}

function renderDiagnostics(payload) {
  const d = payload.diagnostics || {};
  const snapshot = payload.snapshot;
  const bits = [
    ['fit status', d.fit_status ?? '--'],
    ['weighted R²', fmt(d.weighted_r_squared, 5)],
    ['weighted RMSE (total variance)', fmt(d.weighted_rmse_total_variance, 8)],
    ['fit duration', snapshot ? fmt(snapshot.fit_duration_seconds, 3) + ' s' : '--'],
    ['max |Δparameter| vs previous frame',
      d.parameter_stability ? fmt(d.parameter_stability.max_absolute_parameter_change, 6) : '--'],
    ['unsupported grid cells',
      snapshot && snapshot.grid ? snapshot.grid.unsupported_cells : '--'],
  ];
  document.getElementById('diagBody').innerHTML = bits.map(([k, v]) => (
    '<tr><td>' + k + '</td><td>' + v + '</td></tr>')).join('');
  const residuals = d.residuals_by_moneyness || {};
  document.getElementById('residualBody').innerHTML = Object.keys(residuals).map((bucket) => {
    const item = residuals[bucket];
    return '<tr><td>' + bucket + '</td><td>' + (item.count ?? '--') + '</td><td>' +
      fmt(item.mean_total_variance_residual, 8) + '</td><td>' +
      fmt(item.max_abs_total_variance_residual, 8) + '</td></tr>';
  }).join('') || '<tr><td colspan="4" class="muted">no residual buckets</td></tr>';
  const forwards = snapshot ? snapshot.forwards : null;
  const choices = forwards ? forwards.choices : [];
  document.getElementById('forwardBody').innerHTML = choices.map((choice) => (
    '<tr><td>' + choice.expiry + '</td><td>' + fmt(choice.forward, 2) + '</td><td>' +
    choice.method + '</td><td>' + (choice.label.category) + '</td><td>' +
    (choice.label.construction || '') + '</td></tr>')).join('') ||
    '<tr><td colspan="5" class="muted">no forward resolved</td></tr>';
  const unresolved = forwards ? forwards.unresolved : [];
  document.getElementById('forwardUnresolved').innerHTML = unresolved.map((item) => (
    '<li>' + item.expiry + ': ' + item.reason + '</li>')).join('');
}

function render(payload) {
  document.getElementById('sourceLabel').textContent = payload.source;
  renderHealth(payload);
  renderSurface(payload);
  renderTrace(payload);
  renderArbitrage(payload);
  renderDiagnostics(payload);
  const slider = document.getElementById('historySlider');
  const live = document.getElementById('liveToggle').checked;
  if (live) {
    slider.max = Math.max(0, payload.history_length - 1);
    slider.value = slider.max;
  }
  document.getElementById('historyLabel').textContent =
    (Number(slider.value) + 1) + ' / ' + payload.history_length +
    (payload.snapshot ? ' @ ' + payload.snapshot.fit_timestamp.slice(11, 19) + ' IST' : '');
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
    document.getElementById('healthReasons').innerHTML =
      '<li>dashboard cannot reach its own server: ' + error + '</li>';
  }
}
"""


def render_html(payload: dict[str, Any], *, refresh_ms: int = 1000) -> str:
    """Render the read-only dashboard shell with an embedded first payload."""

    payload_json = json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{payload["title"]}</title>
<script src="{PLOTLY_CDN}"></script>
<style>
  html, body {{ margin:0; background:#ffffff; color:#111111;
    font-family:-apple-system, Arial, Helvetica, sans-serif; font-size:13px; }}
  header {{ display:flex; align-items:baseline; gap:14px; padding:8px 14px 4px; }}
  h1 {{ font-size:15px; margin:0; }}
  .badge {{ font-size:11px; border:1px solid #999; border-radius:3px; padding:1px 6px;
    color:#444; }}
  .health {{ display:flex; gap:8px; padding:6px 14px; flex-wrap:wrap; }}
  .health.dead {{ background:#fdecec; }}
  .health.slow {{ background:#fff6e0; }}
  .health.no_data {{ background:#fdecec; }}
  .tile {{ border:1px solid #e2e2e2; border-radius:4px; padding:4px 10px; min-width:104px; }}
  .tile-label {{ font-size:10px; letter-spacing:0.05em; color:#777; }}
  .tile-value {{ font-size:16px; font-variant-numeric:tabular-nums;
    font-family:"SF Mono", Menlo, monospace; }}
  .arb {{ margin:6px 14px; padding:6px 10px; border-radius:4px; font-weight:700; }}
  .arb.ok {{ background:#eaf6ec; color:#1a7a34; }}
  .arb.failed {{ background:#c0221c; color:#ffffff; }}
  .arb.unknown {{ background:#eeeeee; color:#555; }}
  main {{ display:grid; grid-template-columns:minmax(420px, 1.35fr) minmax(360px, 1fr);
    gap:10px; padding:0 14px 14px; align-items:start; }}
  .panel {{ border:1px solid #e2e2e2; border-radius:5px; padding:8px; }}
  .panel h2 {{ font-size:12px; margin:0 0 6px; letter-spacing:0.04em; color:#444; }}
  #surfaceChart {{ height:62vh; min-height:380px; }}
  #latencyChart {{ height:210px; }}
  table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
  th, td {{ text-align:left; padding:2px 6px; border-bottom:1px solid #f0f0f0;
    font-size:11.5px; }}
  th {{ color:#666; font-weight:600; }}
  ul {{ margin:4px 0 0 16px; padding:0; }}
  li {{ color:#c0221c; }}
  li.ok {{ color:#1a7a34; }}
  .muted {{ color:#999; }}
  .failed {{ display:flex; height:100%; align-items:center; justify-content:center;
    color:#c0221c; font-weight:700; }}
  .controls {{ display:flex; align-items:center; gap:10px; padding:0 14px 6px; }}
  input[type=range] {{ flex:1; }}
</style>
</head>
<body>
<header>
  <h1>{payload["title"]}</h1>
  <span class="badge">READ-ONLY — D19 watching only, never places or influences an order</span>
  <span class="badge" id="sourceLabel"></span>
</header>
<div class="health" id="healthStrip"></div>
<ul id="healthReasons"></ul>
<div class="arb" id="arbBanner"></div>
<div class="controls">
  <label><input type="checkbox" id="liveToggle" checked onchange="refresh()" /> live</label>
  <input type="range" id="historySlider" min="0" max="0" value="0"
    oninput="document.getElementById('liveToggle').checked=false; refresh()" />
  <span id="historyLabel"></span>
</div>
<main>
  <div class="panel">
    <h2>IMPLIED VOLATILITY SURFACE — moneyness x maturity x IV</h2>
    <div id="surfaceChart"></div>
  </div>
  <div>
    <div class="panel">
      <h2>SUSTAINED LATENCY — feed age, surface age, fit duration across the session</h2>
      <div id="latencyChart"></div>
    </div>
    <div class="panel" style="margin-top:10px">
      <h2>SUR-05 ARBITRAGE</h2>
      <div id="arbCounts" class="muted"></div>
      <table><thead><tr><th>kind</th><th>k</th><th>T (y)</th><th>value</th>
        <th>threshold</th></tr></thead><tbody id="arbBody"></tbody></table>
    </div>
    <div class="panel" style="margin-top:10px">
      <h2>SUR-06 DIAGNOSTICS</h2>
      <table><tbody id="diagBody"></tbody></table>
      <table style="margin-top:6px"><thead><tr><th>moneyness bucket</th><th>n</th>
        <th>mean residual</th><th>max |residual|</th></tr></thead>
        <tbody id="residualBody"></tbody></table>
    </div>
    <div class="panel" style="margin-top:10px">
      <h2>FORWARD SOURCE PER EXPIRY — a model choice, stated</h2>
      <table><thead><tr><th>expiry</th><th>forward</th><th>method</th><th>category</th>
        <th>construction</th></tr></thead><tbody id="forwardBody"></tbody></table>
      <ul id="forwardUnresolved"></ul>
    </div>
  </div>
</main>
<script>
const axisState = {{ivMin: null, ivMax: null, maturityMax: null}};
let lastPayload = {payload_json};
{_chart_script()}
render(stabiliseAxes(lastPayload));
setInterval(refresh, {refresh_ms});
</script>
</body>
</html>
"""
