"""Export compact, reviewable Market-JEPA result tables from external run artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

SEEDS = (1, 7, 23, 42, 101)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"no rows for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    aggregate = json.loads((args.run_root / "results.json").read_text())
    seeds = {
        seed: json.loads((args.run_root / f"seed-{seed}" / "results.json").read_text())
        for seed in SEEDS
    }
    (args.output / "results.json").write_text(json.dumps(aggregate, indent=2) + "\n")
    write_csv(args.output / "incremental_skill.csv", aggregate["summary"])
    write_csv(args.output / "seed_stability.csv", aggregate["rows"])

    ablations: list[dict[str, Any]] = []
    names = (
        "handcrafted_base",
        "jepa",
        "base_plus_jepa",
        "base_plus_pca",
        "base_plus_random",
        "base_plus_shuffled_jepa",
        "flattened_context",
    )
    for diagnostic in ("diagnostic_1", "diagnostic_2"):
        sample = seeds[SEEDS[0]]["probes"][diagnostic]
        for horizon, targets in sample.items():
            for target in targets:
                row: dict[str, Any] = {
                    "diagnostic": diagnostic,
                    "horizon": horizon,
                    "target": target,
                }
                for name in names:
                    values = [
                        seeds[seed]["probes"][diagnostic][horizon][target][name]["mae_skill"]
                        for seed in SEEDS
                    ]
                    row[f"median_{name}_skill"] = statistics.median(values)
                ablations.append(row)
    write_csv(args.output / "ablation_summary.csv", ablations)

    interactions: list[dict[str, Any]] = []
    shocks: list[dict[str, Any]] = []
    for diagnostic in ("diagnostic_1", "diagnostic_2"):
        for signal in seeds[SEEDS[0]]["interactions"][diagnostic]:
            values = [seeds[seed]["interactions"][diagnostic][signal] for seed in SEEDS]
            interactions.append(
                {
                    "diagnostic": diagnostic,
                    "signal": signal,
                    "target": values[0]["target"],
                    "median_incremental_mae_skill": statistics.median(
                        value["incremental_mae_skill"] for value in values
                    ),
                    "positive_seeds": sum(value["incremental_mae_skill"] > 0 for value in values),
                    "median_interaction_auc": statistics.median(
                        value["with_interaction"]["roc_auc"] for value in values
                    ),
                    "median_interaction_balanced_accuracy": statistics.median(
                        value["with_interaction"]["balanced_accuracy"] for value in values
                    ),
                }
            )
        shock_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        for seed in SEEDS:
            for lag, targets in seeds[seed]["transition_shocks"][diagnostic].items():
                for target, value in targets.items():
                    if value is not None:
                        shock_groups[(lag, target)].append(value)
        for (lag, target), values in shock_groups.items():
            shocks.append(
                {
                    "diagnostic": diagnostic,
                    "lag": lag,
                    "target": target,
                    "median_spearman": statistics.median(values),
                    "positive_seeds": sum(value > 0 for value in values),
                }
            )
    write_csv(args.output / "interaction_summary.csv", interactions)
    write_csv(args.output / "transition_shock_summary.csv", shocks)

    regimes: list[dict[str, Any]] = []
    representative = seeds[42]
    for session, payload in representative["regimes"].items():
        for regime in payload["summary"]:
            row = {
                "session": session,
                "regime": regime["regime"],
                "samples": regime["samples"],
                "share": regime["share"],
                "mean_session_fraction": regime["mean_session_fraction"],
            }
            row.update(regime["means"])
            regimes.append(row)
    write_csv(args.output / "regime_summary_seed42.csv", regimes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
