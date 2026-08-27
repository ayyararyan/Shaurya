#!/usr/bin/python3
"""Non-packaged fake remote dependencies for remote_protocol tests."""
import contextlib, hashlib, importlib.util, io, json, os, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[3]
source = root / "ops/libexec/remote_protocol.py"
spec = importlib.util.spec_from_file_location("remote_protocol_fixture", source)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class FixtureDependencies:
    def __init__(self):
        boundary = Path("/private/tmp").resolve()
        if not self.root().resolve().is_relative_to(boundary): raise SystemExit("hermetic remote root escape")
    def system(self): return "linux"
    def architecture(self): return "x86_64"
    def root(self): return Path(os.environ["FIXTURE_CHAIN_ROOT"])
    def status(self): return module.load_json(Path(os.environ["FIXTURE_REMOTE_STATUS"]), module.STATUS_FIELDS)
    def claim_root(self): return self.root()
    def result_path(self, claim_id): return self.root() / f"{claim_id}.result.json"
    def result_root(self): return self.root()
    def now_ns(self): return time.time_ns()
    def record(self, component):
        path = Path(os.environ["FIXTURE_CHAIN_RECORD"])
        with path.open("a", encoding="ascii") as output: output.write(component + "\n")
    def adversarial_swap(self, point, claim=None):
        selected = os.environ.get("FIXTURE_REMOTE_SWAP_POINT")
        if selected != point: return
        if point in {"after_attestation_write", "after_claim_write"}:
            target = Path(os.environ["FIXTURE_REMOTE_SWAP_TARGET"]); held = self.root().with_name(self.root().name + ".held")
            os.rename(self.root(), held); os.symlink(target, self.root())
            return
        if point == "after_result_read" and claim is not None:
            target = Path(os.environ["FIXTURE_REMOTE_SWAP_TARGET"])
            os.replace(target, self.result_path(claim["claim_id"]))
    def bind_executor_config(self, claim_id, attestation_path, attestation_digest):
        status = self.status(); path = self.root() / f"{claim_id}.executor.json"
        attestation = module.load_json(attestation_path, module.ATTESTATION_FIELDS)
        config = {"execution_session_id": status["execution_session_id"], "launch_attestation_root": str(self.root()),
                  "expected_cli_release_digest": attestation["cli_release_digest"],
                  "expected_deployment_manifest_digest": attestation["deployment_manifest_digest"],
                  "expected_executor_build_digest": attestation["executor_build_digest"],
                  "maximum_launch_attestation_age_ns": 10_000_000_000, "mode": "shadow", "schema_version": "1.0.0"}
        path.write_bytes(module.canonical(config)); os.chmod(path, 0o600)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        runtime = {"peer_digest": attestation["cli_release_digest"], "executable_digest": status["executor_build_digest"],
                   "config_digest": digest, "orchestration_unit": module.UNIT_TEMPLATE, "unit_pinned": True,
                   "live_gate": "OFF", "replay": False, "executor_config_path": str(path),
                   "launch_attestation_path": str(attestation_path), "launch_attestation_digest": attestation_digest,
                   "execution_session_id": status["execution_session_id"]}
        runtime_path = self.root() / f"{claim_id}.runtime.json"; runtime_path.write_bytes(module.canonical(runtime)); os.chmod(runtime_path, 0o600)
        return path, digest
    def runtime(self, claim, attestation):
        if attestation["invocation_id"] != claim["claim_id"]: raise module.ProtocolError()
        return module.load_json(self.root() / f"{claim['claim_id']}.runtime.json", module.RUNTIME_FIELDS)
    def verify_sibling(self, component, path):
        key = {"auth": "auth_helper_digest", "broker": "broker_helper_digest", "watcher": "watcher_digest"}[component]
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.status()[key]: raise module.ProtocolError(module.EXIT_REFUSAL)
    def start(self, instance):
        if os.environ.get("FIXTURE_START_REFUSAL") == "1": raise module.ProtocolError(module.EXIT_REFUSAL)
        claim_id = instance.removeprefix("shaurya-shadow-once@").removesuffix(".service")
        claim = module.load_json(self.root() / f"{claim_id}.claim.json", module.CLAIM_FIELDS)
        evidence = {"invocation_id": claim_id, "unit_instance": instance,
                    "attestation_digest": claim["attestation_digest"], "execution_session_id": claim["execution_session_id"],
                    "executor_build_digest": claim["executable_digest"], "restart": "no", "persistent_timer": False,
                    "ready": True, "peers_ready": True, "observation_fresh": True, "attested": True,
                    "ledger_ready": True, "claim_consumed": True, "live_gate": "OFF"}
        override = os.environ.get("FIXTURE_WATCH_OVERRIDE")
        if override:
            key, raw = override.split("=", 1); evidence[key] = json.loads(raw)
        result = self.result_path(claim_id); result.write_bytes(module.canonical(evidence)); os.chmod(result, 0o600)
    def cleanup_instance(self, instance):
        if not instance.startswith("shaurya-shadow-once@") or not instance.endswith(".service"): raise module.ProtocolError()
        self.record("cleanup:" + instance)
    def cleanup_config(self, claim_id, path, digest, allow_missing=False):
        runtime = self.root() / f"{claim_id}.runtime.json"
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise module.ProtocolError()
            path.unlink()
        elif not allow_missing: raise module.ProtocolError()
        if runtime.exists(): runtime.unlink()
        elif not allow_missing: raise module.ProtocolError()
    def interruption(self, point):
        if os.environ.get("FIXTURE_REMOTE_INTERRUPT_POINT") == point:
            raise module.ProtocolError(module.EXIT_INTERNAL)
        if os.environ.get("FIXTURE_REMOTE_POWER_LOSS_POINT") == point:
            os._exit(module.EXIT_INTERNAL)
    def _subprocess(self, component, arguments):
        command = [sys.executable, "-B", __file__, component, *arguments]
        error_stream = None if os.environ.get("FIXTURE_DEBUG") == "1" else __import__("subprocess").DEVNULL
        result = __import__("subprocess").run(command, stdout=__import__("subprocess").PIPE,
                                              stderr=error_stream, env=os.environ, check=False)
        if result.returncode: raise module.ProtocolError(result.returncode)
        return result.stdout
    def run_broker(self, claim_path): return self._subprocess("broker", ["--claim", str(claim_path)])
    def run_watcher(self, claim_path, deadline_ns): return self._subprocess("watcher", ["--claim", str(claim_path), "--deadline-ns", str(deadline_ns)])
    def run_auth(self, expected_digest):
        helper = Path(os.environ.get("FIXTURE_AUTH_HELPER", str(root / "ops/libexec/kotak-auth-helper")))
        if hashlib.sha256(helper.read_bytes()).hexdigest() != expected_digest:
            raise module.ProtocolError(module.EXIT_REFUSAL)
        if os.environ.get("FIXTURE_AUTH_REFUSAL") == "1":
            raise module.ProtocolError(module.EXIT_REFUSAL)
        result = __import__("subprocess").run([str(helper)], stdout=__import__("subprocess").PIPE,
                                               stderr=__import__("subprocess").DEVNULL, check=False,
                                               env=os.environ)
        if result.returncode == module.EXIT_REFUSAL: raise module.ProtocolError(module.EXIT_REFUSAL)
        if result.returncode or len(result.stdout) > 16 * 1024: raise module.ProtocolError(module.EXIT_UNAVAILABLE)
        return result.stdout

if __name__ == "__main__":
    component, arguments = sys.argv[1], sys.argv[2:]; dependencies = FixtureDependencies()
    try:
        if component == "doctor": code = module.doctor(arguments, dependencies)
        elif component == "broker": code = module.broker(arguments, dependencies)
        elif component == "watcher": code = module.watcher(arguments, dependencies)
        else: code = module.EXIT_USAGE
    except module.ProtocolError as error:
        if os.environ.get("FIXTURE_DEBUG") == "1":
            import traceback
            with Path(os.environ["FIXTURE_CHAIN_RECORD"]).open("a", encoding="ascii") as debug_output:
                traceback.print_exc(file=debug_output)
        code = error.code
    raise SystemExit(code)
