# ruff: noqa: E501
"""Read-only HTTP and HTML surface for ANL-06.

Only GET and HEAD are implemented.  The dashboard has no input control that mutates model state;
the sole browser preference is the visual theme persisted in ``localStorage``.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from shaurya.analytics.ofi_dashboard import CompleteLineJsonlTail, OfiDashboardEngine

ALLOWED_METHODS = ("GET", "HEAD")


class OfiDashboardState:
    def __init__(self, engine: OfiDashboardEngine, tail: CompleteLineJsonlTail) -> None:
        self.engine = engine
        self.tail = tail
        self._lock = threading.RLock()

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return self.engine.payload(
                rows_parsed=self.tail.rows_parsed,
                torn_lines=self.tail.torn_lines,
                trailing_partial_bytes=self.tail.trailing_partial_bytes,
                malformed_lines=self.tail.malformed_lines,
            )

    def history(self, index: int) -> dict[str, Any]:
        with self._lock:
            return self.engine.history_payload(index)

    def cells(self) -> dict[str, Any]:
        with self._lock:
            return self.engine.cells_payload()

    def html(self) -> str:
        return render_html(self.payload())


_STYLE = """
:root {
  --ink:#1d1f22; --ink2:#575a5f; --ink3:#8b8d90; --rule:#dcd8ce;
  --rule2:#e8e4da; --bg:#f4f2ec; --panel:#faf8f2; --slate:#46586b;
  --brass:#b5851f; --brick:#8f3327; --sage:#5b7a52; color-scheme:light;
}
:root[data-theme="dark"] {
  --ink:#e6e2d8; --ink2:#a4a29a; --ink3:#76746e; --rule:#2d3137;
  --rule2:#24272b; --bg:#17191c; --panel:#1c1f23; --slate:#8199b0;
  --brass:#d3a44a; --brick:#c05c46; --sage:#8faa7c; color-scheme:dark;
}
* { box-sizing:border-box; }
html,body { margin:0; min-height:100%; background:var(--bg); color:var(--ink);
  font-family:ui-monospace,SFMono-Regular,"SF Mono","JetBrains Mono","IBM Plex Mono",
  Menlo,Consolas,"Liberation Mono",monospace; font-size:12px; line-height:1.45;
  font-variant-numeric:tabular-nums; }
header { display:flex; gap:14px; align-items:center; padding:11px 18px 10px;
  border-bottom:1px solid var(--rule); position:sticky; top:0; background:var(--bg); z-index:5; }
h1 { margin:0; font-size:12.5px; letter-spacing:.06em; }
.spacer { flex:1; }
.stamp,.eyebrow { color:var(--ink3); font-size:9px; letter-spacing:.15em;
  text-transform:uppercase; }
.stamp strong { color:var(--brass); }
button { font:inherit; font-size:9px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink2); background:none; border:1px solid var(--rule); padding:4px 9px; cursor:pointer; }
.rail { display:flex; flex-wrap:wrap; border-bottom:1px solid var(--rule);
  border-left:3px solid var(--slate); padding:8px 18px 9px; }
.rail.stale { border-left-color:var(--brass); }
.rail-cell { min-width:110px; padding:0 15px; border-left:1px solid var(--rule2); }
.rail-cell:first-child { border-left:0; padding-left:0; }
.label { color:var(--ink3); font-size:8.5px; letter-spacing:.14em; text-transform:uppercase; }
.value { color:var(--ink); font-size:14px; white-space:nowrap; }
.hero { display:grid; grid-template-columns:minmax(330px,1.3fr) repeat(3,minmax(150px,.55fr));
  border-bottom:1px solid var(--rule); }
