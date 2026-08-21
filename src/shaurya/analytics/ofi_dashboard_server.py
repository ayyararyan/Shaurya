# ruff: noqa: E501
"""Read-only HTTP and HTML surface for ANL-06.

Only GET and HEAD are implemented.  The dashboard has no input control that mutates model state;
the sole browser preference is the visual theme persisted in ``localStorage``.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from shaurya.analytics.ofi_dashboard import OfiDashboardEngine
from shaurya.data.tape import CompleteLineJsonlTail

ALLOWED_METHODS = ("GET", "HEAD")
MATRIX_LOOKBACKS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
MATRIX_HORIZONS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _compact_leader(leader: Any) -> dict[str, Any] | None:
    leader_map = _mapping(leader)
    if not leader_map:
        return None
    accumulated = _mapping(leader_map.get("accumulated"))
    return {
        "model": leader_map.get("model"),
        "h1_seconds": leader_map.get("h1_seconds"),
        "h2_seconds": leader_map.get("h2_seconds"),
        "accumulated": (
            {
                key: accumulated.get(key)
                for key in (
                    "future_incremental_oos_r2_over_m0",
                    "future_raw_oos_r2",
                    "placebo_benchmarked_increment",
                    "past_incremental_oos_r2_over_m0",
                )
            }
            if accumulated
            else None
        ),
    }


def _compact_live_studies(live: Any) -> dict[str, Any]:
    live_map = _mapping(live)
    if not live_map:
        return {"status": "unavailable"}
    source = _mapping(live_map.get("source"))
    d38 = _mapping(live_map.get("d38"))
    touch_01 = _mapping(d38.get("touch_01_print_locations"))
    touch_02 = _mapping(d38.get("touch_02_effective_touch"))
    d39 = _mapping(live_map.get("d39"))
    d39_cells = _sequence(d39.get("cells"))
    primary_d39 = [
        cell
        for cell in d39_cells
        if isinstance(cell, dict)
        and cell.get("reference_price") == "displayed_mid"
        and cell.get("levels") == 10
    ]
    d40 = _mapping(live_map.get("d40"))
    return {
        "status": live_map.get("status"),
        "current_stage": live_map.get("current_stage"),
        "cycle": live_map.get("cycle"),
        "updated_at": live_map.get("updated_at"),
        "last_error": live_map.get("last_error"),
        "confirmatory_eligible": live_map.get("confirmatory_eligible", False),
        "successive_prefixes_independent": live_map.get(
            "successive_prefixes_independent", False
        ),
        "source": {
            key: source.get(key)
            for key in (
                "dataset_id",
                "last_receive_ts",
                "snapshot_at",
                "observations",
                "channel_rows",
                "sample_role",
            )
        },
        "d38": {
            "status": d38.get("status"),
            "updated_at": d38.get("updated_at"),
            "overall": touch_01.get("overall"),
            "displayed_spread_ticks": touch_01.get("displayed_spread_ticks"),
            "effective_touch_by_window": touch_02.get("by_window", []),
            "primary_window_seconds": touch_02.get("primary_window_seconds"),
        },
        "d39": {
            "status": d39.get("status"),
            "completed_cells": d39.get("completed_cells", 0),
            "total_cells": d39.get("total_cells", 600),
            "primary_displayed_mid_m10": primary_d39,
        },
        "d40": {
            "status": d40.get("status"),
            "completed_cells": d40.get("completed_cells", 0),
            "total_cells": d40.get("total_cells", 7),
            "rows": d40.get("rows", []),
            "curve": d40.get("curve", {}),
        },
    }


def _compact_rolling_c8(rolling: Any) -> dict[str, Any]:
    value = _mapping(rolling)
    if not value:
        return {"status": "not_configured", "cells": []}
    return {
        key: value.get(key)
        for key in (
            "status",
            "started_at",
            "updated_at",
            "training_window_seconds",
            "forecast_cadence_seconds",
            "causal_gap_seconds",
            "model",
            "reference_price",
            "levels",
            "source",
            "last_forecast_anchor_ts_ns",
            "pending_count",
            "cells",
            "metric_definition",
            "confirmatory_eligible",
        )
    }


def _matrix_view(rolling: dict[str, Any]) -> dict[str, Any]:
    values: dict[tuple[float, float], dict[str, Any]] = {}
    for raw in _sequence(rolling.get("cells")):
        row = _mapping(raw)
        h1 = row.get("lookback_seconds")
        h2 = row.get("horizon_seconds")
        score = row.get("cumulative_oos_r2")
        if h1 is None or h2 is None:
            continue
        values[(float(h1), float(h2))] = {
            "h1_seconds": float(h1),
            "h2_seconds": float(h2),
            "cumulative_oos_r2": score,
            "rolling_mean_win_score_5m": row.get("rolling_mean_win_score_5m"),
            "rolling_win_score_n_5m": row.get("rolling_win_score_n_5m", 0),
            "rolling_wins_5m": row.get("rolling_wins_5m", 0),
            "rolling_neutral_5m": row.get("rolling_neutral_5m", 0),
            "rolling_losses_5m": row.get("rolling_losses_5m", 0),
            "scored_n": row.get("scored_n", 0),
            "forecasts_issued": row.get("forecasts_issued", 0),
            "source": "rolling_c8_30m",
        }
    return {
        "h1_seconds": list(MATRIX_LOOKBACKS_SECONDS),
        "h2_seconds": list(MATRIX_HORIZONS_SECONDS),
        "cells": [values[key] for key in sorted(values)],
    }


def compact_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the decision-view payload used by the browser's polling loop.

    The full research state remains available at ``/api/state`` and ``/api/cells``.  The default
    screen intentionally carries only the objects needed to answer the owner's current question.
    """

    config = _mapping(payload.get("config"))
    live_studies = _compact_live_studies(payload.get("live_studies"))
    rolling_c8 = _compact_rolling_c8(payload.get("rolling_c8"))
    return {
        "schema_version": payload.get("schema_version"),
        "drive_mode": payload.get("drive_mode"),
        "tape_identity": payload.get("tape_identity"),
        "run_id": payload.get("run_id"),
        "history_length": payload.get("history_length"),
        "status_rail": payload.get("status_rail", {}),
        "honesty": payload.get("honesty", {}),
        "leader": _compact_leader(payload.get("leader")),
        "axes": payload.get("axes", {}),
        "config": {"refit_cadence_seconds": config.get("refit_cadence_seconds")},
        "live_studies": live_studies,
        "rolling_c8": rolling_c8,
        "matrix": _matrix_view(rolling_c8),
        "confirmatory_eligible": payload.get("confirmatory_eligible", False),
        "read_only": payload.get("read_only", True),
        "no_socket": payload.get("no_socket", True),
        "no_order_path": payload.get("no_order_path", True),
    }


