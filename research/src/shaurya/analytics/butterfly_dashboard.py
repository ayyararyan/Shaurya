# ruff: noqa: E501
"""Essential butterfly presentation; calculations remain server-side."""

STYLE = r"""
.bfly {margin:8px 24px 20px;padding:22px;background:var(--panel);border:1px solid var(--rule);border-radius:12px}
.bfly h2 {font-size:20px;letter-spacing:0;margin:0 0 8px}.bfly p,.bfly small {font-size:12px;color:var(--ink-2);line-height:1.6}
.bfly-tools {display:flex;gap:12px;align-items:center;margin:16px 0}.bfly select,.bfly input {font:inherit;padding:8px;border:1px solid var(--rule);border-radius:6px;background:var(--bg);color:var(--ink);max-width:160px}
.bfly-grid {display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.bfly-choice {border:1px solid var(--rule);border-radius:8px;padding:16px}.bfly-choice.selected {border-color:var(--slate)}
.bfly-choice small {display:block;margin-bottom:5px}
.bfly-choice h3 {font-size:17px;margin:0 0 5px}.bfly-choice strong {display:block;font-size:26px;margin:4px 0 12px}.bfly-choice button {margin-top:12px;text-transform:none;letter-spacing:0}
.bfly .bad {color:var(--brick)}.bfly details {margin:16px 0 0}.bfly-detail {padding:0 16px 16px}.bfly-legs {display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:14px 0;font-size:14px}.bfly-detail p {margin:8px 0}
.bfly-check {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:12px 0}.bfly-check dt {font-size:12px;color:var(--ink-2);margin-bottom:6px}.bfly-check dd {margin:0;font-size:16px;font-weight:600}
@media(max-width:650px){.bfly {margin:8px 16px;padding:16px}.bfly-grid {grid-template-columns:1fr}.bfly-choice strong {font-size:24px}.bfly-tools {flex-wrap:wrap}.bfly-check {grid-template-columns:1fr 1fr}}
"""

PANEL = r"""
<section class="bfly" id="butterflyPanel" aria-label="Short iron butterfly shortlist">
<h2>Butterfly shortlist</h2>
<p>One lot · daily recentering until expiry · all amounts in rupees</p>
<p id="bflyStatus">Waiting for prices…</p>
<div class="bfly-tools"><label>Wing width <select id="bflyWidth" onchange="renderButterflies(bflyPayload)"><option value="all">400 &amp; 500</option><option value="400">400 each side</option><option value="500">500 each side</option></select></label></div>
<div class="bfly-grid" id="bflyRows"></div>
<p>Top three by estimated profit relative to static risk. <b>Net profit is after costs, not the entry credit.</b><br>
Downside is the 5th percentile: 5% of simulated outcomes are worse. It is not maximum loss.</p>
<details id="bflyDetails"><summary>Selected butterfly · legs &amp; costs</summary><div class="bfly-detail" id="bflyDetailBody"></div></details>
<details><summary>Check whether to recenter my butterfly</summary><div class="bfly-detail">
<div class="bfly-tools"><label>Current centre <input id="bflyHeldCenter" type="number" step="50" placeholder="e.g. 24000" oninput="renderButterflyTracker()"></label><label>Wings <select id="bflyHeldWidth" onchange="renderButterflyTracker()"><option value="400">400 each side</option><option value="500">500 each side</option></select></label></div><div id="bflyTracker" aria-live="polite"></div></div></details>
</section>
"""

