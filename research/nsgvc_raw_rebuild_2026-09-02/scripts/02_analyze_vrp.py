from pathlib import Path
import os
import pandas as pd, numpy as np, math
from datetime import datetime, timedelta, time
from scipy.optimize import brentq
from scipy.stats import norm, pearsonr, spearmanr, ttest_1samp
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

B=Path(os.environ['NSGVC_WORK'])
spot=pd.read_csv(B/'spot_2022_2026.csv',parse_dates=['datetime','date'])
opt=pd.read_csv(B/'option_0920_entries_2023_2026.csv')
opt['date']=pd.to_datetime(opt['date'])
spot=spot.sort_values('datetime').copy()

# Global close-to-close returns; includes overnight gaps at next session first bar.
spot['logret']=np.log(spot['close']/spot['close'].shift(1))
# avoid bridging pathological non-neighbor gaps longer than 5 calendar days? keep weekends/holidays, discard >7d
calgap=(spot['datetime']-spot['datetime'].shift(1)).dt.total_seconds()/86400
spot.loc[calgap>7,'logret']=np.nan

# Trading sessions and expiry calendar
sessions=pd.DatetimeIndex(sorted(spot['date'].unique()))
sset=set(sessions)
start=sessions.min(); end=pd.Timestamp('2026-06-30')
# Generate scheduled weekly expiries: Thu before Sep-2025, Tue Sep-2025 onward.
sched=[]
d=start.normalize()
while d<=end:
    wd=3 if d < pd.Timestamp('2025-09-01') else 1  # Mon=0
    # add if correct weekday; easier iterate each day
    if d.weekday()==wd:
        sched.append(d)
    d+=pd.Timedelta(days=1)
actual=[]
for s in sched:
    candidates=sessions[(sessions<=s) & (sessions>=s-pd.Timedelta(days=7))]
    if len(candidates):
        a=candidates.max()
        if not actual or a>actual[-1]: actual.append(a)
actual=pd.DatetimeIndex(actual)

def next_expiry(d):
    x=actual[actual>=d]
    return x.min() if len(x) else pd.NaT

# Daily realized variance features.
daily=[]
for d,g in spot.groupby('date',sort=True):
    g=g.sort_values('datetime')
    # use all valid 1m cc returns; first bar includes overnight gap
    ss=np.nansum(np.square(g['logret'].to_numpy(float)))
    daily.append((d, ss, ss*252, g.iloc[0]['open'],g.iloc[-1]['close'],g['high'].max(),g['low'].min(),len(g)))
daily=pd.DataFrame(daily,columns=['date','rv_sum','rv_var_ann','day_open','day_close','day_high','day_low','nbar']).sort_values('date')
daily['log_rv_var']=np.log(daily['rv_var_ann'].clip(lower=1e-10))
daily['lag1_logrv']=daily['log_rv_var'].shift(1)
daily['lag5_logrv']=daily['log_rv_var'].shift(1).rolling(5).mean()
daily['lag22_logrv']=daily['log_rv_var'].shift(1).rolling(22).mean()
daily['prev_ret']=np.log(daily['day_close'].shift(1)/daily['day_close'].shift(2))

# Pivot option entries
piv=opt.pivot_table(index='date',columns=['side','offset'],values='open',aggfunc='last')
piv.columns=[f'{s}_{int(o):+d}' for s,o in piv.columns]
piv=piv.reset_index()

# 09:20 spot feature rows and first-5 data through 09:19
entry_rows=[]
for d,g in spot.groupby('date',sort=True):
    if d<pd.Timestamp('2023-01-01') or d>pd.Timestamp('2026-05-14'): continue
    g=g.sort_values('datetime')
    r20=g[g['datetime'].dt.strftime('%H:%M')=='09:20']
    pre=g[(g['datetime'].dt.strftime('%H:%M')>='09:15')&(g['datetime'].dt.strftime('%H:%M')<='09:19')]
    if r20.empty or len(pre)<5: continue
    r=r20.iloc[0]
    open_ret=np.log(pre.iloc[-1]['close']/pre.iloc[0]['open'])
    # within first 5 mins: first ret open->close then cc
    closes=pre['close'].to_numpy(float); rr=np.empty(len(pre)); rr[0]=np.log(closes[0]/float(pre.iloc[0]['open'])); rr[1:]=np.diff(np.log(closes))
    first5_var=np.mean(rr**2)*252*375
    first5_range=(pre['high'].max()-pre['low'].min())/float(r['open'])
    entry_rows.append((d,float(r['open']),float(r['close']),open_ret,first5_var,first5_range))