class OfiDashboardState:
    def __init__(
        self,
        engine: OfiDashboardEngine,
        tail: CompleteLineJsonlTail,
        *,
        live_studies_path: Path | None = None,
        rolling_c8_path: Path | None = None,
    ) -> None:
        self.engine = engine
        self.tail = tail
        self.live_studies_path = live_studies_path
        self.rolling_c8_path = rolling_c8_path
        self._lock = threading.RLock()
        self._cached_payload = self._engine_payload()
        self._cached_cells = self.engine.cells_payload()

    def _engine_payload(self) -> dict[str, Any]:
        return self.engine.payload(
            rows_parsed=self.tail.rows_parsed,
            torn_lines=self.tail.torn_lines,
            trailing_partial_bytes=self.tail.trailing_partial_bytes,
            malformed_lines=self.tail.malformed_lines,
        )

    def live_studies(self) -> dict[str, Any]:
        if self.live_studies_path is None:
            return {"status": "not_configured"}
        try:
            loaded: Any = json.loads(self.live_studies_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"status": "waiting_for_worker", "path": str(self.live_studies_path)}
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "unavailable",
                "path": str(self.live_studies_path),
                "error": type(exc).__name__,
            }
        if not isinstance(loaded, dict):
            return {"status": "unavailable", "error": "state_is_not_an_object"}
        return loaded

    def rolling_c8(self) -> dict[str, Any]:
        if self.rolling_c8_path is None:
            return {"status": "not_configured"}
        try:
            loaded: Any = json.loads(self.rolling_c8_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"status": "waiting_for_worker", "path": str(self.rolling_c8_path)}
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "unavailable",
                "path": str(self.rolling_c8_path),
                "error": type(exc).__name__,
            }
        return loaded if isinstance(loaded, dict) else {"status": "unavailable"}

    def payload(self) -> dict[str, Any]:
        with self._lock:
            # A full 225-cell refit holds the engine lock for minutes. Serving the last complete
            # immutable frame keeps observability live while the estimator is busy; the sidecar
            # state is still re-read on every request.
            if not self.engine.fit_in_progress:
                self._cached_payload = self._engine_payload()
            value = dict(self._cached_payload)
            status_rail = dict(value.get("status_rail") or {})
            status_rail["refit_in_progress"] = self.engine.fit_in_progress
            value["status_rail"] = status_rail
            value["live_studies"] = self.live_studies()
            value["rolling_c8"] = self.rolling_c8()
            return value

    def history(self, index: int) -> dict[str, Any]:
        with self._lock:
            return self.engine.history_payload(index)

    def cells(self) -> dict[str, Any]:
        with self._lock:
            if not self.engine.fit_in_progress:
                self._cached_cells = self.engine.cells_payload()
            value = dict(self._cached_cells)
            value["refit_in_progress"] = self.engine.fit_in_progress
            return value

    def overview(self) -> dict[str, Any]:
        return compact_dashboard_payload(self.payload())

    def html(self) -> str:
        return render_html(self.payload())


