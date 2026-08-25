"""Time from Gate B classification (gap-fill minute) to the day's peak.

Answers Aryan's question of 2026-08-23: "what is the average time difference
between the peak occurring and the time at which that day has been classified
as a trending day?"

Reads the panel produced by gate_b_exit_ceiling.py. No new data, no BS proxy.
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260823)
PANEL = "gate_b_exit_ceiling_panel.csv"


def perm_diff(a, b, stat, n=20000):
    obs = stat(a, b)
    pool = np.concatenate([a, b])
    na = len(a)
    hits = 0
    for _ in range(n):
        RNG.shuffle(pool)
        hits += abs(stat(pool[:na], pool[na:])) >= abs(obs) - 1e-12
    return obs, hits / n


def spearman_perm(x, y, n=5000):
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    r = np.corrcoef(rx, ry)[0, 1]
    hits = sum(abs(np.corrcoef(rx, RNG.permutation(ry))[0, 1]) >= abs(r) - 1e-12
               for _ in range(n))
    return r, hits / n


def main():
    d = pd.read_csv(PANEL)
    fires, ctrl = d[d.is_gate_b == 1], d[d.is_gate_b == 0]

    for col, lab in [("oracle_peak_elapsed_min", "premium peak"),
                     ("spot_argmax_elapsed_min", "spot peak")]:
        a = fires[col].dropna().to_numpy(float)
        b = ctrl[col].dropna().to_numpy(float)
        dmed, pmed = perm_diff(a, b, lambda x, y: np.median(x) - np.median(y))
        dmean, pmean = perm_diff(a, b, lambda x, y: np.mean(x) - np.mean(y))
        print(f"{lab:13s} N={len(a)}/{len(b)} "
              f"median {np.median(a):6.1f} vs {np.median(b):6.1f} (diff {dmed:+.1f}, p={pmed:.3f}) | "
              f"mean {np.mean(a):6.1f} vs {np.mean(b):6.1f} (diff {dmean:+.1f}, p={pmean:.3f})")

    med = np.median(fires.oracle_peak_elapsed_min.dropna())
    for nm, g in [("fires", fires), ("controls", ctrl)]:
        s = g.oracle_peak_elapsed_min.dropna().to_numpy(float)
        u = g.oracle_peak_u.dropna().to_numpy(float)
        print(f"{nm:9s} within +/-30min of {med:.0f}: {100 * np.mean(abs(s - med) <= 30):5.1f}% | "
              f"+/-60min: {100 * np.mean(abs(s - med) <= 60):5.1f}% | "
              f"thirds {100 * np.mean(u < 1/3):.1f}/{100 * np.mean((u >= 1/3) & (u < 2/3)):.1f}/"
              f"{100 * np.mean(u >= 2/3):.1f}")
        print(f"{nm:9s} deciles: {np.percentile(s, np.arange(10, 100, 10)).round(0).astype(int)}")

    for nm, g in [("fires", fires), ("controls", ctrl)]:
        g = g.dropna(subset=["oracle_peak_elapsed_min", "oracle_peak_ret_pct", "entry_minute"])
        r, p = spearman_perm(g.oracle_peak_elapsed_min, g.oracle_peak_ret_pct)
        r2, p2 = spearman_perm(g.entry_minute, g.oracle_peak_elapsed_min)
        print(f"{nm:9s} rho(elapsed, peak size)={r:+.3f} p={p:.3f} | "
              f"rho(classification clock, elapsed)={r2:+.3f} p={p2:.3f}")


if __name__ == "__main__":
    main()
