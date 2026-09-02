from pathlib import Path
import os
import pandas as pd, numpy as np
from scipy import stats
B=Path(os.environ['NSGVC_WORK'])
t=pd.read_csv(B/'ironfly_trades_corrected.csv',parse_dates=['date','expiry'])

def choose_first(df,ratio_th):
    x=df[df.pred_ratio<=ratio_th].sort_values(['expiry','date'])
    return x.groupby('expiry',as_index=False).first()

def choose_fixed_nearest(df,target_h):
    # one trade per expiry at h trading days nearest target, causal fixed timing
    x=df.copy(); x['dist']=(x['h_trading_days']-target_h).abs() if 'h_trading_days' in x.columns else np.nan

def summ(d,cost=2,seed=1):
    if len(d)==0:return None
    pnl=d.pnl-cost; cap=d.maxloss+cost; R=pnl/cap
    rng=np.random.default_rng(seed)
    means=[]
    arr=R.to_numpy()
    for _ in range(5000):means.append(rng.choice(arr,size=len(arr),replace=True).mean())
    lo,hi=np.quantile(means,[.025,.975])
    # cumulative if risk max 1% equity per trade
    eq=peak=1.;mdd=0
    for r in arr:
        eq*=1+.01*r;peak=max(peak,eq);mdd=max(mdd,1-eq/peak)
    return {'n':len(d),'mean_pnl':pnl.mean(),'median_pnl':pnl.median(),'win':(pnl>0).mean(),'mean_R':R.mean(),'median_R':R.median(),'R_ci_lo':lo,'R_ci_hi':hi,'maxloss_rate':(pnl<=-(cap-cost)*.98).mean(),'mean_maxloss_pts':d.maxloss.mean(),'median_credit':d.credit.median(),'eq_1pct':eq,'maxdd_1pct':mdd}

rows=[]
for w in [200,250,300,400,500]:
 for th in [.65,.7,.75,.8]:
  for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
   base=t[(t.width==w)&(t.year.isin(yrs))].copy()
   d=choose_first(base,th).sort_values('date')
   s=summ(d,2)
   if s:rows.append({'width':w,'ratio_th':th,'split':split,**s})
g=pd.DataFrame(rows)
print('WEEKLY FIRST-ELIGIBLE CROSS SPLIT')
print(g.pivot_table(index=['width','ratio_th'],columns='split',values=['n','mean_R','win','mean_pnl']).round(4).to_string())
print('\nValidation ranking >=20 weeks')
v=g[(g.split=='val')&(g.n>=20)].copy();v['score']=v.mean_R # simple
print(v.sort_values('score',ascending=False).head(20).to_string(index=False))

# Candidate family 300/400/500 th=.7 detailed costs
for w in [300,400,500]:
 print('\n=== width',w,'ratio<=.7 ===')
 for cost in [0,2,4,6,8]:
  rr=[]
  for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
   d=choose_first(t[(t.width==w)&(t.year.isin(yrs))],.7).sort_values('date')
   rr.append({'split':split,**summ(d,cost)})
  print('cost',cost);print(pd.DataFrame(rr).to_string(index=False))
 # DTE distribution
 for split,yrs in [('val',[2025]),('test',[2026])]:
  d=choose_first(t[(t.width==w)&(t.year.isin(yrs))],.7)
  # recover h from corrected model file
  md=pd.read_csv(B/'vrp_model_corrected.csv',parse_dates=['date'])[['date','h_trading_days','pred_ratio']]
  d=d.merge(md,on='date',suffixes=('','_m'))
  print(split,'entry horizon',d.h_trading_days.describe().to_dict())

# fixed-entry-day by horizon rounding: choose each expiry's row with rounded remaining sessions = target, no signal and ratio signal
md=pd.read_csv(B/'vrp_model_corrected.csv',parse_dates=['date'])[['date','h_trading_days','pred_ratio']]
tm=t.drop(columns=['pred_ratio'],errors='ignore').merge(md,on='date',how='left')
fixed=[]
for w in [300,400,500]:
 for h in [1,2,3,4,5]:
  for th in [None,.7,.8]:
   for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
    x=tm[(tm.width==w)&(tm.year.isin(yrs))].copy();x['hdiff']=(x.h_trading_days-h).abs();x=x.sort_values(['expiry','hdiff','date']).groupby('expiry',as_index=False).first();x=x[x.hdiff<.25]
    if th is not None:x=x[x.pred_ratio<=th]
    s=summ(x.sort_values('date'),2)
    if s:fixed.append({'width':w,'h':h,'th':'all' if th is None else th,'split':split,**s})
f=pd.DataFrame(fixed)
print('\nFIXED HORIZON interesting')
print(f[(f.width==500)&(f.th.isin(['all',.7,.8]))].pivot_table(index=['h','th'],columns='split',values=['n','mean_R','win']).round(4).to_string())

g.to_csv(B/'weekly_first_eligible.csv',index=False);f.to_csv(B/'weekly_fixed_horizon.csv',index=False)
