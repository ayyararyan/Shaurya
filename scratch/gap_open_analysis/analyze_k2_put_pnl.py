#!/usr/bin/env python3
"""Observed-premium P&L sanity check for the frozen k=2 PUT signal."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import ttest_1samp

SCRATCH = Path("/Users/maheit/Documents/Shaurya/scratch/gap_open_analysis")
PANEL = SCRATCH / "k2_expiry_vix_rose_panel.csv"
OPTION_CACHE = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options"
)
MANIFEST = OPTION_CACHE / "manifest.jsonl"
ENTRY_CLOCK = "09:17"
TARGET_START = "09:18"
TARGET_END = "09:45"


def manifest_rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def select_manifest_file(rows: list[dict[str, object]], date: str, relative_strike: str) -> Path:
    day = pd.Timestamp(date).date()
    matches = [
        row
        for row in rows
        if row.get("drv_option_type") == "PUT"
        and row.get("strike") == relative_strike
        and pd.Timestamp(str(row["from_date"])).date() <= day
        and pd.Timestamp(str(row["to_date"])).date() >= day
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {relative_strike} PUT file for {date}, found {len(matches)}"
        )
    row = matches[0]
    return OPTION_CACHE / str(row["from_date"])[:4] / Path(str(row["path"])).name


def read_option_file(path: Path, relative_strike: str) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"required safely staged file is missing: {path}")
    frame = pd.read_csv(
        path,
        usecols=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "strike",
            "spot",
            "option_type",
            "rel_strike",
            "expiry_flag",
            "expiry_code",
        ],
    )
    frame["date"] = frame["datetime"].str[:10]
    frame["clock"] = frame["datetime"].str[11:16]
    frame["datetime_key"] = frame["datetime"].str[:19]
    frame["source_relative_strike"] = relative_strike
    if set(frame["option_type"].dropna()) != {"PE"}:
        raise RuntimeError(f"non-PUT rows in {path}")
    if set(frame["expiry_flag"].dropna()) != {"WEEK"} or set(frame["expiry_code"].dropna()) != {1}:
        raise RuntimeError(f"unexpected expiry contract in {path}")
    if set(frame["rel_strike"].dropna()) != {relative_strike}:
        raise RuntimeError(f"relative-strike label mismatch in {path}")
    return frame


def mean_median(series: pd.Series) -> dict[str, float]:
    return {"mean": float(series.mean()), "median": float(series.median())}


def relative_strike(entry_strike: float, exit_atm_strike: float) -> str:
    strike_step = int(round((entry_strike - exit_atm_strike) / 50.0))
    return "ATM" if strike_step == 0 else f"ATM{strike_step:+d}"


def same_contract_quote(
    quote_lookup: pd.DataFrame, datetime_key: str, strike: float, date: str
) -> pd.Series:
    match = quote_lookup.xs((datetime_key, strike))
    if isinstance(match, pd.DataFrame):
        match = match.drop_duplicates(subset=["close", "volume"])
        if len(match) != 1:
            raise RuntimeError(f"ambiguous same-contract quote for {date} at {datetime_key}")
        return match.iloc[0]
    return match


def main() -> None:
    frozen = pd.read_csv(PANEL, dtype={"date": str})
    combined = frozen[(frozen["is_expiry_day"] == 1) & (frozen["vix_rose"] == True)].copy()  # noqa: E712
    signal = combined[combined["initial_high_first"] == 0].copy()
    if len(combined) != 108 or len(signal) != 57:
        raise RuntimeError(f"frozen sample changed: combined={len(combined)}, signal={len(signal)}")
    rows = manifest_rows()
    atm_paths = sorted({select_manifest_file(rows, date, "ATM") for date in signal["date"]})
    if len(atm_paths) != 39:
        raise RuntimeError(f"expected 39 staged ATM files, found {len(atm_paths)}")
    atm = pd.concat([read_option_file(path, "ATM") for path in atm_paths], ignore_index=True)
    atm = atm[atm["date"].isin(signal["date"])].sort_values(["date", "clock"])

    skeleton: list[dict[str, object]] = []
    required_relative_paths: dict[Path, str] = {}
    for row in signal.itertuples(index=False):
        day = atm[atm["date"] == row.date]
        entry_rows = day[day["clock"] == ENTRY_CLOCK]
        target = day[(day["clock"] >= TARGET_START) & (day["clock"] <= TARGET_END)]
        if len(entry_rows) != 1 or len(target) != 28:
            raise RuntimeError(
                f"unexpected minute coverage on {row.date}: "
                f"entry={len(entry_rows)}, target={len(target)}"
            )
        entry = entry_rows.iloc[0]
        target_low = target.loc[target["spot"].idxmin()]
        target_high = target.loc[target["spot"].idxmax()]
        if not np.isclose(float(target_low["spot"]), float(row.target_low), atol=1e-6):
            raise RuntimeError(f"target low differs from frozen panel on {row.date}")
        if not np.isclose(float(target_high["spot"]), float(row.target_high), atol=1e-6):
            raise RuntimeError(f"target high differs from frozen panel on {row.date}")
        if target_low["datetime_key"] == target_high["datetime_key"]:
            raise RuntimeError(f"same-minute target extrema on {row.date}")
        reconstructed_high_first = int(target_high["datetime_key"] < target_low["datetime_key"])
        if reconstructed_high_first != int(row.target_high_first):
            raise RuntimeError(f"target label mismatch on {row.date}")
        selected_exit = target_low if reconstructed_high_first == 0 else target_high

        low_relative = relative_strike(float(entry["strike"]), float(target_low["strike"]))
        high_relative = relative_strike(float(entry["strike"]), float(target_high["strike"]))
        for relative in (low_relative, high_relative):
            if relative != "ATM":
                required_relative_paths[select_manifest_file(rows, row.date, relative)] = relative
        selected_relative = low_relative if reconstructed_high_first == 0 else high_relative
        skeleton.append(
            {
                "date": row.date,
                "target_high_first": reconstructed_high_first,
                "sequence_hit": int(reconstructed_high_first == 0),
                "entry_datetime": entry["datetime_key"],
                "entry_spot": float(entry["spot"]),
                "entry_strike": float(entry["strike"]),
                "entry_put_close": float(entry["close"]),
                "entry_put_volume": float(entry["volume"]),
                "target_low_datetime": target_low["datetime_key"],
                "target_low_spot": float(target_low["spot"]),
                "target_high_datetime": target_high["datetime_key"],
                "target_high_spot": float(target_high["spot"]),
                "selected_exit_datetime": selected_exit["datetime_key"],
                "selected_exit_kind": (
                    "target_low" if reconstructed_high_first == 0 else "target_high"
                ),
                "target_low_relative_strike": low_relative,
                "target_high_relative_strike": high_relative,
                "exit_relative_strike": selected_relative,
            }
        )

    if len(required_relative_paths) != 48:
        raise RuntimeError(
            f"expected 48 relative-strike files, found {len(required_relative_paths)}"
        )
    option_frames = [atm]
    option_frames.extend(
        read_option_file(path, relative) for path, relative in required_relative_paths.items()
    )
    quotes = pd.concat(option_frames, ignore_index=True)
    quote_lookup = quotes.set_index(["datetime_key", "strike"], verify_integrity=False)
    records: list[dict[str, object]] = []
    for record in skeleton:
        entry_strike = float(record["entry_strike"])
        low_quote = same_contract_quote(
            quote_lookup,
            str(record["target_low_datetime"]),
            entry_strike,
            str(record["date"]),
        )
        high_quote = same_contract_quote(
            quote_lookup,
            str(record["target_high_datetime"]),
            entry_strike,
            str(record["date"]),
        )
        selected_quote = low_quote if record["sequence_hit"] else high_quote
        entry_premium = float(record["entry_put_close"])
        low_premium = float(low_quote["close"])
        high_premium = float(high_quote["close"])
        selected_premium = float(selected_quote["close"])
        downside_points = float(record["entry_spot"]) - float(record["target_low_spot"])
        adverse_points = float(record["target_high_spot"]) - float(record["entry_spot"])
        record.update(
            {
                "target_low_put_close": low_premium,
                "target_low_put_volume": float(low_quote["volume"]),
                "target_high_put_close": high_premium,
                "target_high_put_volume": float(high_quote["volume"]),
                "selected_exit_put_close": selected_premium,
                "selected_exit_put_volume": float(selected_quote["volume"]),
                "downside_excursion_points": downside_points,
                "downside_excursion_pct_spot": downside_points / float(record["entry_spot"]),
                "adverse_excursion_points": adverse_points,
                "adverse_excursion_pct_spot": adverse_points / float(record["entry_spot"]),
                "pnl_at_target_low_points": low_premium - entry_premium,
                "pnl_at_target_low_pct": low_premium / entry_premium - 1.0,
                "selected_exit_pnl_points": selected_premium - entry_premium,
                "selected_exit_pnl_pct": selected_premium / entry_premium - 1.0,
            }
        )
        records.append(record)
    trades = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    if (
        trades[["entry_put_close", "target_low_put_close", "target_high_put_close"]]
        .isna()
        .any()
        .any()
    ):
        raise RuntimeError("missing premium in completed trade panel")
    premium_columns = ["entry_put_close", "target_low_put_close", "target_high_put_close"]
    if (trades[premium_columns] <= 0).any().any():
        raise RuntimeError("non-positive premium in completed trade panel")
    volume_columns = ["entry_put_volume", "target_low_put_volume", "target_high_put_volume"]
    if (trades[volume_columns] <= 0).any().any():
        raise RuntimeError("non-positive traded volume in completed trade panel")
    wins = trades[trades["sequence_hit"] == 1]
    losses = trades[trades["sequence_hit"] == 0]
    hit_rate = float(trades["sequence_hit"].mean())
    average_win_points = float(wins["selected_exit_pnl_points"].mean())
    average_win_return = float(wins["selected_exit_pnl_pct"].mean())
    average_loss_points = -float(losses["selected_exit_pnl_points"].mean())
    average_loss_return = -float(losses["selected_exit_pnl_pct"].mean())
    actual_expectancy_points = (
        hit_rate * average_win_points - (1.0 - hit_rate) * average_loss_points
    )
    actual_expectancy_return = (
        hit_rate * average_win_return - (1.0 - hit_rate) * average_loss_return
    )
    coinflip_expectancy_points = 0.5 * (average_win_points - average_loss_points)
    coinflip_expectancy_return = 0.5 * (average_win_return - average_loss_return)
    expectancy_ttest = ttest_1samp(trades["selected_exit_pnl_pct"], 0.0)
    breakeven_win_rate_points = average_loss_points / (average_win_points + average_loss_points)
    breakeven_win_rate_return = average_loss_return / (average_win_return + average_loss_return)
    max_loss_actual_return = hit_rate / (1.0 - hit_rate) * average_win_return
    max_loss_coinflip_return = average_win_return
    stricter_loss_ceiling = min(max_loss_actual_return, max_loss_coinflip_return)
    recommended_stop_return = round(0.8 * stricter_loss_ceiling, 2)

    results = {
        "definitions": {
            "entry": "close of actual ATM weekly PUT 09:17 minute bar",
            "hit_exit": "same entry strike PUT close at first target-window spot low minute",
            "miss_exit": "same entry strike PUT close at first target-window spot high minute",
            "target": "09:18 through 09:45 inclusive, first occurrence of extrema",
            "premium_data": "observed 1-minute OHLC close; not bid/ask or Black-Scholes",
        },
        "data_audit": {
            "combined_days": len(combined),
            "put_signal_days": len(trades),
            "atm_files": len(atm_paths),
            "relative_strike_files": len(required_relative_paths),
            "dynamic_atm_exit_mismatches_corrected": int(
                (trades["exit_relative_strike"] != "ATM").sum()
            ),
            "missing_trade_quotes": 0,
            "sequence_hits": len(wins),
            "sequence_misses": len(losses),
            "sequence_hit_rate": hit_rate,
        },
        "entry_premium": mean_median(trades["entry_put_close"]),
        "downside_excursion_all_days_points": mean_median(trades["downside_excursion_points"]),
        "downside_excursion_all_days_pct_spot": mean_median(trades["downside_excursion_pct_spot"]),
        "target_low_exit_premium_all_days": mean_median(trades["target_low_put_close"]),
        "target_low_pnl_all_days_points": mean_median(trades["pnl_at_target_low_points"]),
        "target_low_pnl_all_days_pct": mean_median(trades["pnl_at_target_low_pct"]),
        "hit_days": {
            "n": len(wins),
            "pnl_points": mean_median(wins["selected_exit_pnl_points"]),
            "pnl_pct": mean_median(wins["selected_exit_pnl_pct"]),
            "positive_premium_pnl_count": int((wins["selected_exit_pnl_points"] > 0).sum()),
        },
        "miss_days": {
            "n": len(losses),
            "adverse_points": mean_median(losses["adverse_excursion_points"]),
            "adverse_pct_spot": mean_median(losses["adverse_excursion_pct_spot"]),
            "exit_premium": mean_median(losses["selected_exit_put_close"]),
            "pnl_points": mean_median(losses["selected_exit_pnl_points"]),
            "pnl_pct": mean_median(losses["selected_exit_pnl_pct"]),
            "negative_premium_pnl_count": int((losses["selected_exit_pnl_points"] < 0).sum()),
        },
        "expectancy": {
            "average_win_points": average_win_points,
            "average_win_return": average_win_return,
            "average_loss_points": average_loss_points,
            "average_loss_return": average_loss_return,
            "actual_hit_rate": hit_rate,
            "actual_expectancy_points": actual_expectancy_points,
            "actual_expectancy_return": actual_expectancy_return,
            "coinflip_expectancy_points": coinflip_expectancy_points,
            "coinflip_expectancy_return": coinflip_expectancy_return,
            "observed_return_t_stat": float(expectancy_ttest.statistic),
            "observed_return_ttest_p": float(expectancy_ttest.pvalue),
            "breakeven_win_rate_points": breakeven_win_rate_points,
            "breakeven_win_rate_return": breakeven_win_rate_return,
            "max_average_loss_actual_return": max_loss_actual_return,
            "max_average_loss_coinflip_return": max_loss_coinflip_return,
            "recommended_stop_return": float(recommended_stop_return),
        },
    }
    trades.to_csv(SCRATCH / "k2_expiry_vix_put_trades.csv", index=False)
    (SCRATCH / "k2_expiry_vix_put_pnl_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    def pct(value: float) -> str:
        return f"{100 * value:.1f}%"

    def pct2(value: float) -> str:
        return f"{100 * value:.2f}%"

    report = "\n".join(
        [
            "# Actual-premium PUT P&L sanity check",
            "",
            "The frozen signal sample contains 57 of the 108 expiry-plus-VIX-rise days: buy the "
            "ATM weekly PUT at the 09:17 minute close when the initial window is low-before-high. "
            "The sequence hit is target low-before-high during 09:18–09:45. Entry and exit use "
            "observed option minute-bar closes. The exact 09:17 strike is tracked through exit; "
            f"this corrects {results['data_audit']['dynamic_atm_exit_mismatches_corrected']} "
            "days where the dynamic ATM series rolled to a different strike.",
            "",
            "## Observed economics",
            "",
            f"- Signal N: **{len(trades)}**; sequence hits: **{len(wins)}**; misses: "
            f"**{len(losses)}**; hit rate: **{pct(hit_rate)}**.",
            f"- Entry PUT premium: mean **{results['entry_premium']['mean']:.2f}**, median "
            f"**{results['entry_premium']['median']:.2f}** points.",
            f"- Entry spot to target low, all signal days: mean **"
            f"{results['downside_excursion_all_days_points']['mean']:.1f}** points "
            f"({pct2(results['downside_excursion_all_days_pct_spot']['mean'])}), median **"
            f"{results['downside_excursion_all_days_points']['median']:.1f}** points "
            f"({pct2(results['downside_excursion_all_days_pct_spot']['median'])}). Positive means "
            "spot fell below entry.",
            f"- PUT at target-low minute, all days: mean **"
            f"{results['target_low_exit_premium_all_days']['mean']:.2f}**, median **"
            f"{results['target_low_exit_premium_all_days']['median']:.2f}**. P&L: mean **"
            f"{results['target_low_pnl_all_days_points']['mean']:+.2f}** points / "
            f"**{pct(results['target_low_pnl_all_days_pct']['mean'])}**, median **"
            f"{results['target_low_pnl_all_days_points']['median']:+.2f}** / "
            f"**{pct(results['target_low_pnl_all_days_pct']['median'])}**.",
            f"- Hit-day exit at target low: average gain **{average_win_points:.2f} points / "
            f"{pct(average_win_return)}**; median **"
            f"{results['hit_days']['pnl_points']['median']:.2f} / "
            f"{pct(results['hit_days']['pnl_pct']['median'])}**.",
            f"- Miss convention: conservatively exit when spot first reaches the target-window "
            f"high, which occurs before its low on these days. Adverse spot excursion: mean **"
            f"{results['miss_days']['adverse_points']['mean']:.1f} points / "
            f"{pct2(results['miss_days']['adverse_pct_spot']['mean'])}**, median **"
            f"{results['miss_days']['adverse_points']['median']:.1f} / "
            f"{pct2(results['miss_days']['adverse_pct_spot']['median'])}**. Exit PUT premium: "
            f"mean **{results['miss_days']['exit_premium']['mean']:.2f}**, median **"
            f"{results['miss_days']['exit_premium']['median']:.2f}**; P&L mean **"
            f"{results['miss_days']['pnl_points']['mean']:+.2f} / "
            f"{pct(results['miss_days']['pnl_pct']['mean'])}**, median **"
            f"{results['miss_days']['pnl_points']['median']:+.2f} / "
            f"{pct(results['miss_days']['pnl_pct']['median'])}**.",
            f"- Sequencing and premium profitability are not identical: only "
            f"**{results['hit_days']['positive_premium_pnl_count']}/{len(wins)}** sequence-hit "
            f"exits made money, while **"
            f"{len(losses) - results['miss_days']['negative_premium_pnl_count']}/{len(losses)}** "
            "sequence-miss stop exits still had positive premium P&L.",
            "",
            "## Breakeven and stop math",
            "",
            f"Using mean premium returns, average win is **{pct(average_win_return)}** and "
            f"average loss is **{pct(average_loss_return)}**. At the observed {pct(hit_rate)} "
            f"hit rate: {hit_rate:.3f}×{pct(average_win_return)} − "
            f"{1 - hit_rate:.3f}×{pct(average_loss_return)} = **"
            f"{pct(actual_expectancy_return)} per trade**. The return-based breakeven hit rate "
            f"is **{pct(breakeven_win_rate_return)}**. In premium points the same calculation "
            f"is {hit_rate:.3f}×{average_win_points:.2f} − "
            f"{1 - hit_rate:.3f}×{average_loss_points:.2f} = **"
            f"{actual_expectancy_points:.2f} points per trade**. With only 57 observations, the "
            f"mean-return t-test is not significant (p={float(expectancy_ttest.pvalue):.3f}).",
            f"At a forced 50% hit rate: 0.5×{pct(average_win_return)} − "
            f"0.5×{pct(average_loss_return)} = **{pct(coinflip_expectancy_return)} per trade**, "
            f"or **{coinflip_expectancy_points:.2f} premium points**.",
            f"The maximum tolerable average loss is **{pct(max_loss_actual_return)}** at the "
            f"observed hit rate and **{pct(max_loss_coinflip_return)}** at a 50% hit rate. A "
            f"practical conservative starting stop is therefore about **"
            f"{pct(float(recommended_stop_return))} of premium paid**, leaving a 20% cushion "
            "below the stricter theoretical ceiling.",
            "",
            "## Caveats",
            "",
            "This is an in-sample, post-selected, 57-trade paper backtest. Minute-bar closes are "
            "actual observed traded prices but not guaranteed executable bid/ask fills; spreads, "
            "slippage, fees, taxes, and intraminute ordering are not modeled. The extrema-based "
            "hit/miss exits are hindsight path proxies, not yet a fully specified live stop or "
            "profit-taking rule. Prospective validation is required.",
            "",
        ]
    )
    (SCRATCH / "report_k2_expiry_vix_put_pnl.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
