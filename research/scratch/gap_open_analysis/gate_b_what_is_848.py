"""What does Gate B's headline 84.8% hit rate actually measure?

Traced 2026-08-23 from gate_b_common.py:259 back through k2_expiry_vix_rose_panel.csv.

    reversed := initial_high_first != target_high_first

    initial_high_first -- in 09:15-09:17 (3 minutes), did the high precede the low?
    target_high_first  -- in 09:18-09:45 (28 minutes), did the high precede the low?

So "84.8%" is the rate at which a 3-minute order-of-extremes pattern FAILS TO REPEAT
over the following 28 minutes. It is not a directional forecast of the day, it says
nothing about magnitude, and it is not measured at the close.
"""
import pandas as pd

PANEL = "k2_expiry_vix_rose_panel.csv"
CEILING = "gate_b_exit_ceiling_panel.csv"


def main():
    p = pd.read_csv(PANEL)
    p = p[p.k == 2]
    c = pd.read_csv(CEILING)
    p["date"] = p["date"].astype(str)
    c["date"] = c["date"].astype(str)
    m = c.merge(p[["date", "initial_high_first", "target_high_first"]], on="date", how="left")
    fires, ctl = m[m.is_gate_b == 1], m[m.is_gate_b == 0]

    print(f"decision 09:17 | initial 09:15-09:17 | target 09:18-09:45 "
          f"({p.target_window_minutes.iloc[0]} min)\n")
    for name, g in [("FIRES   ", fires), ("CONTROLS", ctl)]:
        print(f"{name} N={len(g):3d}  initial_high_first={100*g.initial_high_first.mean():5.1f}%  "
              f"target_high_first={100*g.target_high_first.mean():5.1f}%  "
              f"reversed={100*g.reversed.mean():5.1f}%")

    print("\nfires cross-tab (rows initial, cols target):")
    print(pd.crosstab(fires.initial_high_first, fires.target_high_first))
    print("\ncontrols cross-tab:")
    print(pd.crosstab(ctl.initial_high_first, ctl.target_high_first))

    print("\nDoes the label separate money? (fires, real premiums, hold to close)")
    print(fires.groupby("reversed")[["close_ret_pct", "close_move_pts"]]
          .agg(["count", "mean", "median"]).round(2))


if __name__ == "__main__":
    main()
