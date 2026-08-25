#!/usr/bin/env python3
"""Create ALO-SMM option instruments.csv from a Kotak derivative scrip master.

Optionally updates the front NIFTY futures token/symbol/lot size in alo_smm.json.
The script is intentionally tolerant of common Kotak master-column aliases; inspect
its output before every run because broker master formats can change.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,json,re,sys
from pathlib import Path
from zoneinfo import ZoneInfo

ALIASES={
 'token':['pSymbol','token','instrumentToken','instrument_token'],
 'symbol':['pTrdSymbol','tradingSymbol','trading_symbol','symbol'],
 'name':['pSymbolName','pAssetCode','underlying','symbolName','name'],
 'cp':['pOptionType','optionType','option_type'],
 'strike':['dStrikePrice','dStrikePrice;','strikePrice','strike_price','strike'],
 'expiry':['pExpiryDate','lExpiryDate','expiryDate','expiry_date','expiry'],
 'ref_key':['pScripRefKey','scripRefKey','scrip_ref_key'],
 'lot':['lLotSize','lotSize','lot_size'],
 'tick':['dTickSize','tickSize','tick_size'],
 'inst':['pInstType','pInstName','instrumentType','instrument_type'],
}
IST=ZoneInfo('Asia/Kolkata')
KOTAK_NSE_FO_EPOCH_OFFSET_SECONDS=315511200

def field(row,key):
    for k in ALIASES[key]:
        if k in row and str(row[k]).strip()!='': return str(row[k]).strip()
    return ''
def parse_num(s):
    s=s.replace(',','').strip(); return float(s) if s else 0.0

def parse_ref_expiry(ref_key):
    match=re.search(r'(\d{1,2})([A-Z]{3})(\d{2})',ref_key.strip().upper())
    if not match:raise ValueError(f'cannot parse expiry from pScripRefKey {ref_key!r}')
    day,month,year=match.groups()
    try:return dt.datetime.strptime(f'{int(day):02d}{month}20{year}','%d%b%Y').date()
    except ValueError as exc:raise ValueError(f'invalid expiry in pScripRefKey {ref_key!r}') from exc

def parse_expiry(s,ref_key,*,today=None):
    s=s.strip()
    parsed=None
    if re.fullmatch(r'\d+(?:\.0+)?',s):
        x=int(float(s))
        seconds=None
        if x>10**15:seconds=x/1e9
        elif x>10**12:seconds=x/1e3
        elif x>10**9:seconds=x
        if seconds is not None:
            parsed=dt.datetime.fromtimestamp(
                seconds+KOTAK_NSE_FO_EPOCH_OFFSET_SECONDS,dt.timezone.utc
            )
    if parsed is None:
        for fmt in ('%d-%b-%Y','%d%b%Y','%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
            try:
                d=dt.datetime.strptime(s,fmt).date()
                parsed=dt.datetime.combine(d,dt.time(15,30),IST).astimezone(dt.timezone.utc)
                break
            except ValueError:pass
    if parsed is None:raise ValueError(f'cannot parse expiry {s!r}')

    parsed_date=parsed.astimezone(IST).date()
    ref_date=parse_ref_expiry(ref_key)
    if parsed_date!=ref_date:
        raise ValueError(
            f'expiry mismatch: pExpiryDate {s!r} implies {parsed_date}, '
            f'pScripRefKey {ref_key!r} implies {ref_date}'
        )
    today=today or dt.datetime.now(IST).date()
    if parsed_date<today:
        raise ValueError(f'expired contract: expiry {parsed_date} is before today {today}')
    return dt.datetime.combine(ref_date,dt.time(15,30),IST).astimezone(dt.timezone.utc)

def normalize_strike(s):
    strike=parse_num(s)
    while strike>=100000:strike/=100
    return strike
def cp_norm(s):
    u=s.upper()
    if 'CE' in u or u in {'C','CALL'}: return 'CE'
    if 'PE' in u or u in {'P','PUT'}: return 'PE'
    return ''
def is_target(name,underlying):
    u=name.upper(); t=underlying.upper()
    if t not in u:return False
    if t=='NIFTY' and any(x in u for x in ('BANKNIFTY','FINNIFTY','MIDCPNIFTY')):return False
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--master',required=True)
    ap.add_argument('--underlying',default='NIFTY')
    ap.add_argument('--center',type=float,required=True,help='Approximate spot/futures level used only to choose strike window')
    ap.add_argument('--width',type=int,default=7,help='Number of strike steps each side of center')
    ap.add_argument('--step',type=float,default=50)
    ap.add_argument('--expiry',help='Option expiry date YYYY-MM-DD; default nearest future expiry')
    ap.add_argument('--out',default='config/instruments.csv')
    ap.add_argument('--update-config',default='',help='Optional alo_smm.json to update with front futures token/symbol/lot size')
    args=ap.parse_args()

    text=Path(args.master).read_text(errors='replace');sample=text[:8192]
    try:dialect=csv.Sniffer().sniff(sample,delimiters=',;|\t')
    except csv.Error:dialect=csv.excel
    rows=list(csv.DictReader(text.splitlines(),dialect=dialect));today=dt.datetime.now(IST).date()
    opts=[];futs=[]
    for r in rows:
        name=' '.join([field(r,'name'),field(r,'symbol')]).upper()
        if not is_target(name,args.underlying):continue
        try:ex=parse_expiry(field(r,'expiry'),field(r,'ref_key'),today=today)
        except Exception as exc:
            print(
                f"WARNING: skipping {field(r,'symbol') or field(r,'ref_key') or '<unknown>'}: {exc}",
                file=sys.stderr,
            )
            continue
        try:token=int(float(field(r,'token')))
        except Exception:continue
        if token<=0:continue
        sym=field(r,'symbol');lot=int(parse_num(field(r,'lot')) or 65);tick=parse_num(field(r,'tick')) or .05
        cp=cp_norm(field(r,'cp'))
        inst=field(r,'inst').upper()
        if cp:
            try:strike=normalize_strike(field(r,'strike'))
            except Exception:continue
            if strike>0:opts.append((ex,strike,cp,token,sym,lot,tick))
        elif 'FUT' in inst or 'FUT' in sym.upper():
            futs.append((ex,token,sym,lot))

    if not opts:raise SystemExit('No matching option rows. Inspect master columns/underlying naming.')
    if args.expiry:
        target=dt.date.fromisoformat(args.expiry)
        candidates=[x for x in opts if x[0].astimezone(ZoneInfo('Asia/Kolkata')).date()==target]
    else:
        nearest=min(x[0] for x in opts);candidates=[x for x in opts if x[0]==nearest]
    lo=args.center-args.width*args.step;hi=args.center+args.width*args.step
    candidates=[x for x in candidates if lo-1e-9<=x[1]<=hi+1e-9]
    have={}
    for x in candidates:have.setdefault(x[1],set()).add(x[2])
    candidates=[x for x in candidates if have.get(x[1])=={'CE','PE'}]
    candidates.sort(key=lambda x:(x[1],x[2]))
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['token','exchange_segment','trading_symbol','cp','strike','expiry_unix_ns','lot_size','tick_size'])
        for ex,strike,cp,token,sym,lot,tick in candidates:w.writerow([token,'nse_fo',sym,cp,f'{strike:g}',int(ex.timestamp()*1e9),lot,tick])
    print(f'Wrote {len(candidates)} option contracts ({len(candidates)//2} paired strikes) to {out}')
    if len(candidates)<12:print('WARNING: fewer than six paired strikes; surface quality may fail.',file=sys.stderr)

    if args.update_config:
        if not futs:raise SystemExit('Options written, but no matching NIFTY future found; config not updated.')
        front=min(futs,key=lambda x:x[0])
        cfg_path=Path(args.update_config);cfg=json.loads(cfg_path.read_text())
        cfg.setdefault('futures',{})['token']=front[1];cfg['futures']['symbol']=front[2];cfg['futures']['lot_size']=front[3]
        cfg_path.write_text(json.dumps(cfg,indent=2)+'\n')
        print(f'Updated front future in {cfg_path}: token={front[1]} symbol={front[2]} lot={front[3]} expiry={front[0].date()}')

if __name__=='__main__':main()
