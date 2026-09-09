"""
train.py
--------
Trains the XGBoost fraud classifier AND a suite of baseline "existing
systems" (rule-based thresholds, logistic regression, random forest,
isolation forest) on the same time-based train/test split, then produces
one comparison report so you can see exactly how much XGBoost buys you
over each alternative.

Usage:
    python train.py ../data/synthetic.csv
    python train.py ../data/from_db.csv          # data pulled from Postgres

Time-based split (not random shuffle): train on earlier transactions,
test on later ones - matches how the system is actually used (scoring the
future given the past).
"""

import _pathfix  # noqa: F401
import os
import sys
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score, roc_auc_score, precision_recall_curve,
    precision_score, recall_score, f1_score, confusion_matrix,
)

import config
from feature_engineering import build_feature_table, FEATURE_COLUMNS
from baselines import get_baseline_suite
from ensemble import CalibratedUnsupervised

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False


def time_based_split(df: pd.DataFrame, test_size: float):
    df = df.sort_values("timestamp")
    cutoff = df["timestamp"].quantile(1 - test_size)
    return df[df["timestamp"] <= cutoff], df[df["timestamp"] > cutoff]


def encode_categoricals(df, feature_cols):
    dummies = pd.get_dummies(df["txn_type"], prefix="txn_type")
    df = pd.concat([df, dummies], axis=1)
    return df, feature_cols + list(dummies.columns)


def evaluate(name, y_true, probs, flags):
    """One consistent metrics row per model, whatever kind it is."""
    row = {"model": name}
    try:
        row["pr_auc"] = average_precision_score(y_true, probs)
        row["roc_auc"] = roc_auc_score(y_true, probs)
    except ValueError:
        row["pr_auc"], row["roc_auc"] = np.nan, np.nan
    row["precision"] = precision_score(y_true, flags, zero_division=0)
    row["recall"] = recall_score(y_true, flags, zero_division=0)
    row["f1"] = f1_score(y_true, flags, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, flags, labels=[0, 1]).ravel()
    row["true_positives"] = tp
    row["false_positives"] = fp
    row["false_negatives"] = fn
    row["true_negatives"] = tn
    return row


def train_xgboost(X_train, y_train, X_test, y_test):
    n_pos = max(y_train.sum(), 1)
    n_neg = len(y_train) - n_pos
    scale_pos_weight = (n_neg / n_pos) if config.AUTO_SCALE_POS_WEIGHT else 1.0

    # eval_metric MUST be "logloss", not "aucpr": with fraud this rare (a
    # handful of positives in the whole eval set), aucpr/PR-AUC saturates
    # at its ceiling the moment the model ranks those few positives above
    # everything else - which can happen after a single tree. Early
    # stopping then fires immediately (best_iteration stays 0), leaving a
    # model that ranks correctly but outputs barely-differentiated
    # probabilities (verified: this was collapsing to two constant values,
    # ~0.48 for every legitimate transaction and ~0.52 for every fraud
    # one - technically perfect ROC/PR-AUC, useless as a probability).
    # logloss keeps improving well past that point because it penalizes
    # HOW confident each prediction is, not just the ranking - so early
    # stopping against it actually lets the model learn a real probability
    # spread before it stops. max_depth/min_child_weight/reg_lambda are
    # tightened vs. a plain default to keep a model with only a handful of
    # positive examples from memorizing them outright.
    model = xgb.XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.08,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5, gamma=0.1,
        reg_lambda=2.0, objective="binary:logistic", eval_metric="logloss",
        scale_pos_weight=scale_pos_weight, random_state=config.RANDOM_STATE,
        tree_method="hist", early_stopping_rounds=50,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    return model


