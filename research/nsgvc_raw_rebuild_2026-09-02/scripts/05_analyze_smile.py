from pathlib import Path
import os
import math, warnings
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm, spearmanr
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import r2_score, mean_absolute_error, roc_auc_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV

warnings.filterwarnings('ignore')
B=Path(os.environ['NSGVC_WORK'])
R=Path(os.environ['NSGVC_SMILE'])
R.mkdir(exist_ok=True)
p=pd.read_csv(B/'vrp_model_corrected.csv',parse_dates=['date','expiry']).sort_values('date').copy()
p['year']=p.date.dt.year
p['log_ratio']=np.log(p['fwd_int_var'].clip(lower=1e-12)/p['iv_int_var'].clip(lower=1e-12))
p['premium_positive']=(p['fwd_int_var']<p['iv_int_var']).astype(int)
p['rv_beats_iv']=(p['fwd_int_var']>p['iv_int_var']).astype(int)
p['ratio_le_070']=(p['vrp_ratio']<=0.70).astype(int)

# Volume at 09:20, for QC
ov=pd.read_csv(B/'option_0920_entries_2023_2026.csv',parse_dates=['date'])
vp=ov.pivot_table(index='date',columns=['side','offset'],values='volume',aggfunc='last')
vp.columns=[f'VOL_{s}_{int(o):+d}' for s,o in vp.columns]
vp=vp.reset_index()
p=p.merge(vp,on='date',how='left')

RFR=0.06

def black_price(sig,F,K,T,df,side):
    if sig<=0 or T<=0:
        return df*max((F-K) if side=='CALL' else (K-F),0.0)
    v=sig*math.sqrt(T)
    d1=(math.log(F/K)+0.5*v*v)/v
    d2=d1-v
    if side=='CALL':
        return df*(F*norm.cdf(d1)-K*norm.cdf(d2))
    return df*(K*norm.cdf(-d2)-F*norm.cdf(-d1))

def invert_option(price,F,K,T,side,df):
    if not all(np.isfinite(x) for x in [price,F,K,T,df]) or price<=0 or F<=0 or K<=0 or T<=0: return np.nan
    intrinsic=df*max((F-K) if side=='CALL' else (K-F),0.0)
    upper=df*(F if side=='CALL' else K)
    if price <= intrinsic+1e-5 or price >= upper-1e-5: return np.nan
    f=lambda s:black_price(s,F,K,T,df,side)-price
    try:
        return brentq(f,1e-4,4.0,maxiter=100)
    except Exception:
        return np.nan

# Construct OTM IV smile using a common ATM parity-implied forward.
for j in range(-10,11):
    p[f'smile_iv_{j:+d}']=np.nan
    p[f'smile_px_{j:+d}']=np.nan
    p[f'smile_vol_{j:+d}']=np.nan

for idx,row in p.iterrows():
    F=float(row['forward']); K0=float(row['K']); T=float(row['T_cal']); atm=float(row['iv'])
    if not all(np.isfinite(x) and x>0 for x in [F,K0,T,atm]): continue
    df=math.exp(-RFR*T)
    p.at[idx,'smile_iv_+0']=atm
    p.at[idx,'smile_px_+0']=float(row['CALL_+0']+row['PUT_+0'])
    p.at[idx,'smile_vol_+0']=float(row.get('VOL_CALL_+0',0)+row.get('VOL_PUT_+0',0))
    for j in range(-10,11):
        if j==0: continue
        K=K0+50*j
        side='PUT' if K < F else 'CALL'
        col=f'{side}_{j:+d}'
        price=row.get(col,np.nan)
        vol=row.get(f'VOL_{side}_{j:+d}',np.nan)
        iv=invert_option(price,F,K,T,side,df)
        # Conservative print QC: require at least Rs 1 premium and positive minute volume.
        if not (np.isfinite(price) and price>=1.0 and np.isfinite(vol) and vol>0):
            iv=np.nan
        if np.isfinite(iv) and not (0.02 <= iv <= 1.5): iv=np.nan
        p.at[idx,f'smile_iv_{j:+d}']=iv
        p.at[idx,f'smile_px_{j:+d}']=price
        p.at[idx,f'smile_vol_{j:+d}']=vol

