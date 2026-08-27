#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
tmp=$(mktemp -d /private/tmp/shaurya-ops-release.XXXXXX)
trap 'find "$tmp" -depth -delete' EXIT INT TERM
export PYTHONDONTWRITEBYTECODE=1 SOURCE_DATE_EPOCH=1700000000
fixture="$root/tests/ops/fixtures/portable_fixture_driver.py"
source_commit=$(/usr/bin/git -C "$root" rev-parse --verify HEAD)
mkdir "$tmp/a" "$tmp/b" "$tmp/c"
"$root/ops/package_release.sh" --output-dir "$tmp/a" --version 1.0.0 --source-epoch "$SOURCE_DATE_EPOCH" --source-commit "$source_commit" >/dev/null
"$root/ops/package_release.sh" --output-dir "$tmp/b" --version 1.0.0 --source-epoch "$SOURCE_DATE_EPOCH" --source-commit "$source_commit" >/dev/null
cmp "$tmp/a/kotak-1.0.0.tar.gz" "$tmp/b/kotak-1.0.0.tar.gz"
cmp "$tmp/a/kotak-1.0.0.manifest.json" "$tmp/b/kotak-1.0.0.manifest.json"
"$root/ops/verify_manifest.sh" "$tmp/a/kotak-1.0.0.manifest.json" "$tmp/a/kotak-1.0.0.tar.gz" >/dev/null
mkdir "$tmp/bad"
python3 - "$tmp/bad" <<'PY'
import hashlib,json,sys,tarfile
from io import BytesIO
from pathlib import Path
root=Path(sys.argv[1]); payload=b'x'; digest=hashlib.sha256(payload).hexdigest()
def emit(name, members, files):
    archive=root/f'{name}.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for member,data in members:
            bundle.addfile(member, None if data is None else BytesIO(data))
    manifest={'schema_version':'1.0.0','release_version':name,'compatibility_version':'1','source_commit':'1'*40,'source_epoch':1,'archive_digest':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}
    (root/f'{name}.json').write_text(json.dumps(manifest,sort_keys=True,separators=(',',':'))+'\n')
def entry(path, mode='0644', size=1, sha=digest):
    return {'path':path,'sha256':sha,'size':size,'mode':mode,'role':'fixture'}
info=tarfile.TarInfo('file');info.size=1;info.mode=0o755;emit('wrong-mode',[(info,payload)],[entry('file')])
for name,kind in [('symlink',tarfile.SYMTYPE),('hardlink',tarfile.LNKTYPE)]:
    info=tarfile.TarInfo('file');info.type=kind;info.linkname='../outside';info.mode=0o644
    emit(name,[(info,None)],[entry('file',size=0,sha=hashlib.sha256(b'').hexdigest())])
info=tarfile.TarInfo('../escape');info.size=1;info.mode=0o644;emit('traversal',[(info,payload)],[entry('../escape')])
info=tarfile.TarInfo('a');info.size=1;info.mode=0o644;emit('partial',[(info,payload)],[entry('a'),entry('b')])
info=tarfile.TarInfo('file');info.size=1;info.mode=0o644;emit('duplicate',[(info,payload)],[entry('file'),entry('file')])
PY
for bad in wrong-mode symlink hardlink traversal partial duplicate; do
  if "$root/ops/verify_manifest.sh" "$tmp/bad/$bad.json" "$tmp/bad/$bad.tar.gz" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