_STYLE = """
:root {
  --ink:#1d1f22; --ink2:#575a5f; --ink3:#8b8d90; --rule:#dcd8ce;
  --bg:#f4f2ec; --panel:#faf8f2; --wash:#eeeadf; --slate:#46586b; --brass:#b5851f;
  --brick:#8f3327; --sage:#5b7a52; color-scheme:light;
}
:root[data-theme="dark"] {
  --ink:#e6e2d8; --ink2:#a4a29a; --ink3:#76746e; --rule:#2d3137;
  --bg:#17191c; --panel:#1c1f23; --wash:#202328; --slate:#8199b0; --brass:#d3a44a;
  --brick:#c05c46; --sage:#8faa7c; color-scheme:dark;
}
* { box-sizing:border-box; }
html,body { margin:0; min-height:100%; background:var(--bg); color:var(--ink);
  font-family:ui-monospace,SFMono-Regular,"SF Mono","JetBrains Mono","IBM Plex Mono",
  Menlo,Consolas,"Liberation Mono",monospace; font-size:12px; line-height:1.45;
  font-variant-numeric:tabular-nums; }
header { display:flex; gap:14px; align-items:center; padding:11px 18px 10px;
  border-bottom:1px solid var(--rule); background:var(--bg); }
h1 { margin:0; font-size:12.5px; letter-spacing:.06em; }
.spacer { flex:1; }
.stamp { color:var(--ink3); font-size:9px; letter-spacing:.15em; text-transform:uppercase; }
.stamp strong { color:var(--brass); }
button { font:inherit; font-size:9px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink2); background:none; border:1px solid var(--rule); padding:4px 9px; cursor:pointer; }
.matrix-page { max-width:980px; margin:44px auto; padding:0 22px; }
.matrix-title { margin:0; font-size:24px; letter-spacing:-.025em; }
.matrix-subtitle { margin:7px 0 22px; color:var(--ink2); font-size:13px; }
.matrix-status { display:flex; flex-wrap:wrap; gap:7px 18px; padding:9px 0;
  border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); color:var(--ink2); }
.matrix-wrap { overflow:auto; margin-top:20px; }
.result-matrix { width:100%; min-width:720px; border-collapse:collapse; table-layout:fixed;
  background:var(--panel); font-size:14px; }
.result-matrix th,.result-matrix td { border:1px solid var(--rule); padding:15px 12px; text-align:center; }
.result-matrix thead th { background:var(--wash); font-size:15px; }
.result-matrix tbody th { background:var(--wash); text-align:left; font-size:15px; }
.result-matrix .corner { width:190px; text-align:left; vertical-align:bottom; }
.result-matrix .corner span,.result-matrix .corner strong { display:block; }
.result-matrix .corner span { color:var(--ink2); font-size:10px; letter-spacing:.09em; text-transform:uppercase; }
.result-matrix .corner strong { margin-top:11px; font-weight:600; }
.result-matrix td.positive { color:var(--sage); background:color-mix(in srgb,var(--sage) 8%,var(--panel)); }
.result-matrix td.negative { color:var(--brick); background:color-mix(in srgb,var(--brick) 7%,var(--panel)); }
.result-matrix td.missing { color:var(--ink3); }
.result-matrix td .accuracy { display:block; margin-top:3px; color:var(--ink2); font-size:10px; }
.matrix-note { margin-top:12px; color:var(--ink3); font-size:11px; }
@media(max-width:620px) {
  header .stamp { display:none; }
  .matrix-page { margin-top:24px; padding:0 10px; }
  .matrix-title { font-size:20px; }
}
"""
_SCRIPT = r"""
const LOOKBACKS=[0.5,1,2,5,10],HORIZONS=[0.5,1,2,5,10,20];
let lastPayload=__PAYLOAD__;
function themeName(){return document.documentElement.dataset.theme==='dark'?'dark':'light';}
function applyTheme(name){
  document.documentElement.dataset.theme=name;
  try{localStorage.setItem('anl06-theme',name);}catch(error){}
  document.getElementById('themeToggle').textContent=name==='dark'?'\u25D1 LIGHT':'\u25D0 DARK';
}
function initTheme(){
  let name=null; try{name=localStorage.getItem('anl06-theme');}catch(error){}
  if(name!=='light'&&name!=='dark') name=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  applyTheme(name);
}
function toggleTheme(){applyTheme(themeName()==='dark'?'light':'dark');}
function pct(value){return value===null||value===undefined?'\u2014':(Number(value)*100).toFixed(2)+'%';}
function clock(ts){
  if(!ts) return '\u2014'; const date=new Date(ts); if(Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+' IST';
}
function matrixValues(payload){
  const values=new Map();
  ((payload.matrix||{}).cells||[]).forEach(row=>values.set(Number(row.h1_seconds)+'|'+Number(row.h2_seconds),{
    value:row.cumulative_oos_r2,score:row.rolling_mean_win_score_5m,
    scoreN:row.rolling_win_score_n_5m,wins:row.rolling_wins_5m,
    neutral:row.rolling_neutral_5m,losses:row.rolling_losses_5m,
    scored:row.scored_n,issued:row.forecasts_issued,source:row.source}));
  return values;
}
function render(payload){
  lastPayload=payload; const rolling=payload.rolling_c8||{},source=rolling.source||{};
  const values=matrixValues(payload);
  document.getElementById('status').innerHTML=[
    'Source through <b>'+clock(source.last_receive_ts)+'</b>',
    'Training window <b>past 30 min</b>',
    'Forecast every <b>'+(rolling.forecast_cadence_seconds||5)+'s</b>',
    'Pending outcomes <b>'+(rolling.pending_count||0)+'</b>',
    '<b>Live walk-forward</b>'
  ].map(item=>'<span>'+item+'</span>').join('');
  const head='<tr><th class="corner"><span>Sampling / lookback horizon \u2192</span><strong>Predicted horizon \u2193</strong></th>'+
    LOOKBACKS.map(h=>'<th>'+h+'s</th>').join('')+'</tr>';
  const body=HORIZONS.map(h2=>'<tr><th>'+h2+'s</th>'+LOOKBACKS.map(h1=>{
    const cell=values.get(h1+'|'+h2); if(!cell||cell.value===null||cell.value===undefined)
      return '<td class="missing" title="Waiting for matured live forecasts">\u2014</td>';
    const value=Number(cell.value); const cls=value>=0?'positive':'negative';
    const score=cell.score===null||cell.score===undefined?'\u2014':Number(cell.score).toFixed(2);
    return '<td class="'+cls+'" title="Cumulative OOS R-squared · n='+cell.scored+
      ' · 5m points +1/0/-1='+cell.wins+'/'+cell.neutral+'/'+cell.losses+'">'+pct(value)+
      '<span class="accuracy">5m score '+score+' · n='+cell.scoreN+'</span></td>';
  }).join('')+'</tr>').join('');
  document.getElementById('matrix').innerHTML='<thead>'+head+'</thead><tbody>'+body+'</tbody>';
  document.getElementById('source').textContent=String(payload.drive_mode||'').toUpperCase()+' \u00B7 '+payload.history_length+' REFITS';
}
async function refresh(){try{const response=await fetch('/api/overview');render(await response.json());}
  catch(error){document.getElementById('source').textContent='SERVER UNREACHABLE';}}
initTheme();render(lastPayload);setInterval(refresh,5000);
"""