.hero > div { padding:15px 18px; border-left:1px solid var(--rule2); }
.hero > div:first-child { border-left:3px solid var(--slate); }
.hero-main { font-size:43px; line-height:1; letter-spacing:-.035em; margin:5px 0 7px; }
.hero-main em { font-size:15px; font-style:normal; color:var(--ink3); }
.hero-id { color:var(--ink2); font-size:13px; }
.hero-stat b { display:block; font-size:25px; font-weight:400; margin-top:7px; }
.hero-stat small { display:block; color:var(--ink3); margin-top:5px; }
.honesty { display:grid; grid-template-columns:repeat(5,1fr); border-bottom:1px solid var(--rule); }
.honesty > div { padding:11px 18px; border-left:1px solid var(--rule2); }
.honesty > div:first-child { border-left:3px solid var(--brass); }
.honesty b { display:block; font-size:20px; font-weight:400; }
.honesty small { color:var(--ink3); }
main { padding:17px 18px 36px; }
.section-head { display:flex; align-items:center; gap:10px; margin:15px 0 9px; }
.section-head h2 { margin:0; color:var(--ink3); font-size:9.5px; letter-spacing:.17em;
  text-transform:uppercase; white-space:nowrap; }
.section-head:after { content:""; height:1px; background:var(--rule); flex:1; }
.models { display:grid; grid-template-columns:repeat(2,minmax(470px,1fr)); gap:18px; }
.model { min-width:0; }
.model-title { display:flex; align-items:baseline; gap:9px; margin:0 0 6px; }
.model-title b { font-size:15px; }
.model-title span { color:var(--ink3); font-size:9px; letter-spacing:.1em; text-transform:uppercase; }
.heatmap { display:grid; grid-template-columns:50px repeat(5,minmax(72px,1fr));
  border-top:1px solid var(--rule); border-left:1px solid var(--rule); }
.axis,.cell { min-height:68px; padding:6px; border-right:1px solid var(--rule);
  border-bottom:1px solid var(--rule); }
.axis { display:flex; align-items:center; justify-content:center; color:var(--ink3);
  font-size:8px; letter-spacing:.1em; text-transform:uppercase; min-height:25px; }
.cell { background:color-mix(in srgb,var(--slate) calc(var(--mag)*32%),transparent);
  position:relative; }
.cell.brick { background:color-mix(in srgb,var(--brick) 34%,transparent);
  box-shadow:inset 3px 0 0 var(--brick); }
.cell.warming { background:transparent; color:var(--brass); }
.cell.insufficient,.cell.blocked { background:transparent; color:var(--ink3); }
.cell .score { font-size:14px; line-height:1.15; }
.cell .bench { font-size:12px; margin-top:3px; }
.cell .block { color:var(--ink3); font-size:8.5px; margin-top:4px; white-space:nowrap; }
.cell .q { position:absolute; right:5px; top:4px; color:var(--ink3); font-size:8px; }
.glyph { margin-right:3px; }
.diagnostic { border-left:3px solid var(--brass); padding:9px 12px; color:var(--ink2);
  background:var(--panel); }
.legend { color:var(--ink3); font-size:9px; margin:7px 0 0; }
.brick-word { color:var(--brick); }.sage-word { color:var(--sage); }
@media(max-width:1150px) { .models{grid-template-columns:1fr}.hero{grid-template-columns:1fr 1fr}
  .honesty{grid-template-columns:1fr 1fr}.hero>div:first-child{grid-column:1/-1} }
"""


_SCRIPT = r"""
const fmt = (x,d=3) => x === null || x === undefined || Number.isNaN(Number(x))
  ? '\u2014' : Number(x).toFixed(d);
const pct = (x,d=2) => x === null || x === undefined ? '\u2014' : (Number(x)*100).toFixed(d);
let lastPayload = __PAYLOAD__;

function themeName(){ return document.documentElement.dataset.theme === 'dark' ? 'dark':'light'; }
function applyTheme(name){
  document.documentElement.dataset.theme=name;
  try{localStorage.setItem('anl06-theme',name);}catch(error){}
  const button=document.getElementById('themeToggle');
  button.textContent=name==='dark'?'\u25D1 LIGHT':'\u25D0 DARK';
}
function initTheme(){
  let name=null; try{name=localStorage.getItem('anl06-theme');}catch(error){}
  if(name!=='light'&&name!=='dark') name=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  applyTheme(name);
}
function toggleTheme(){applyTheme(themeName()==='dark'?'light':'dark');}

