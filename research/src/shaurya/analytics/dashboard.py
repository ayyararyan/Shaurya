"""ANL-03 dashboard with the NSGVC nearest-weekly realized-volatility forecast."""

from __future__ import annotations

import html as html_lib
import math
import re
from typing import Any

from shaurya.analytics import butterfly_dashboard as _butterfly_ui
from shaurya.analytics import dashboard_base as _base
from shaurya.analytics.surface_feed import SurfaceEngine
from shaurya.analytics.variance_carry import realized_volatility_forecast

PLOTLY_CDN = _base.PLOTLY_CDN


def _rv_forecast_from_atm_payload(atm: dict[str, Any]) -> dict[str, Any]:
    """Build the frozen NSGVC front-expiry RV forecast from dashboard ATM state."""

    front = atm.get("front")
    if not isinstance(front, dict):
        return {"status": "unavailable", "reason": "no_front_atm_reading"}
    atm_iv = front.get("implied_volatility")
    maturity_days = front.get("maturity_days")
    if not isinstance(atm_iv, (int, float)) or not isinstance(maturity_days, (int, float)):
        return {"status": "unavailable", "reason": "front_atm_or_maturity_missing"}
    if atm_iv <= 0.0 or maturity_days <= 0.0:
        return {"status": "unavailable", "reason": "front_atm_or_maturity_nonpositive"}

    # SurfaceFeed reports maturity_days as maturity_years * 365.0, so divide by
    # that same basis here to recover the exact maturity used by the fitted ATM read.
    maturity_years = float(maturity_days) / 365.0
    try:
        forecast = realized_volatility_forecast(
            atm_iv=float(atm_iv),
            maturity_years=maturity_years,
        )
    except ValueError as error:
        return {"status": "unavailable", "reason": str(error)}
    return {
        "status": "ok",
        "expiry": str(front.get("expiry", "")),
        "maturity_days": float(maturity_days),
        **forecast.to_dict(),
    }


def build_payload(engine: SurfaceEngine, *, title: str, source: str) -> dict[str, Any]:
    """Build the standard payload and append the front-expiry RV forecast."""

    payload = _base.build_payload(engine, title=title, source=source)
    atm = payload.get("atm")
    payload["rv_forecast"] = _rv_forecast_from_atm_payload(atm if isinstance(atm, dict) else {})
    return payload


def build_history_payload(engine: SurfaceEngine, index: int) -> dict[str, Any]:
    """Build one historical payload with the same frozen RV forecast fields."""

    payload = _base.build_history_payload(engine, index)
    atm = payload.get("atm")
    payload["rv_forecast"] = _rv_forecast_from_atm_payload(atm if isinstance(atm, dict) else {})
    return payload