done
if "$root/ops/package_release.sh" --output-dir "$tmp/c" --version 2.0.0 --source-epoch "$SOURCE_DATE_EPOCH" --source-commit "$source_commit" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if "$root/ops/package_release.sh" --output-dir "$tmp/c" --version 1.0.0 --source-epoch "$SOURCE_DATE_EPOCH" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
if "$root/ops/package_release.sh" --output-dir "$tmp/c" --version 1.0.0 --source-epoch "$SOURCE_DATE_EPOCH" --source-commit 1111111111111111111111111111111111111111 >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
HOME="$tmp/package-home" XDG_STATE_HOME="$tmp/package-state" FIXTURE_TOOL_MODE=package FIXTURE_RELEASE_VERSION=2.0.0 "$fixture" --output-dir "$tmp/c" --version 2.0.0 --source-epoch "$SOURCE_DATE_EPOCH" --source-commit "$source_commit" >/dev/null
for lane in one two; do
  home="$tmp/$lane/home"; prefix="$tmp/$lane/prefix"; mkdir -p "$home" "$prefix"; printf foreign > "$prefix/foreign.txt"
  if [ "$lane" = one ]; then
    printf '%s\n' '{"pid":999999,"schema_version":"1.0.0","token":"00000000-0000-4000-8000-000000000001"}' > "$prefix/.kotak-release-operation.lock"
    chmod 600 "$prefix/.kotak-release-operation.lock"
  fi
  HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/install.sh" --prefix "$prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
  HOME="$home" "$prefix/bin/kotak" version | grep -q 'kotak 1.0.0'
  mkdir -p "$home/.config/kotak"
  chmod 700 "$home/.config" "$home/.config/kotak"
  cp "$root/ops/manifests/deployment.example.json" "$home/.config/kotak/deployment.json"
  cp "$root/ops/manifests/operator-device.example.json" "$home/.config/kotak/operator-device.json"
  /usr/bin/ssh-keygen -q -t ed25519 -N '' -f "$home/.config/kotak/operator_ed25519"
  python3 -B - "$home/.config/kotak/operator_ed25519.pub" "$home/.config/kotak/operator-device.json" "$home/.config/kotak/known_hosts" <<'PY'
import base64,hashlib,json,sys
public=open(sys.argv[1]).read().strip().split(); blob=base64.b64decode(public[1])
p=sys.argv[2]; value=json.load(open(p)); value['public_key_fingerprint']='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
open(p,'w').write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
open(sys.argv[3],'w').write('shaurya-fixture '+public[0]+' '+public[1]+'\n')
PY
  chmod 600 "$home/.config/kotak/operator_ed25519" "$home/.config/kotak/known_hosts"
  HOME="$home" XDG_CONFIG_HOME="$home/.config" XDG_STATE_HOME="$tmp/$lane/state" "$prefix/bin/kotak" doctor | grep -q 'status=success'
  for command in doctor status preflight; do
    HOME="$home" XDG_CONFIG_HOME="$home/.config" XDG_STATE_HOME="$tmp/$lane/state" "$prefix/bin/kotak" "$command" --dry-run | grep -q 'status=dry_run'
  done
  HOME="$home" XDG_CONFIG_HOME="$home/.config" XDG_STATE_HOME="$tmp/$lane/state" "$prefix/bin/kotak" auth --dry-run --confirm KOTAK_AUTH | grep -q 'status=dry_run'
  HOME="$home" XDG_CONFIG_HOME="$home/.config" XDG_STATE_HOME="$tmp/$lane/state" "$prefix/bin/kotak" prepare --dry-run --confirm SHAURYA_PREPARE | grep -q 'status=dry_run'
  for command in shaurya-shadow-launch shadow-launch; do
    HOME="$home" XDG_CONFIG_HOME="$home/.config" XDG_STATE_HOME="$tmp/$lane/state" "$prefix/bin/kotak" "$command" --dry-run --confirm SHAURYA_SHADOW_LAUNCH | grep -q 'status=dry_run'
  done
  HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/install.sh" --prefix "$prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null
  [ "$(readlink "$prefix/libexec/kotak/current")" = 'releases/2.0.0' ]
  [ "$(readlink "$prefix/libexec/kotak/previous")" = 'releases/1.0.0' ]
  if [ "$lane" = one ]; then
    chmod 600 "$prefix/libexec/kotak/releases/1.0.0/README.md"
    if HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/install.sh" --prefix "$prefix" --rollback 1.0.0 >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
    [ "$(readlink "$prefix/libexec/kotak/current")" = 'releases/2.0.0' ]
    chmod 644 "$prefix/libexec/kotak/releases/1.0.0/README.md"
    cp "$prefix/libexec/kotak/releases/1.0.0/release-manifest.json" "$tmp/release-manifest.saved"
    python3 - "$prefix/libexec/kotak/releases/1.0.0/release-manifest.json" <<'PY'
