import zipfile, re, csv, io, math, os
from pathlib import Path
import pandas as pd, numpy as np

B=Path(os.environ['NSGVC_WORK'])
# -------- Spot minute panel --------
spot_zip=Path(os.environ['NSGVC_SPOT_ZIP'])
frames=[]
with zipfile.ZipFile(spot_zip) as z:
    names=[n for n in z.namelist() if n.endswith('__NIFTY__1m.csv')]
    for n in names:
        # include 2022 onward for lags
        m=re.search(r'/monthly/(\d{4})/', n)
        if not m or int(m.group(1))<2022: continue
        df=pd.read_csv(z.open(n))
        # normalize schema
        df.columns=[c.lower() for c in df.columns]
        if 'datetime' not in df.columns: continue
        dt=pd.to_datetime(df['datetime'], errors='coerce')
        df=df.assign(datetime=dt)
        df=df.dropna(subset=['datetime'])
        # timezone timestamps converted/read already; keep local clock from strings if needed
        frames.append(df[['datetime','open','high','low','close']])
spot=pd.concat(frames, ignore_index=True).drop_duplicates('datetime').sort_values('datetime')
# convert to local naive for easy grouping
if getattr(spot['datetime'].dt,'tz',None) is not None:
    spot['datetime']=spot['datetime'].dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
spot['date']=spot['datetime'].dt.normalize()
spot['time']=spot['datetime'].dt.strftime('%H:%M')
spot=spot[(spot['time']>='09:15') & (spot['time']<='15:29')].copy()
spot.to_csv(B/'spot_2022_2026.csv', index=False)
print('spot',len(spot),spot.date.nunique(),spot.datetime.min(),spot.datetime.max())

# -------- Option 09:20 open panel, all offsets/sides --------
pat=re.compile(r'(?:.*/)?data/(?P<year>\d{4})/(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})__WEEK1__(?P<tag>ATM(?:[+-]\d+)?)__(?P<side>CALL|PUT)__1m\.csv$')
rows=[]
for zp in [Path(os.environ['NSGVC_OPTION_ZIP'])]:
    with zipfile.ZipFile(zp) as z:
        for name in z.namelist():
            m=pat.match(name)
            if not m: continue
            tag=m.group('tag'); off=0 if tag=='ATM' else int(tag[3:]); side=m.group('side')
            with z.open(name) as fh:
                header=fh.readline().decode('utf-8').strip().split(',')
                # scan raw lines; datetime begins yyyy-mm-dd HH:MM
                for b in fh:
                    if len(b)<16: continue
                    if b[11:16] != b'09:20': continue
                    a=b.decode('utf-8').rstrip().split(',')
                    if len(a)<6: continue
                    try:
                        dt=a[0][:19]
                        op=float(a[1]); hi=float(a[2]); lo=float(a[3]); cl=float(a[4]); vol=float(a[5])
                    except Exception:
                        continue
                    rows.append((dt[:10], int(m.group('year')), off, side, op, hi, lo, cl, vol))
opt=pd.DataFrame(rows,columns=['date','source_year','offset','side','open','high','low','close','volume'])
# The frozen package declares its option-data/training window as beginning
# 2023-01-23. The consolidated archive also contains 15 earlier January 2023
# sessions, which are intentionally outside that frozen research universe.
opt=opt[(opt['source_year']>=2023)&(opt['date']>='2023-01-23')].copy()
opt=opt.drop_duplicates(['date','offset','side'],keep='last').sort_values(['date','side','offset'])
opt.to_csv(B/'option_0920_entries_2023_2026.csv',index=False)
print('opt rows',len(opt),'dates',opt.date.nunique(),'range',opt.date.min(),opt.date.max())
print(opt.groupby(['source_year','side']).size())