# Compact, pre-declared smile features at 100/200/300/400/500 points.
for dpts in [100,200,300,400,500]:
    j=dpts//50
    put=p[f'smile_iv_{-j:+d}']; call=p[f'smile_iv_{j:+d}']
    p[f'put_skew_{dpts}']=put-p['iv']
    p[f'call_skew_{dpts}']=call-p['iv']
    p[f'rr_{dpts}']=put-call  # positive = puts richer
    p[f'bf_{dpts}']=(put+call)/2-p['iv']
    p[f'wing_avg_{dpts}']=(put+call)/2

# Local quadratic fit in standardized log-moneyness units across +/-300 points.
def fit_shape(row,maxoff=6):
    xs=[]; ys=[]
    F=row['forward']; atm=row['iv']; T=row['T_cal']; K0=row['K']
    denom=atm*math.sqrt(T) if np.isfinite(atm) and np.isfinite(T) and atm>0 and T>0 else np.nan
    if not np.isfinite(denom) or denom<=0:return (np.nan,np.nan,np.nan,np.nan)
    for j in range(-maxoff,maxoff+1):
        iv=row.get(f'smile_iv_{j:+d}',np.nan)
        if not np.isfinite(iv): continue
        K=K0+50*j
        z=math.log(K/F)/denom
        if abs(z)>4.5: continue
        xs.append(z);ys.append(iv)
    if len(xs)<7 or np.ptp(xs)<0.5:return (np.nan,np.nan,np.nan,np.nan)
    X=np.column_stack([np.ones(len(xs)),xs,np.square(xs)])
    coef=np.linalg.lstsq(X,np.array(ys),rcond=None)[0]
    fitted=X@coef
    rmse=float(np.sqrt(np.mean((np.array(ys)-fitted)**2)))
    return float(coef[0]),float(coef[1]),float(coef[2]),rmse
shape=np.array([fit_shape(r) for _,r in p.iterrows()])
p[['smile_intercept','smile_slope','smile_curvature','smile_fit_rmse']]=shape

# Basic QC and feature coverage
qc=[]
for j in range(-10,11):
    col=f'smile_iv_{j:+d}'
    qc.append({'offset':j,'points':j*50,'coverage':p[col].notna().mean(),'median_iv':p[col].median(),'p05':p[col].quantile(.05),'p95':p[col].quantile(.95)})
qc=pd.DataFrame(qc)
qc.to_csv(R/'smile_iv_qc.csv',index=False)

features_shape=['rr_200','bf_200','rr_400','bf_400','smile_slope','smile_curvature']
features_shape_rich=['rr_100','bf_100','rr_200','bf_200','rr_300','bf_300','rr_400','bf_400','rr_500','bf_500','smile_slope','smile_curvature']
base_state=['log_iv_int','logT']
base_full=['lag1_logrv','lag5_logrv','lag22_logrv','log_iv_int','logT','open5_logvar','open5_range','abs_open5_ret','prev_ret']

# Use complete cases across compact feature set to make model comparisons apples-to-apples.
d=p.dropna(subset=['log_ratio']+base_full+features_shape).copy()
print('COMPLETE MODEL SAMPLE',d.groupby('year').size().to_dict())

# Fit standardized ridge with alpha chosen by time-series CV only in development sample.
def ridge_fit(train,cols):
    pipe=make_pipeline(StandardScaler(),Ridge())
    cv=TimeSeriesSplit(n_splits=5)
    gs=GridSearchCV(pipe,{'ridge__alpha':[0.01,0.1,1,10,100]},cv=cv,scoring='neg_mean_squared_error')
    gs.fit(train[cols],train['log_ratio'])
    return gs.best_estimator_,gs.best_params_['ridge__alpha']

def reg_metrics(dd,pred):
    return {'n':len(dd),'r2':r2_score(dd.log_ratio,pred),'corr':np.corrcoef(dd.log_ratio,pred)[0,1],'mae':mean_absolute_error(dd.log_ratio,pred)}