import json,sys
p=sys.argv[1];d=json.load(open(p));d['source_epoch']+=1;open(p,'w').write(json.dumps(d,sort_keys=True,separators=(',',':'))+'\n')
PY
    if HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/install.sh" --prefix "$prefix" --rollback 1.0.0 >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
    [ "$(readlink "$prefix/libexec/kotak/current")" = 'releases/2.0.0' ]
    cp "$tmp/release-manifest.saved" "$prefix/libexec/kotak/releases/1.0.0/release-manifest.json"
  fi
  HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/install.sh" --prefix "$prefix" --rollback 1.0.0 >/dev/null
  [ "$(readlink "$prefix/libexec/kotak/current")" = 'releases/1.0.0' ]
  shasum -a 256 "$prefix/libexec/kotak/installed-manifest.json" "$prefix/libexec/kotak/releases/1.0.0/release-manifest.json" | awk '{print $1}' > "$tmp/$lane-installed-hashes"
  cp "$prefix/libexec/kotak/installed-manifest.json" "$tmp/$lane-installed.json"
  if [ "$lane" = one ]; then
    cp "$tmp/$lane-installed.json" "$tmp/mismatched-installed.json"
    python3 - "$tmp/mismatched-installed.json" <<'PY'
import json,sys
p=sys.argv[1];d=json.load(open(p));d['current_version']='foreign';open(p,'w').write(json.dumps(d,sort_keys=True,separators=(',',':'))+'\n')
PY
    if HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/uninstall.sh" --prefix "$prefix" --installed-manifest "$tmp/mismatched-installed.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
    cp "$prefix/libexec/kotak/release-index.json" "$tmp/release-index.saved"
    printf '\n' >> "$prefix/libexec/kotak/release-index.json"
    if HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/uninstall.sh" --prefix "$prefix" --installed-manifest "$tmp/$lane-installed.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
    cp "$tmp/release-index.saved" "$prefix/libexec/kotak/release-index.json"
  fi
  HOME="$home" XDG_STATE_HOME="$tmp/$lane/state" "$root/ops/uninstall.sh" --prefix "$prefix" --installed-manifest "$tmp/$lane-installed.json" >/dev/null
  [ "$(cat "$prefix/foreign.txt")" = foreign ]
  [ ! -e "$prefix/libexec/kotak" ]
  [ ! -e "$prefix/bin/kotak" ]
done
cmp "$tmp/one-installed-hashes" "$tmp/two-installed-hashes"
digest_one=$(shasum -a 256 "$tmp/a/kotak-1.0.0.tar.gz" | awk '{print $1}')
digest_two=$(shasum -a 256 "$tmp/b/kotak-1.0.0.tar.gz" | awk '{print $1}')
[ "$digest_one" = "$digest_two" ]
if HOME="$tmp/home" "$root/ops/install.sh" --prefix / --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
foreign_prefix="$tmp/foreign-prefix"
mkdir -p "$foreign_prefix/libexec/kotak"
ln -s ../../outside "$foreign_prefix/libexec/kotak/current"
if HOME="$tmp/foreign-home" XDG_STATE_HOME="$tmp/foreign-state" "$root/ops/install.sh" --prefix "$foreign_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(readlink "$foreign_prefix/libexec/kotak/current")" = ../../outside ]
[ ! -e "$foreign_prefix/libexec/kotak/releases" ]
modified_prefix="$tmp/modified-prefix"
modified_home="$tmp/modified-home"
HOME="$modified_home" XDG_STATE_HOME="$tmp/modified-state" "$root/ops/install.sh" --prefix "$modified_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
cp "$modified_prefix/libexec/kotak/installed-manifest.json" "$tmp/modified-installed.json"
printf '%s\n' '# operator-owned modification' >> "$modified_prefix/bin/kotak"
modified_digest=$(shasum -a 256 "$modified_prefix/bin/kotak" | awk '{print $1}')
index_digest=$(shasum -a 256 "$modified_prefix/libexec/kotak/release-index.json" | awk '{print $1}')
if HOME="$modified_home" XDG_STATE_HOME="$tmp/modified-state" "$root/ops/install.sh" --prefix "$modified_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(readlink "$modified_prefix/libexec/kotak/current")" = 'releases/1.0.0' ]
[ ! -e "$modified_prefix/libexec/kotak/releases/2.0.0" ]
[ "$(shasum -a 256 "$modified_prefix/libexec/kotak/release-index.json" | awk '{print $1}')" = "$index_digest" ]
if HOME="$modified_home" XDG_STATE_HOME="$tmp/modified-state" "$root/ops/uninstall.sh" --prefix "$modified_prefix" --installed-manifest "$tmp/modified-installed.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(shasum -a 256 "$modified_prefix/bin/kotak" | awk '{print $1}')" = "$modified_digest" ]
[ -L "$modified_prefix/libexec/kotak/current" ] && [ -f "$modified_prefix/libexec/kotak/installed-manifest.json" ]
interrupted_prefix="$tmp/interrupted-prefix"
HOME="$tmp/interrupted-home" XDG_STATE_HOME="$tmp/interrupted-state" "$root/ops/install.sh" --prefix "$interrupted_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
interrupted_index=$(shasum -a 256 "$interrupted_prefix/libexec/kotak/release-index.json" | awk '{print $1}')
if HOME="$tmp/interrupted-home" XDG_STATE_HOME="$tmp/interrupted-state" FIXTURE_INTERRUPT=after_stage FIXTURE_TOOL_MODE=install "$fixture" --prefix "$interrupted_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 70 ]; fi
[ "$(readlink "$interrupted_prefix/libexec/kotak/current")" = 'releases/1.0.0' ]
[ ! -e "$interrupted_prefix/libexec/kotak/releases/2.0.0" ]
[ -z "$(find "$interrupted_prefix/libexec/kotak/releases" -maxdepth 1 -type d -name '.staging-2.0.0-*' -print)" ]
[ "$(shasum -a 256 "$interrupted_prefix/libexec/kotak/release-index.json" | awk '{print $1}')" = "$interrupted_index" ]