function rail(payload){
  const r=payload.status_rail;
  const stale=r.fit_age_seconds!==null && r.fit_age_seconds>payload.config.refit_cadence_seconds*2;
  const values=[['mode',payload.drive_mode],['tape',payload.tape_identity.split('/').pop()],
    ['run id',payload.run_id],['anchors',r.anchors_consumed],['rows',r.rows_parsed],
    ['torn / partial',r.torn_lines+' / '+r.trailing_partial_bytes+' B'],
    ['malformed',r.malformed_lines],['epoch',r.current_epoch],['fit age',fmt(r.fit_age_seconds,1)+' s'],
    ['refits done / skipped',r.refits_completed+' / '+r.refits_skipped],
    ['warming / insufficient',r.warming_cells+' / '+r.insufficient_cells],
    ['last refit',r.last_completed_refit_wall_clock? r.last_completed_refit_wall_clock.slice(11,19)+' UTC':'NEVER']];
  const holder=document.getElementById('rail'); holder.className='rail'+(stale?' stale':'');
  holder.innerHTML=values.map(([k,v])=>'<div class="rail-cell"><div class="label">'+k+
    '</div><div class="value">'+(v??'\u2014')+'</div></div>').join('');
}
function hero(payload){
  const cell=payload.leader; const holder=document.getElementById('hero');
  if(!cell || !cell.accumulated){
    holder.innerHTML='<div><div class="eyebrow">authoritative accumulated leader</div>'+
      '<div class="hero-main">WARMING</div><div class="hero-id">No cell is ranked before the gate.</div></div>'+
      '<div class="hero-stat"><span class="label">chance expectation</span><b>'+payload.honesty.expected_by_chance_at_5pct+
      '</b><small>of 175 at 5%</small></div>'; return;
  }
  const a=cell.accumulated;
  holder.innerHTML='<div><div class="eyebrow">authoritative accumulated placebo-benchmarked increment</div>'+
    '<div class="hero-main">'+(Number(a.placebo_benchmarked_increment)>=0?'\u25B2 ':'\u25BC ')+
    pct(a.placebo_benchmarked_increment)+'<em> pp</em></div><div class="hero-id">'+cell.model+
    ' \u00B7 h1 '+cell.h1_seconds+' s \u00B7 h2 '+cell.h2_seconds+
    ' s \u00B7 deterministically derived from two estimated increments</div></div>'+
    '<div class="hero-stat"><span class="label">raw OOS R\u00B2</span><b>'+pct(a.future_raw_oos_r2)+
    '%</b><small>estimated \u00B7 accumulated</small></div>'+
    '<div class="hero-stat"><span class="label">raw future increment</span><b>'+pct(a.future_incremental_oos_r2_over_m0)+
    ' pp</b><small>estimated \u00B7 versus M0</small></div>'+
    '<div class="hero-stat"><span class="label">past-mirror increment</span><b>'+pct(a.past_incremental_oos_r2_over_m0)+
    ' pp</b><small>estimated benchmark \u00B7 chance '+payload.honesty.expected_by_chance_at_5pct+'/175</small></div>';
}
function honesty(payload){
  const h=payload.honesty;
  document.getElementById('honesty').innerHTML=[
    ['green now',h.cells_green_now,'estimated \u00B7 p \u2264 5%, future beats mirror'],
    ['expected by chance',fmt(h.expected_by_chance_at_5pct,2),'deterministically derived \u00B7 175 cells'],
    ['BH-FDR positive',h.bh_fdr_positive_5pct,'estimated \u00B7 dependence-aware q \u2264 5%'],
    ['ever green',h.cells_ever_green,'deterministically derived churn record'],
    ['distinct leaders',h.distinct_cells_that_have_led,'derived \u00B7 current '+(h.current_leader||'\u2014')]
  ].map(([k,v,s])=>'<div><span class="label">'+k+'</span><b>'+v+'</b><small>'+s+'</small></div>').join('');
}
function cellHtml(cell){
  const cls=cell.status==='ESTIMATED'?(cell.past_mirror_exceeds_or_equals_future?'brick':''):
    (cell.status==='WARMING'?'warming':cell.status==='INSUFFICIENT'?'insufficient':'blocked');
  if(cell.status!=='ESTIMATED') return '<div class="cell '+cls+'" style="--mag:0" title="'+cell.reason+'">'+
    '<div class="score">'+cell.status+'</div><div class="block">train '+cell.support.common_train_n+
    ' \u00B7 test '+cell.support.common_test_n+'</div></div>';
  const a=cell.accumulated,b=cell.block; const sign=Number(a.placebo_benchmarked_increment)>=0?'\u25B2':'\u25BC';
  const mag=Math.min(1,Math.abs(Number(a.placebo_benchmarked_increment))*12);
  const title='future increment '+pct(a.future_incremental_oos_r2_over_m0)+' pp; past mirror '+
    pct(a.past_incremental_oos_r2_over_m0)+' pp; '+cell.coefficient_interpretation;
  return '<div class="cell '+cls+'" style="--mag:'+mag+'" title="'+title+'">'+
    '<div class="q">q EST '+pct(cell.bh_fdr_q_value,1)+'</div><div class="score">EST R\u00B2 '+
    pct(a.future_raw_oos_r2)+'%</div><div class="bench"><span class="glyph">'+sign+'</span>\u0394bench '+
    pct(a.placebo_benchmarked_increment)+' pp DERIVED</div><div class="block">BLOCK EST R\u00B2 '+
    pct(b.future_raw_oos_r2)+'% \u00B7 \u0394 '+pct(b.placebo_benchmarked_increment)+' pp</div></div>';
}
function grids(payload){
  const hs=payload.axes.h1_seconds, horizons=payload.axes.h2_seconds;
  const lookup=new Map(payload.cells.map(c=>[c.cell_key,c]));
  document.getElementById('models').innerHTML=payload.axes.models.map(model=>{
    let grid='<div class="axis">h1 \\ h2</div>'+horizons.map(h=>'<div class="axis">'+h+' s</div>').join('');
    hs.forEach(h1=>{ grid+='<div class="axis">'+h1+' s</div>';
      horizons.forEach(h2=>{grid+=cellHtml(lookup.get(model+'|'+h1+'|'+h2));}); });
    return '<section class="model"><div class="model-title"><b>'+model+'</b><span>5 \u00D7 5 complete grid</span></div>'+
      '<div class="heatmap">'+grid+'</div></section>';
  }).join('');
}
function render(payload){lastPayload=payload;rail(payload);hero(payload);honesty(payload);grids(payload);
  document.getElementById('source').textContent=payload.drive_mode.toUpperCase()+' \u00B7 '+payload.history_length+' REFITS';}
