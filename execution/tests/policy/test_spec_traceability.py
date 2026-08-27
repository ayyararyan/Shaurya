from __future__ import annotations

import argparse
import re
from pathlib import Path


PREFIXES = {
    "BND", "CON", "INS", "IDM", "FSM", "RSK", "LED", "REC",
    "OPS", "PORT", "SEC", "SHD", "LIVE", "D51",
}
STATUSES = {"Specified", "Implemented", "Tested", "Blocked", "Live-unverified"}


def require(condition: bool, message: object) -> None:
    if not condition:
        raise SystemExit(str(message))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--start-commit", required=True)
    args = parser.parse_args()
    spec = (args.repo_root / "execution" / "EXECUTION_CONTROL_PLANE_SPEC.md").read_text()
    for heading in ("Verified facts", "Design decisions", "Unresolved live blockers", "Prohibited actions"):
        require(bool(re.search(rf"^## {re.escape(heading)}$", spec, re.MULTILINE)), heading)
    rows = re.findall(r"^\| (EXE-([A-Z0-9]+)-\d{3}) \|(.+?)\|$", spec, re.MULTILINE)
    ids = [row[0] for row in rows]
    require(len(ids) == len(set(ids)), "duplicate requirement ID")
    require(PREFIXES <= {row[1] for row in rows}, "missing requirement prefix")
    require(len(rows) >= 40, "traceability table is not independently testable enough")
    for full_row in re.findall(r"^\| EXE-[A-Z0-9]+-\d{3} \|.+$", spec, re.MULTILINE):
        cells = [cell.strip() for cell in full_row.strip("|").split("|")]
        require(len(cells) == 7, full_row)
        require(cells[5] in STATUSES, cells[5])
        if cells[5] in {"Implemented", "Tested"}:
            require(cells[3] != "Pending", full_row)
        if cells[5] == "Tested":
            require(cells[4] != "Pending", full_row)
        if cells[0].startswith("EXE-LIVE-"):
            require(cells[5] == "Live-unverified", full_row)


if __name__ == "__main__":
    main()