# Every update interruption keeps the old launcher runnable; the next install recovers then completes.
for point in before_release_publish after_release_publish after_current after_previous after_index after_installed; do
  crash_prefix="$tmp/crash-$point/prefix"; crash_home="$tmp/crash-$point/home"; crash_state="$tmp/crash-$point/state"
  mkdir -p "$crash_home"
  HOME="$crash_home" XDG_STATE_HOME="$crash_state" "$root/ops/install.sh" --prefix "$crash_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
  if HOME="$crash_home" XDG_STATE_HOME="$crash_state" FIXTURE_POWER_LOSS="$point" FIXTURE_TOOL_MODE=install "$fixture" --prefix "$crash_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 99 ]; fi
  "$crash_prefix/bin/kotak" version | grep -q '^kotak 1.0.0 compatibility=1$'
  [ -f "$crash_prefix/libexec/kotak/transaction.json" ]
  [ "$(readlink "$crash_prefix/libexec/kotak/transaction-current")" = releases/1.0.0 ]
  HOME="$crash_home" XDG_STATE_HOME="$crash_state" "$root/ops/install.sh" --prefix "$crash_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null
  [ "$(readlink "$crash_prefix/libexec/kotak/current")" = releases/2.0.0 ]
  [ ! -e "$crash_prefix/libexec/kotak/transaction.json" ]
done

# Every uninstall transaction boundary, including manifest/directory removal, resumes safely.
for point in uninstall_after_stage uninstall_after_commit uninstall_before_manifest_remove uninstall_after_manifest uninstall_after_release uninstall_after_launcher_stage uninstall_after_metadata uninstall_after_stage_directory uninstall_after_releases_directory uninstall_after_journal; do
  stop_prefix="$tmp/stop-$point/prefix"; stop_home="$tmp/stop-$point/home"; stop_state="$tmp/stop-$point/state"
  HOME="$stop_home" XDG_STATE_HOME="$stop_state" "$root/ops/install.sh" --prefix "$stop_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
  cp "$stop_prefix/libexec/kotak/installed-manifest.json" "$tmp/stop-$point-installed.json"
  printf foreign > "$stop_prefix/foreign.txt"
  if HOME="$stop_home" XDG_STATE_HOME="$stop_state" FIXTURE_POWER_LOSS="$point" FIXTURE_TOOL_MODE=uninstall "$fixture" --prefix "$stop_prefix" --installed-manifest "$tmp/stop-$point-installed.json" >/dev/null; then exit 1; else [ "$?" -eq 99 ]; fi
  if [ "$point" = uninstall_after_journal ]; then
    [ ! -e "$stop_prefix/libexec/kotak/uninstall-transaction.json" ]
  else
    [ -f "$stop_prefix/libexec/kotak/uninstall-transaction.json" ]
  fi
  if "$stop_prefix/bin/kotak" version >/dev/null 2>&1; then exit 1; fi
  HOME="$stop_home" XDG_STATE_HOME="$stop_state" "$root/ops/uninstall.sh" --prefix "$stop_prefix" --installed-manifest "$tmp/stop-$point-installed.json" >/dev/null
  [ "$(cat "$stop_prefix/foreign.txt")" = foreign ]
  [ ! -e "$stop_prefix/libexec/kotak" ]
