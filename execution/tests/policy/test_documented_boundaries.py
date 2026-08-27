from __future__ import annotations

import argparse
from pathlib import Path


def require(condition: bool, message: object) -> None:
    if not condition:
        raise SystemExit(str(message))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--start-commit", required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    readme = (root / "README.md").read_text()
    for term in ("data/", "research/", "execution/", "no broker or order authority"):
        require(term in readme, term)
    checklist = (root / "execution/docs/LIVE_ENABLEMENT_CHECKLIST.md").read_text()
    blockers = (
        "endpoints", "order-update", "place, modify, cancel", "startup order, trade, and position",
        "exact-token SELL", "end-of-day inventory", "network and order-stream", "daily loss",
        "one-lot", "contract-note", "separate live build",
    )
    require(all(item in checklist for item in blockers), "mandatory live blocker missing")
    require(checklist.count("- [ ]") >= len(blockers), "live blockers not open")
    require("- [x]" not in checklist.lower(), "live blocker marked complete")
    shadow = (root / "execution/docs/SHADOW_SAFETY.md").read_text().lower()
    require("never broker-confirmed" in shadow and "no kotak credential" in shadow, "shadow boundary")
    threat = (root / "execution/docs/THREAT_MODEL.md").read_text().lower()
    for item in ("unauthorized local peer", "ambiguous submission", "ledger truncation", "symlink", "queue overflow", "supply-chain"):
        require(item in threat, item)


if __name__ == "__main__":
    main()
