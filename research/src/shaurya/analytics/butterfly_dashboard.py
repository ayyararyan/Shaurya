# ruff: noqa: E501
# Embedded HTML/JavaScript lines retain their own formatting.
"""Forecast-first BFLY dashboard presentation; no calculation or trading in JavaScript."""

from __future__ import annotations

STYLE = """
.bfly { margin:8px 24px 20px; padding:20px; background:var(--panel);
  border:1px solid var(--rule); border-radius:10px; }
.bfly h2 { font-size:18px; margin:0 0 8px; letter-spacing:0; }
.bfly p { color:var(--ink-2); font-size:12px; margin:8px 0; }
.bfly-tools { display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin:14px 0; }
.bfly label { font-size:12px; } .bfly select,.bfly input { font:inherit; font-size:12px;
 color:var(--ink); background:var(--bg); padding:7px; border:1px solid var(--rule);
 border-radius:4px; max-width:200px; }
.bfly-scroll { overflow:auto; max-width:100%; }
.bfly table { min-width:850px; } .bfly th { font-size:10px; }
.bfly td { font-size:12px; padding:9px 10px; } .bfly td:first-child { padding-left:0; }
.bfly .selected { background:var(--rule-soft); }
.bfly button { font-size:12px; letter-spacing:0; text-transform:none; padding:5px 9px; }
.bfly details { margin:14px 0 0; }
.bfly-detail { padding:0 16px 16px; }
.bfly .bad { color:var(--brick); } .bfly .good { color:var(--sage); }
.bfly small { display:block; color:var(--ink-2); margin-top:3px; }
.bfly-metrics { display:flex; flex-wrap:wrap; gap:12px 24px; margin:12px 0; }
.bfly-metrics span { font-size:12px; } .bfly-metrics b { display:block; font-size:16px; }
@media(max-width:650px) { .bfly { margin:8px 16px; padding:14px; }
 .bfly-tools { gap:10px; } }
"""

