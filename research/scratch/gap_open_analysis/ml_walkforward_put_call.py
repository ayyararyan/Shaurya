#!/usr/bin/env python3
"""Expanding-window walk-forward CALL/PUT classifier for the 09:17 decision point.

Label: sign of r_after_r2_to_0945 (actual spot return from 09:17 decision price to 09:45
target-window close) -> 1 = CALL (up), 0 = PUT (down).

Features (all known by 09:17, no leakage): gap, gap_dir, iv_bucket, opening_iv,
is_expiry_day, vix_rose, vix_overnight_gap, initial_high_first, initial_range_magnitude,
weekday.

Protocol requested: hold out the most recent slice of the sample completely untouched
(no evaluation on it in this run). On the remaining historical pool, run expanding-window
walk-forward: seed with an initial chronological training block, predict the next block,
fold that block into training, predict the next, etc. Report train-fit and walk-forward
(out-of-fold, never-seen-when-predicted) validation performance only. No test-set numbers
are produced by this script.
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
BINARY = ["is_expiry_day", "vix_rose", "initial_high_first", "vix_data_missing"]
CATEGORICAL = ["iv_bucket", "weekday"]

HELD_OUT_FRACTION = 0.15  # most-recent slice, untouched by this run
N_WALKFORWARD_FOLDS = 7
INITIAL_TRAIN_FRACTION = 0.40  # of the walk-forward pool (post held-out split)


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
    df["vix_data_missing"] = df["vix_overnight_gap"].isna().astype(int)
    df["vix_overnight_gap"] = df["vix_overnight_gap"].fillna(0.0)
    return df


def make_pipeline(model) -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL + ["gap_dir"]),
        ],
        remainder="passthrough",
    )
    return Pipeline([("pre", pre), ("model", model)])


def walk_forward(df: pd.DataFrame, feature_cols: list[str], model_factory, name: str) -> dict:
    n = len(df)
    n_held_out = int(round(n * HELD_OUT_FRACTION))
    pool = df.iloc[: n - n_held_out].reset_index(drop=True)
    held_out_dates = (df.iloc[n - n_held_out]["date"], df.iloc[-1]["date"])

    n_pool = len(pool)
    initial_train_n = int(round(n_pool * INITIAL_TRAIN_FRACTION))
    remaining = n_pool - initial_train_n
    fold_size = remaining // N_WALKFORWARD_FOLDS

    fold_reports = []
    oof_true, oof_pred, oof_proba = [], [], []
    train_accs = []

    cursor = initial_train_n
    for fold_i in range(N_WALKFORWARD_FOLDS):
        fold_end = cursor + fold_size if fold_i < N_WALKFORWARD_FOLDS - 1 else n_pool
        train = pool.iloc[:cursor]
        val = pool.iloc[cursor:fold_end]
        if len(val) == 0:
            break
        X_train, y_train = train[feature_cols], train["y"]
        X_val, y_val = val[feature_cols], val["y"]

        pipe = make_pipeline(model_factory())
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

        fold_reports.append(
            {
                "fold": fold_i + 1,
                "train_n": len(train),
                "val_n": len(val),
                "val_dates": (val["date"].min().date().isoformat(), val["date"].max().date().isoformat()),
                "train_acc": train_acc,
                "val_acc": val_acc,
                "val_base_rate_call": float(y_val.mean()),
            }
        )
        cursor = fold_end

    oof_true = np.array(oof_true)
    oof_pred = np.array(oof_pred)
    oof_proba = np.array(oof_proba)
    overall_val_acc = accuracy_score(oof_true, oof_pred)
    try:
        overall_val_auc = roc_auc_score(oof_true, oof_proba)
    except ValueError:
        overall_val_auc = float("nan")
    majority_baseline = max(oof_true.mean(), 1 - oof_true.mean())

    return {
        "name": name,
        "n_total": n,
        "n_held_out_untouched": n_held_out,
        "held_out_date_range": (held_out_dates[0].date().isoformat(), held_out_dates[1].date().isoformat()),
        "n_pool": n_pool,
        "initial_train_n": initial_train_n,
        "fold_reports": fold_reports,
        "mean_train_acc": float(np.mean(train_accs)),
        "overall_walkforward_val_acc": float(overall_val_acc),
        "overall_walkforward_val_auc": float(overall_val_auc),
        "walkforward_pool_majority_baseline": float(majority_baseline),
    }


def print_report(result: dict) -> None:
    print(f"\n===== {result['name']} =====")
    print(f"Total days: {result['n_total']}  |  Held out untouched (most recent, NOT evaluated): "
          f"{result['n_held_out_untouched']} days ({result['held_out_date_range'][0]} to {result['held_out_date_range'][1]})")
    print(f"Walk-forward pool: {result['n_pool']} days  |  Initial seed train: {result['initial_train_n']} days")
    print(f"{'Fold':>4} {'Train N':>8} {'Val N':>6} {'Val period':>25} {'TrainAcc':>9} {'ValAcc':>8} {'ValBaseRate(CALL)':>18}")
    for f in result["fold_reports"]:
        period = f"{f['val_dates'][0]}..{f['val_dates'][1]}"
        print(f"{f['fold']:>4} {f['train_n']:>8} {f['val_n']:>6} {period:>25} "
              f"{f['train_acc']*100:>8.1f}% {f['val_acc']*100:>7.1f}% {f['val_base_rate_call']*100:>17.1f}%")
    print(f"\nMean in-sample train accuracy across folds: {result['mean_train_acc']*100:.1f}%")
    print(f"Pooled out-of-fold walk-forward VALIDATION accuracy: {result['overall_walkforward_val_acc']*100:.1f}%")
    print(f"Pooled out-of-fold walk-forward VALIDATION AUC:      {result['overall_walkforward_val_auc']:.3f}")
    print(f"Majority-class baseline over the same validation pool: {result['walkforward_pool_majority_baseline']*100:.1f}%")


def main() -> None:
    df = build_dataset()
    feature_cols = NUMERIC + BINARY + CATEGORICAL + ["gap_dir"]
    print(f"Dataset: {len(df)} days, {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"Overall base rate (CALL / up days): {df['y'].mean()*100:.1f}%")

    baseline_result = walk_forward(
        df, feature_cols, lambda: LogisticRegression(max_iter=2000), "Logistic Regression (linear, no explicit interactions)"
    )
    print_report(baseline_result)

    gbm_result = walk_forward(
        df,
        feature_cols,
        lambda: GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0
        ),
        "Gradient Boosted Trees (captures interactions, e.g. expiry x VIX-rise, gap x IV-bucket)",
    )
    print_report(gbm_result)


if __name__ == "__main__":
    main()