_BODY = """<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Shaurya OFI — rolling OOS R² table</title><style>__STYLE__</style></head>
<body><header><h1>SHAURYA OFI / ROLLING OOS R²</h1>
<span class="stamp"><strong>READ-ONLY</strong> · EXPLORATORY · NOT A SIGNAL · NO SOCKET · NO ORDER PATH</span>
<span class="spacer"></span><span class="stamp" id="source"></span>
<button id="themeToggle" type="button" onclick="toggleTheme()">◐ DARK</button></header>
<main class="matrix-page"><h2 class="matrix-title">CCZ OFI (C8) · displayed mid · 10 book levels</h2>
<p class="matrix-subtitle">Each forecast refits C8 on only the preceding 30 minutes. Cells accumulate OOS R² as those live future outcomes become observable.</p>
<div id="status" class="matrix-status"></div><div class="matrix-wrap">
<table id="matrix" class="result-matrix" aria-label="CCZ OFI absolute out-of-sample R-squared by sampling and predicted horizon"></table></div>
<p class="matrix-note"><b>5m score:</b> +1 when the realised move reaches the forecast magnitude in its direction; −1 when it reaches that magnitude in the opposite direction; 0 otherwise. The displayed score is the trailing-five-minute mean. R² remains cumulative from corrected-worker launch.</p></main>
<script>__SCRIPT__</script></body></html>"""


