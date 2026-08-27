#!/usr/bin/python3
"""Non-packaged dependency injector for portable_ops hermetic tests."""
import importlib.util, os, sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
source = root / "ops/libexec/portable_ops.py"
spec = importlib.util.spec_from_file_location("portable_ops_fixture", source)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class FixtureDependencies(module.ProductionDependencies):
    def __init__(self):
        boundary = Path("/private/tmp").resolve()
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
            raw = os.environ.get(key)
            if raw and not Path(raw).resolve().is_relative_to(boundary):
                raise SystemExit(f"hermetic {key} escape")
    @property
    def ssh_path(self): return os.environ["FIXTURE_SSH_BIN"]
    def popen(self, argv, **kwargs):
        if not argv or argv[0] != os.environ["FIXTURE_SSH_BIN"] or argv[0] == "/usr/bin/ssh":
            raise SystemExit("hermetic network executable escape")
        return super().popen(argv, **kwargs)
    def child_environment(self):
        result = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}
        for key, value in os.environ.items():
            if key.startswith("FIXTURE_"): result[key] = value
        return result
    def adversarial_swap(self, path, point):
        key = {"state_before_publish": "FIXTURE_STATE_SWAP_TARGET", "lock_after_acquire": "FIXTURE_LOCK_SWAP_TARGET",
               "prefix_after_open": "FIXTURE_PREFIX_SWAP_TARGET", "identity_before_popen": "FIXTURE_IDENTITY_SWAP_TARGET"}.get(point)
        inplace_key = {"identity_before_popen": "FIXTURE_IDENTITY_INPLACE_MUTATE",
                       "known_hosts_before_popen": "FIXTURE_KNOWN_HOSTS_INPLACE_MUTATE"}.get(point)
        if inplace_key and os.environ.get(inplace_key) == "1":
            with path.open("r+b", buffering=0) as stream:
                stream.seek(-1, os.SEEK_END); original = stream.read(1); stream.seek(-1, os.SEEK_END)
                stream.write(b" " if original != b" " else b"\n"); os.fsync(stream.fileno())
            return
        if not key or not os.environ.get(key): return
        target = Path(os.environ[key]); held = path.with_name(path.name + f".held-{os.getpid()}")
        os.rename(path, held); os.symlink(target, path)
        if point == "identity_before_popen": return
        raise module.OpsError("simulated_ancestor_swap", module.EXIT_REFUSAL)
    def interruption(self, point):
        if os.environ.get("FIXTURE_INTERRUPT") == point:
            raise module.OpsError("simulated_interruption", module.EXIT_INTERNAL)
        if os.environ.get("FIXTURE_POWER_LOSS") == point:
            os._exit(99)
    def release_manifest_path(self, default):
        return Path(os.environ.get("FIXTURE_RELEASE_MANIFEST", str(default)))
    def release_version(self): return os.environ.get("FIXTURE_RELEASE_VERSION", module.VERSION)
    def new_invocation_id(self):
        return os.environ.get("FIXTURE_INVOCATION_ID", super().new_invocation_id())
    def now_ns(self):
        return int(os.environ.get("FIXTURE_NOW_NS", str(super().now_ns())))
    def ssh_identity_path(self): return Path(os.environ["FIXTURE_SSH_IDENTITY"])
    def transport_snapshot_root(self):
        root = Path(os.environ["FIXTURE_TRANSPORT_SNAPSHOT_ROOT"])
        if not root.resolve().is_relative_to(Path("/private/tmp").resolve()):
            raise SystemExit("hermetic transport snapshot escape")
        return root
    def attest_release(self, path): return module.validate_release_manifest(path)

if __name__ == "__main__":
    mode = os.environ.get("FIXTURE_TOOL_MODE")
    if mode: sys.argv.insert(1, f"--internal-{mode}")
    raise SystemExit(module.main(FixtureDependencies()))
