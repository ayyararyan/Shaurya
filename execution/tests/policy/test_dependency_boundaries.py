from __future__ import annotations

import argparse
import ast
from pathlib import Path


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def require(condition: bool, message: object) -> None:
    if not condition:
        raise SystemExit(str(message))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--start-commit", required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    execution_import = "shaurya" + ".execution"
    data_import = "shaurya" + ".data"
    contracts_import = "shaurya" + ".contracts"
    for project in (root / "data", root / "research"):
        for path in project.rglob("*.py"):
            require(not any(name.startswith(execution_import) for name in imports(path)), path)
    allowed_exporter = root / "execution/ops/export_routing_snapshot.py"
    for path in (root / "execution").rglob("*.py"):
        if "planning" in path.parts or path == allowed_exporter:
            continue
        found = imports(path)
        require(not any(name.startswith(data_import) for name in found), path)
        require(not any(name.startswith(contracts_import) for name in found), path)
    source_suffixes = {".cpp", ".hpp", ".h", ".cmake"}
    for path in (root / "execution").rglob("*"):
        if not path.is_file() or "planning" in path.parts:
            continue
        if path.suffix not in source_suffixes and path.name != "CMakeLists.txt":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        require("../data" not in text and "../research" not in text, path)


if __name__ == "__main__":
    main()
