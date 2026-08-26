#!/usr/bin/env python3
"""Is Gate B's mid-IV (14-18%) filter a real subgroup, or a scan artifact?

New module.  It does not modify, and is not imported by, any pre-existing script.  It
reuses the path/exit machinery in ``gate_b_common.py``.

Question
--------
The published Gate B applies FOUR conditions: non-expiry, gap-down, overnight VIX rise,
and opening-IV bucket ``middle_14_18``.  The first three define a population of 198 days;
the fourth cuts it to 56, of which 33 fire on a gap fill.  The IV buckets on those 198
days are near-even thirds (low 81 / mid 56 / high 61), so "mid" is not a natural cluster --
it is one of three similar-sized slices picked out by a 21-cell interaction scan.  This
module runs the Gate-B gap-fill trade across ALL 198 days, splits by bucket, and asks
whether the mid bucket is statistically distinguishable from the other two.

The test is deliberately built so that "mid is significant and the others are not" is NOT
accepted as evidence of a subgroup effect.  What is reported is the formal heterogeneity
(interaction) test: does the outcome actually differ ACROSS buckets?

Outcomes measured, per bucket and pooled
----------------------------------------
1. fire rate            -- share of the bucket's days on which the gap fills after 09:17
2. directional hit rate -- P(reversed | gap fills), the analogue of the published 84.8%
3. persistence gap      -- the statistic the original 21-cell scan actually maximised
4. hold-to-close P&L    -- on REAL strike-tracked traded premiums (primary) and on the
                           Black-Scholes constant-IV proxy (for comparability only)

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from gate_b_common import gate_b_subset, reproduction_guard, rule_return
from gate_b_full_paths import load_full_paths
from ml_gated_put_call import build_dataset

BUCKETS = ("low_<14", "middle_14_18", "high_>18")
RNG_SEED = 20260822
N_PERM = 20_000


# --------------------------------------------------------------------------- population


def parent_population() -> pd.DataFrame:
    """The three-condition population: non-expiry, gap-down, overnight VIX rise."""
    df = build_dataset()
    uni = df[
        (df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)
    ].copy()
    uni = uni.sort_values("date").reset_index(drop=True)
    uni["date_str"] = uni["date"].dt.strftime("%Y-%m-%d")
    uni["reversed"] = uni["initial_high_first"] != uni["target_high_first"]
    return uni


def gate_b_population_paths(paths: list[dict]) -> list[dict]:
    """Gap-fill fires among the 198 parent days (i.e. VIX rose, any IV bucket)."""
    return [p for p in paths if p["vix_rose"] == 1]


# ------------------------------------------------------------------------------- stats


def one_sample(x: np.ndarray) -> dict:
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if len(x) < 3:
        return {"n": len(x), "mean": np.nan, "median": np.nan, "win": np.nan,
                "p": np.nan, "sd": np.nan}
    return {
        "n": int(len(x)),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "win": float((x > 0).mean() * 100.0),
        "sd": float(x.std(ddof=1)),
        "p": float(stats.ttest_1samp(x, 0.0).pvalue),
    }


def proportion_ci(k: int, n: int) -> tuple[float, float]:
    """Wilson 95% interval, in percent."""
    if n == 0:
        return (np.nan, np.nan)
    z = 1.959963985
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half) * 100.0, min(1.0, centre + half) * 100.0)


def persistence_gap(sub: pd.DataFrame) -> dict:
    """The statistic the original 21-cell scan maximised.

    accuracy   = share of days on which the 09:15-09:17 order of extremes REPEATS in the
                 09:18-09:45 window
    gap        = P(target high first | initial high first) - P(target high first | initial
                 low first), in percentage points.  A large NEGATIVE gap is the reversal
                 signature Gate B was selected on.
    """
    hf = sub["initial_high_first"].astype(bool)
    th = sub["target_high_first"].astype(bool)
    n = len(sub)
    if n == 0 or hf.nunique() < 2:
        return {"n": n, "accuracy": np.nan, "gap_pp": np.nan, "p": np.nan}
    a = float(th[hf].mean())
    b = float(th[~hf].mean())
    table = np.array(
        [[int((th & hf).sum()), int((~th & hf).sum())],
         [int((th & ~hf).sum()), int((~th & ~hf).sum())]]
    )
    p = float(stats.fisher_exact(table)[1])
    return {
        "n": n,
        "accuracy": float((hf == th).mean() * 100.0),
        "gap_pp": (a - b) * 100.0,
        "p": p,
    }


# -------------------------------------------------------------------------------- main


def main() -> None:
    paths = load_full_paths()
    reproduction_guard(gate_b_subset(paths))

    uni = parent_population()
    fires = gate_b_population_paths(paths)
    fire_dates = {p["date"] for p in fires}
    uni["filled"] = uni["date_str"].isin(fire_dates)

    out: dict = {"generated_for": "Gate B mid-IV subgroup test (scope addition H, I)"}

    print("=" * 100)
    print("H. IS THE MID-IV FILTER REAL, OR A SUBGROUP ARTIFACT?")
    print("=" * 100)
    print(f"\nParent population (non-expiry + gap-down + overnight VIX rise): "
          f"N = {len(uni)}, {uni['date_str'].min()} .. {uni['date_str'].max()}")
    print("The mid-IV restriction is a FOURTH condition; it is tested here, not assumed.\n")

    # ---------------------------------------------------------------- 1. the funnel
    print("-" * 100)
    print("H.1  Funnel and fire counts")
    print("-" * 100)
    header = f"{'bucket':<14} {'days':>6} {'fires':>7} {'fire rate':>10} {'reversed|fire':>14} {'hit rate':>10} {'95% CI':>18}"
    print(header)
    print("-" * len(header))
    funnel = {}
    for bucket in BUCKETS + ("POOLED",):
        if bucket == "POOLED":
            days = uni
            sub_fires = fires
        else:
            days = uni[uni["iv_bucket"] == bucket]
            sub_fires = [p for p in fires if p["iv_bucket"] == bucket]
        rev = sum(p["reversed"] for p in sub_fires)
        lo, hi = proportion_ci(rev, len(sub_fires))
        funnel[bucket] = {
            "days": int(len(days)),
            "fires": int(len(sub_fires)),
            "fire_rate": float(len(sub_fires) / len(days) * 100.0),
            "reversed": int(rev),
            "hit_rate": float(rev / len(sub_fires) * 100.0) if sub_fires else np.nan,
            "hit_ci": [lo, hi],
        }
        print(f"{bucket:<14} {len(days):>6} {len(sub_fires):>7} "
              f"{funnel[bucket]['fire_rate']:>9.1f}% {rev:>14} "
              f"{funnel[bucket]['hit_rate']:>9.1f}% "
              f"{'[' + format(lo, '.1f') + ', ' + format(hi, '.1f') + ']':>18}")
    out["funnel"] = funnel

    # -------------------------------------------- 2. heterogeneity of the hit rate
    print("\n" + "-" * 100)
    print("H.2  Is the directional hit rate ACTUALLY different across buckets?")
    print("     (the formal heterogeneity test -- not 'mid is significant and the others are not')")
    print("-" * 100)
    table = np.array([
        [funnel[b]["reversed"], funnel[b]["fires"] - funnel[b]["reversed"]] for b in BUCKETS
    ])
    chi2, p_chi, dof, _ = stats.chi2_contingency(table)
    print(f"  3x2 contingency (reversed vs not, by bucket): chi2={chi2:.3f}, dof={dof}, p={p_chi:.4f}")
    # mid vs the other two pooled
    mid = np.array([funnel["middle_14_18"]["reversed"],
                    funnel["middle_14_18"]["fires"] - funnel["middle_14_18"]["reversed"]])
    rest = np.array([
        sum(funnel[b]["reversed"] for b in BUCKETS if b != "middle_14_18"),
        sum(funnel[b]["fires"] - funnel[b]["reversed"] for b in BUCKETS if b != "middle_14_18"),
    ])
    p_mid_rest = stats.fisher_exact(np.vstack([mid, rest]))[1]
    print(f"  mid vs (low + high) pooled, Fisher exact: p={p_mid_rest:.4f}  "
          f"[mid {mid[0]}/{mid.sum()} = {mid[0]/mid.sum()*100:.1f}%  vs  "
          f"rest {rest[0]}/{rest.sum()} = {rest[0]/rest.sum()*100:.1f}%]")
    pairwise = {}
    for a, b in (("middle_14_18", "low_<14"), ("middle_14_18", "high_>18"), ("low_<14", "high_>18")):
        t = np.array([
            [funnel[a]["reversed"], funnel[a]["fires"] - funnel[a]["reversed"]],
            [funnel[b]["reversed"], funnel[b]["fires"] - funnel[b]["reversed"]],
        ])
        pv = float(stats.fisher_exact(t)[1])
        pairwise[f"{a} vs {b}"] = pv
        print(f"  {a:<14} vs {b:<14} Fisher exact p={pv:.4f}")
    # each bucket against a 50/50 coin
    print("\n  Each bucket against a 50/50 coin (binomial, two-sided):")
    binom = {}
    for b in BUCKETS + ("POOLED",):
        k, n = funnel[b]["reversed"], funnel[b]["fires"]
        pv = float(stats.binomtest(k, n, 0.5).pvalue)
        binom[b] = pv
        print(f"    {b:<14} {k}/{n} = {k/n*100:5.1f}%   p={pv:.4f}")
    out["hit_rate_tests"] = {
        "chi2_3x2": {"chi2": float(chi2), "dof": int(dof), "p": float(p_chi)},
        "mid_vs_rest_fisher_p": float(p_mid_rest),
        "pairwise_fisher_p": pairwise,
        "vs_coin_binomial_p": binom,
    }

    # ---------------------------------- 3. the ORIGINAL discovery statistic by bucket
    print("\n" + "-" * 100)
    print("H.3  The statistic Gate B was actually DISCOVERED on (order-of-extremes")
    print("     persistence over ALL days in the bucket, not only the gap-fill fires)")
    print("-" * 100)
    hdr = f"{'bucket':<14} {'N days':>7} {'accuracy':>10} {'persistence gap':>17} {'Fisher p':>10}"
    print(hdr); print("-" * len(hdr))
    disc = {}
    for bucket in BUCKETS + ("POOLED",):
        sub = uni if bucket == "POOLED" else uni[uni["iv_bucket"] == bucket]
        r = persistence_gap(sub)
        disc[bucket] = r
        print(f"{bucket:<14} {r['n']:>7} {r['accuracy']:>9.1f}% {r['gap_pp']:>+16.1f}pp {r['p']:>10.4f}")
    out["discovery_statistic"] = disc

    # -------------------------------------------------------------- 4. real-premium P&L
    print("\n" + "-" * 100)
    print("H.4  Hold-to-close P&L of the Gate-B CALL, by bucket")
    print("     PRIMARY = real strike-tracked traded premiums.  BS = the constant-IV proxy,")
    print("     restricted to the SAME days, shown only for comparability.")
    print("-" * 100)
    pnl = {}
    hdr = (f"{'bucket':<14} {'fires':>6} {'priced':>7} {'real mean':>11} {'real med':>10} "
           f"{'win%':>7} {'p vs 0':>9} | {'BS mean':>9} {'BS med':>9} {'BS p':>8} {'real-BS':>9}")
    print(hdr); print("-" * len(hdr))
    per_bucket_returns: dict[str, np.ndarray] = {}
    per_bucket_pairs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for bucket in BUCKETS + ("POOLED",):
        sub = fires if bucket == "POOLED" else [p for p in fires if p["iv_bucket"] == bucket]
        real = np.asarray([rule_return(p, "real_prices") for p in sub], dtype=float)
        bs = np.asarray([rule_return(p, "bs_prices") for p in sub], dtype=float)
        keep = np.isfinite(real) & np.isfinite(bs)
        r_stats = one_sample(real[keep])
        b_stats = one_sample(bs[keep])
        diff = real[keep] - bs[keep]
        p_pair = float(stats.ttest_1samp(diff, 0.0).pvalue) if keep.sum() >= 3 else np.nan
        per_bucket_returns[bucket] = real[keep]
        per_bucket_pairs[bucket] = (real[keep], bs[keep])
        pnl[bucket] = {
            "fires": int(len(sub)), "priced": int(keep.sum()),
            "real": r_stats, "bs": b_stats,
            "real_minus_bs_mean": float(diff.mean()) if keep.sum() else np.nan,
            "real_minus_bs_p": p_pair,
        }
        print(f"{bucket:<14} {len(sub):>6} {int(keep.sum()):>7} "
              f"{r_stats['mean']:>+10.2f}% {r_stats['median']:>+9.2f}% {r_stats['win']:>6.1f}% "
              f"{r_stats['p']:>9.4f} | {b_stats['mean']:>+8.2f}% {b_stats['median']:>+8.2f}% "
              f"{b_stats['p']:>8.4f} {diff.mean():>+8.2f}pp")
    out["hold_to_close_pnl"] = pnl

    # ---------------------------------------- 5. heterogeneity of the return itself
    print("\n" + "-" * 100)
    print("H.5  Is the RETURN actually different across buckets?")
    print("-" * 100)
    groups = [per_bucket_returns[b] for b in BUCKETS]
    f_stat, p_anova = stats.f_oneway(*groups)
    h_stat, p_kw = stats.kruskal(*groups)
    mid_r = per_bucket_returns["middle_14_18"]
    rest_r = np.concatenate([per_bucket_returns[b] for b in BUCKETS if b != "middle_14_18"])
    t_mr, p_mr = stats.ttest_ind(mid_r, rest_r, equal_var=False)
    u_mr, p_mw = stats.mannwhitneyu(mid_r, rest_r, alternative="two-sided")
    print(f"  one-way ANOVA across the three buckets : F={f_stat:.3f}, p={p_anova:.4f}")
    print(f"  Kruskal-Wallis (rank based)            : H={h_stat:.3f}, p={p_kw:.4f}")
    print(f"  mid (N={len(mid_r)}, mean {mid_r.mean():+.2f}%) vs rest "
          f"(N={len(rest_r)}, mean {rest_r.mean():+.2f}%):")
    print(f"      Welch t-test  p={p_mr:.4f}")
    print(f"      Mann-Whitney  p={p_mw:.4f}")

    # permutation test of the "mid is special" claim
    rng = np.random.default_rng(RNG_SEED)
    labels = np.array([p["iv_bucket"] for p in fires])
    real_all = np.asarray([rule_return(p, "real_prices") for p in fires], dtype=float)
    ok = np.isfinite(real_all)
    labels_ok, real_ok = labels[ok], real_all[ok]
    n_mid = int((labels_ok == "middle_14_18").sum())
    observed_delta = (
        real_ok[labels_ok == "middle_14_18"].mean() - real_ok[labels_ok != "middle_14_18"].mean()
    )
    idx = np.arange(len(real_ok))
    draws = np.empty(N_PERM)
    for i in range(N_PERM):
        pick = rng.permutation(idx)
        a, b = pick[:n_mid], pick[n_mid:]
        draws[i] = real_ok[a].mean() - real_ok[b].mean()
    p_perm = float((np.abs(draws) >= abs(observed_delta)).mean())
    print(f"\n  Label-permutation test ({N_PERM:,} draws): the mid bucket's mean return is")
    print(f"  {observed_delta:+.2f}pp away from the rest.  A random relabelling of which "
          f"{n_mid} of the")
    print(f"  {len(real_ok)} fires are 'mid' is at least this extreme {p_perm*100:.1f}% of the time "
          f"(p={p_perm:.4f}).")
    out["return_heterogeneity"] = {
        "anova": {"F": float(f_stat), "p": float(p_anova)},
        "kruskal": {"H": float(h_stat), "p": float(p_kw)},
        "mid_vs_rest_welch_p": float(p_mr),
        "mid_vs_rest_mannwhitney_p": float(p_mw),
        "permutation": {"n_draws": N_PERM, "observed_delta_pp": float(observed_delta),
                        "p": p_perm},
    }

    # ---------------------------------------------------- 6. multiple comparisons status
    print("\n" + "-" * 100)
    print("H.6  Multiple-comparisons status of the original mid-bucket claim")
    print("-" * 100)
    raw = disc["middle_14_18"]["p"]
    n_tests = 21
    print(f"  The mid-IV cell was selected from a {n_tests}-cell interaction scan.")
    print(f"  Its discovery statistic on this population: persistence gap "
          f"{disc['middle_14_18']['gap_pp']:+.1f}pp, Fisher p={raw:.4f}.")
    print(f"  Bonferroni-adjusted p (x{n_tests})            : {min(1.0, raw * n_tests):.4f}")
    print(f"  Sidak-adjusted p                            : "
          f"{1 - (1 - raw) ** n_tests:.4f}")
    out["multiple_comparisons"] = {
        "n_cells_scanned": n_tests,
        "raw_discovery_p": float(raw),
        "bonferroni_p": float(min(1.0, raw * n_tests)),
        "sidak_p": float(1 - (1 - raw) ** n_tests),
    }

    # -------------------------------------------------------------- I. firing frequency
    print("\n" + "=" * 100)
    print("I. FIRING FREQUENCY UNDER EACH READING")
    print("=" * 100)
    first = pd.to_datetime(uni["date_str"].min())
    last = pd.to_datetime(uni["date_str"].max())
    years = (last - first).days / 365.25
    freq = {}
    for label, sub in (("published Gate B (mid-IV only)",
                        [p for p in fires if p["iv_bucket"] == "middle_14_18"]),
                       ("pooled Gate B (all IV buckets)", fires)):
        per_year = len(sub) / years
        freq[label] = {"fires": len(sub), "per_year": per_year}
        print(f"  {label:<34} {len(sub):>4} fires over {years:.2f} years "
              f"= {per_year:5.1f} per year (~1 every {252/per_year:4.1f} trading days)")
    print("\n  Fires per calendar year:")
    cal = pd.DataFrame([{"date": p["date"], "bucket": p["iv_bucket"]} for p in fires])
    cal["year"] = cal["date"].str[:4]
    tab = cal.pivot_table(index="year", columns="bucket", aggfunc="size", fill_value=0)
    tab["ALL"] = tab.sum(axis=1)
    print(tab.to_string())
    print("\n  (2021 starts 2021-01-05 and 2026 ends 2026-05-14 -- both are partial years.)")
    out["firing_frequency"] = {
        "span_years": float(years),
        "by_reading": freq,
        "by_calendar_year": json.loads(tab.to_json(orient="index")),
    }

    with open("gate_b_iv_subgroup_results.json", "w") as handle:
        json.dump(out, handle, indent=2, default=float)
    print("\nWrote gate_b_iv_subgroup_results.json")


if __name__ == "__main__":
    main()
