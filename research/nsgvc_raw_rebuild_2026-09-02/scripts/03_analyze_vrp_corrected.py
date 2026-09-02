from pathlib import Path
import os
import pandas as pd, numpy as np, math
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
B=Path(os.environ['NSGVC_WORK'])
p=pd.read_csv(B/'vrp_daily_panel.csv',parse_dates=['date','expiry'])
t=pd.read_csv(B/'ironfly_trades.csv',parse_dates=['date','expiry'])
# Reconstruct realized integrated variance from earlier trading-time annualization.
p['fwd_int_var']=p['fwd_var_ann']*p['h_trading_days']/252.0
p['iv_int_var']=p['iv_var']*p['T_cal']
p['fwd_rv_cal']=np.sqrt(p['fwd_int_var']/p['T_cal'])
p['vrp_int']=p['iv_int_var']-p['fwd_int_var']
p['vrp_ratio']=p['fwd_int_var']/p['iv_int_var']
p['vrp_vol_cal']=p['iv']-p['fwd_rv_cal']
p['log_fwd_int']=np.log(p['fwd_int_var'].clip(lower=1e-12))
p['log_iv_int']=np.log(p['iv_int_var'].clip(lower=1e-12))
p['logT']=np.log(p['T_cal'].clip(lower=1e-8))
p['year']=p.date.dt.year
# Retain model-complete rows
features=['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_int','logT','open5_logvar','open5_range','abs_open5_ret','prev_ret']
d=p.dropna(subset=['log_fwd_int','iv']+features).copy()

def met(df,pred_int):
    # report integrated variance log R2 and calendar-ann vol metrics
    pv=np.sqrt(pred_int/df.T_cal.to_numpy())
    yv=df.fwd_rv_cal.to_numpy()
    return dict(n=len(df),r2_logint=r2_score(df.log_fwd_int,np.log(pred_int)),r2_vol=r2_score(yv,pv),corr=np.corrcoef(yv,pv)[0,1],mae_vol=mean_absolute_error(yv,pv),rmse_vol=math.sqrt(mean_squared_error(yv,pv)))

specs={
'HAR':['lag1_logrv','lag5_logrv','lag22_logrv','logT'],
'IV_only':['log_iv_int','logT'],
'HAR_IV':['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_int','logT'],
'HAR_IV_open':features
}
dev=d[d.year.isin([2023,2024])]; val=d[d.year==2025]; test=d[d.year==2026]
print('samples',len(dev),len(val),len(test))
rows=[]
for name,c in specs.items():
 m=LinearRegression().fit(dev[c],dev.log_fwd_int); pred=np.exp(m.predict(val[c])); rows.append({'model':name,**met(val,pred)})
h=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1,random_state=1).fit(dev[features],dev.log_fwd_int)
pred=np.exp(h.predict(val[features]));rows.append({'model':'HGB',**met(val,pred)})
vr=pd.DataFrame(rows).sort_values('r2_logint',ascending=False)
print('\nVAL\n',vr.to_string(index=False))
sel=vr.iloc[0].model;print('selected',sel)
train=d[d.year.isin([2023,2024,2025])]
if sel=='HGB':
 m=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1,random_state=1).fit(train[features],train.log_fwd_int); c=features
else:
 c=specs[sel];m=LinearRegression().fit(train[c],train.log_fwd_int)
test=test.copy();test['pred_int']=np.exp(m.predict(test[c]));test['pred_rv_cal']=np.sqrt(test.pred_int/test.T_cal);test['pred_vrp_int']=test.iv_int_var-test.pred_int;test['pred_ratio']=test.pred_int/test.iv_int_var;test['pred_vol_edge']=test.iv-test.pred_rv_cal
print('\nTEST',met(test,test.pred_int.to_numpy()))
# all diagnostic
rr=[]
for name,c2 in specs.items():
 mm=LinearRegression().fit(train[c2],train.log_fwd_int); pr=np.exp(mm.predict(test[c2]));rr.append({'model':name,**met(test,pr)})
hh=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1,random_state=1).fit(train[features],train.log_fwd_int);pr=np.exp(hh.predict(test[features]));rr.append({'model':'HGB',**met(test,pr)})
print('\nTEST ALL\n',pd.DataFrame(rr).sort_values('r2_logint',ascending=False).to_string(index=False))
# stats
st=[]
for label,dd in [('dev',d[d.year.isin([2023,2024])]),('val',d[d.year==2025]),('test',d[d.year==2026])]:
 st.append(dict(split=label,n=len(dd),mean_iv=dd.iv.mean(),mean_rv_cal=dd.fwd_rv_cal.mean(),mean_vol_gap=(dd.iv-dd.fwd_rv_cal).mean(),median_vol_gap=(dd.iv-dd.fwd_rv_cal).median(),pct_ivvar_gt_rv=(dd.iv_int_var>dd.fwd_int_var).mean(),median_rv_iv_ratio=np.median(dd.fwd_int_var/dd.iv_int_var),mean_int_vrp=(dd.iv_int_var-dd.fwd_int_var).mean()))
print('\nINTEGRATED VRP STATS\n',pd.DataFrame(st).to_string(index=False))
# By horizon
x=d.copy();x['hround']=x.h_trading_days.round()
print('\nBY HORIZON\n',x.groupby('hround').agg(n=('date','size'),pct=('vrp_int',lambda z:(z>0).mean()),median_ratio=('vrp_ratio','median'),iv=('iv','median'),rv=('fwd_rv_cal','median')).to_string())
# build strict predictions all d: dev fit -> dev/val; train through 2025 -> test
if sel=='HGB':
 md=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1,random_state=1).fit(dev[features],dev.log_fwd_int); cc=features
