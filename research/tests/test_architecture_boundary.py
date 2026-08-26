from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(name.name for name in node.names)
    return modules


def test_research_uses_only_the_public_data_facade() -> None:
    violations: list[str] = []
    for source_root in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in source_root.rglob("*.py"):
            for module in _imports(path):
                if module.startswith("shaurya.data.") or module.startswith("shaurya.data_cli"):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_research_dataset_entry_points_use_catalogue_handles() -> None:
    paths = (
        ROOT / "src/shaurya/cli/surface_dashboard.py",
        ROOT / "src/shaurya/cli/ofi_dashboard.py",
        ROOT / "src/shaurya/cli/live_ofi_studies.py",
        ROOT / "src/shaurya/analytics/post_close_alpha_research.py",
        ROOT / "scripts/ofi_full_session_controller.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "DataAccess" in source
        assert "DataCatalog" in source
        assert "DhanCredentials" not in source
        assert "DhanLiveStream" not in source
        assert "JsonlTapeWriter" not in source
