#!/usr/bin/env python3
import base64, hashlib, json, os, pty, select, subprocess, tempfile, time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
fixture = root / "tests/ops/fixtures/portable_fixture_driver.py"
with tempfile.TemporaryDirectory(prefix="shaurya-ops-auth-", dir="/private/tmp") as raw:
    temp = Path(raw); (temp/"home").mkdir(); (temp/"config/kotak").mkdir(parents=True); (temp/"responses").mkdir(); (temp/"held").mkdir()
    for path in (temp/"home", temp/"config", temp/"config/kotak"): path.chmod(0o700)
    (temp/"config/kotak/deployment.json").write_bytes((root/"ops/manifests/deployment.example.json").read_bytes())
    identity=temp/"config/kotak/operator_ed25519"
    subprocess.run(["/usr/bin/ssh-keygen","-q","-t","ed25519","-N","","-f",str(identity)],check=True)
    public=identity.with_suffix(".pub").read_text().strip().split(); blob=base64.b64decode(public[1])
    operator=json.loads((root/"ops/manifests/operator-device.example.json").read_text())
    operator["public_key_fingerprint"]="SHA256:"+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    (temp/"config/kotak/operator-device.json").write_text(json.dumps(operator,sort_keys=True,separators=(",",":"))+"\n")
    (temp/"config/kotak/known_hosts").write_text("shaurya-fixture "+public[0]+" "+public[1]+"\n")
    identity.chmod(0o600); (temp/"config/kotak/known_hosts").chmod(0o600)
    (temp/"chain").mkdir(); (temp/"chain").chmod(0o700)
    deployment=json.loads((temp/"config/kotak/deployment.json").read_text())
    status={"status":"ok","remote_os":deployment["expected_remote_os"],
            "remote_architecture":deployment["expected_remote_architecture"],
            "executor_commit":deployment["executor_commit"],"executor_source_state":"clean",
            "executor_source_tree_sha256":deployment["executor_source_tree_sha256"],
            "executor_build_digest":deployment["executor_build_digest"],
            "deployment_digest":deployment["deployment_manifest_digest"],"live_gate":"OFF","unit_status":"inactive",
            "timer_present":False,"protocol_versions":deployment["protocol_versions"],
            "auth_helper_digest":deployment["auth_helper_digest"],"doctor_helper_digest":deployment["doctor_helper_digest"],
            "broker_helper_digest":deployment["broker_helper_digest"],"protocol_helper_digest":deployment["protocol_helper_digest"],
            "watcher_digest":deployment["watcher_digest"],"orchestration_unit":deployment["orchestration_unit"],
            "unit_template_digest":deployment["unit_template_digest"],
            "execution_session_id":"00000000-0000-4000-8000-000000000003"}
    (temp/"remote-status.json").write_text(json.dumps(status,sort_keys=True,separators=(",",":"))+"\n")
    (temp/"responses/doctor.json").write_text(json.dumps(status,sort_keys=True,separators=(",",":"))+"\n")
    env = {"HOME":str(temp/"home"),"XDG_CONFIG_HOME":str(temp/"config"),"XDG_STATE_HOME":str(temp/"state"),
           "PYTHONDONTWRITEBYTECODE":"1","FIXTURE_SSH_BIN":str(root/"tests/ops/fixtures/bin/ssh"),
           "FIXTURE_SSH_RECORD":str(temp/"record"),"FIXTURE_RESPONSE_DIR":str(temp/"responses"),"FIXTURE_REPO_ROOT":str(root),
           "FIXTURE_SSH_IDENTITY":str(identity),"FIXTURE_REMOTE_STATUS":str(temp/"remote-status.json"),
           "FIXTURE_CHAIN_ROOT":str(temp/"chain"),"FIXTURE_CHAIN_RECORD":str(temp/"chain.record"),
           "FIXTURE_TRANSPORT_SNAPSHOT_ROOT":str(temp/"held")}
    # No terminal prompt or diagnostic bytes exist until a secret-free doctor
    # connection has matched every pinned deployment measurement.
    mismatched=dict(status); mismatched["executor_source_tree_sha256"]="f"*64
    (temp/"responses/doctor.json").write_text(json.dumps(mismatched,sort_keys=True,separators=(",",":"))+"\n")
    refused=subprocess.run([str(fixture),"auth","--confirm","KOTAK_AUTH"],env=env,
                           stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if refused.returncode!=5 or b"unverified" not in refused.stdout: raise SystemExit("auth preflight mismatch accepted")
    if b"stdin_sha256=" in (temp/"record").read_bytes(): raise SystemExit("auth bytes sent before doctor trust")
    (temp/"responses/doctor.json").write_text(json.dumps(status,sort_keys=True,separators=(",",":"))+"\n")
    (temp/"record").unlink()
    wrapper=root/"ops/libexec/kotak-remote-doctor"
    invalid_env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LANG":"C","SSH_ORIGINAL_COMMAND":"arbitrary-command"}
    if subprocess.run([str(wrapper)],env=invalid_env,stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False).returncode!=3:
        raise SystemExit("forced-command wrapper accepted an open command")
    pid, fd = pty.fork()
    if pid == 0: os.execve(str(fixture), ["kotak","auth","--confirm","KOTAK_AUTH"], env)
    captured = b""
    while b"diagnostic code:" not in captured.lower():
        ready,_,_=select.select([fd],[],[],5)
        if not ready: raise SystemExit("prompt timeout")
        captured += os.read(fd,4096)
    synthetic=b"654321"; os.write(fd,synthetic+b"\n"); deadline=time.monotonic()+10; status=None
    while time.monotonic()<deadline:
        ready,_,_=select.select([fd],[],[],0.1)
        if ready:
            try: captured += os.read(fd,4096)
            except OSError: pass
        waited, candidate=os.waitpid(pid,os.WNOHANG)
        if waited==pid: status=candidate; break
    if status is None: os.kill(pid,9); os.waitpid(pid,0); raise SystemExit("auth completion timeout")
    if os.waitstatus_to_exitcode(status)!=0: raise SystemExit(captured)
    record=(temp/"record").read_bytes()
    if synthetic in captured or synthetic in record: raise SystemExit("secret leaked")
    if hashlib.sha256(synthetic+b"\n").hexdigest().encode() not in record: raise SystemExit("transport digest absent")
    if "doctor:auth\n" not in (temp/"chain.record").read_text(): raise SystemExit("auth bypassed doctor attestation")
    if b"arg=shaurya-operator-v1\n" not in record: raise SystemExit("auth bypassed forced-command token")
    if b"identity_fd_consumed=yes\n" not in record: raise SystemExit("ssh fixture did not consume identity descriptor")
    if b"known_hosts_fd_consumed=yes\n" not in record or b"transport_fds_unlinked_read_only=yes\n" not in record:
        raise SystemExit("ssh fixture did not consume immutable trust snapshots")
    if record.count(b"arg=shaurya-operator-v1\n") != 2: raise SystemExit("auth did not use measured forced-command boundary twice")
    if b"authenticated" in captured or b"status=diagnostic" not in captured or b"verified=no" not in captured: raise SystemExit("unsafe auth output")
    if any((temp/"held").iterdir()): raise SystemExit("named transport snapshot residue")
    for path in temp.rglob("*"):
        if path.is_file() and synthetic in path.read_bytes(): raise SystemExit("persistent secret bytes")
    before=set(temp.rglob("*")); result=subprocess.run([str(fixture),"auth","--dry-run","--confirm","KOTAK_AUTH"],env=env,stdout=subprocess.PIPE,check=True)
    if b"dry_run" not in result.stdout or set(temp.rglob("*"))!=before: raise SystemExit("dry-run mutation")
    wrong=subprocess.run([str(fixture),"auth","--dry-run","--confirm","WRONG"],env=env,stdout=subprocess.PIPE,check=False)
    if wrong.returncode!=2 or b"confirmation_refused" not in wrong.stdout: raise SystemExit("dry-run confirmation accepted")
    helper=root/"ops/libexec/kotak-auth-helper"
    for invalid in (b"", b"12345\n", b"1234567\n", b"12x456\n"):
        checked=subprocess.run([str(helper)],input=invalid,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        if checked.returncode!=2 or checked.stdout or (invalid.strip() and invalid.strip() in checked.stderr): raise SystemExit("invalid auth disclosure")

    import importlib.util
    source=root/"ops/libexec/portable_ops.py"; spec=importlib.util.spec_from_file_location("auth_validation",source)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    deployment=module.validate_deployment(temp/"config/kotak/deployment.json")
    if not module.validate_remote_response("auth",{"status":"synthetic_transport_only","diagnostic_ok":True},deployment):
        raise SystemExit("diagnostic response refused")
    if module.validate_remote_response("auth",{"status":"synthetic_transport_only","diagnostic_ok":True,"authenticated":True},deployment):
        raise SystemExit("authentication claim accepted")

    fixture_spec=importlib.util.spec_from_file_location("auth_fixture_dependencies",root/"tests/ops/fixtures/portable_fixture_driver.py")
    fixture_module=importlib.util.module_from_spec(fixture_spec); fixture_spec.loader.exec_module(fixture_module)
    saved_environment=dict(os.environ); os.environ.clear(); os.environ.update(env)
    try:
        candidate=temp/"auth-hash-mismatch"; candidate.write_text("#!/bin/sh\nprintf '{}\\n'\n"); candidate.chmod(0o755)
        cases=[("hash-mismatch", {"FIXTURE_AUTH_HELPER":str(candidate)}, module.EXIT_REFUSAL),
               ("result-loss", {"FIXTURE_DROP_AUTH_RESPONSE":"1"}, module.EXIT_UNAVAILABLE),
               ("refusal", {"FIXTURE_AUTH_REFUSAL":"1"}, module.EXIT_REFUSAL)]
        for name,settings,expected in cases:
            for key,value in settings.items(): os.environ[key]=value
            secret=bytearray(b"123456\n")
            try: code,response=module.run_remote("auth",deployment,secret,fixture_module.FixtureDependencies())
            finally:
                module.wipe_bytearray(secret)
                for key in settings: os.environ.pop(key,None)
            if code==module.EXIT_SUCCESS and not module.validate_remote_response("auth",response or {},deployment):
                code=module.EXIT_UNAVAILABLE
            if code!=expected or any(secret): raise SystemExit(f"auth {name} classification/wipe failed: {code}")
        os.environ["FIXTURE_SSH_DELAY"]="6"
        secret=bytearray(b"123456\n")
        try: code,_=module.run_remote("auth",deployment,secret,fixture_module.FixtureDependencies())
        finally: module.wipe_bytearray(secret)
        if code!=module.EXIT_TIMEOUT or any(secret): raise SystemExit("auth timeout classification/wipe failed")
    finally:
        os.environ.clear(); os.environ.update(saved_environment)

    class InterruptedTerminal:
        def __init__(self): self.restored=False; self.closed=False
        def open(self): return 9
        def disable_echo(self, descriptor): return object()
        def write_prompt(self, descriptor): return None
        def read_byte(self, descriptor): raise KeyboardInterrupt()
        def restore_echo(self, descriptor, state): self.restored=True
        def write_newline(self, descriptor): return None
        def close(self, descriptor): self.closed=True
    terminal=InterruptedTerminal(); wiped=[]; original=module.wipe_bytearray
    def observe(value):
        original(value); wiped.append(bytes(value))
    module.wipe_bytearray=observe
    try:
        try: module.hidden_code(terminal)
        except module.OpsError as error:
            if error.code!="auth_interrupted": raise
        else: raise SystemExit("auth interruption accepted")
    finally: module.wipe_bytearray=original
    if not terminal.restored or not terminal.closed or not wiped or any(any(item) for item in wiped):
        raise SystemExit("auth interruption did not restore and wipe")
print("test_auth_transport: PASS")