PANEL = """
<section class="bfly" id="butterflyPanel" aria-label="Short iron butterfly carry">
<h2>Short iron butterflies</h2>
<p>400 / 500-point wings per side · one lot · hold through expiry · daily recentering check</p>
<p id="bflyStatus">Loading butterfly prices from the fitted surface…</p>
<div class="bfly-tools">
<label>Wings <select id="bflyWidth" onchange="renderButterflies(bflyPayload)">
<option value="all">400 &amp; 500 points</option><option value="400">400 each side</option>
<option value="500">500 each side</option></select></label>
<label>Rank by <select id="bflySort" onchange="renderButterflies(bflyPayload)">
<option value="risk">Net scenario carry / static risk</option>
<option value="carry">Net expiry scenario carry</option>
<option value="local">Local gamma–theta carry</option>
<option value="overnight">Next-open hold carry</option>
<option value="cost">Lowest estimated total costs</option></select></label>
<label><input type="checkbox" id="bflyAll" onchange="renderButterflies(bflyPayload)"> Show all</label>
</div>
<div class="bfly-scroll"><table>
<thead><tr><th>Centre / wings</th><th class="num">Entry credit</th>
<th class="num">Local carry / day</th><th class="num">Next-open · hold</th>
<th class="num">Expiry · recenter</th>
<th class="num">Expiry · hold</th><th class="num">5th percentile</th>
<th class="num">Est. total costs</th><th class="num">Carry / risk</th></tr></thead>
<tbody id="bflyRows"></tbody></table></div>
<p>₹ per lot. Expiry carry is a <b>conditional simulation mean</b>, not a guaranteed return.
Local carry is an approximation, not an expiry forecast. Click a centre for legs and risks.</p>
<details id="bflyDetails"><summary>Selected butterfly · legs, carry and risk</summary>
<div class="bfly-detail" id="bflyDetailBody"></div></details>
<details><summary>Recenter check · enter your current centre</summary><div class="bfly-detail">
<p>This is a what-if check, not a broker position. Check at 15:15 IST, at most once per trading day;
no recentering on expiry day. Recenter to the nearest 50-point strike when drift ≥ half-width.</p>
<div class="bfly-tools"><label>Held centre <input id="bflyHeldCenter" type="number" step="50"
placeholder="e.g. 24000" oninput="renderButterflyTracker()"></label>
<label>Wings <select id="bflyHeldWidth" onchange="renderButterflyTracker()">
<option value="400">400 each side</option><option value="500">500 each side</option>
</select></label></div><p id="bflyTracker"></p></div></details>
<details><summary>Model assumptions &amp; costs</summary><div class="bfly-detail">
<p>Short centre call + put; long lower put and upper call. Nearest-weekly NIFTY only.
400/500 means 800/1000 points total span. Centre candidates are within half a wing-width of the forward.</p>
<p>Current model prices and fixed-IV Greeks use eSSVI. Entry assumes buying asks, selling bids,
one extra adverse tick per leg, known lot sizes and displayed depth for at least one lot.
Quotes must be ≤3 seconds old. These are indicative simultaneous-leg prices, not guaranteed fills.</p>
<p>Paths: frozen RV, driftless lognormal forward, variance proportional to calendar time—including nights,
weekends and exchange holidays. 1,024 antithetic paths with a fixed seed. This is not a separately trained
overnight forecast. Future marks use <b>flat front ATM IV</b>, not a predicted future smile.
Scenario differences include RV ±20/25%, future IV ±20%, doubled friction, and first-overnight ±2% gaps.</p>
<p>At 15:15 on non-expiry trading days, recenter if |forward − centre| ≥200 points for 400 wings,
or ≥250 for 500 wings. Close all four legs and open the new same-width position.
Each recenter pays full estimated costs; no futures hedge, no look-ahead.</p>
<p>Costs: sell-premium STT 0.15%; long-exercise intrinsic STT 0.15%; exchange + IPFT 0.03553%;
SEBI 0.0001%; buy stamp 0.003%; GST 18% on exchange/SEBI/brokerage. Assume Kotak Trade API
₹0 brokerage. Manual ₹10/order sensitivity is shown separately. Future half-spreads use current
per-leg half-spreads (floor 0.05 points) plus a tick. No income tax or unidentified broker margin included.</p>
<p>Static maximum loss is before exercise tax and applies only to an unchanged butterfly—not repeated
recentering. A 5th percentile is not a worst-case bound. The ranking denominator is static risk, not
actual capital or broker margin. Monte Carlo error does not measure model error.</p>
<p>Sources: <a href="https://www.optionseducation.org/strategies/all-strategies/short-iron-butterfly">OIC legs/payoff</a> ·
<a href="https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax">NSE STT</a> ·
<a href="https://nsearchives.nseindia.com/content/circulars/FA73061.pdf">NSE exchange fees</a> ·
<a href="https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf">2026 holiday calendar</a> ·
<a href="https://www.kotakneo.com/pricing/">Kotak pricing</a></p>
</div></details>
</section>
"""