_RV_STYLE = """
body { height:auto; min-height:100vh; overflow:auto; }
header { flex-wrap:wrap; padding:16px 24px; }
header h1 { font-size:17px; letter-spacing:0; }
header .stamp { font-size:10px; }
#sourceLabel { display:none; }
.rv-forecast { padding:22px 24px 16px; }
.rv-context { font-size:13px; color:var(--ink-2); margin-bottom:14px; overflow-wrap:anywhere; }
.rv-cards { display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }
.rv-card { padding:22px; border:1px solid var(--rule); border-radius:10px;
  background:var(--panel); min-width:0; }
.rv-card.primary { border:2px solid var(--slate); }
.rv-card h2 { margin:0 0 12px; font-size:15px; font-weight:600; color:var(--ink); }
.rv-value { font-size:40px; line-height:1.2; letter-spacing:-2px; }
.rv-card.primary .rv-value { font-size:40px; font-weight:600; }
.rv-card p { margin:8px 0 0; color:var(--ink-2); font-size:12px; }
.rv-status { margin:14px 0 0; color:var(--ink-2); font-size:12px; }
main { display:block; flex:none; }
.stage { border-right:0; }
#surfaceChart { height:480px; min-height:360px; }
.controls { flex-wrap:wrap; font-size:11px; }
.notes, .banner { padding-left:24px; font-size:12px; }
details { margin:12px 24px; border:1px solid var(--rule); border-radius:8px; }
summary { cursor:pointer; padding:14px 18px; font-size:13px; font-weight:600; }
.aside { overflow:visible; display:grid; grid-template-columns:repeat(3,1fr); gap:24px; }
.aside section + section { margin-top:0; }
.mispricing-panel { height:auto; min-height:0; max-height:500px; }
.atm { flex-wrap:wrap; }
@media(max-width:900px) {
  html, body { width:100%; max-width:100%; overflow-x:hidden; }
  header { padding:12px 16px; box-sizing:border-box; } header .stamp { display:none; }
  .rv-forecast { width:100%; max-width:100%; box-sizing:border-box; padding:16px; }
  .rv-cards { grid-template-columns:minmax(0,1fr); gap:10px; }
  .rv-card { padding:16px; } .rv-card.primary { grid-column:auto; }
  .rv-value { font-size:34px; } .rv-card.primary .rv-value { font-size:34px; }
  .rv-card h2 { font-size:13px; }
  details { width:calc(100% - 32px); max-width:calc(100% - 32px);
    box-sizing:border-box; margin:10px 16px; }
  .aside { display:block; } .aside section + section { margin-top:20px; }
  #surfaceChart { height:380px; } .viewmodes { margin-left:0; }
}
"""

_RV_SCRIPT = r"""
function renderRvForecast(payload) {
  const f = payload.rv_forecast || {};
  const number = (v, scale, digits) => typeof v === 'number' && Number.isFinite(v)
    ? (v * scale).toFixed(digits) : '—';
  document.getElementById('rvValue').textContent =
    f.status === 'ok' ? number(f.forecast_annualized_realized_volatility, 100, 2) + '%' : '—';
  document.getElementById('ivValue').textContent =
    f.status === 'ok' ? number(f.atm_iv, 100, 2) + '%' : '—';
  document.getElementById('qValue').textContent =
    f.status === 'ok' ? number(f.rv_iv_vol_ratio, 1, 3) : '—';
  document.getElementById('rvContext').textContent = f.status === 'ok'
    ? 'Nearest expiry · ' + f.expiry + ' · ' + number(f.maturity_days, 1, 2) + ' days remaining'
    : 'Nearest-expiry forecast unavailable';
  const arb = (payload.snapshot || {}).arbitrage;
  document.getElementById('arbBanner').textContent = arb && !arb.passed
    ? 'Surface arbitrage check failed — do not use these prices for entry.' : '';
  const stamp = payload.snapshot ? payload.snapshot.fit_timestamp : '';
  const historical = !document.getElementById('liveToggle').checked
    || payload.view_mode === 'saved_snapshot';
  const stale = (payload.health_verdict || {}).surface_is_stale;
  document.getElementById('rvStatus').textContent = f.status !== 'ok'
    ? 'Forecast unavailable: ' + (f.reason || 'waiting for a valid surface')
    : (historical ? 'Saved / historical snapshot — not live prices'
      : stale ? 'Stale source fit — not a fresh forecast' :
      'Forecast from the displayed fit') + (stamp ? ' · ' + new Date(stamp).toLocaleString('en-IN',
      {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'})
      + ' IST' : '');
}
const _renderWithRvBase = render;
render = function(payload, forceSurfaceRedraw) {
  renderRvForecast(payload);
  _renderWithRvBase(payload, forceSurfaceRedraw);
};
renderRvForecast(lastPayload);
"""


