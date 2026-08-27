from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


FORBIDDEN = re.compile(r"BEGIN (?:RSA |OPENSSH )?PRIVATE KEY|\b(?:totp|access_token|refresh_token)\s*[:=]", re.I)


def require(condition: bool, message: object) -> None:
    if not condition:
        raise SystemExit(str(message))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--start-commit", required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    personal_prefix = "/" + "Users/"
    changed = subprocess.run(
        ["git", "diff", "--name-only", args.start_commit, "--", "data", "research"],
        cwd=root, check=True, text=True, capture_output=True,
    ).stdout.strip()
    require(not changed, changed)
    tracked = set(subprocess.run(
        ["git", "ls-files", "execution"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.splitlines())
    tracked.update(subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--", "execution"],
        cwd=root, check=True, text=True, capture_output=True,
    ).stdout.splitlines())
    for relative in sorted(tracked):
        path = root / relative
        if "planning" in path.parts:
            continue
        require(path.suffix not in {".log", ".pyc", ".pem", ".key", ".token"}, path)
        blob = subprocess.run(
            ["git", "show", f":{relative}"], cwd=root, text=True, capture_output=True
        )
        if blob.returncode != 0:
            blob = subprocess.run(
                ["git", "show", f"HEAD:{relative}"], cwd=root, check=True,
                text=True, capture_output=True,
            )
        require(not FORBIDDEN.search(blob.stdout), path)
        require(personal_prefix not in blob.stdout, path)


if __name__ == "__main__":
    main()