entry=pd.DataFrame(entry_rows,columns=['date','spot_open_0920','spot_close_0920','open5_ret','open5_var_ann','open5_range'])

panel=entry.merge(daily[['date','lag1_logrv','lag5_logrv','lag22_logrv','prev_ret']],on='date',how='left').merge(piv,on='date',how='inner')
panel['expiry']=panel['date'].map(next_expiry)
panel=panel.dropna(subset=['expiry'])

# Black-76 straddle inversion using put-call parity inferred forward.
def black_straddle(sig,F,K,T,df):
    if sig<=0 or T<=0: return df*abs(F-K)
    v=sig*math.sqrt(T)
    d1=(math.log(F/K)+0.5*v*v)/v
    d2=d1-v
    c=df*(F*norm.cdf(d1)-K*norm.cdf(d2))
    p=df*(K*norm.cdf(-d2)-F*norm.cdf(-d1))
    return c+p

def infer_iv(C,P,K,T,r=0.06):
    if not (np.isfinite(C) and np.isfinite(P) and C>0 and P>0 and T>0): return np.nan,np.nan
    df=math.exp(-r*T)
    F=K+(C-P)/df
    if F<=0: return np.nan,np.nan
    price=C+P
    intrinsic=df*abs(F-K)
    if price<=intrinsic+1e-8: return np.nan,F
    f=lambda s:black_straddle(s,F,K,T,df)-price
    try: iv=brentq(f,1e-4,5.0,maxiter=100)
    except Exception: iv=np.nan
    return iv,F

# target forward realized variance from 09:20 through expiry 15:29.
spot_by_date={d:g.sort_values('datetime') for d,g in spot.groupby('date')}
targets=[]
for r in panel.itertuples():
    d=r.date; ex=r.expiry
    dates=sessions[(sessions>=d)&(sessions<=ex)]
    vals=[]
    n=0
    for dd in dates:
        g=spot_by_date.get(dd)
        if g is None: continue
        if dd==d:
            gg=g[g['datetime'].dt.strftime('%H:%M')>='09:20'].copy()
            if gg.empty: continue
            # first return should be 09:20 open -> close
            arr=gg['logret'].to_numpy(float)
            arr[0]=math.log(float(gg.iloc[0]['close'])/float(gg.iloc[0]['open']))
        else:
            gg=g.copy(); arr=gg['logret'].to_numpy(float)
        arr=arr[np.isfinite(arr)]
        vals.extend(arr.tolist()); n+=len(arr)
    if n<100: targets.append((d,np.nan,np.nan,np.nan,np.nan)); continue
    ss=float(np.sum(np.square(vals)))
    h_days=n/375.0
    var_ann=ss*252.0/h_days
    st=float(spot_by_date[ex].iloc[-1]['close'])
    targets.append((d,var_ann,math.sqrt(var_ann),h_days,st))
targ=pd.DataFrame(targets,columns=['date','fwd_var_ann','fwd_rv','h_trading_days','expiry_spot'])
panel=panel.merge(targ,on='date',how='left')

# IV, K, DTE
ivs=[]
for r in panel.itertuples():
    S=float(r.spot_open_0920); K=round(S/50)*50
    C=getattr(r,'CALL_+0',np.nan) if hasattr(r,'CALL_+0') else np.nan
    # tuple names sanitize +? easier dataframe lookup below
    ivs.append(np.nan)
