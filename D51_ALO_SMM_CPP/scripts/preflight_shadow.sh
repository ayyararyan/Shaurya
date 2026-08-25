#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 - <<'PY'
import csv, json, os, sys
from collections import defaultdict
from pathlib import Path
cfg=json.loads(Path('config/alo_smm.json').read_text())
errors=[]
if cfg.get('mode')!='shadow': errors.append('config mode must be shadow')
ft=int(cfg.get('futures',{}).get('token',0) or 0)
if ft<=0: errors.append('futures.token is still zero')
p=Path(cfg.get('paths',{}).get('instruments_csv','config/instruments.csv'))
if not p.exists(): errors.append(f'missing instrument file: {p}')
else:
    rows=[]
    with p.open() as f:
        lines=(ln for ln in f if not ln.lstrip().startswith('#'))
        rows=list(csv.DictReader(lines))
    if not rows: errors.append('instrument file is empty')
    pairs=defaultdict(set)
    dummy=False
    for r in rows:
        try:
            tok=int(r.get('token','0'))
            if 100000 <= tok <= 100999: dummy=True
        except Exception: pass
        pairs[(r.get('expiry_unix_ns'),r.get('strike'))].add(r.get('cp'))
    npairs=sum(v>={'CE','PE'} for v in pairs.values())
    minpairs=int(cfg.get('quality',{}).get('min_surface_pairs',5))+1
    if npairs<minpairs: errors.append(f'need at least {minpairs} paired strikes, found {npairs}')
    if dummy: errors.append('instrument file still appears to contain packaged dummy tokens')
for k in ['KOTAK_CONSUMER_KEY','KOTAK_MOBILE','KOTAK_UCC','KOTAK_MPIN']:
    if not os.getenv(k): errors.append(f'missing environment variable {k}')
if not (os.getenv('KOTAK_TOTP_SECRET') or os.getenv('KOTAK_TOTP')):
    errors.append('set KOTAK_TOTP_SECRET or a current KOTAK_TOTP')
if os.getenv('ALO_LIVE_ACK') or os.getenv('ALO_LIVE_START_FLAT_ACK'):
    errors.append('live acknowledgement variables must not be set during shadow month')
if errors:
    print('SHADOW PREFLIGHT FAILED:', file=sys.stderr)
    for e in errors: print(' - '+e, file=sys.stderr)
    sys.exit(2)
print(f'SHADOW PREFLIGHT PASS: futures_token={ft}, paired_strikes={npairs}')
PY