specs={
    'IV_state':base_state,
    'IV_plus_smile':base_state+features_shape,
    'HAR_IV_open':base_full,
    'HAR_IV_open_plus_smile':base_full+features_shape,
}
res=[]
dev=d[d.year.isin([2023,2024])];val=d[d.year==2025];test=d[d.year==2026]
for name,cols in specs.items():
    m,a=ridge_fit(dev,cols); pred=m.predict(val[cols]);res.append({'model':name,'split':'val','alpha':a,**reg_metrics(val,pred)})
    train=d[d.year.isin([2023,2024,2025])]
    m2,a2=ridge_fit(train,cols); pred2=m2.predict(test[cols]);res.append({'model':name,'split':'test','alpha':a2,**reg_metrics(test,pred2)})
regres=pd.DataFrame(res);regres.to_csv(R/'gap_models_with_smile.csv',index=False)
print('\nGAP MODELS')
print(regres.to_string(index=False))

# Classification: can smile identify dangerous cases where realized variance beats IV?
def logit_fit(train,cols,target):
    # fixed mild L2, standardize. Avoid tuning tiny class samples.
    m=make_pipeline(StandardScaler(),LogisticRegression(max_iter=2000,C=1.0,class_weight='balanced'))
    m.fit(train[cols],train[target]);return m
classres=[]
for target in ['rv_beats_iv','ratio_le_070']:
    for name,cols in specs.items():
        for splitname,tr,te in [('val',dev,val),('test',d[d.year.isin([2023,2024,2025])],test)]:
            if te[target].nunique()<2: continue
            m=logit_fit(tr,cols,target); prob=m.predict_proba(te[cols])[:,1]
            classres.append({'target':target,'model':name,'split':splitname,'n':len(te),'base_rate':te[target].mean(),'auc':roc_auc_score(te[target],prob),'brier':brier_score_loss(te[target],prob)})
classres=pd.DataFrame(classres);classres.to_csv(R/'gap_classification_with_smile.csv',index=False)
print('\nCLASSIFICATION')
print(classres.to_string(index=False))

# Univariate validation/test relationships for transparent interpretation.
uni=[]
for splitname,dd in [('dev',dev),('val',val),('test',test)]:
    for f in features_shape_rich:
        if f not in dd: continue
        z=dd[[f,'log_ratio','vrp_ratio','fwd_rv_cal']].dropna()
        if len(z)<20:continue
        uni.append({'split':splitname,'feature':f,'n':len(z),'spearman_log_ratio':z[f].corr(z.log_ratio,method='spearman'),'spearman_vrp_ratio':z[f].corr(z.vrp_ratio,method='spearman')})
uni=pd.DataFrame(uni);uni.to_csv(R/'smile_univariate_gap.csv',index=False)

# Merge smile into locked weekly candidates and examine preferred 500-wide iron fly.
locked=pd.read_csv(Path(os.environ['NSGVC_LOCKED_TRADES']),parse_dates=['date','expiry'])
smcols=['date']+features_shape_rich+['iv','T_cal','vrp_ratio','pred_ratio','spot_open_0920','expiry_spot']
locked=locked.merge(p[smcols],on='date',how='left',suffixes=('','_panel'))
locked['full_loss']=(np.isclose(locked['pnl'],-locked['maxloss'],atol=1e-6)).astype(int)
locked['loss']=(locked['net_R_cost2']<0).astype(int)
locked['abs_expiry_move']=np.abs(locked['expiry_spot']/locked['spot_open_0920']-1)
locked.to_csv(R/'locked_candidates_with_smile.csv',index=False)

# Strategy mapping: smile shape vs economics and outcome, by width and split.
strat=[]
for w in [400,500]:
    for sp in ['dev','val','test']:
        dd=locked[(locked.width==w)&(locked.split==sp)].copy()
        for f in ['rr_200','bf_200','rr_400','bf_400','rr_500','bf_500','smile_slope','smile_curvature']:
            z=dd[[f,'net_R_cost2','loss','full_loss','maxloss','credit','abs_expiry_move']].dropna()
            if len(z)<8: continue
            rec={'width':w,'split':sp,'feature':f,'n':len(z),
                 'rho_R':z[f].corr(z.net_R_cost2,method='spearman'),
                 'rho_abs_move':z[f].corr(z.abs_expiry_move,method='spearman'),
                 'rho_maxloss_pts':z[f].corr(z.maxloss,method='spearman')}
            if z.loss.nunique()>1:
                try: rec['auc_loss_raw']=roc_auc_score(z.loss,z[f])
                except: rec['auc_loss_raw']=np.nan
            if z.full_loss.nunique()>1:
                try: rec['auc_full_loss_raw']=roc_auc_score(z.full_loss,z[f])
                except: rec['auc_full_loss_raw']=np.nan
            strat.append(rec)