def main(raw_path: str):
    if config.COLS["label"] is None:
        raise ValueError("config.COLS['label'] is None - supervised training needs labeled data.")

    print(f"Loading and engineering features from {raw_path} ...")
    df = build_feature_table(raw_path)
    df, full_feature_cols = encode_categoricals(df, FEATURE_COLUMNS)
    df[full_feature_cols] = df[full_feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    train_df, test_df = time_based_split(df, config.TEST_SIZE)
    print(f"Train rows: {len(train_df)}  Test rows: {len(test_df)}")
    print(f"Train fraud rate: {train_df['label'].mean():.5f}  Test fraud rate: {test_df['label'].mean():.5f}")

    X_train, y_train = train_df[full_feature_cols], train_df["label"]
    X_test, y_test = test_df[full_feature_cols], test_df["label"]

    results = []

    # --- Baselines ("existing systems") -----------------------------------
    print("\nTraining baseline / existing systems for comparison...")
    UNSUPERVISED_KEYS = ("isolation_forest", "local_outlier_factor")
    baselines = get_baseline_suite(train_fraud_rate=y_train.mean())
    for key, model in baselines.items():
        # RuleEngine reads whatever columns its rule predicates reference
        # (e.g. sender_hours_since_device_change), not just FEATURE_COLUMNS
        # - the same full feature table ensemble.py hands it live. Every
        # other baseline is a plain sklearn-style model restricted to the
        # numeric FEATURE_COLUMNS/one-hot matrix.
        fit_X, eval_X = (train_df, test_df) if key == "rule_based" else (X_train, X_test)

        if key in UNSUPERVISED_KEYS:
            model.fit(fit_X)  # unsupervised - no labels used
        else:
            model.fit(fit_X, y_train)

        probs = model.predict_proba_fraud(eval_X)
        flags = model.predict_flag(eval_X) if hasattr(model, "predict_flag") else (probs >= config.ALERT_THRESHOLD).astype(int)
        results.append(evaluate(model.name, y_test, probs, flags))
        print(f"  done: {model.name}")

    # --- Persist the unsupervised detectors + rule engine for live ensemble
    # scoring (ml/ensemble.py, used by score.py and monitor.py). Each
    # unsupervised model is calibrated against the TRAINING set's own
    # decision_function range - see CalibratedUnsupervised's docstring for
    # why that has to be a fixed range, not re-computed per scoring batch.
    UNSUPERVISED_PATHS = {"isolation_forest": config.ISOLATION_FOREST_PATH, "local_outlier_factor": config.LOF_PATH}
    for key, path in UNSUPERVISED_PATHS.items():
        raw_model = baselines[key].model
        raw_scores = -raw_model.decision_function(X_train)
        joblib.dump(CalibratedUnsupervised(raw_model, float(raw_scores.min()), float(raw_scores.max())), path)
        print(f"  saved calibrated {key} to {path}")
    joblib.dump(baselines["rule_based"], config.RULE_ENGINE_PATH)
    print(f"  saved rule engine to {config.RULE_ENGINE_PATH}")

    # --- XGBoost (primary model) --------------------------------------------
    if HAS_XGBOOST:
        print("\nTraining XGBoost...")
        xgb_model = train_xgboost(X_train, y_train, X_test, y_test)
        xgb_probs = xgb_model.predict_proba(X_test)[:, 1]
        xgb_flags = (xgb_probs >= config.ALERT_THRESHOLD).astype(int)
        results.append(evaluate("XGBoost", y_test, xgb_probs, xgb_flags))

        xgb_model.save_model(config.MODEL_PATH)
        with open(config.FEATURE_LIST_PATH, "w") as f:
            json.dump(full_feature_cols, f)
        print(f"XGBoost model saved to {config.MODEL_PATH}")

        top_features = sorted(zip(full_feature_cols, xgb_model.feature_importances_), key=lambda x: -x[1])[:10]
        print("\nTop features driving XGBoost's predictions:")
        for fname, imp in top_features:
            print(f"  {fname:35s} {imp:.4f}")
    else:
        print(
            "\nxgboost is not installed - skipping the primary model and reporting "
            "baselines only. Install with: pip install xgboost"
        )

    # --- Comparison report ---------------------------------------------------
    report = pd.DataFrame(results).sort_values("pr_auc", ascending=False)
    os.makedirs(os.path.dirname(config.COMPARISON_REPORT_PATH), exist_ok=True)
    report.to_csv(config.COMPARISON_REPORT_PATH, index=False)

    print("\n" + "=" * 78)
    print("MODEL COMPARISON (held-out future transactions, ranked by PR-AUC)")
    print("=" * 78)
    print(report.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"\nFull comparison report saved to {config.COMPARISON_REPORT_PATH}")
    if HAS_XGBOOST:
        best = report.iloc[0]["model"]
        print(f"\nBest performer on PR-AUC: {best}"
              + ("  <- XGBoost wins" if best == "XGBoost" else "  (XGBoost did not top this metric - inspect the report)"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python train.py /path/to/transactions.csv")
        sys.exit(1)
    main(sys.argv[1])