done

# Full installed-byte attestation checks inactive owned releases as well as current.
attest_prefix="$tmp/attest-prefix"; attest_home="$tmp/attest-home"; attest_state="$tmp/attest-state"
HOME="$attest_home" XDG_STATE_HOME="$attest_state" "$root/ops/install.sh" --prefix "$attest_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
HOME="$attest_home" XDG_STATE_HOME="$attest_state" "$root/ops/install.sh" --prefix "$attest_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null
mkdir -p "$attest_home/.config/kotak"; chmod 700 "$attest_home" "$attest_home/.config" "$attest_home/.config/kotak"
cp "$root/ops/manifests/deployment.example.json" "$attest_home/.config/kotak/deployment.json"
cp "$root/ops/manifests/operator-device.example.json" "$attest_home/.config/kotak/operator-device.json"
printf '\n' >> "$attest_prefix/libexec/kotak/releases/1.0.0/README.md"
if HOME="$attest_home" XDG_CONFIG_HOME="$attest_home/.config" XDG_STATE_HOME="$attest_state" "$attest_prefix/bin/kotak" doctor >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
cp "$root/ops/README.md" "$attest_prefix/libexec/kotak/releases/1.0.0/README.md"
printf '%s\n' 1111111111111111111111111111111111111111 > "$attest_prefix/libexec/kotak/releases/2.0.0/SOURCE_REVISION"
if HOME="$attest_home" XDG_CONFIG_HOME="$attest_home/.config" XDG_STATE_HOME="$attest_state" "$attest_prefix/bin/kotak" doctor >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi

# A 64-entry index cannot accept a 65th release and leaves current unchanged.
cap_prefix="$tmp/cap-prefix"
HOME="$tmp/cap-home" XDG_STATE_HOME="$tmp/cap-state" "$root/ops/install.sh" --prefix "$cap_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
python3 -B - "$cap_prefix/libexec/kotak/release-index.json" <<'PY'
import json,sys
p=sys.argv[1];v=json.load(open(p));v.update({f'foreign-{i:02d}':'f'*64 for i in range(63)});open(p,'w').write(json.dumps(v,sort_keys=True,separators=(',',':'))+'\n')
PY
if HOME="$tmp/cap-home" XDG_STATE_HOME="$tmp/cap-state" "$root/ops/install.sh" --prefix "$cap_prefix" --archive "$tmp/c/kotak-2.0.0.tar.gz" --manifest "$tmp/c/kotak-2.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(readlink "$cap_prefix/libexec/kotak/current")" = releases/1.0.0 ]

# Lexical traversal cannot normalize into a broad prefix.
for unsafe in "$tmp/.." "$HOME/child/.." /Users /usr /usr/local /opt /private/tmp "$(dirname "$HOME")"; do
  if HOME="$tmp/home" XDG_STATE_HOME="$tmp/traversal-state" "$root/ops/install.sh" --prefix "$unsafe" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
done

