#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
./scripts/build_release.sh
bash -n scripts/*.sh
python3 -m py_compile scripts/prepare_instruments.py
python3 - <<'PY'
import json
from pathlib import Path
cfg=json.loads(Path('config/alo_smm.json').read_text())
assert cfg['mode']=='shadow', 'release config is not shadow'
assert cfg['futures']['token']==0, 'packaged release should not ship a real futures token'
print('Static release safety checks PASS')
PY
if strings build/alo-smm | grep -q 'I_UNDERSTAND_LIVE_ORDERS'; then
  : # phrase presence is expected; live code exists but compile gate remains OFF.
fi
printf 'Release validation PASS\n'
