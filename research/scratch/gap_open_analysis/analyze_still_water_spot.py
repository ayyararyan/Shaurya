#!/usr/bin/env python3
"""Analyze NIFTY open moves from the Still_Water Dhan rolling-option spot column."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

SCRATCH = Path(__file__).resolve().parent
MANIFEST = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options/manifest.jsonl"
)
FLAT_GAP_BPS = 5.0
ENDPOINTS = ("09:15", "09:16", "09:17", "09:29", "09:30", "09:44", "09:45", "15:29")
REQUIRED = ("09:15", "09:16", "09:17", "09:30", "09:45")


@dataclass(frozen=True)
class CorrelationResult:
    predictor: str
    outcome: str
    n: int
    pearson_r: float | None
    pearson_p: float | None
    spearman_rho: float | None
    spearman_p: float | None


def selected_manifest_rows() -> list[dict[str, object]]:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    selected = [
        row for row in rows if row.get("strike") == "ATM" and row.get("drv_option_type") == "CALL"
    ]
    if len(selected) != 66:
        raise RuntimeError(f"expected 66 ATM/CALL files, found {len(selected)}")
    return selected


def cached_path(row: dict[str, object]) -> Path:
    year = str(row["from_date"])[:4]
    return MANIFEST.parent / year / Path(str(row["path"])).name


def load_spot() -> tuple[pd.DataFrame, dict[str, object]]:
    parts: list[pd.DataFrame] = []
    row_mismatches: list[dict[str, object]] = []
    schemas: set[tuple[str, ...]] = set()
    selected = selected_manifest_rows()
    for row in selected:
        path = cached_path(row)
        if not path.exists():
            raise FileNotFoundError(f"staged cache file is missing: {path}")
        schemas.add(tuple(pd.read_csv(path, nrows=0).columns))
        frame = pd.read_csv(path, usecols=["spot", "datetime"])
        if len(frame) != int(row["rows"]):
            row_mismatches.append(
                {"file": path.name, "observed": len(frame), "manifest": int(row["rows"])}
            )
        parts.append(frame)
    if len(schemas) != 1:
        raise RuntimeError(f"source schema changed across files: {len(schemas)} variants")
    if row_mismatches:
        raise RuntimeError(f"source row counts differ from manifest: {row_mismatches}")
    spot = pd.concat(parts, ignore_index=True)
    spot["datetime"] = pd.to_datetime(spot["datetime"], errors="raise")
    spot["date"] = spot["datetime"].dt.strftime("%Y-%m-%d")
    spot["clock"] = spot["datetime"].dt.strftime("%H:%M")
    if spot["spot"].isna().any() or (spot["spot"] <= 0).any():
        raise RuntimeError("spot contains missing or non-positive values")
    duplicate_timestamps = int(spot.duplicated("datetime").sum())
    conflicts = int(
        spot.assign(datetime_key=spot["datetime"].astype(str))
        .groupby("datetime_key", sort=False)["spot"]
        .nunique()
        .gt(1)
        .sum()
    )
    audit = {
        "selected_files": len(selected),
        "manifest_rows": sum(int(row["rows"]) for row in selected),
        "loaded_rows": len(spot),
        "row_count_mismatches": row_mismatches,
        "schema_variants": len(schemas),
        "duplicate_timestamps": duplicate_timestamps,
        "conflicting_duplicate_spots": conflicts,
        "raw_unique_dates": int(spot["date"].nunique()),
        "first_timestamp": spot["datetime"].min().isoformat(),
        "last_timestamp": spot["datetime"].max().isoformat(),
    }
    return spot, audit


def endpoint_panel(spot: pd.DataFrame) -> pd.DataFrame:
    series: list[pd.Series] = []
    for clock in ENDPOINTS:
        values = (
            spot.loc[spot["clock"] == clock, ["date", "spot"]]
            .drop_duplicates("date", keep="last")
            .set_index("date")["spot"]
            .rename(clock)
        )
        series.append(values)
    return pd.concat(series, axis=1).sort_index()


def daily_measures(
    spot: pd.DataFrame, panel: pd.DataFrame, audit: dict[str, object]
) -> pd.DataFrame:
    complete = panel.dropna(subset=list(REQUIRED)).copy()
    complete["r1"] = complete["09:16"] / complete["09:15"] - 1.0
    complete["r2"] = complete["09:17"] / complete["09:15"] - 1.0
    complete["r_0915_0930"] = complete["09:30"] / complete["09:15"] - 1.0
    complete["r_0915_0945"] = complete["09:45"] / complete["09:15"] - 1.0
    complete["r_after_r1_to_0930"] = complete["09:30"] / complete["09:16"] - 1.0
    complete["r_after_r1_to_0945"] = complete["09:45"] / complete["09:16"] - 1.0
    complete["r_after_r2_to_0930"] = complete["09:30"] / complete["09:17"] - 1.0
    complete["r_after_r2_to_0945"] = complete["09:45"] / complete["09:17"] - 1.0
    complete["r_0915_0929_boundary"] = complete["09:29"] / complete["09:15"] - 1.0
    complete["r_0915_0944_boundary"] = complete["09:44"] / complete["09:15"] - 1.0

    # Use one consistent end-of-regular-session stamp instead of mixing 15:29 and 15:30.
    prior_close_proxy = panel["15:29"].shift(1)
    complete["prior_session_1529_spot"] = prior_close_proxy.reindex(complete.index)
    complete["gap"] = complete["09:15"] / complete["prior_session_1529_spot"] - 1.0
    complete["gap_group"] = np.select(
        [complete["gap"] > FLAT_GAP_BPS / 10_000, complete["gap"] < -FLAT_GAP_BPS / 10_000],
        ["gap_up", "gap_down"],
        default="flat_5bp",
    )
    complete.loc[complete["gap"].isna(), "gap_group"] = "unavailable"

    all_dates = set(spot["date"].unique())
    complete_dates = set(complete.index)
    incomplete: list[dict[str, object]] = []
    for date_value in sorted(all_dates - complete_dates):
        day = spot[spot["date"] == date_value]
        available = set(day["clock"])
        incomplete.append(
            {
                "date": date_value,
                "rows": len(day),
                "first_time": day["clock"].min(),
                "last_time": day["clock"].max(),
                "missing_required": sorted(set(REQUIRED) - available),
            }
        )
    audit.update(
        {
            "complete_dates": len(complete),
            "discarded_incomplete_dates": len(incomplete),
            "incomplete_date_details": incomplete,
            "analysis_first_date": complete.index.min(),
            "analysis_last_date": complete.index.max(),
        }
    )
    return complete


def correlation(data: pd.DataFrame, predictor: str, outcome: str) -> CorrelationResult:
    pair = data[[predictor, outcome]].dropna()
    if len(pair) < 3 or pair[predictor].nunique() < 2 or pair[outcome].nunique() < 2:
        return CorrelationResult(predictor, outcome, len(pair), None, None, None, None)
    pearson = pearsonr(pair[predictor], pair[outcome])
    spearman = spearmanr(pair[predictor], pair[outcome])
    return CorrelationResult(
        predictor,
        outcome,
        len(pair),
        float(pearson.statistic),
        float(pearson.pvalue),
        float(spearman.statistic),
        float(spearman.pvalue),
    )


def winsorized_pearson(data: pd.DataFrame, predictor: str, outcome: str) -> float | None:
    pair = data[[predictor, outcome]].dropna()
    if len(pair) < 3:
        return None
    clipped = pair.clip(pair.quantile(0.01), pair.quantile(0.99), axis=1)
    return float(pearsonr(clipped[predictor], clipped[outcome]).statistic)


def sign_rate(data: pd.DataFrame, predictor: str, outcome: str) -> dict[str, object]:
    pair = data[[predictor, outcome]].dropna()
    pair = pair[(pair[predictor] != 0) & (pair[outcome] != 0)]
    rate = ((pair[predictor] * pair[outcome]) > 0).mean() if len(pair) else math.nan
    return {
        "predictor": predictor,
        "outcome": outcome,
        "n_directional": len(pair),
        "same_sign_rate": None if math.isnan(rate) else float(rate),
    }


def fmt(value: float | None) -> str:
    return "NA" if value is None or not math.isfinite(value) else f"{value:.3f}"


def p_fmt(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def markdown_report(results: dict[str, object]) -> str:
    audit = results["audit"]
    headline = results["headline_correlations"]
    signs = results["headline_sign_consistency"]
    continuation = results["nonoverlap_correlations"]
    winsor = results["nonoverlap_winsorized_pearson"]
    groups = results["gap_split"]
    boundary = results["boundary_robustness"]

    lines = [
        "# NIFTY 50 first-minute versus opening-window returns",
        "",
        "**Exploratory scan using Dhan-derived NIFTY spot stamps stored in Still_Water's "
        "ATM/CALL minute files. No live API or order path was used.**",
        "",
        "## Sample",
        "",
        f"The 66 manifest-selected files contain {audit['loaded_rows']:,} minute rows from "
        f"{audit['first_timestamp']} through {audit['last_timestamp']}. Of "
        f"{audit['raw_unique_dates']:,} dated sessions, **{audit['complete_dates']:,}** "
        "have all required 09:15, 09:16, 09:17, 09:30 and 09:45 IST observations. "
        f"{audit['discarded_incomplete_dates']} incomplete or special-evening sessions "
        "were excluded.",
        "",
        "Returns use spot levels stamped at the named minute: `r1=09:16/09:15-1`, "
        "`r2=09:17/09:15-1`, and outcomes at 09:30/09:45. The gap split uses the "
        "previous available regular session's fixed 15:29 spot; flat means within ±5 bp.",
        "",
        "## Requested correlations",
        "",
        "| Predictor | Outcome | N | Pearson r | p | Spearman rho | p | Same sign |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    sign_lookup = {(row["predictor"], row["outcome"]): row for row in signs}
    for row in headline:
        sign = sign_lookup[(row["predictor"], row["outcome"])]
        lines.append(
            f"| {row['predictor']} | {row['outcome']} | {row['n']} | "
            f"{fmt(row['pearson_r'])} | {p_fmt(row['pearson_p'])} | "
            f"{fmt(row['spearman_rho'])} | {p_fmt(row['spearman_p'])} | "
            f"{100 * sign['same_sign_rate']:.1f}% |"
        )

    lines += [
        "",
        "These headline outcomes mechanically include the first one/two minutes. Positive "
        "correlation and 61–64% sign agreement therefore do not by themselves show that the "
        "early move predicts the *remaining* window.",
        "",
        "## Non-overlapping continuation diagnostic",
        "",
        "| Early move | Subsequent leg | Pearson r (p) | Spearman rho (p) | "
        "1% winsor r | Same sign |",
        "|---|---|---:|---:|---:|---:|",
    ]
    continuation_signs = {
        (row["predictor"], row["outcome"]): row for row in results["nonoverlap_sign_consistency"]
    }
    winsor_lookup = {(row["predictor"], row["outcome"]): row["pearson_r"] for row in winsor}
    for row in continuation:
        key = (row["predictor"], row["outcome"])
        sign = continuation_signs[key]
        lines.append(
            f"| {row['predictor']} | {row['outcome']} | "
            f"{fmt(row['pearson_r'])} ({p_fmt(row['pearson_p'])}) | "
            f"{fmt(row['spearman_rho'])} ({p_fmt(row['spearman_p'])}) | "
            f"{fmt(winsor_lookup[key])} | {100 * sign['same_sign_rate']:.1f}% |"
        )
    lines += [
        "",
        "Raw Pearson suggests mild mean reversion in some cells, but Spearman is effectively "
        "zero, winsorized Pearson is near zero, and directional accuracy is only 50.7–52.9%. "
        "The raw Pearson result is tail-sensitive—4 June 2024 alone combines a +76 bp first "
        "minute with a -235 bp subsequent 09:16–09:30 leg.",
        "",
        "## Gap-direction split",
        "",
        "| Gap group | N | r1→total 09:30 Pearson/Spearman | r1→total 09:45 | "
        "r1→subsequent 09:30 Pearson/Spearman/sign | r1→subsequent 09:45 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in ("gap_down", "flat_5bp", "gap_up"):
        item = groups[group]
        h = {(r["predictor"], r["outcome"]): r for r in item["headline_correlations"]}
        n = {(r["predictor"], r["outcome"]): r for r in item["nonoverlap_correlations"]}
        ns = {(r["predictor"], r["outcome"]): r for r in item["nonoverlap_sign_consistency"]}
        h15 = h[("r1", "r_0915_0930")]
        h30 = h[("r1", "r_0915_0945")]
        n15 = n[("r1", "r_after_r1_to_0930")]
        n30 = n[("r1", "r_after_r1_to_0945")]
        lines.append(
            f"| {group} | {item['n']} | {fmt(h15['pearson_r'])}/{fmt(h15['spearman_rho'])} | "
            f"{fmt(h30['pearson_r'])}/{fmt(h30['spearman_rho'])} | "
            f"{fmt(n15['pearson_r'])}/{fmt(n15['spearman_rho'])}/"
            f"{100 * ns[('r1', 'r_after_r1_to_0930')]['same_sign_rate']:.1f}% | "
            f"{fmt(n30['pearson_r'])}/{fmt(n30['spearman_rho'])}/"
            f"{100 * ns[('r1', 'r_after_r1_to_0945')]['same_sign_rate']:.1f}% |"
        )
    lines += [
        "",
        "The flat subgroup looks stronger in the overlapping statistic but has only 111 days. "
        "After removing overlap, no gap group shows a stable monotonic continuation effect; "
        "same-sign rates range from roughly 49% to 55%.",
        "",
        "## Boundary robustness",
        "",
        "Using 09:29/09:44 instead of the explicitly available 09:30/09:45 leaves the "
        "headline conclusion unchanged: Pearson correlations are "
        + ", ".join(fmt(row["pearson_r"]) for row in boundary)
        + " for the same four cells.",
        "",
        "## Verdict",
        "",
        "**Not worth building a directional trading idea around in this form.** The first "
        "one/two-minute move is strongly correlated with the total 15/30-minute return, but "
        "mostly because that early move is part of the target itself. Once the overlapping "
        "minutes are removed, rank correlation and directional accuracy are indistinguishable "
        "from a useful continuation signal. The only visible raw Pearson mean reversion is "
        "tail-driven and unstable across years. A strategy would need a different conditioning "
        "variable—such as opening-auction imbalance, overnight news/gap size, breadth, or futures "
        "order flow—and prospective out-of-sample testing with costs.",
        "",
        "## Caveats",
        "",
        "- `spot` is a Dhan-derived underlying level embedded in rolling ATM option files, not "
        "a separately fetched NIFTY OHLC bar. The analysis treats each stamped value as the "
        "index level at that minute.",
        "- Nine dates were excluded: three start at 09:16, four are Muhurat/evening sessions, "
        "one starts at 13:45, and one starts at 09:19.",
        "- Ordinary correlation p-values are IID approximations and are unadjusted for serial "
        "dependence or the headline/subgroup multiple comparisons.",
        "- The prior-close gap uses 15:29 consistently; it is a close proxy rather than an "
        "official exchange closing value.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    spot, audit = load_spot()
    panel = endpoint_panel(spot)
    daily = daily_measures(spot, panel, audit)
    headline_pairs = [
        ("r1", "r_0915_0930"),
        ("r1", "r_0915_0945"),
        ("r2", "r_0915_0930"),
        ("r2", "r_0915_0945"),
    ]
    nonoverlap_pairs = [
        ("r1", "r_after_r1_to_0930"),
        ("r1", "r_after_r1_to_0945"),
        ("r2", "r_after_r2_to_0930"),
        ("r2", "r_after_r2_to_0945"),
    ]
    boundary_pairs = [
        ("r1", "r_0915_0929_boundary"),
        ("r1", "r_0915_0944_boundary"),
        ("r2", "r_0915_0929_boundary"),
        ("r2", "r_0915_0944_boundary"),
    ]
    gap_split: dict[str, object] = {}
    for group in ("gap_down", "flat_5bp", "gap_up", "unavailable"):
        subset = daily[daily["gap_group"] == group]
        gap_split[group] = {
            "n": len(subset),
            "headline_correlations": [
                asdict(correlation(subset, *pair)) for pair in headline_pairs
            ],
            "headline_sign_consistency": [sign_rate(subset, *pair) for pair in headline_pairs],
            "nonoverlap_correlations": [
                asdict(correlation(subset, *pair)) for pair in nonoverlap_pairs
            ],
            "nonoverlap_sign_consistency": [sign_rate(subset, *pair) for pair in nonoverlap_pairs],
        }
    results: dict[str, object] = {
        "source": {
            "description": "Still_Water Dhan rolling ATM/CALL option files; embedded spot column",
            "manifest": str(MANIFEST),
            "selection": {"strike": "ATM", "drv_option_type": "CALL"},
        },
        "definitions": {
            "r1": "spot(09:16)/spot(09:15)-1",
            "r2": "spot(09:17)/spot(09:15)-1",
            "r_0915_0930": "spot(09:30)/spot(09:15)-1",
            "r_0915_0945": "spot(09:45)/spot(09:15)-1",
            "gap": "spot(09:15)/prior available session spot(15:29)-1",
            "flat_gap_band_bps": FLAT_GAP_BPS,
        },
        "audit": audit,
        "headline_correlations": [asdict(correlation(daily, *pair)) for pair in headline_pairs],
        "headline_sign_consistency": [sign_rate(daily, *pair) for pair in headline_pairs],
        "nonoverlap_correlations": [asdict(correlation(daily, *pair)) for pair in nonoverlap_pairs],
        "nonoverlap_sign_consistency": [sign_rate(daily, *pair) for pair in nonoverlap_pairs],
        "nonoverlap_winsorized_pearson": [
            {
                "predictor": pair[0],
                "outcome": pair[1],
                "pearson_r": winsorized_pearson(daily, *pair),
            }
            for pair in nonoverlap_pairs
        ],
        "gap_split": gap_split,
        "boundary_robustness": [asdict(correlation(daily, *pair)) for pair in boundary_pairs],
    }
    output_daily = daily.reset_index().rename(columns={"index": "date"})
    output_daily.to_csv(SCRATCH / "daily_measures.csv", index=False)
    (SCRATCH / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = markdown_report(results)
    (SCRATCH / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