SCRIPT = r"""
let bflyPayload=lastPayload;
let bflySelected=null;
const bfNum=(x,d=0)=>typeof x==='number' && Number.isFinite(x) ? x.toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d}) : '—';
const bfMoney=x=>'₹'+bfNum(x);
function renderButterflies(payload) {
 bflyPayload=payload;
 const b=(payload.snapshot||{}).butterflies||{}, note=document.getElementById('bflyStatus');
 const stale=(payload.health_verdict||{}).surface_is_stale || (payload.health_verdict||{}).status==='dead';
 const historical=!document.getElementById('liveToggle').checked || payload.view_mode==='saved_snapshot';
 note.className=stale?'bad':'';
 if(b.status!=='ok') {
  note.textContent='No eligible butterfly prices in this snapshot.';
  document.getElementById('bflyRows').innerHTML='';
  document.getElementById('bflyDetailBody').textContent='Waiting for a valid four-leg quote.';
  renderButterflyTracker();return;
 }
 note.textContent=(historical?'Saved snapshot':stale?'Stale prices — do not use for entry':'Indicative prices')+' · expiry '+b.expiry;
 const width=document.getElementById('bflyWidth').value;
 const shown=b.candidates.filter(x=>width==='all'||x.width===Number(width)).sort((a,c)=>c.carry_risk_ratio-a.carry_risk_ratio).slice(0,3);
 if(!shown.some(x=>x.id===bflySelected))bflySelected=shown.length?shown[0].id:null;
 document.getElementById('bflyRows').innerHTML=shown.map(x=>{
  const s=x.scenarios.base.recenter;
  const flag=x.signal_label==='no_positive_scenario_edge'?'No positive estimated edge':x.signal_label==='within_monte_carlo_noise'?'Edge within simulation noise':x.signal_label==='stress_sensitive'?'Can lose under stress':'Positive in tested scenarios';
  return '<article class="bfly-choice '+(x.id===bflySelected?'selected':'')+'"><h3>'+bfNum(x.center)+' centre</h3><p>'+x.width+'-point wings each side</p><small>Estimated net profit · to expiry</small><strong>'+bfMoney(s.mean)+'</strong><small>Downside scenario</small><b class="bad">'+bfMoney(s.p05)+'</b><p>'+flag+'</p><button onclick="selectButterfly(\''+x.id+'\')">View four legs</button></article>';
 }).join('') || '<p>No eligible prices for this width.</p>';
 renderButterflyDetail(shown.find(x=>x.id===bflySelected),b);renderButterflyTracker();
}
function selectButterfly(id){bflySelected=id;renderButterflies(bflyPayload);document.getElementById('bflyDetails').open=true;document.getElementById('bflyDetails').scrollIntoView({behavior:'smooth',block:'nearest'});}
function renderButterflyDetail(x,b){
 const el=document.getElementById('bflyDetailBody');if(!x){el.textContent='No eligible butterfly selected.';return;}
 const s=x.scenarios.base;
 el.innerHTML='<p><b>'+bfNum(x.center)+' centre · '+x.width+' wings · '+x.lot_size+' units per leg</b></p><div class="bfly-legs">'+x.legs.map(l=>'<div>'+escapeHtml(l.side)+' '+bfNum(l.strike)+' '+escapeHtml(l.type)+'</div>').join('')+'</div>'+
 '<p>Cash received at entry: <b>'+bfMoney(x.credit_rupees)+'</b> before costs. This is not profit: the options still have a payout liability.</p>'+
 '<p>Estimated total trading costs: <b>'+bfMoney(s.mean_total_cost)+'</b>, already deducted from net profit.</p>'+
 '<p>If held without recentering: estimated net profit '+bfMoney(s.hold.mean)+'. Static maximum loss '+bfMoney(x.static_max_loss_before_exercise_tax)+' before exercise tax; repeated recentering can lose more.</p>'+
 '<p><b>Recenter rule:</b> check at 15:15 IST, once per trading day except expiry day. If the forward moves '+x.width/2+' points from the centre, close all four legs and reopen at the nearest 50-point centre.</p>';
}
function renderButterflyTracker() {
  const b=(bflyPayload.snapshot || {}).butterflies || {};
  const center=Number(document.getElementById('bflyHeldCenter').value);
  const width=Number(document.getElementById('bflyHeldWidth').value);
  const holder=document.getElementById('bflyTracker');
  if(!Number.isFinite(center) || center<=0 || !Number.isFinite(b.forward)) {
    holder.textContent='Enter your current centre.'; return;
  }
  const drift=b.forward-center, target=Math.floor(b.forward/50+.5)*50;
  const next=(b.recenter_checks || [])[0];
  const recenter=!!next && Math.abs(drift)>=width/2;
  const nextDate=next ? new Date(next) : null;
  const nextTime=nextDate && Number.isFinite(nextDate.getTime())
    ? nextDate.toLocaleDateString('en-GB',{timeZone:'Asia/Kolkata',day:'numeric',month:'short'})+
      ', '+nextDate.toLocaleTimeString('en-US',{timeZone:'Asia/Kolkata',hour:'numeric',minute:'2-digit'})+' IST'
    : 'None before expiry';
  const fields=[['Forward drift',(drift>0?'+':'')+bfNum(drift,1)+' pts'],
    ['Recenter?',recenter?'Yes':'No'],
    ['New centre',bfNum(recenter?target:center)+(recenter?'':' (unchanged)')],
    ['Next check',nextTime]];
  holder.innerHTML='<dl class="bfly-check">'+fields.map(([label,value])=>
    '<div><dt>'+label+'</dt><dd>'+escapeHtml(value)+'</dd></div>').join('')+'</dl>';

}

const _renderBeforeButterflies=render;
render=function(payload,forceSurfaceRedraw){renderButterflies(payload);_renderBeforeButterflies(payload,forceSurfaceRedraw);};
renderButterflies(lastPayload);
"""
