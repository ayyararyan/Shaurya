"""ANL-03 dashboard with the NSGVC nearest-weekly realized-volatility forecast."""

from __future__ import annotations

from typing import Any

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
    payload["rv_forecast"] = _rv_forecast_from_atm_payload(
        atm if isinstance(atm, dict) else {}
    )
    return payload


def build_history_payload(engine: SurfaceEngine, index: int) -> dict[str, Any]:
    """Build one historical payload with the same frozen RV forecast fields."""

    payload = _base.build_history_payload(engine, index)
    atm = payload.get("atm")
    payload["rv_forecast"] = _rv_forecast_from_atm_payload(
        atm if isinstance(atm, dict) else {}
    )
    return payload


_RV_STYLE = """
.rv-forecast {
  display:flex; align-items:center; gap:24px; flex:none;
  padding:10px 18px 11px; border-bottom:1px solid var(--rule); background:var(--panel);
}
.rv-head {
  font-size:9px; letter-spacing:.17em; text-transform:uppercase; color:var(--ink-3);
  display:flex; flex-direction:column; gap:2px; white-space:nowrap;
}
.rv-head span { letter-spacing:.08em; text-transform:none; opacity:.78; }
.rv-hero {
  font-size:34px; line-height:1; letter-spacing:-.01em; white-space:nowrap;
  font-variant-numeric:tabular-nums;
}
.rv-hero em { font-size:13px; font-style:normal; color:var(--ink-3); margin-left:4px; }
.rv-stats { display:flex; flex-wrap:wrap; gap:7px 24px; }
.rv-stat { display:flex; flex-direction:column; gap:1px; white-space:nowrap; }
.rv-stat i { font-style:normal; font-size:8.5px; letter-spacing:.13em;
  text-transform:uppercase; color:var(--ink-3); }
.rv-stat b { font-size:13px; font-weight:400; color:var(--ink-2); }
.rv-note { margin-left:auto; max-width:430px; font-size:9.5px; color:var(--ink-3); }
"""


_RV_SCRIPT = r"""
function renderRvForecast(payload) {
  const band = document.getElementById('rvForecastBand');
  if (!band) return;
  const f = payload.rv_forecast || {status: 'unavailable'};
  const pct = (value) => (value === null || value === undefined || Number.isNaN(Number(value)))
    ? '\u2014' : (Number(value) * 100).toFixed(3);
  if (f.status !== 'ok') {
    band.innerHTML = '<div class="rv-head">FORECAST RV' +
      '<span>nearest-weekly NSGVC model</span></div>' +
      '<div class="rv-hero">\u2014<em>%</em></div>' +
      '<div class="rv-note">' + escapeHtml(f.reason || 'forecast unavailable') + '</div>';
    return;
  }
  const qState = f.q_below_reference ? 'below 0.70' : 'above 0.70';
  band.innerHTML =
    '<div class="rv-head">FORECAST RV<span>annualized realized volatility</span></div>' +
    '<div class="rv-hero" title="' + f.forecast_annualized_realized_volatility + '">' +
      pct(f.forecast_annualized_realized_volatility) + '<em>%</em></div>' +
    '<div class="rv-stats">' +
      '<div class="rv-stat"><i>ATM IV</i><b>' + pct(f.atm_iv) + '%</b></div>' +
      '<div class="rv-stat"><i>q = RVint / IVint</i><b>' + fmt(f.q_ratio, 4) +
        ' \u00b7 ' + qState + '</b></div>' +
      '<div class="rv-stat"><i>horizon</i><b>' + fmt(f.maturity_days, 2) + ' d</b></div>' +
      '<div class="rv-stat"><i>expiry</i><b>' + escapeHtml(f.expiry) + '</b></div>' +
    '</div>' +
    '<div class="rv-note">IV-only forecast of forward integrated realized variance; ' +
      'annualized RV = sqrt(predicted integrated RV / T). Model: ' +
      escapeHtml(f.model_version) + '.</div>';
}

const _renderWithRvBase = render;
render = function(payload, forceSurfaceRedraw) {
  _renderWithRvBase(payload, forceSurfaceRedraw);
  renderRvForecast(payload);
};
renderRvForecast(lastPayload);
"""


def render_html(payload: dict[str, Any], *, refresh_ms: int = 1000) -> str:
    """Render the base dashboard and add a live RV-forecast band below ATM IV."""

    html = _base.render_html(payload, refresh_ms=refresh_ms)
    html = html.replace(
        '<div class="atm" id="atmBand"></div>',
        '<div class="atm" id="atmBand"></div>\n'
        '<div class="rv-forecast" id="rvForecastBand"></div>',
        1,
    )
    html = html.replace("</style>", _RV_STYLE + "\n</style>", 1)
    html = html.replace("</body>", "<script>\n" + _RV_SCRIPT + "\n</script>\n</body>", 1)
    return html
