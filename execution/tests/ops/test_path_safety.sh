#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
tmp=$(mktemp -d /private/tmp/shaurya-ops-path-safety.XXXXXX)
trap 'find "$tmp" -depth -delete' EXIT INT TERM
export PYTHONDONTWRITEBYTECODE=1
fixture="$root/tests/ops/fixtures/portable_fixture_driver.py"
source_commit=$(/usr/bin/git -C "$root" rev-parse --verify HEAD)

# Test dependency injection cannot escape to a real home or a non-temporary
# remote/service state root even if the environment requests it.
personal_root=/"Users"/aryanayyar
if HOME="$personal_root" XDG_CONFIG_HOME="$personal_root/.config" "$fixture" help >/dev/null 2>&1; then exit 1; fi
if HOME="$tmp/home" FIXTURE_CHAIN_ROOT="$personal_root" \
   "$root/tests/ops/fixtures/remote_fixture_driver.py" doctor doctor >/dev/null 2>&1; then exit 1; fi

mkdir -p "$tmp/home" "$tmp/config/kotak" "$tmp/foreign-state"
chmod 700 "$tmp/home" "$tmp/config" "$tmp/config/kotak" "$tmp/foreign-state"
cp "$root/ops/manifests/deployment.example.json" "$tmp/config/kotak/deployment.json"
cp "$root/ops/manifests/operator-device.example.json" "$tmp/config/kotak/operator-device.json"
cat > "$tmp/release.json" <<'EOF'
{"archive_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","compatibility_version":"1","files":[{"mode":"0644","path":"fixture","role":"fixture","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","size":1}],"release_version":"fixture-1","schema_version":"1.0.0","source_commit":"1111111111111111111111111111111111111111","source_epoch":1}
EOF
chmod 644 "$tmp/release.json"
if HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/config" XDG_STATE_HOME="$tmp/state" FIXTURE_RELEASE_MANIFEST="$tmp/release.json" FIXTURE_STATE_SWAP_TARGET="$tmp/foreign-state" "$fixture" prepare --confirm SHAURYA_PREPARE >/dev/null; then
  exit 1
else
  [ "$?" -eq 2 ]
fi
[ -z "$(find "$tmp/foreign-state" -mindepth 1 -maxdepth 1 -print)" ]
[ -L "$tmp/state/kotak" ]

mkdir -p "$tmp/foreign-config/kotak"
chmod 700 "$tmp/foreign-config" "$tmp/foreign-config/kotak"
ln -s "$tmp/foreign-config" "$tmp/config-link"
if HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/config-link" XDG_STATE_HOME="$tmp/safe-state" "$root/ops/kotak" doctor >/dev/null; then
  exit 1
else
  [ "$?" -eq 2 ]
fi

mkdir "$tmp/package" "$tmp/foreign-lock"
chmod 700 "$tmp/package" "$tmp/foreign-lock"
printf '%s\n' foreign > "$tmp/foreign-lock/operator-file"
"$root/ops/package_release.sh" --output-dir "$tmp/package" --version 1.0.0 --source-epoch 1700000000 --source-commit "$source_commit" >/dev/null
if HOME="$tmp/home" XDG_STATE_HOME="$tmp/lock-state" FIXTURE_LOCK_SWAP_TARGET="$tmp/foreign-lock" FIXTURE_TOOL_MODE=install "$fixture" --prefix "$tmp/lock-prefix" --archive "$tmp/package/kotak-1.0.0.tar.gz" --manifest "$tmp/package/kotak-1.0.0.manifest.json" >/dev/null; then
  exit 1
else
  [ "$?" -eq 2 ]
fi
[ "$(cat "$tmp/foreign-lock/operator-file")" = foreign ]
[ -L "$tmp/lock-prefix/.kotak-release-operation.lock" ]
[ ! -e "$tmp/lock-prefix/libexec" ]

mkdir "$tmp/prefix" "$tmp/foreign-prefix"
chmod 700 "$tmp/prefix" "$tmp/foreign-prefix"
printf '%s\n' foreign > "$tmp/foreign-prefix/operator-file"
if HOME="$tmp/home" XDG_STATE_HOME="$tmp/prefix-state" FIXTURE_PREFIX_SWAP_TARGET="$tmp/foreign-prefix" FIXTURE_TOOL_MODE=install "$fixture" --prefix "$tmp/prefix" --archive "$tmp/package/kotak-1.0.0.tar.gz" --manifest "$tmp/package/kotak-1.0.0.manifest.json" >/dev/null; then
  exit 1
else
  [ "$?" -eq 2 ]
fi
[ "$(cat "$tmp/foreign-prefix/operator-file")" = foreign ]
[ ! -e "$tmp/foreign-prefix/libexec" ]

python3 -B - "$root" "$tmp" <<'PY'
import importlib.util,os,sys
from pathlib import Path
root=Path(sys.argv[1]); source=root/'ops/libexec/portable_ops.py'
spec=importlib.util.spec_from_file_location('portable_ops_path_test',source); module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
deployment=module.validate_deployment(root/'ops/manifests/deployment.example.json')
remote_source=root/'ops/libexec/remote_protocol.py'
remote_spec=importlib.util.spec_from_file_location('remote_protocol_path_test',remote_source)
remote=importlib.util.module_from_spec(remote_spec);remote_spec.loader.exec_module(remote)
if remote.canonical_deployment_digest(root/'ops/manifests/deployment.example.json') != deployment['deployment_manifest_digest']:
    raise SystemExit('local and remote deployment digest algorithms diverged')