# dataframe lookup
ivlist=[]; flist=[]; klist=[]; tlist=[]
for _,r in panel.iterrows():
    S=float(r['spot_open_0920']); K=int(math.floor(S/50+0.5)*50)
    exdt=pd.Timestamp(r['expiry'])+pd.Timedelta(hours=15,minutes=30)
    entdt=pd.Timestamp(r['date'])+pd.Timedelta(hours=9,minutes=20)
    T=(exdt-entdt).total_seconds()/(365.0*86400)
    C=r.get('CALL_+0',np.nan); P=r.get('PUT_+0',np.nan)
    iv,F=infer_iv(C,P,K,T,0.06)
    ivlist.append(iv); flist.append(F); klist.append(K); tlist.append(T)
panel['iv']=ivlist; panel['forward']=flist; panel['K']=klist; panel['T_cal']=tlist
panel['iv_var']=panel['iv']**2
panel['log_iv_var']=np.log(panel['iv_var'].clip(lower=1e-10))
panel['dte_sessions']=panel['h_trading_days']
panel['open5_logvar']=np.log(panel['open5_var_ann'].clip(lower=1e-10))
panel['abs_open5_ret']=panel['open5_ret'].abs()
panel['year']=panel['date'].dt.year
# Gap in vol points
panel['vrp_expost']=panel['iv']-panel['fwd_rv']

# Trade outcomes for iron-fly widths
trade_rows=[]
for _,r in panel.iterrows():
    if not np.isfinite(r['expiry_spot']): continue
    K=float(r['K']); ST=float(r['expiry_spot'])
    C0=r.get('CALL_+0',np.nan); P0=r.get('PUT_+0',np.nan)
    for w in [50,100,150,200,250,300,400,500]:
        off=int(w/50)
        Cw=r.get(f'CALL_+{off}',np.nan)
        Pw=r.get(f'PUT_-{off}',np.nan)
        if not all(np.isfinite(x) and x>=0 for x in [C0,P0,Cw,Pw]): continue
        credit=float(C0+P0-Cw-Pw)
        payoff=max(ST-K,0)+max(K-ST,0)-max(ST-(K+w),0)-max((K-w)-ST,0)
        pnl=credit-payoff
        maxloss=w-credit
        if maxloss<=0: continue
        trade_rows.append((r['date'],r['year'],r['expiry'],w,credit,payoff,pnl,maxloss,pnl/maxloss,r['iv'],r['fwd_rv'],r['vrp_expost']))
trades=pd.DataFrame(trade_rows,columns=['date','year','expiry','width','credit','payoff','pnl','maxloss','romr','iv','fwd_rv','vrp_expost'])

# Clean model panel
features_base=['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_var','dte_sessions','open5_logvar','open5_range','abs_open5_ret','prev_ret']
modeldf=panel.dropna(subset=['fwd_var_ann','iv']+features_base).copy()
modeldf['ylog']=np.log(modeldf['fwd_var_ann'].clip(lower=1e-10))

splits={'dev':modeldf[modeldf.year.isin([2023,2024])], 'val':modeldf[modeldf.year==2025], 'test':modeldf[modeldf.year==2026]}
print('MODEL SAMPLE', {k:len(v) for k,v in splits.items()})
print('date ranges', {k:(v.date.min(),v.date.max()) for k,v in splits.items()})

specs={
 'HAR': ['lag1_logrv','lag5_logrv','lag22_logrv','dte_sessions'],
 'IV_only':['log_iv_var','dte_sessions'],
 'HAR_IV':['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_var','dte_sessions'],
 'HAR_IV_open':['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_var','dte_sessions','open5_logvar','open5_range','abs_open5_ret','prev_ret']
}

def fit_predict_linear(train,test,cols):
    m=LinearRegression().fit(train[cols],train.ylog)
    return m,np.exp(m.predict(test[cols]))

def metrics(d,predvar):
    predvol=np.sqrt(predvar); yvol=d.fwd_rv.to_numpy(float)
    return dict(n=len(d), r2_vol=r2_score(yvol,predvol), corr=np.corrcoef(yvol,predvol)[0,1], mae_vol=mean_absolute_error(yvol,predvol), rmse_vol=math.sqrt(mean_squared_error(yvol,predvol)), r2_logvar=r2_score(d.ylog,np.log(predvar)))