else:
 cc=specs[sel];md=LinearRegression().fit(dev[cc],dev.log_fwd_int)
d.loc[dev.index,'pred_int']=np.exp(md.predict(dev[cc]))
d.loc[val.index,'pred_int']=np.exp(md.predict(val[cc]))
d.loc[test.index,'pred_int']=test.pred_int.values
d['pred_ratio']=d.pred_int/d.iv_int_var
d['pred_vol_edge']=d.iv-np.sqrt(d.pred_int/d.T_cal)
d['pred_vrp_int']=d.iv_int_var-d.pred_int
# join to trades, replacing old signal
keep=d[['date','pred_int','pred_ratio','pred_vol_edge','pred_vrp_int','fwd_rv_cal','vrp_int','vrp_ratio']]
t2=t.drop(columns=['pred_rv','pred_edge'],errors='ignore').merge(keep,on='date',how='inner')
# Strategy grid gates on predicted RV / implied variance ratio. <1 means forecast says IV expensive.
def summ(dd,cost=2):
 if len(dd)==0:return None
 pnl=dd.pnl-cost; cap=dd.maxloss+cost; R=pnl/cap
 return dict(n=len(dd),mean_pnl=pnl.mean(),median_pnl=pnl.median(),win=(pnl>0).mean(),mean_R=R.mean(),median_R=R.median(),sum_R=R.sum(),se_R=R.std(ddof=1)/np.sqrt(len(R)) if len(R)>1 else np.nan)
rows=[]
for w in [100,150,200,250,300,400,500]:
 for ratio_th in [.5,.6,.7,.8,.9,1.0,1.1,1.2]:
  for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
   dd=t2[(t2.width==w)&(t2.year.isin(yrs))&(t2.pred_ratio<=ratio_th)].sort_values('date')
   s=summ(dd,2)
   if s:rows.append({'width':w,'ratio_th':ratio_th,'split':split,**s})
g=pd.DataFrame(rows)
vv=g[(g['split']=='val')&(g.n>=30)].copy();vv['score']=vv.mean_R-.5*vv.se_R
print('\nTOP VAL STRATEGIES corrected signal\n',vv.sort_values('score',ascending=False).head(25).to_string(index=False))
if len(vv):
 best=vv.sort_values('score',ascending=False).iloc[0];print('best',best[['width','ratio_th','n','mean_R','score']].to_dict())
 for cost in [0,2,4,6]:
  out=[]
  for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
   dd=t2[(t2.width==best.width)&(t2.year.isin(yrs))&(t2.pred_ratio<=best.ratio_th)].sort_values('date')
   out.append({'split':split,**summ(dd,cost)})
  print('\nCOST',cost,'\n',pd.DataFrame(out).to_string(index=False))
# sensible cross-split
selg=g[(g.width.isin([300,400,500]))&(g.ratio_th.isin([.6,.7,.8,.9,1.0]))]
print('\nCROSS SPLIT\n',selg.pivot_table(index=['width','ratio_th'],columns='split',values=['n','mean_R','win']).round(4).to_string())
# signal-PnL corr
for w in [300,400,500]:
 for yr in [2025,2026]:
  dd=t2[(t2.width==w)&(t2.year==yr)]
  print('corr pred ratio vs pnl',w,yr,dd.pred_ratio.corr(dd.pnl),dd.pred_ratio.corr(dd.pnl,method='spearman'))
  print('corr expost vrp vs pnl',w,yr,dd.vrp_int.corr(dd.pnl),dd.vrp_int.corr(dd.pnl,method='spearman'))

# straddle terminal PnL directly (using credit = C0+P0 from p and terminal abs move)
strad=[]
for _,r in p.iterrows():
 c=r.get('CALL_+0',np.nan);q=r.get('PUT_+0',np.nan)
 if not (np.isfinite(c) and np.isfinite(q) and np.isfinite(r.expiry_spot)):continue
 pnl=c+q-abs(r.expiry_spot-r.K)
 strad.append((r.date,r.year,c+q,pnl,r.vrp_int,r.vrp_ratio))
strad=pd.DataFrame(strad,columns=['date','year','credit','pnl','vrp_int','vrp_ratio']).merge(keep[['date','pred_ratio']],on='date')
print('\nSTRADDLE gross by split')
for split,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
 dd=strad[strad.year.isin(yrs)];print(split,len(dd),dd.pnl.mean(),dd.pnl.median(),(dd.pnl>0).mean())
 for th in [.6,.7,.8,.9,1.0]:
  z=dd[dd.pred_ratio<=th]
  if len(z):print(' ratio',th,len(z),z.pnl.mean(),z.pnl.median(),(z.pnl>0).mean())

vr.to_csv(B/'model_validation_corrected.csv',index=False)
pd.DataFrame(rr).to_csv(B/'model_test_corrected.csv',index=False)
pd.DataFrame(st).to_csv(B/'vrp_integrated_stats.csv',index=False)
d.to_csv(B/'vrp_model_corrected.csv',index=False)
t2.to_csv(B/'ironfly_trades_corrected.csv',index=False)
g.to_csv(B/'strategy_grid_corrected.csv',index=False)
strad.to_csv(B/'straddle_terminal.csv',index=False)