SCRIPT = r"""
let bflyPayload = lastPayload;
let bflySelected = null;
const bfNum = (x,d=0) => typeof x === 'number' && Number.isFinite(x)
  ? x.toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d}) : '—';
const bfMoney = x => '₹' + bfNum(x);
function renderButterflies(payload) {
  bflyPayload=payload;
  const b=(payload.snapshot || {}).butterflies || {};
  const historical=!document.getElementById('liveToggle').checked;
  const stale=(payload.health_verdict || {}).surface_is_stale;
  const feed=(payload.health_verdict || {}).status;
  const note=document.getElementById('bflyStatus');
  if (b.status !== 'ok') {
    note.className='bad';
    note.textContent='No eligible prices: '+(b.reason || 'waiting for a valid fit')+
      (b.rejected ? ' · '+Object.entries(b.rejected).map(([k,v])=>k.replaceAll('_',' ')+': '+v).join(' · ') : '');
    document.getElementById('bflyRows').innerHTML='';
    document.getElementById('bflyDetailBody').textContent='No eligible four-leg snapshot.';
    renderButterflyTracker(); return;
  }
  const qualifier=historical ? 'Historical snapshot' : stale || feed==='dead'
    ? 'STALE — not current executable prices' : 'Indicative prices';
  note.textContent=qualifier+' · '+b.expiry+' · '+b.candidates.length+' eligible · '+b.as_of;
  note.className=stale || feed==='dead' ? 'bad' : '';
  const width=document.getElementById('bflyWidth').value;
  const sort=document.getElementById('bflySort').value;
  const all=b.candidates.filter(x=>width==='all' || x.width===Number(width));
  const score=x=>sort==='carry' ? x.scenarios.base.recenter.mean : sort==='local'
    ? x.gamma_theta_day : sort==='overnight' ? x.scenarios.base.overnight.mean : sort==='cost' ? -x.scenarios.base.mean_total_cost : x.carry_risk_ratio;
  all.sort((a,c)=>score(c)-score(a));
  const shown=document.getElementById('bflyAll').checked ? all : all.slice(0,5);
  if(!all.some(x=>x.id===bflySelected)) bflySelected=all.length ? all[0].id : null;
  document.getElementById('bflyRows').innerHTML=shown.map(x=>{
    const s=x.scenarios.base;
    return '<tr class="'+(x.id===bflySelected ? 'selected' : '')+'"><td><button onclick="'+
      "selectButterfly('"+x.id+"')"+'">'+bfNum(x.center)+' / '+x.width+'</button></td>'+
      '<td class="num">'+bfMoney(x.credit_rupees)+'</td>'+
      '<td class="num">'+bfMoney(x.gamma_theta_day)+'</td>'+
      '<td class="num">'+bfMoney(s.overnight.mean)+'</td>'+
      '<td class="num">'+bfMoney(s.recenter.mean)+'<small>±'+bfNum(s.recenter.mc_se)+' MC SE</small></td>'+
      '<td class="num">'+bfMoney(s.hold.mean)+'</td>'+
      '<td class="num bad">'+bfMoney(s.recenter.p05)+'</td>'+
      '<td class="num">'+bfMoney(s.mean_total_cost)+'</td>'+
      '<td class="num">'+bfNum(x.carry_risk_ratio*100,1)+'%</td></tr>';
  }).join('') || '<tr><td colspan="9">No eligible butterflies for this width.</td></tr>';
  const selected=all.find(x=>x.id===bflySelected);
  renderButterflyDetail(selected,b);
  renderButterflyTracker();
}
function selectButterfly(id) {
  bflySelected=id; renderButterflies(bflyPayload);
  document.getElementById('bflyDetails').open=true;
}
function renderButterflyDetail(x,b) {
  const holder=document.getElementById('bflyDetailBody');
  if(!x) {holder.textContent='No eligible selection.'; return;}
  const s=x.scenarios.base,g=x.greeks_per_lot;
  holder.innerHTML='<p><b>'+bfNum(x.center)+' centre · '+x.width+' wings · '+x.lot_size+
    ' units per leg</b> · '+escapeHtml(x.signal_label.replaceAll('_',' '))+'</p>'+
    '<div class="bfly-metrics">'+
    '<span>Entry credit before costs<b>'+bfMoney(x.credit_rupees)+'</b></span>'+
    '<span>Entry spread + slip + fees<b>'+bfMoney(x.entry_cost_rupees)+'</b></span>'+
    '<span>Net initial credit<b>'+bfMoney(x.net_entry_credit_points*x.lot_size)+'</b></span>'+
    '<span>Static max loss, before exercise tax<b>'+bfMoney(x.static_max_loss_before_exercise_tax)+'</b></span>'+
    '<span>Next-open hold mark P&L, after close costs<b>'+bfMoney(s.overnight.mean)+'</b></span>'+
    '<span>Mean recenter count<b>'+bfNum(s.mean_recenters,2)+'</b></span>'+
    '<span>Base loss probability<b>'+bfNum(s.recenter.loss_probability*100,1)+'%</b></span>'+
    '<span>Mean of worst 5% of base paths<b>'+bfMoney(s.recenter.tail_mean)+'</b></span></div>'+
    '<p>Forward '+bfNum(x.forward,2)+' · net breakevens before exercise tax '+
      bfNum(x.breakeven_low_before_exercise_tax,1)+' / '+bfNum(x.breakeven_high_before_exercise_tax,1)+
      ' · displayed entry depth '+x.available_lots+' lots.</p>'+
    '<p>Model credit '+bfNum(x.model_credit_points,2)+' pts · market mid credit '+
      bfNum(x.mid_credit_points,2)+' pts · bid/ask credit '+bfNum(x.credit_points,2)+' pts.</p>'+
    '<p>Signed Greeks per lot: delta '+bfNum(g.delta,3)+' ₹/point · gamma '+bfNum(g.gamma,5)+
      ' ₹/point² · theta '+bfMoney(g.theta_day)+'/calendar day · vega '+bfMoney(g.vega_point)+
      '/IV point. Fixed-strike IV sensitivity to the forward.</p>'+
    '<div class="bfly-scroll"><table><thead><tr><th>Side</th><th>Option</th><th>Bid</th><th>Ask</th>'+
      '<th>Model</th><th>IV</th><th>Quote age</th></tr></thead><tbody>'+x.legs.map(l=>
      '<tr><td>'+l.side+' '+x.lot_size+'</td><td>'+bfNum(l.strike)+' '+l.type+'</td><td>'+bfNum(l.bid,2)+
      '</td><td>'+bfNum(l.ask,2)+'</td><td>'+bfNum(l.model_price,2)+'</td><td>'+bfNum(l.iv*100,2)+
      '%</td><td>'+bfNum(l.quote_age_seconds,2)+'s</td></tr>').join('')+'</tbody></table></div>'+
    '<div class="bfly-scroll"><table><thead><tr><th>Conditional scenario</th><th>Recenter mean</th>'+
      '<th>Hold mean</th><th>5th percentile</th><th>Total friction</th></tr></thead><tbody>'+
      Object.entries(x.scenarios).map(([name,z])=>'<tr><td>'+escapeHtml(name.replaceAll('_',' '))+
      '</td><td>'+bfMoney(z.recenter.mean)+'</td><td>'+bfMoney(z.hold.mean)+'</td><td>'+bfMoney(z.recenter.p05)+
      '</td><td>'+bfMoney(z.mean_total_cost)+'</td></tr>').join('')+'</tbody></table></div>'+
    '<p>Manual ₹10/order brokerage would add about '+bfMoney(s.manual_brokerage_extra)+
      ' including GST to the base recenter strategy. Actual broker margin: unavailable.</p>'+
    '<p>Next open / terminal mark: '+escapeHtml(b.next_open)+
      '. Recenter checks: '+escapeHtml(b.recenter_checks.join(' · ') || 'none before expiry')+'</p>';
}
function renderButterflyTracker() {
  const b=(bflyPayload.snapshot || {}).butterflies || {};
  const center=Number(document.getElementById('bflyHeldCenter').value);
  const width=Number(document.getElementById('bflyHeldWidth').value);
  const holder=document.getElementById('bflyTracker');
  if(!center || !b.forward) {holder.textContent='Enter the centre of an existing butterfly to inspect drift.'; return;}
  const drift=b.forward-center, trigger=width/2, target=Math.floor(b.forward/50+.5)*50;
  const stale=(bflyPayload.health_verdict || {}).surface_is_stale;
  const historical=!document.getElementById('liveToggle').checked;
  holder.textContent=(historical ? 'HISTORICAL WHAT-IF · ' : stale ? 'STALE SNAPSHOT · ' : '')+'Forward drift '+bfNum(drift,1)+' points · threshold '+
    trigger+' · '+(Math.abs(drift)>=trigger ? 'threshold breached; target centre '+bfNum(target) :
    'inside threshold; keep centre')+'. Evaluate only at the scheduled daily check. '+
    'Next check: '+((b.recenter_checks || [])[0] || 'none before expiry')+'. No orders sent.';
}
const _renderBeforeButterflies=render;
render=function(payload,forceSurfaceRedraw) {
  renderButterflies(payload);
  _renderBeforeButterflies(payload,forceSurfaceRedraw);
};
renderButterflies(lastPayload);
"""
