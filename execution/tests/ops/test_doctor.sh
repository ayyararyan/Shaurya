#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
tmp=$(mktemp -d /private/tmp/shaurya-ops-doctor.XXXXXX)
trap 'find "$tmp" -depth -delete' EXIT INT TERM
export PYTHONDONTWRITEBYTECODE=1 HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/config" XDG_STATE_HOME="$tmp/state"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/kotak"
chmod 700 "$HOME" "$XDG_CONFIG_HOME" "$XDG_CONFIG_HOME/kotak"

if "$root/ops/kotak" doctor >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if "$root/ops/kotak" --internal-uninstall >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi

# The POSIX bootstrap keeps help/version available and doctor factual when no Python candidate exists.
mkdir -p "$tmp/bootstrap/libexec"; cp "$root/ops/kotak" "$tmp/bootstrap/kotak"
printf '%s\n' '#!/bin/sh' 'exit 70' > "$tmp/bootstrap/libexec/select-python"
chmod 755 "$tmp/bootstrap/kotak" "$tmp/bootstrap/libexec/select-python"
PATH=/nonexistent KOTAK_PYTHON=/foreign "$tmp/bootstrap/kotak" help | grep -q '^kotak 1.0.0$'
PATH=/nonexistent KOTAK_PYTHON=/foreign "$tmp/bootstrap/kotak" version | grep -q 'compatibility=1'
if PATH=/nonexistent KOTAK_PYTHON=/foreign "$tmp/bootstrap/kotak" help extra >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if PATH=/nonexistent KOTAK_PYTHON=/foreign "$tmp/bootstrap/kotak" --help extra >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if output=$(PATH=/nonexistent KOTAK_PYTHON=/foreign "$tmp/bootstrap/kotak" doctor); then exit 1; else [ "$?" -eq 70 ]; fi
[ "$output" = '[KOTAK_RESULT] command=doctor status=python_unavailable code=70 verified=no' ]

selected=$("$root/ops/libexec/select-python")
"$selected" -I -S -E -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)'
if [ -x /usr/bin/python3 ]; then
  /usr/bin/python3 -I -B "$root/ops/libexec/portable_ops.py" help | grep -q '^kotak 1.0.0$'
fi

# Hostile PATH programs cannot participate in script location or runtime selection.
mkdir "$tmp/poison"
printf '%s\n' '#!/bin/sh' "printf poison > '$tmp/poison-used'" 'exit 99' > "$tmp/poison/dirname"
chmod 755 "$tmp/poison/dirname"
PATH="$tmp/poison" "$root/ops/kotak" help >/dev/null
if PATH="$tmp/poison" "$root/ops/kotak" doctor >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if PATH="$tmp/poison" "$root/ops/install.sh" >/dev/null 2>&1; then exit 1; else [ "$?" -eq 2 ]; fi
[ ! -e "$tmp/poison-used" ]

printf '%s' '{"schema_version":"1.0.0","schema_version":"1.0.0"}' > "$tmp/bad.json"
chmod 600 "$tmp/bad.json"
if /usr/bin/python3 -B - "$root" "$tmp/bad.json" <<'PY'
import importlib.util,sys
from pathlib import Path
source=Path(sys.argv[1])/'ops/libexec/portable_ops.py'
spec=importlib.util.spec_from_file_location('doctor_test',source); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
try: module.validate_deployment(Path(sys.argv[2]))
except module.OpsError: raise SystemExit(3)
raise SystemExit(0)
PY
then exit 1; else [ "$?" -eq 3 ]; fi

# The deployment source-tree pin is mandatory and exact even when an attacker
# recomputes the manifest's self-checksum after deleting or corrupting it.
/usr/bin/python3 -B - "$root" "$tmp" <<'PY'
import hashlib,importlib.util,json,sys
from pathlib import Path
root,temp=Path(sys.argv[1]),Path(sys.argv[2]); source=root/'ops/libexec/portable_ops.py'
spec=importlib.util.spec_from_file_location('doctor_source_tree_test',source)
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
original=json.loads((root/'ops/manifests/deployment.example.json').read_text())
for name,mutate in (("missing",lambda value:value.pop("executor_source_tree_sha256")),
                    ("wrong",lambda value:value.__setitem__("executor_source_tree_sha256","not-a-digest"))):
    value=dict(original); mutate(value); value["deployment_manifest_digest"]="0"*64
    value["deployment_manifest_digest"]=hashlib.sha256(module.canonical(value)).hexdigest()
    path=temp/f"deployment-{name}.json"; path.write_bytes(module.canonical(value)); path.chmod(0o600)
    try: module.validate_deployment(path)
    except module.OpsError: pass
    else: raise SystemExit(f"{name} executor source-tree pin accepted")
PY

# Offline capability checks are explicit and fail closed on unsupported platform/architecture/dependencies.
/usr/bin/python3 -B - "$root" <<'PY'
import importlib.util,sys
from pathlib import Path
source=Path(sys.argv[1])/'ops/libexec/portable_ops.py'
spec=importlib.util.spec_from_file_location('doctor_capability_test',source); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
class WrongPlatform(module.ProductionDependencies):
    def local_platform(self): return 'linux'
class WrongArchitecture(module.ProductionDependencies):
    def local_architecture(self): return 'sparc'
class MissingDependency(module.ProductionDependencies):
    def required_local_commands(self): return ('/private/tmp/definitely-missing-shaurya-command',)
for dependency in (WrongPlatform(),WrongArchitecture(),MissingDependency()):
    try: module.validate_local_capabilities(dependency)
    except module.OpsError as error:
        assert error.exit_code == module.EXIT_USAGE
    else: raise SystemExit('unsupported local environment accepted')
PY

printf '%s\n' 'test_doctor: PASS'