async function refresh(){try{const response=await fetch('/api/state');render(await response.json());}
  catch(error){document.getElementById('source').textContent='SERVER UNREACHABLE';}}
initTheme();render(lastPayload);setInterval(refresh,1000);
"""


_BODY = """<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Shaurya ANL-06 — dynamic OFI horse race</title><style>__STYLE__</style></head>
<body><header><h1>SHAURYA ANL-06 / DYNAMIC OFI HORSE RACE</h1>
<span class="stamp"><strong>READ-ONLY</strong> · EXPLORATORY · NOT A SIGNAL · NO SOCKET · NO ORDER PATH</span>
<span class="spacer"></span><span class="stamp" id="source"></span>
<button id="themeToggle" type="button" onclick="toggleTheme()">◐ DARK</button></header>
<div id="rail" class="rail"></div><section id="hero" class="hero"></section>
<section id="honesty" class="honesty"></section><main>
<div class="section-head"><h2>ACCUMULATED WALK-FORWARD GRID · RAW OOS R² + PLACEBO-BENCHMARKED INCREMENT ALWAYS VISIBLE</h2></div>
<div id="models" class="models"></div>
<p class="legend"><span class="brick-word">BRICK</span> is reserved for past-mirror increment ≥ future increment.
Magnitude otherwise uses a single-hue slate ramp. Sign is always a glyph and signed number. WARMING,
INSUFFICIENT, BLOCKED and negative cells remain visible. q is the BH-FDR adjusted dependence-aware view.</p>
<div class="section-head"><h2>SAME-WINDOW CONSTRUCTION DIAGNOSTIC · STRUCTURALLY SEPARATED</h2></div>
<div class="diagnostic">Contemporaneous fits are construction diagnostics only. They are never ranked,
never enter the leader, and never change the 175-cell future family.</div></main>
<script>__SCRIPT__</script></body></html>"""


def render_html(payload: dict[str, Any]) -> str:
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
        if parsed.path == "/api/cells":
            self._send(json.dumps(self.state.cells()).encode(), "application/json")
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
