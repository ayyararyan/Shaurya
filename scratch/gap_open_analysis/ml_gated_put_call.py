#!/usr/bin/env python3
"""Two-stage (gated) CALL/PUT model, as requested.

Stage 1 (the gate) is NOT learned — it is the two conditions already found in the
interaction scan: the model only fires on days matching one of the two regimes.
Stage 2 is a walk-forward directional classifier trained ONLY within each gate's
qualifying days.

Gate A: is_expiry_day == 1 AND vix_rose == 1                (Effect 1 regime, N~108)
Gate B: is_expiry_day == 0 AND gap_dir == 'down' AND vix_rose == 1   (Effect 2's
        parent regime, BEFORE restricting to mid-IV — iv_bucket is kept as a
        FEATURE inside this gate so we can see whether the model actually finds
        mid-IV useful, rather than assuming it by construction).

Label: sign of r_after_r2_to_0945 (09:17 -> 09:45 realized return) -> CALL(1)/PUT(0).
Same held-out-untouched + expanding-window walk-forward protocol as the ungated run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer

SCRATCH_DIR = "/Users/maheit/Documents/Shaurya/scratch/gap_open_analysis"

NUMERIC = ["gap", "opening_iv", "vix_overnight_gap", "initial_range_magnitude"]
BINARY = ["initial_high_first"]
CATEGORICAL = ["iv_bucket", "weekday"]


def build_dataset() -> pd.DataFrame:
    dm = pd.read_csv(f"{SCRATCH_DIR}/daily_measures.csv", parse_dates=["date"])
    k2 = pd.read_csv(f"{SCRATCH_DIR}/k2_expiry_vix_rose_panel.csv", parse_dates=["date"])
    df = k2.merge(dm[["date", "r_after_r2_to_0945"]], on="date", how="inner", validate="one_to_one")
    df = df.sort_values("date").reset_index(drop=True)
    df["gap_dir"] = np.where(df["gap"] > 0, "up", "down")
    df["y"] = (df["r_after_r2_to_0945"] > 0).astype(int)
    df["vix_rose"] = df["vix_rose"].astype(int)
    df["is_expiry_day"] = df["is_expiry_day"].astype(int)
    df["initial_high_first"] = df["initial_high_first"].astype(int)
    df["vix_overnight_gap"] = df["vix_overnight_gap"].fillna(0.0)
    return df


def make_pipeline(model, categorical_cols) -> Pipeline:
    pre = ColumnTransformer(
        transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols)],
        remainder="passthrough",
    )
    return Pipeline([("pre", pre), ("model", model)])


def walk_forward(df, feature_cols, categorical_cols, model_factory, name,
                  held_out_fraction, n_folds, initial_train_fraction):
    n = len(df)
    n_held_out = max(1, int(round(n * held_out_fraction)))
    pool = df.iloc[: n - n_held_out].reset_index(drop=True)
    held_out_dates = (df.iloc[n - n_held_out]["date"], df.iloc[-1]["date"])

    n_pool = len(pool)
    initial_train_n = max(10, int(round(n_pool * initial_train_fraction)))
    remaining = max(n_folds, n_pool - initial_train_n)
    fold_size = max(1, remaining // n_folds)

    fold_reports = []
    oof_true, oof_pred, oof_proba = [], [], []
    train_accs = []
    importances = []

    cursor = initial_train_n
    fold_i = 0
    while cursor < n_pool:
        fold_end = min(cursor + fold_size, n_pool) if fold_i < n_folds - 1 else n_pool
        train = pool.iloc[:cursor]
        val = pool.iloc[cursor:fold_end]
        if len(val) == 0 or train["y"].nunique() < 2:
            cursor = fold_end
            fold_i += 1
            continue
        X_train, y_train = train[feature_cols], train["y"]
        X_val, y_val = val[feature_cols], val["y"]

        model = model_factory()
        pipe = make_pipeline(model, categorical_cols)
        pipe.fit(X_train, y_train)

        train_pred = pipe.predict(X_train)
        val_pred = pipe.predict(X_val)
        val_proba = pipe.predict_proba(X_val)[:, 1]

        train_acc = accuracy_score(y_train, train_pred)
        val_acc = accuracy_score(y_val, val_pred)
        train_accs.append(train_acc)
        oof_true.extend(y_val.tolist())
        oof_pred.extend(val_pred.tolist())
        oof_proba.extend(val_proba.tolist())

        if hasattr(model, "feature_importances_"):
            feat_names = pipe.named_steps["pre"].get_feature_names_out()
            importances.append(dict(zip(feat_names, model.feature_importances_)))

        fold_reports.append({
            "fold": fold_i + 1,
            "train_n": len(train), "val_n": len(val),
            "val_dates": (val["date"].min().date().isoformat(), val["date"].max().date().isoformat()),
            "train_acc": train_acc, "val_acc": val_acc,
            "val_base_rate_call": float(y_val.mean()),
        })
        cursor = fold_end
        fold_i += 1
        if fold_i >= n_folds and cursor >= n_pool:
            break

    oof_true = np.array(oof_true); oof_pred = np.array(oof_pred); oof_proba = np.array(oof_proba)
    overall_val_acc = accuracy_score(oof_true, oof_pred)
    try:
        overall_val_auc = roc_auc_score(oof_true, oof_proba)
    except ValueError:
        overall_val_auc = float("nan")
    majority_baseline = max(oof_true.mean(), 1 - oof_true.mean()) if len(oof_true) else float("nan")

    avg_importance = {}
    if importances:
        keys = importances[0].keys()
        for k in keys:
            avg_importance[k] = float(np.mean([imp.get(k, 0.0) for imp in importances]))

    return {
        "name": name, "n_total": n, "n_held_out_untouched": n_held_out,
        "held_out_date_range": (held_out_dates[0].date().isoformat(), held_out_dates[1].date().isoformat()),
        "n_pool": n_pool, "initial_train_n": initial_train_n,
        "fold_reports": fold_reports, "mean_train_acc": float(np.mean(train_accs)) if train_accs else float("nan"),
        "overall_walkforward_val_acc": float(overall_val_acc),
        "overall_walkforward_val_auc": float(overall_val_auc),
        "walkforward_pool_majority_baseline": float(majority_baseline),
        "n_oof": len(oof_true),
        "feature_importance": avg_importance,
    }


def print_report(result: dict) -> None:
    print(f"\n===== {result['name']} =====")
    print(f"Gate-qualifying days: {result['n_total']}  |  Held out untouched (most recent): "
          f"{result['n_held_out_untouched']} days ({result['held_out_date_range'][0]} to {result['held_out_date_range'][1]})")
    print(f"Walk-forward pool: {result['n_pool']} days  |  Initial seed train: {result['initial_train_n']} days")
    print(f"{'Fold':>4} {'Train N':>8} {'Val N':>6} {'Val period':>25} {'TrainAcc':>9} {'ValAcc':>8} {'ValBaseRate(CALL)':>18}")
    for f in result["fold_reports"]:
        period = f"{f['val_dates'][0]}..{f['val_dates'][1]}"
        print(f"{f['fold']:>4} {f['train_n']:>8} {f['val_n']:>6} {period:>25} "
              f"{f['train_acc']*100:>8.1f}% {f['val_acc']*100:>7.1f}% {f['val_base_rate_call']*100:>17.1f}%")
    print(f"\nMean in-sample train accuracy across folds: {result['mean_train_acc']*100:.1f}%")
    print(f"Pooled out-of-fold walk-forward VALIDATION accuracy (N={result['n_oof']}): {result['overall_walkforward_val_acc']*100:.1f}%")
    print(f"Pooled out-of-fold walk-forward VALIDATION AUC:      {result['overall_walkforward_val_auc']:.3f}")
    print(f"Majority-class baseline over the same validation pool: {result['walkforward_pool_majority_baseline']*100:.1f}%")
    if result["feature_importance"]:
        print("\nMean GBM feature importance across folds (higher = more useful to the model):")
        for k, v in sorted(result["feature_importance"].items(), key=lambda kv: -kv[1]):
            print(f"  {k:<28} {v:.3f}")


def main() -> None:
    df = build_dataset()

    gate_a = df[(df["is_expiry_day"] == 1) & (df["vix_rose"] == 1)].reset_index(drop=True)
    gate_b = df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)].reset_index(drop=True)

    print(f"Gate A (expiry + VIX-rise) qualifying days: {len(gate_a)}")
    print(f"Gate B (non-expiry + gap-down + VIX-rise) qualifying days: {len(gate_b)}  "
          f"[iv_bucket kept as a feature, not a filter, to test whether mid-IV matters]")
    print(f"Gate B breakdown by iv_bucket: {gate_b['iv_bucket'].value_counts().to_dict()}")
    print(f"Gate B base rate of CALL (y=1) by iv_bucket:")
    print(gate_b.groupby("iv_bucket")["y"].mean().to_string())

    feat_cols = NUMERIC + BINARY + CATEGORICAL + ["gap_dir"]

    for name_suffix, subset in [("GATE A: expiry + VIX-rise", gate_a), ("GATE B: non-expiry + gap-down + VIX-rise", gate_b)]:
        cat_cols = [c for c in CATEGORICAL + ["gap_dir"] if subset[c].nunique() > 1]
        cols = NUMERIC + BINARY + cat_cols

        lr_result = walk_forward(
            subset, cols, cat_cols, lambda: LogisticRegression(max_iter=2000),
            f"{name_suffix} -- Logistic Regression",
            held_out_fraction=0.15, n_folds=4, initial_train_fraction=0.40,
        )
        print_report(lr_result)

        gbm_result = walk_forward(
            subset, cols, cat_cols,
            lambda: GradientBoostingClassifier(n_estimators=100, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=0),
            f"{name_suffix} -- Gradient Boosted Trees",
            held_out_fraction=0.15, n_folds=4, initial_train_fraction=0.40,
        )
        print_report(gbm_result)


if __name__ == "__main__":
    main()