digest='d'*64; tree='e'*64; commit='1'*40
sample=(f'shaurya-executor 0.1.0 mode=shadow kotak_live=off commit={commit} '
        f'source_state=clean source_tree_sha256={tree} build_sha256={digest}\n').encode()
assert remote.parse_executor_version(sample,digest)==(commit,'clean',tree,digest)
try: remote.parse_executor_version(sample,'e'*64)
except remote.ProtocolError: pass
else: raise SystemExit('executor self-reported digest was trusted')
dirty=sample.replace(b'source_state=clean',b'source_state=dirty')
try: remote.parse_executor_version(dirty,digest)
except remote.ProtocolError: pass
else: raise SystemExit('dirty executor source was trusted')
for malformed in (sample.replace(b' source_tree_sha256='+tree.encode(),b''),):
    try: remote.parse_executor_version(malformed,digest)
    except remote.ProtocolError: pass
    else: raise SystemExit('missing executor source tree was trusted')
wrong_tree=sample.replace(tree.encode(),b'f'*64)
if remote.parse_executor_version(wrong_tree,digest)[2] != 'f'*64:
    raise SystemExit('executor source tree was not surfaced for deployment comparison')
# Exercise the real ProductionDependencies.status comparison branch with
# protected-I/O probes. Syntactically valid but unverified evidence is
# unavailable (5), never a verified remote refusal (3).
deployment=dict(deployment)
status={"status":"ok","remote_os":"linux","remote_architecture":"x86_64",
        "executor_commit":deployment["executor_commit"],"executor_source_state":"clean",
        "executor_source_tree_sha256":deployment["executor_source_tree_sha256"],
        "executor_build_digest":deployment["executor_build_digest"],
        "deployment_digest":deployment["deployment_manifest_digest"],"live_gate":"OFF",
        "unit_status":"inactive","timer_present":False,"protocol_versions":deployment["protocol_versions"],
        "auth_helper_digest":deployment["auth_helper_digest"],"doctor_helper_digest":deployment["doctor_helper_digest"],
        "broker_helper_digest":deployment["broker_helper_digest"],"protocol_helper_digest":deployment["protocol_helper_digest"],
        "watcher_digest":deployment["watcher_digest"],"orchestration_unit":deployment["orchestration_unit"],
        "unit_template_digest":remote.EXPECTED_UNIT_DIGEST,
        "execution_session_id":"00000000-0000-4000-8000-000000000003"}
class StatusProbe(remote.ProductionDependencies):
    def system(self): return "linux"
    def architecture(self): return "x86_64"
    def verify_unit_template(self): return None
    def executor_version(self):
        return deployment["executor_commit"],"clean","f"*64,deployment["executor_build_digest"]
saved=(remote.load_json,remote.load_deployment,remote.digest_fixed_file,remote.load_any_json,remote.subprocess.run)
class Completed:
    returncode=0; stdout=b""
remote.load_json=lambda *_:dict(status)
remote.load_deployment=lambda *_:dict(deployment)
remote.digest_fixed_file=lambda path: status[next(key for key in status if key.endswith("_digest") and key.startswith({
    "kotak-auth-helper":"auth_helper","kotak-remote-doctor":"doctor_helper","shaurya-session-broker":"broker_helper",
    "remote_protocol.py":"protocol_helper","shaurya-shadow-watcher":"watcher"}[path.name]))]
remote.load_any_json=lambda *_:{"execution_session_id":status["execution_session_id"]}
remote.subprocess.run=lambda *args,**kwargs:Completed()
try:
    try: StatusProbe().status()
    except remote.ProtocolError as error:
        if error.code != remote.EXIT_UNAVAILABLE: raise SystemExit(f'production status mismatch classified {error.code}, not 5')
    else: raise SystemExit('production status accepted wrong source tree')
finally:
    remote.load_json,remote.load_deployment,remote.digest_fixed_file,remote.load_any_json,remote.subprocess.run=saved
held=Path(sys.argv[2])/'fsync-root'; held.mkdir(); held.chmod(0o700)
with remote.HeldDirectory(held) as directory:
    observed=[]; real_fsync=remote.os.fsync
    remote.os.fsync=lambda descriptor: observed.append(descriptor)
    try: remote.write_at(directory,'durable.tombstone',b'{}\n')
    finally: remote.os.fsync=real_fsync
    if directory.fd not in observed: raise SystemExit('tombstone directory was not fsynced')
os.environ.pop('KOTAK_TEST_MODE',None)
os.environ['KOTAK_SSH_BIN']=str(root/'tests/ops/fixtures/bin/ssh')
if module.ProductionDependencies().ssh_path != '/usr/bin/ssh': raise SystemExit('production SSH override was honored')
PY

printf '%s\n' 'test_path_safety: PASS'