# dev fits, val metrics
valres=[]; models={}
for name,cols in specs.items():
    m,p=fit_predict_linear(splits['dev'],splits['val'],cols)
    models[name]=(m,cols)
    valres.append({'model':name,**metrics(splits['val'],p)})
# HGB enhanced fixed params
cols=features_base
hgb=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1.0,random_state=1).fit(splits['dev'][cols],splits['dev'].ylog)
p=np.exp(hgb.predict(splits['val'][cols])); valres.append({'model':'HGB',**metrics(splits['val'],p)}); models['HGB']=(hgb,cols)
valres=pd.DataFrame(valres).sort_values('r2_vol',ascending=False)
print('\nVALIDATION MODELS\n',valres.to_string(index=False))
selected=valres.iloc[0]['model']
print('SELECTED',selected)

# refit selected on dev+val and test
trainall=modeldf[modeldf.year.isin([2023,2024,2025])]
test=splits['test'].copy()
if selected=='HGB':
    cols=features_base; sm=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1.0,random_state=1).fit(trainall[cols],trainall.ylog); predvar=np.exp(sm.predict(test[cols]))
else:
    cols=specs[selected]; sm=LinearRegression().fit(trainall[cols],trainall.ylog); predvar=np.exp(sm.predict(test[cols]))
test['pred_var']=predvar; test['pred_rv']=np.sqrt(predvar); test['pred_edge']=test['iv']-test['pred_rv']
print('\nTEST SELECTED METRICS',metrics(test,predvar))

# also OOS metrics for all candidates refit 23-25, diagnostic only (not selection)
testres=[]
for name,cols2 in specs.items():
    m,p=fit_predict_linear(trainall,test,cols2); testres.append({'model':name,**metrics(test,p)})
hgb2=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1.0,random_state=1).fit(trainall[features_base],trainall.ylog)
p=np.exp(hgb2.predict(test[features_base])); testres.append({'model':'HGB',**metrics(test,p)})
print('\nTEST ALL DIAGNOSTIC\n',pd.DataFrame(testres).sort_values('r2_vol',ascending=False).to_string(index=False))

# VRP descriptive by split
vrpstats=[]
for label,d in [('dev',modeldf[modeldf.year.isin([2023,2024])]),('val',modeldf[modeldf.year==2025]),('test',modeldf[modeldf.year==2026])]:
    vrp=d.iv-d.fwd_rv
    vrpstats.append(dict(split=label,n=len(d),mean_iv=d.iv.mean(),mean_rv=d.fwd_rv.mean(),mean_gap=vrp.mean(),median_gap=vrp.median(),pct_iv_gt_rv=(vrp>0).mean(),corr_iv_rv=d.iv.corr(d.fwd_rv)))
print('\nVRP STATS\n',pd.DataFrame(vrpstats).to_string(index=False))

# Generate predictions for every year using strict scheme: dev fit predicts val, refit through val predicts test.
# For dev, rolling/insample fitted values only used for descriptive threshold calibration; use leave? We use fitted dev for thresholds only.
if selected=='HGB':
    mdev=HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=200,l2_regularization=1.0,random_state=1).fit(splits['dev'][features_base],splits['dev'].ylog)
    modeldf.loc[splits['dev'].index,'pred_rv']=np.sqrt(np.exp(mdev.predict(splits['dev'][features_base])))
    modeldf.loc[splits['val'].index,'pred_rv']=np.sqrt(np.exp(mdev.predict(splits['val'][features_base])))
    modeldf.loc[test.index,'pred_rv']=test.pred_rv.values
else:
    c=specs[selected]; mdev=LinearRegression().fit(splits['dev'][c],splits['dev'].ylog)
    modeldf.loc[splits['dev'].index,'pred_rv']=np.sqrt(np.exp(mdev.predict(splits['dev'][c])))
    modeldf.loc[splits['val'].index,'pred_rv']=np.sqrt(np.exp(mdev.predict(splits['val'][c])))
    modeldf.loc[test.index,'pred_rv']=test.pred_rv.values