# An identical pre-existing launcher is never claimed or removed by the manifest.
preserve="$tmp/preserve-prefix"; mkdir -p "$preserve/bin"
printf '%s' '#!/bin/sh
set -eu
case "$0" in */*) parent=${0%/*} ;; *) parent=. ;; esac
prefix=$(CDPATH= cd -- "$parent/.." && pwd -P)
base=$prefix/libexec/kotak
case "${1-}" in --internal-*) printf "%s\n" "[KOTAK_RESULT] command=parser status=usage_refused code=2 verified=no"; exit 2 ;; esac
if [ -e "$base/transaction.json" ]; then [ -L "$base/transaction-current" ] || exit 70; exec "$base/transaction-current/kotak" "$@"; fi
[ ! -e "$base/uninstall-transaction.json" ] || exit 70
[ -L "$base/current" ] || exit 70
exec "$base/current/kotak" "$@"
' > "$preserve/bin/kotak"; chmod 755 "$preserve/bin/kotak"
HOME="$tmp/preserve-home" XDG_STATE_HOME="$tmp/preserve-state" "$root/ops/install.sh" --prefix "$preserve" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
cp "$preserve/libexec/kotak/installed-manifest.json" "$tmp/preserve-installed.json"
HOME="$tmp/preserve-home" XDG_STATE_HOME="$tmp/preserve-state" "$root/ops/uninstall.sh" --prefix "$preserve" --installed-manifest "$tmp/preserve-installed.json" >/dev/null
[ -f "$preserve/bin/kotak" ]

# An unexpected previous pointer is foreign state and blocks removal.
unexpected="$tmp/unexpected-prefix"
HOME="$tmp/unexpected-home" XDG_STATE_HOME="$tmp/unexpected-state" "$root/ops/install.sh" --prefix "$unexpected" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
cp "$unexpected/libexec/kotak/installed-manifest.json" "$tmp/unexpected-installed.json"
ln -s releases/1.0.0 "$unexpected/libexec/kotak/previous"
if HOME="$tmp/unexpected-home" XDG_STATE_HOME="$tmp/unexpected-state" "$root/ops/uninstall.sh" --prefix "$unexpected" --installed-manifest "$tmp/unexpected-installed.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ -L "$unexpected/libexec/kotak/current" ] && [ -f "$unexpected/bin/kotak" ]
rm "$unexpected/libexec/kotak/previous"
HOME="$tmp/unexpected-home" XDG_STATE_HOME="$tmp/unexpected-state" "$root/ops/uninstall.sh" --prefix "$unexpected" --installed-manifest "$tmp/unexpected-installed.json" >/dev/null

# The kernel-backed prefix lock refuses a live holder and recovers an unlocked stale record.
lock_prefix="$tmp/lock-prefix"; mkdir -p "$lock_prefix"
/usr/bin/python3 -B - "$lock_prefix/.kotak-release-operation.lock" "$tmp/lock-ready" <<'PY' &
import fcntl,os,sys,time
fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600); fcntl.flock(fd,fcntl.LOCK_EX)
open(sys.argv[2],'w').write('ready\n'); time.sleep(4)
PY
lock_pid=$!
while [ ! -f "$tmp/lock-ready" ]; do :; done
if HOME="$tmp/lock-home" XDG_STATE_HOME="$tmp/lock-state" "$root/ops/install.sh" --prefix "$lock_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
kill "$lock_pid" 2>/dev/null || true; wait "$lock_pid" 2>/dev/null || true
HOME="$tmp/lock-home" XDG_STATE_HOME="$tmp/lock-state" "$root/ops/install.sh" --prefix "$lock_prefix" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null

# Omitting --prefix uses only the isolated HOME/.local default.
default_home="$tmp/default-home"; mkdir -p "$default_home"
HOME="$default_home" XDG_STATE_HOME="$tmp/default-state" "$root/ops/install.sh" --archive "$tmp/a/kotak-1.0.0.tar.gz" --manifest "$tmp/a/kotak-1.0.0.manifest.json" >/dev/null
[ -x "$default_home/.local/bin/kotak" ]
cp "$default_home/.local/libexec/kotak/installed-manifest.json" "$tmp/default-installed.json"
HOME="$default_home" XDG_STATE_HOME="$tmp/default-state" "$root/ops/uninstall.sh" --installed-manifest "$tmp/default-installed.json" >/dev/null
[ ! -e "$default_home/.local/libexec/kotak" ]

# Packaged bytes expose no production fixture/test dependency override.
mkdir "$tmp/scan"; tar -xzf "$tmp/a/kotak-1.0.0.tar.gz" -C "$tmp/scan"
if rg -n 'KOTAK_TEST_MODE|KOTAK_TEST_|KOTAK_TOOL_MODE|KOTAK_INVOCATION_ID|FIXTURE_' "$tmp/scan" >/dev/null; then exit 1; fi
printf 'test_portable_release: PASS archive_sha256=%s isolated_homes=2\n' "$digest_one"
