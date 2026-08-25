#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="D51_ALO_SMM_shadow_month_${STAMP}.zip"
python3 - "$OUT" <<'PY'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import sys
root=Path('.')
out=sys.argv[1]
keep=['stats','state','config/alo_smm.json','config/instruments.csv','docs','README.md','VERSION','VALIDATION.md']
with ZipFile(out,'w',ZIP_DEFLATED) as z:
    for item in keep:
        p=root/item
        if p.is_file(): z.write(p,p.as_posix())
        elif p.is_dir():
            for f in p.rglob('*'):
                if f.is_file(): z.write(f,f.as_posix())
print(out)
PY