modeldf['pred_edge']=modeldf.iv-modeldf.pred_rv

# Join predictions into trades
trades=trades.merge(modeldf[['date','pred_rv','pred_edge']],on='date',how='inner')

# Strategy grid: economically simple edge thresholds in vol pts and widths. Select on 2025 by mean net ROMR with >=25 trades, cost=2 points.
def summarize_trade(d,cost=0):
    if len(d)==0:return None
    pnl=d.pnl-cost; cap=d.maxloss+cost
    r=pnl/cap
    # sequential simple fixed-risk cumulative in R units, max drawdown for 1R notion via cum sum
    cs=r.cumsum(); peak=cs.cummax(); dd=(peak-cs).max() if len(cs) else np.nan
    return dict(n=len(d),mean_pnl=pnl.mean(),median_pnl=np.median(pnl),win=(pnl>0).mean(),mean_romr=r.mean(),median_romr=np.median(r),sum_romr=r.sum(),max_cumR_dd=dd)

grid=[]
for w in [100,150,200,250,300,400,500]:
    for th in [0,1,2,3,4,5]:
        for yr in [2023,2024,2025,2026]:
            d=trades[(trades.width==w)&(trades.year==yr)&(trades.pred_edge>=th)].sort_values('date')
            s=summarize_trade(d,2.0)
            if s: grid.append({'width':w,'edge_th':th,'year':yr,**s})
grid=pd.DataFrame(grid)
valgrid=grid[(grid.year==2025)&(grid.n>=25)].sort_values(['mean_romr','sum_romr'],ascending=False)
print('\nTOP VAL GRID cost2\n',valgrid.head(15).to_string(index=False))
if len(valgrid):
    best=valgrid.iloc[0]; bw=int(best.width); bth=float(best.edge_th)
else: bw=200;bth=2
print('BEST RULE',bw,bth)
for cost in [0,2,4,6]:
    print('\nCOST',cost)
    rows=[]
    for label,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
        d=trades[(trades.width==bw)&(trades.year.isin(yrs))&(trades.pred_edge>=bth)].sort_values('date')
        s=summarize_trade(d,cost)
        rows.append({'split':label,**(s or {})})
    print(pd.DataFrame(rows).to_string(index=False))

# unconditional iron fly comparison by width and split (cost2)
un=[]
for w in [100,150,200,250,300,400,500]:
    for label,yrs in [('dev',[2023,2024]),('val',[2025]),('test',[2026])]:
        d=trades[(trades.width==w)&(trades.year.isin(yrs))].sort_values('date')
        s=summarize_trade(d,2)
        if s: un.append({'width':w,'split':label,**s})
print('\nUNCONDITIONAL cost2\n',pd.DataFrame(un).to_string(index=False))

# Relation forecast edge to trade PnL in test, width best
for label,yrs in [('val',[2025]),('test',[2026])]:
    d=trades[(trades.width==bw)&(trades.year.isin(yrs))].dropna(subset=['pred_edge']).copy()
    if len(d):
        print(label,'edge-pnl pearson',d.pred_edge.corr(d.pnl),'spearman',d.pred_edge.corr(d.pnl,method='spearman'))
        try:
            d['edge_quintile']=pd.qcut(d.pred_edge,5,duplicates='drop')
            print(d.groupby('edge_quintile',observed=True).agg(n=('pnl','size'),edge=('pred_edge','mean'),pnl=('pnl','mean'),romr=('romr','mean'),win=('pnl',lambda x:(x>0).mean())).to_string())
        except Exception as e: print(e)

# save outputs
panel.to_csv(B/'vrp_daily_panel.csv',index=False)
modeldf.to_csv(B/'vrp_model_panel.csv',index=False)
trades.to_csv(B/'ironfly_trades.csv',index=False)
valres.to_csv(B/'model_validation.csv',index=False)
pd.DataFrame(testres).to_csv(B/'model_test_diagnostic.csv',index=False)
grid.to_csv(B/'strategy_grid.csv',index=False)
pd.DataFrame(vrpstats).to_csv(B/'vrp_stats.csv',index=False)
print('\nSAVED')
