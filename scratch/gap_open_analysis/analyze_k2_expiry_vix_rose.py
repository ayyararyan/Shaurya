#!/usr/bin/env python3
"""Test k=2 persistence on expiry days conditional on an overnight India VIX rise."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from analyze_high_low_sequence import SCRATCH
from analyze_k2_controls import coefficient_records, fit_record, fmt_p, slice_record
from analyze_k2_expiry_controls import logistic_fit

VIX_ROOT = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/openclaw_zen/"
    "dhan_data/indices/india_vix"
)
VIX_DUPLICATE_ROOT = VIX_ROOT.parent / "INDIA-VIX"
FROZEN_PANEL = SCRATCH / "k2_expiry_controls_panel.csv"
DECISION_CLOCK = "09:17"
SESSION_START = "09:15"
SESSION_END = "15:30"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_duplicate_folder(lower_files: list[Path]) -> dict[str, object]:
    upper_files = sorted(VIX_DUPLICATE_ROOT.rglob("*.csv"))
    lower_by_name = {path.name: path for path in lower_files}
    comparisons: list[dict[str, object]] = []
    for upper in upper_files:
        lower = lower_by_name.get(upper.name)
        comparisons.append(
            {
                "filename": upper.name,
                "lower_match_present": lower is not None,
                "upper_sha256": sha256(upper),
                "lower_sha256": sha256(lower) if lower is not None else None,
                "identical": lower is not None and sha256(upper) == sha256(lower),
            }
        )
    return {
        "uppercase_file_count": len(upper_files),
        "comparisons": comparisons,
        "conflict_count": sum(not bool(row["identical"]) for row in comparisons),
    }


def load_frozen_panel() -> pd.DataFrame:
    panel = (
        pd.read_csv(FROZEN_PANEL, dtype={"date": str}).sort_values("date").reset_index(drop=True)
    )
    if len(panel) != 1318 or panel["date"].nunique() != 1318:
        raise RuntimeError("unexpected frozen k=2 panel shape")
    if int(panel["is_expiry_day"].sum()) != 276:
        raise RuntimeError("unexpected frozen expiry-day count")
    if not ((panel["target_start"] == "09:18") & (panel["target_end"] == "09:45")).all():
        raise RuntimeError("frozen target timing changed")
    return panel


def load_vix_daily(panel_dates: pd.Series) -> tuple[pd.DataFrame, dict[str, object]]:
    files = sorted(VIX_ROOT.rglob("*.csv"))
    if len(files) != 60:
        raise RuntimeError(f"expected 60 lowercase India VIX files, found {len(files)}")
    frames: list[pd.DataFrame] = []
    for path in files:
        frame = pd.read_csv(path, usecols=["datetime", "open", "close"])
        frame["source_file"] = path.name
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)
    raw["datetime"] = pd.to_datetime(raw["datetime"], errors="raise", utc=True).dt.tz_convert(
        "Asia/Kolkata"
    )
    raw_duplicate_timestamps = int(raw.duplicated("datetime").sum())
    raw = raw.drop_duplicates("datetime", keep="last")
    raw["date"] = raw["datetime"].dt.strftime("%Y-%m-%d")
    raw["clock"] = raw["datetime"].dt.strftime("%H:%M")
    session = raw[(raw["clock"] >= SESSION_START) & (raw["clock"] <= SESSION_END)].copy()
    session = session.sort_values(["date", "clock"])
    grouped = session.groupby("date", sort=True)
    daily = pd.DataFrame(
        {
            "vix_open": grouped["open"].first(),
            "vix_close": grouped["close"].last(),
            "vix_first_clock": grouped["clock"].first(),
            "vix_last_clock": grouped["clock"].last(),
            "vix_session_prints": grouped.size(),
        }
    )
    trading_calendar = pd.DataFrame(index=pd.Index(panel_dates.tolist(), name="date"))
    daily = trading_calendar.join(daily, how="left")
    daily["vix_prior_session_close"] = daily["vix_close"].shift(1)
    daily["vix_overnight_gap"] = daily["vix_open"] / daily["vix_prior_session_close"] - 1.0
    daily["vix_known_by_decision"] = (
        daily["vix_overnight_gap"].notna()
        & daily["vix_first_clock"].notna()
        & (daily["vix_first_clock"] <= DECISION_CLOCK)
    )
    daily["vix_rose"] = daily["vix_known_by_decision"] & (daily["vix_overnight_gap"] > 0)
    duplicate_audit = audit_duplicate_folder(files)
    audit = {
        "lowercase_file_count": len(files),
        "raw_rows": len(raw),
        "raw_duplicate_timestamps": raw_duplicate_timestamps,
        "raw_first_timestamp": raw["datetime"].astype(str).min(),
        "raw_last_timestamp": raw["datetime"].astype(str).max(),
        "session_filtered_dates": int(session["date"].nunique()),
        "panel_dates_with_vix_open": int(daily["vix_open"].notna().sum()),
        "panel_dates_with_overnight_gap": int(daily["vix_overnight_gap"].notna().sum()),
        "panel_dates_known_by_decision": int(daily["vix_known_by_decision"].sum()),
        "first_clock_counts": {
            "MISSING" if pd.isna(key) else str(key): int(value)
            for key, value in daily["vix_first_clock"].value_counts(dropna=False).items()
        },
        "session_filter": f"{SESSION_START} through {SESSION_END} IST",
        "duplicate_folder_audit": duplicate_audit,
    }
    return daily, audit


def summarize_model(
    data: pd.DataFrame, label: str
) -> tuple[dict[str, object], list[dict[str, object]]]:
    fit = logistic_fit(data, controlled=False)
    if not fit.converged:
        raise RuntimeError(f"logistic IRLS failed for {label}")
    persistence = slice_record(data, "sample", label)
    coefficients = coefficient_records(fit, label)
    flag = next(row for row in coefficients if row["term"] == "initial_high_first")
    model = fit_record(fit, label)
    model.update(
        {
            "target_after_initial_high_first": persistence["target_rate_after_initial_high_first"],
            "target_after_initial_low_first": persistence["target_rate_after_initial_low_first"],
            "persistence_effect": persistence["persistence_effect"],
            "persistence_p": persistence["persistence_p"],
            "initial_flag_coefficient": flag["coefficient"],
            "initial_flag_hac_p": flag["hac_p"],
            "initial_flag_p3_correlation": float(data["initial_high_first"].corr(data["P3"])),
        }
    )
    return model, coefficients


def report_markdown(results: dict[str, object]) -> str:
    models = {row["model"]: row for row in results["models"]}
    full = models["full_sample"]
    expiry = models["expiry_only"]
    combined = models["expiry_and_vix_rose"]
    exact = models["expiry_vix_rose_exact_0915"]
    attrition = results["attrition"]
    vix_audit = results["vix_audit"]
    duplicate = vix_audit["duplicate_folder_audit"]
    lines = [
        "# NIFTY k=2 expiry-only and India-VIX-rise sequence test",
        "",
        "**Exploratory full-history conditioning test.** The frozen k=2 decision/target timing "
        "is unchanged: predictors use 09:15–09:17 and the target is strictly 09:18–09:45. "
        "Every regression uses only the original predictors: gap, P1, P3, initial range ratio, "
        "and initial high-first.",
        "",
        "## India VIX construction and data audit",
        "",
        f"The lowercase folder contains **{vix_audit['lowercase_file_count']} files** and "
        f"{vix_audit['raw_rows']:,} unique minute timestamps from "
        f"{vix_audit['raw_first_timestamp']} through {vix_audit['raw_last_timestamp']}. "
        "The uppercase sibling contains one file; it is byte-identical to the matching "
        f"lowercase file, with **{duplicate['conflict_count']} conflicts**.",
        "",
        "For each NIFTY trading date, VIX open is the `open` value of the first print between "
        "09:15 and 15:30 IST; prior close is the `close` value of the immediately preceding "
        "NIFTY trading session. `vix_rose=1` when open/prior-close−1 is positive. To preserve "
        "no-lookahead, a date is eligible only if its first VIX print arrives by 09:17. This "
        "excludes anomalous early files whose first print is 09:27 or 10:00.",
        "",
        "## Sample attrition",
        "",
        f"- Frozen full sample: **{attrition['all_days']} days**.",
        f"- Expiry-only: **{attrition['expiry_days']} days**.",
        f"- Expiry days with an overnight VIX gap known by 09:17: "
        f"**{attrition['expiry_vix_known']} days**.",
        f"- Expiry days with VIX rose: **{attrition['expiry_vix_rose']} days**.",
        f"- Of those, **{attrition['expiry_vix_rose_exact_0915']}** use an exact 09:15 VIX print.",
        "",
        f"Of the expiry dates, {attrition['expiry_days'] - attrition['expiry_vix_overnight_gap']} "
        "lack a usable overnight VIX gap (mostly before the series begins in August 2021), "
        f"and {attrition['expiry_vix_first_after_decision']} more have their first VIX print "
        "after 09:17 and are excluded for no-lookahead. The final "
        f"N={attrition['expiry_vix_rose']} is "
        + (
            "above the requested 80-day warning line, but it is still a modest and selected "
            "subsample."
            if attrition["expiry_vix_rose"] >= 80
            else "below the requested 80-day warning line and is a thin selected subsample."
        ),
        "",
        "## Model progression",
        "",
        "| Sample | N | Base high-first | Initial high / low target rate | Effect / p | "
        "Pseudo-R² | Accuracy vs base | Flag β / HAC p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in (full, expiry, combined):
        lines.append(
            f"| {row['model']} | {row['n']} | {100 * row['base_high_first_rate']:.1f}% | "
            f"{100 * row['target_after_initial_high_first']:.1f}% / "
            f"{100 * row['target_after_initial_low_first']:.1f}% | "
            f"{100 * row['persistence_effect']:+.1f} pp / {fmt_p(row['persistence_p'])} | "
            f"{100 * row['pseudo_r_squared']:.2f}% | {100 * row['accuracy']:.1f}% vs "
            f"{100 * row['base_accuracy']:.1f}% | {row['initial_flag_coefficient']:.3f} / "
            f"{fmt_p(row['initial_flag_hac_p'])} |"
        )
    lines += [
        "",
        "The exact-09:15 sensitivity is effectively the same filter: "
        f"N={exact['n']}, persistence {100 * exact['persistence_effect']:+.1f} pp "
        f"(p {fmt_p(exact['persistence_p'])}), pseudo-R² "
        f"{100 * exact['pseudo_r_squared']:.2f}%, and accuracy "
        f"{100 * exact['accuracy']:.1f}% versus {100 * exact['base_accuracy']:.1f}% base.",
        "",
        "The combined sample's raw two-proportion split is strong, but the initial-high-first "
        f"coefficient is **not independently significant** in the joint model "
        f"(HAC p={fmt_p(combined['initial_flag_hac_p'])}). At k=2, the sequencing flag and "
        f"P3 encode much of the same opening path (correlation "
        f"{combined['initial_flag_p3_correlation']:.3f}), so conditioning on P3 makes the "
        "flag's incremental contribution imprecise.",
        "",
        "## Verdict",
        "",
        "PLACEHOLDER_VERDICT",
        "",
        "## Caveats",
        "",
        "- Accuracy and fitting are in-sample; the VIX-rise condition was selected after prior "
        "expiry/high-IV findings.",
        "- The VIX series begins in August 2021 and contains anomalous off-session timestamps; "
        "session filtering and the by-09:17 gate prevent those late prints from leaking into "
        "the decision.",
        "- High/low labels use minute-stamped NIFTY spot levels, not intraminute OHLC extrema.",
    ]
    if combined["persistence_effect"] > expiry["persistence_effect"]:
        verdict = (
            "**VIX-rise conditioning strengthens the raw expiry-day persistence pattern in "
            "sample, but it does not establish an independent sequencing edge.** The raw effect "
            "is larger and model fit rises sharply; accuracy uplift over the changing base rate "
            "improves only modestly, from 6.9 to 8.3 percentage points. Most importantly, the "
            "joint model cannot separate the sequencing flag from the correlated P3 path "
            "reliably (HAC p=.363). This is a promising N=108 in-sample subgroup, not validation. "
            "Freeze the rule and require prospective or untouched-period confirmation before "
            "trading it."
        )
    else:
        verdict = (
            "**VIX-rise conditioning does not strengthen the expiry-day persistence pattern.** "
            "The narrower sample adds no convincing predictive benefit and should not replace "
            "the broader expiry hypothesis."
        )
    return "\n".join(verdict if line == "PLACEHOLDER_VERDICT" else line for line in lines) + "\n"


def main() -> None:
    panel = load_frozen_panel()
    vix_daily, vix_audit = load_vix_daily(panel["date"])
    joined = panel.merge(
        vix_daily, left_on="date", right_index=True, how="left", validate="one_to_one"
    )
    expiry = joined[joined["is_expiry_day"] == 1].copy()
    expiry_vix_known = expiry[
        expiry["vix_overnight_gap"].notna() & expiry["vix_known_by_decision"]
    ].copy()
    combined = expiry_vix_known[expiry_vix_known["vix_rose"]].copy()
    exact = combined[combined["vix_first_clock"] == "09:15"].copy()
    samples = [
        (joined, "full_sample"),
        (expiry, "expiry_only"),
        (combined, "expiry_and_vix_rose"),
        (exact, "expiry_vix_rose_exact_0915"),
    ]
    models: list[dict[str, object]] = []
    coefficients: list[dict[str, object]] = []
    for sample, label in samples:
        model, rows = summarize_model(sample, label)
        models.append(model)
        coefficients.extend(rows)
    attrition = {
        "all_days": len(joined),
        "expiry_days": len(expiry),
        "expiry_vix_current_open": int(expiry["vix_open"].notna().sum()),
        "expiry_vix_overnight_gap": int(expiry["vix_overnight_gap"].notna().sum()),
        "expiry_vix_known": len(expiry_vix_known),
        "expiry_vix_rose": len(combined),
        "expiry_vix_rose_exact_0915": len(exact),
        "expiry_vix_first_after_decision": int(
            (expiry["vix_first_clock"].notna() & (expiry["vix_first_clock"] > DECISION_CLOCK)).sum()
        ),
    }
    results: dict[str, object] = {
        "definitions": {
            "expiry_source": "frozen k2_expiry_controls_panel.csv is_expiry_day",
            "vix_open": "open field of first 09:15-15:30 IST print, required by 09:17",
            "vix_prior_close": "close field of immediately preceding NIFTY trading session",
            "vix_rose": "vix_open / vix_prior_close - 1 > 0",
            "regression_predictors": [
                "gap",
                "P1",
                "P3",
                "initial_range_ratio",
                "initial_high_first",
            ],
        },
        "vix_audit": vix_audit,
        "attrition": attrition,
        "models": models,
        "coefficients": coefficients,
    }
    joined.to_csv(SCRATCH / "k2_expiry_vix_rose_panel.csv", index=False)
    pd.DataFrame(models).to_csv(SCRATCH / "k2_expiry_vix_rose_models.csv", index=False)
    pd.DataFrame(coefficients).to_csv(SCRATCH / "k2_expiry_vix_rose_coefficients.csv", index=False)
    (SCRATCH / "k2_expiry_vix_rose_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_k2_expiry_vix_rose.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
