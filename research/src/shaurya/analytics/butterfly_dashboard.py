# ruff: noqa: E501
"""Minimal VolARP presentation; calculations remain server-side and read-only."""

STYLE = r"""
.bfly {margin:8px 24px 20px;padding:22px;background:var(--panel);border:1px solid var(--rule);border-radius:12px}
.bfly h2 {font-size:20px;letter-spacing:0;margin:0 0 8px}.bfly p,.bfly small {font-size:12px;color:var(--ink-2);line-height:1.6}
.bfly-tools {display:flex;gap:12px;align-items:center;margin:16px 0}.bfly select,.bfly input {font:inherit;padding:8px;border:1px solid var(--rule);border-radius:6px;background:var(--bg);color:var(--ink);max-width:160px}
.bfly-grid {display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.bfly-choice {border:1px solid var(--rule);border-radius:8px;padding:16px;min-width:0;overflow-wrap:anywhere}.bfly-choice.selected {border-color:var(--slate)}
.bfly-choice small {display:block;margin-bottom:5px}
.bfly-choice h3 {font-size:17px;margin:0 0 5px}.bfly-choice strong {display:block;font-size:26px;margin:4px 0 12px}
.bfly .bad {color:var(--brick)}.bfly details {margin:16px 0 0}.bfly-detail {padding:0 16px 16px}.bfly-legs {display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:14px 0;font-size:14px}.bfly-detail p {margin:8px 0}
.bfly-check {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:12px 0}.bfly-check dt {font-size:12px;color:var(--ink-2);margin-bottom:6px}.bfly-check dd {margin:0;font-size:16px;font-weight:600}
@media(max-width:900px){.bfly {width:calc(100% - 32px);max-width:calc(100% - 32px);box-sizing:border-box;margin:8px 16px;padding:16px}.bfly-grid {grid-template-columns:minmax(0,1fr)}.bfly-choice strong {font-size:clamp(18px,6vw,24px);overflow-wrap:anywhere}.bfly-tools {flex-wrap:wrap}.bfly-check {grid-template-columns:1fr 1fr}}
"""

PANEL = r"""
<section class="bfly" id="butterflyPanel" aria-label="VolARP short iron butterfly">
<h2>VolARP · ATM short iron butterfly</h2>
<p>One lot · 500-point wings · read-only decision aid · all amounts in rupees</p>
<p id="bflyStatus">Waiting for prices…</p>
<div class="bfly-grid" id="bflyRows"></div>
<details id="bflyDetails"><summary>Four legs and costs</summary><div class="bfly-detail" id="bflyDetailBody"></div></details>
<details><summary>Check whether to recenter my butterfly</summary><div class="bfly-detail">
<div class="bfly-tools"><label>Current centre <input id="bflyHeldCenter" type="number" step="50" placeholder="e.g. 24000" oninput="renderButterflyTracker()"></label></div><div id="bflyTracker" aria-live="polite"></div></div></details>
</section>
"""

SCRIPT = r"""
let bflyPayload=lastPayload;
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
  note.textContent=(historical?'Saved snapshot':stale?'Stale prices — do not use for entry':'Indicative 10:00 IST check')+' · expiry '+b.expiry;
 const x=b.candidates.find(c=>c.width===500), forecast=payload.rv_forecast || {};
 const ratio=typeof (b.strategy_signal||{}).ratio==='number' ? b.strategy_signal.ratio : forecast.rv_iv_vol_ratio;
 const threshold=typeof (b.strategy_signal||{}).threshold==='number' ? b.strategy_signal.threshold : 0.70;
 const condition=typeof (b.strategy_signal||{}).condition_met==='boolean' ? b.strategy_signal.condition_met : ratio < threshold;
 if(!x){ document.getElementById('bflyRows').textContent='No eligible ATM four-leg price.'; return; }
 const state=condition ? 'RV / IV is below 0.70' : 'RV / IV is not below 0.70';
 const payoff=x.max_profit_before_exercise_tax;
 document.getElementById('bflyRows').innerHTML='<article class="bfly-choice selected"><h3>'+bfNum(x.center)+' ATM centre</h3><p>Short put + short call; long '+bfNum(x.width)+'-point wings</p><small>10:00 IST condition</small><strong class="'+(condition?'':'bad')+'">'+escapeHtml(state)+'</strong><small>Current payoff if expiry is at the centre</small><strong>'+bfMoney(payoff)+'</strong><p>Executable credit now: '+bfMoney(x.credit_rupees)+' before costs.</p></article>';
 renderButterflyDetail(x,b);renderButterflyTracker();
}
function renderButterflyDetail(x,b){
 const el=document.getElementById('bflyDetailBody');if(!x){el.textContent='No eligible butterfly selected.';return;}
 const s=x.scenarios.base;
 el.innerHTML='<p><b>'+bfNum(x.center)+' centre · '+x.width+' wings · '+x.lot_size+' units per leg</b></p><div class="bfly-legs">'+x.legs.map(l=>'<div>'+escapeHtml(l.side)+' '+bfNum(l.strike)+' '+escapeHtml(l.type)+'</div>').join('')+'</div>'+
 '<p>Cash received at entry: <b>'+bfMoney(x.credit_rupees)+'</b> before costs. This is not profit: the options still have a payout liability.</p>'+
 '<p>Entry costs: <b>'+bfMoney(x.entry_cost_rupees)+'</b>. If expiry is at the centre, the displayed payoff is net entry credit; static maximum loss is '+bfMoney(x.static_max_loss_before_exercise_tax)+' before exercise tax.</p>'+
 '<p><b>Recenter rule:</b> check at 10:00 IST on trading days before expiry. Continue only while RV / IV remains below 0.70; if the forward has moved <b>more than</b> 250 points, close all four legs and reopen at the nearest 50-point centre. The action when the continuation condition fails is not yet specified.</p>';
}
function renderButterflyTracker() {
  const b=(bflyPayload.snapshot || {}).butterflies || {};
  const center=Number(document.getElementById('bflyHeldCenter').value);
  const width=500;
  const holder=document.getElementById('bflyTracker');
  if(!Number.isFinite(center) || center<=0 || !Number.isFinite(b.forward)) {
    holder.textContent='Enter your current centre.'; return;
  }
  const drift=b.forward-center, target=Math.floor(b.forward/50+.5)*50;
  const rawNext=(b.recenter_checks || [])[0];
  // Saved pre-VolARP snapshots retain their old intraday timestamp. Their
  // trading-day sequence remains valid, but this strategy's check is 10:00.
  const next=rawNext ? new Date(rawNext) : null;
  if(next && Number.isFinite(next.getTime())) next.setUTCHours(4,30,0,0);
  const recenter=!!next && Math.abs(drift)>width/2;
  const nextDate=next;
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
