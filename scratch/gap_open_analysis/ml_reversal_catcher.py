#!/usr/bin/env python3
"""Walk-forward classifier: within the mid-IV Gate B cell (non-expiry + gap-down +
VIX-rise + mid-IV, N=56), predict at 09:17 whether TODAY will be a "reversed" day
(order-flip -> historically a big, slow-building, all-day trend) vs a "continued" day
(order confirms -> historically a small, fast-resolving move).

Important framing: within this cell, "reversed" is already the majority class (39/56 =
69.6%), so a majority-class baseline already scores 69.6% "accuracy" -- that's not new
information, it's the same fact Effect 2's discovery already told us. The useful question
is whether features known at 09:17 let the model do BETTER than that naive baseline, and
in particular whether it can achieve high PRECISION on its "reversed" calls (so that when
it fires, you can trust the trade), not just match the base rate.

Then: for out-of-fold days the model flags as "reversed", report the actual subsequent
move size (points, using the extended end-of-day checkpoints already computed) -- i.e.
what you'd actually have captured had you traded every model-flagged day.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer

sys.path.insert(0, ".")
from ml_gated_put_call import build_dataset

NUMERIC = ["gap", "opening_iv", "vix_overnight_gap", "initial_range_magnitude"]
BINARY = ["initial_high_first"]
CATEGORICAL = ["weekday"]

HELD_OUT_FRACTION = 0.15
N_FOLDS = 4
INITIAL_TRAIN_FRACTION = 0.40


def make_pipeline(model, cat_cols):
    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols)], remainder="passthrough")
    return Pipeline([("pre", pre), ("model", model)])


def walk_forward(df, feat_cols, cat_cols, model_factory, name):
    n = len(df)
    n_held_out = max(1, int(round(n * HELD_OUT_FRACTION)))
    pool = df.iloc[: n - n_held_out].reset_index(drop=True)
    held_out_dates = (df.iloc[n - n_held_out]["date"], df.iloc[-1]["date"])
    n_pool = len(pool)
    initial_train_n = max(10, int(round(n_pool * INITIAL_TRAIN_FRACTION)))
    remaining = max(N_FOLDS, n_pool - initial_train_n)
    fold_size = max(1, remaining // N_FOLDS)

    oof_true, oof_pred, oof_proba, oof_dates = [], [], [], []
    train_accs = []
    fold_reports = []
    cursor = initial_train_n
    fold_i = 0
    while cursor < n_pool:
        fold_end = n_pool if fold_i == N_FOLDS - 1 else min(cursor + fold_size, n_pool)
        train, val = pool.iloc[:cursor], pool.iloc[cursor:fold_end]
        if len(val) == 0 or train["y2"].nunique() < 2:
            cursor = fold_end; fold_i += 1; continue
        pipe = make_pipeline(model_factory(), cat_cols)
        pipe.fit(train[feat_cols], train["y2"])
        train_acc = accuracy_score(train["y2"], pipe.predict(train[feat_cols]))
        val_pred = pipe.predict(val[feat_cols])
        val_proba = pipe.predict_proba(val[feat_cols])[:, 1]
        train_accs.append(train_acc)
        oof_true.extend(val["y2"].tolist()); oof_pred.extend(val_pred.tolist())
        oof_proba.extend(val_proba.tolist()); oof_dates.extend(val["date"].tolist())
        fold_reports.append({
            "fold": fold_i + 1, "train_n": len(train), "val_n": len(val),
            "val_dates": (val["date"].min().date().isoformat(), val["date"].max().date().isoformat()),
            "train_acc": train_acc, "val_acc": accuracy_score(val["y2"], val_pred),
        })
        cursor = fold_end; fold_i += 1

    oof_true = np.array(oof_true); oof_pred = np.array(oof_pred); oof_proba = np.array(oof_proba)
    majority_baseline = max(oof_true.mean(), 1 - oof_true.mean())
    precision = precision_score(oof_true, oof_pred, zero_division=0)
    recall = recall_score(oof_true, oof_pred, zero_division=0)
    try:
        auc = roc_auc_score(oof_true, oof_proba)
    except ValueError:
        auc = float("nan")

    print(f"\n===== {name} =====")
    print(f"N total (mid-IV cell): {n}  |  Held out untouched (most recent): {n_held_out} days "
          f"({held_out_dates[0].date()} to {held_out_dates[1].date()})")
    print(f"Walk-forward pool: {n_pool}  |  Initial seed train: {initial_train_n}")
    for f in fold_reports:
        print(f"  Fold {f['fold']}: train_n={f['train_n']:>3} val_n={f['val_n']:>3} "
              f"period={f['val_dates'][0]}..{f['val_dates'][1]} train_acc={f['train_acc']*100:.1f}% "
              f"val_acc={f['val_acc']*100:.1f}%")
    print(f"Mean train accuracy: {np.mean(train_accs)*100:.1f}%")
    print(f"Pooled out-of-fold validation accuracy: {accuracy_score(oof_true, oof_pred)*100:.1f}% "
          f"(N={len(oof_true)})")
    print(f"Majority-class ('always predict reversed') baseline: {majority_baseline*100:.1f}%")
    print(f"Validation AUC: {auc:.3f}")
    print(f"Precision on 'reversed' calls: {precision*100:.1f}%  |  Recall: {recall*100:.1f}%")
    return pd.DataFrame({"date": oof_dates, "y2_true": oof_true, "y2_pred": oof_pred, "y2_proba": oof_proba})


def main():
    df = build_dataset()
    gate_b = df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)].copy()
    mid = gate_b[gate_b["iv_bucket"] == "middle_14_18"].copy().sort_values("date").reset_index(drop=True)
    mid["y2"] = (mid["initial_high_first"] != mid["target_high_first"]).astype(int)
    print(f"Base rate of 'reversed' in this cell: {mid['y2'].mean()*100:.1f}%  (N={len(mid)})")

    feat_cols = NUMERIC + BINARY + CATEGORICAL
    lr_oof = walk_forward(mid, feat_cols, CATEGORICAL, lambda: LogisticRegression(max_iter=2000),
                           "Logistic Regression -- catch 'reversed' (big-trend) days")
    gbm_oof = walk_forward(mid, feat_cols, CATEGORICAL,
                            lambda: GradientBoostingClassifier(n_estimators=80, max_depth=2, learning_rate=0.05,
                                                                subsample=0.8, random_state=0),
                            "Gradient Boosted Trees -- catch 'reversed' (big-trend) days")

    # Payoff: for out-of-fold days the model FLAGGED as reversed, what was the actual subsequent move?
    ext = pd.read_csv("reversal_timing_extended_detail.csv")
    detail = pd.read_csv("reversal_timing_detail.csv")
    for label, oof in [("Logistic Regression", lr_oof), ("Gradient Boosted Trees", gbm_oof)]:
        flagged = oof[oof["y2_pred"] == 1]["date"].tolist()
        correctly_flagged = oof[(oof["y2_pred"] == 1) & (oof["y2_true"] == 1)]["date"].tolist()
        print(f"\n=== Payoff check ({label}) ===")
        print(f"Out-of-fold days flagged as 'reversed': {len(flagged)} "
              f"(of which {len(correctly_flagged)} were true reversals)")
        moves_all_flagged = ext[ext["date"].isin(flagged)]
        moves_correct_flagged = ext[ext["date"].isin(correctly_flagged)]
        if len(moves_all_flagged):
            print(f"  Among ALL flagged days (right or wrong), move at 09:45: "
                  f"mean={moves_all_flagged['move_pts_at_09:45'].mean():.2f} "
                  f"median={moves_all_flagged['move_pts_at_09:45'].median():.2f}")
            print(f"  Among ALL flagged days, move at end of day: "
                  f"mean={moves_all_flagged['move_pts_at_15:29'].mean():.2f} "
                  f"median={moves_all_flagged['move_pts_at_15:29'].median():.2f}")
        if len(moves_correct_flagged):
            print(f"  Among CORRECTLY flagged (true positive) days, move at end of day: "
                  f"mean={moves_correct_flagged['move_pts_at_15:29'].mean():.2f} "
                  f"median={moves_correct_flagged['move_pts_at_15:29'].median():.2f}")
        # non-reversed days among the flagged set have no "move" in reversal_timing_extended
        # (that file only has the 39 reversed days) -- so flagged-but-wrong days by definition
        # behaved like "continued" days; report how many of those there were.
        wrong = set(flagged) - set(correctly_flagged)
        print(f"  Flagged-but-wrong (false positive, actually a 'continued'/small-move day): {len(wrong)}")


if __name__ == "__main__":
    main()