def _forecast_cards(payload: dict[str, Any]) -> str:
    """Render the first values on the server: visible even if chart JavaScript fails."""
    f = payload.get("rv_forecast") or {}

    def value(key: str, scale: float, digits: int, suffix: str = "") -> str:
        raw = f.get(key)
        if f.get("status") != "ok" or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            return "—"
        return f"{raw * scale:.{digits}f}{suffix}"

    context = (
        f"Nearest expiry · {f.get('expiry', '')} · {value('maturity_days', 1, 2)} days remaining"
        if f.get("status") == "ok"
        else "Nearest-expiry forecast unavailable"
    )
    stamp = (payload.get("snapshot") or {}).get("fit_timestamp", "")
    status = f"Page-load snapshot · {stamp} · waiting for live refresh"
    return f"""<section class="rv-forecast" id="rvForecastBand" aria-label="Volatility overview">
<div class="rv-context" id="rvContext">{html_lib.escape(context)}</div>
<div class="rv-cards">
<article class="rv-card primary"><h2>ATM RV forecast</h2>
<div class="rv-value" id="rvValue">
{value("forecast_annualized_realized_volatility", 100, 2, "%")}</div>
<p>Expected realized volatility · annualized</p></article>
<article class="rv-card"><h2>ATM implied volatility</h2>
<div class="rv-value" id="ivValue">{value("atm_iv", 100, 2, "%")}</div>
<p>From the fitted option surface · annualized</p></article>

<article class="rv-card"><h2>Predicted RV ÷ ATM IV</h2>
<div class="rv-value" id="qValue">{value("rv_iv_vol_ratio", 1, 3)}</div>
<p>Volatility ratio used by VolARP · enter condition &lt; 0.70</p></article>
</div><p class="rv-status" id="rvStatus">{html_lib.escape(status)}</p>
<noscript>Live updates require JavaScript. These are the values at page load.</noscript>
</section>"""


def render_html(payload: dict[str, Any], *, refresh_ms: int = 1000) -> str:
    """Forecast-first layout; research diagnostics remain in the API, not the page."""
    html = _base.render_html(payload, refresh_ms=refresh_ms)
    html = html.replace('<div class="rail" id="healthStrip"></div>', _forecast_cards(payload), 1)
    html = html.replace('<div class="atm" id="atmBand"></div>', "", 1)
    start = html.index('  <div class="aside">')
    end = html.index("</main>", start)
    html = html[:start] + html[end:]
    start = html.index('<section class="mispricing-panel"')
    end = html.index("<script>", start)
    html = html[:start] + html[end:]
    for renderer in (
        "renderHealth",
        "renderAtm",
        "renderArbitrage",
        "renderDiagnostics",
        "renderMispricing",
    ):
        html = html.replace("  " + renderer + "(payload);", "")
    html = re.sub(
        r'<span class="stamp"><b>READ-ONLY</b>.*?</span>',
        '<span class="stamp">READ-ONLY</span>',
        html,
        count=1,
        flags=re.S,
    )
    arbitrage = (payload.get("snapshot") or {}).get("arbitrage") or {}
    surface_summary = (
        "View arbitrage-checked eSSVI surface"
        if arbitrage.get("passed") is True
        else "View eSSVI surface — arbitrage check failed"
    )
    html = html.replace(
        "<main>",
        '<details id="surfaceDetails" ontoggle="if(this.open &amp;&amp; '
        "typeof Plotly !== &quot;undefined&quot;) "
        'renderSurface(stabiliseAxes(lastPayload),true)">'
        f"<summary>{surface_summary}</summary><main>",
        1,
    )
    html = html.replace("</main>", "</main></details>", 1)
    html = html.replace("<h1>" + str(payload["title"]) + "</h1>", "<h1>Shaurya · NIFTY</h1>", 1)
    html = html.replace("</style>", _RV_STYLE + _butterfly_ui.STYLE + "\n</style>", 1)
    html = html.replace("</body>", "<script>\n" + _RV_SCRIPT + "\n</script>\n</body>", 1)
    html = html.replace(
        '<details id="surfaceDetails"', _butterfly_ui.PANEL + '<details id="surfaceDetails"', 1
    )
    html = html.replace("</body>", "<script>\n" + _butterfly_ui.SCRIPT + "\n</script></body>", 1)
    return html