strat=pd.DataFrame(strat);strat.to_csv(R/'strategy_smile_relationships.csv',index=False)
print('\nSTRATEGY RELATIONSHIPS 500')
print(strat[strat.width==500].to_string(index=False))

# Frozen simple median splits based on development only, then evaluate val/test. Direction chosen from dev Spearman with R.
splits=[]
for w in [400,500]:
    d0=locked[(locked.width==w)&(locked.split=='dev')]
    for f in ['rr_200','bf_200','rr_400','bf_400','rr_500','bf_500','smile_slope','smile_curvature']:
        zz=d0[[f,'net_R_cost2']].dropna()
        if len(zz)<15:continue
        th=zz[f].median(); rho=zz[f].corr(zz.net_R_cost2,method='spearman')
        # favorable side is feature >= median if rho>0, else <= median
        direction='high' if rho>=0 else 'low'
        for sp in ['dev','val','test']:
            dd=locked[(locked.width==w)&(locked.split==sp)].dropna(subset=[f]).copy()
            sel=dd[dd[f]>=th] if direction=='high' else dd[dd[f]<=th]
            if not len(sel):continue
            splits.append({'width':w,'feature':f,'dev_threshold':th,'favored':direction,'split':sp,'n':len(sel),
                           'trade_rate':len(sel)/len(dd) if len(dd) else np.nan,
                           'mean_R':sel.net_R_cost2.mean(),'median_R':sel.net_R_cost2.median(),'win':(sel.net_R_cost2>0).mean(),
                           'full_loss_rate':sel.full_loss.mean(),'mean_pnl':sel.net_pnl_cost2.mean()})
medsplit=pd.DataFrame(splits);medsplit.to_csv(R/'strategy_dev_median_filters.csv',index=False)
print('\nDEV-MEDIAN FILTERS 500 TEST')
print(medsplit[(medsplit.width==500)&(medsplit.split.isin(['val','test']))].to_string(index=False))

# Direct economic mapping of BF to maxloss/credit ratio for all 400/500 locked trades.
locked['credit_frac']=locked['credit']/locked['width']
locked['risk_frac']=locked['maxloss']/locked['width']
print('\nECONOMIC CORRELATIONS')
for w in [400,500]:
    dd=locked[locked.width==w]
    for f in [f'bf_{w}',f'rr_{w}']:
        if f in dd:
            print(w,f,'rho credit_frac',dd[f].corr(dd.credit_frac,method='spearman'),'rho risk_frac',dd[f].corr(dd.risk_frac,method='spearman'))

# By quartile on compact key features using DEV cutpoints, preserve across later samples.
quart=[]
for f in ['rr_400','bf_400','rr_500','bf_500','smile_slope','smile_curvature']:
    vals=dev[f].dropna(); qs=vals.quantile([.25,.5,.75]).values
    bins=[-np.inf,*qs,np.inf]
    for sp,dd in [('dev',dev),('val',val),('test',test)]:
        x=dd.dropna(subset=[f]).copy(); x['bucket']=pd.cut(x[f],bins=bins,labels=['Q1','Q2','Q3','Q4'],include_lowest=True)
        for b,g in x.groupby('bucket',observed=True):
            quart.append({'feature':f,'split':sp,'bucket':str(b),'n':len(g),'mean_log_ratio':g.log_ratio.mean(),'mean_ratio':g.vrp_ratio.mean(),'rv_beats_iv':g.rv_beats_iv.mean(),'mean_fwd_rv_cal':g.fwd_rv_cal.mean()})
quart=pd.DataFrame(quart);quart.to_csv(R/'smile_dev_quartiles.csv',index=False)

p.to_csv(R/'smile_daily_panel.csv',index=False)
print('\nQC')
print(qc.to_string(index=False))
print('\nSaved to',R)