def render_html(payload: dict[str, Any]) -> str:
    payload = compact_dashboard_payload(payload)
    payload_json = json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")
    return (
        _BODY.replace("__STYLE__", _STYLE)
        .replace("__PAYLOAD__", payload_json)
        .replace("__SCRIPT__", _SCRIPT.replace("__PAYLOAD__", payload_json))
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "ShauryaANL06/1.0"
    state: OfiDashboardState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(self.state.html().encode(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            self._send(json.dumps(self.state.payload()).encode(), "application/json")
            return
        if parsed.path == "/api/overview":
            self._send(json.dumps(self.state.overview()).encode(), "application/json")
            return
        if parsed.path == "/api/cells":
            self._send(json.dumps(self.state.cells()).encode(), "application/json")
            return
        if parsed.path == "/api/live-studies":
            self._send(json.dumps(self.state.live_studies()).encode(), "application/json")
            return
        if parsed.path == "/api/rolling-c8":
            self._send(json.dumps(self.state.rolling_c8()).encode(), "application/json")
            return
        if parsed.path == "/api/history":
            raw = parse_qs(parsed.query).get("index", ["0"])[0]
            try:
                index = int(raw)
            except ValueError:
                self._send(b'{"error":"index must be an integer"}', "application/json", 400)
                return
            try:
                body = json.dumps(self.state.history(index)).encode()
            except IndexError:
                self._send(b'{"error":"no refits recorded"}', "application/json", 404)
                return
            self._send(body, "application/json")
            return
        self._send(b'{"error":"not found"}', "application/json", 404)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()


def build_server(
    state: OfiDashboardState, *, host: str = "127.0.0.1", port: int = 8776
) -> ThreadingHTTPServer:
    handler = type("_BoundOfiHandler", (_Handler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler)


def serve_in_background(
    state: OfiDashboardState, *, host: str = "127.0.0.1", port: int = 8776
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = build_server(state, host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, name="anl06-dashboard", daemon=True)
    thread.start()
    return server, thread
