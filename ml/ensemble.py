"""
ensemble.py
-----------
Combines the three independent fraud signals this system produces into one
final fraud_probability, instead of shipping XGBoost's raw probability
alone:

  1. XGBoost (supervised)              - ml/train.py's primary model
  2. Isolation Forest + Local Outlier
     Factor (two unsupervised models)  - ml/baselines.py, persisted at
                                          training time, calibrated against
                                          the TRAINING set's own score range
  3. The rule engine                   - ml/rules.py, transparent and
                                          auditable, independent of any ML

Used identically by ml/score.py (offline/batch) and monitor/monitor.py
(live) so the two scoring paths can never drift apart from each other -
same pattern as feature_engineering.py/online_features.py sharing
compute_batch_features.
"""

import os
import json
import numpy as np
import pandas as pd
import joblib

import config
from rules import RuleEngine  # noqa: F401 - needed to unpickle a saved RuleEngine


class CalibratedUnsupervised:
    """Wraps a fitted unsupervised sklearn model (IsolationForest, or
    LocalOutlierFactor with novelty=True) with min/max bounds captured from
    the TRAINING set's decision_function scores.

    Anomaly scores are normalized against this FIXED, stable reference
    range rather than per-batch - per-batch min-max (what baselines.py's
    comparison-report models do, evaluated once over a whole held-out set)
    would be meaningless noise for monitor.py's small live batches (as few
    as 1-10 transactions at a time: with 1 transaction, min==max and every
    score would collapse to 0). Scores more anomalous than anything seen in
    training clip to 1.0 rather than extrapolating past the learned range.
    """

    def __init__(self, model, raw_lo: float, raw_hi: float):
        self.model = model
        self.raw_lo = raw_lo
        self.raw_hi = raw_hi

    def score(self, X):
        raw = -self.model.decision_function(X)  # higher = more anomalous
        span = self.raw_hi - self.raw_lo
        if span < 1e-12:
            return np.zeros(len(raw))
        return np.clip((raw - self.raw_lo) / span, 0.0, 1.0)


def load_ensemble_components():
    """Loads everything needed to score a feature table: the XGBoost model
    + its feature list, the two calibrated unsupervised models, and the
    fitted rule engine. Raises FileNotFoundError with a clear message if
    ml/train.py hasn't been run yet."""
    import xgboost as xgb

    required = {
        "XGBoost model": config.MODEL_PATH,
        "feature list": config.FEATURE_LIST_PATH,
        "Isolation Forest": config.ISOLATION_FOREST_PATH,
        "Local Outlier Factor": config.LOF_PATH,
        "rule engine": config.RULE_ENGINE_PATH,
    }
    missing = [f"{label} ({path})" for label, path in required.items() if not os.path.exists(path)]
    if missing:
        raise FileNotFoundError(
            "Missing trained artifact(s): " + "; ".join(missing) +
            ". Run `python ml/train.py <data.csv>` first."
        )

    with open(config.FEATURE_LIST_PATH) as f:
        feature_cols = json.load(f)
    xgb_model = xgb.XGBClassifier()
    xgb_model.load_model(config.MODEL_PATH)

    return {
        "xgb_model": xgb_model,
        "feature_cols": feature_cols,
        "iso_forest": joblib.load(config.ISOLATION_FOREST_PATH),
        "lof": joblib.load(config.LOF_PATH),
        "rule_engine": joblib.load(config.RULE_ENGINE_PATH),
    }


def score_ensemble(feat_df: pd.DataFrame, components: dict) -> pd.DataFrame:
    """feat_df: feature table already containing FEATURE_COLUMNS plus the
    one-hot txn_type dummy columns (same shape train.py/score.py/monitor.py
    already build). Returns feat_df with fraud_probability/flagged/blocked/
    block_reason and each component's individual score attached (kept for
    transparency in the alert queue / audit trail).
    """
    feature_cols = components["feature_cols"]
    X = feat_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    xgb_prob = components["xgb_model"].predict_proba(X)[:, 1]
    iso_score = components["iso_forest"].score(X)
    lof_score = components["lof"].score(X)
    rule_score, rule_severe, rule_reasons = components["rule_engine"].evaluate(feat_df)
    rule_score = rule_score.to_numpy()
    rule_severe = rule_severe.to_numpy()

    w = config.ENSEMBLE_WEIGHTS
    # Honest blend - fraud_probability IS this number, full stop. No floor
    # forcing it up when signals "agree"; see config.py's comment above
    # ENSEMBLE_WEIGHTS for why a well-calibrated XGBoost makes that
    # unnecessary (and why forcing it was actively harmful: it inflated
    # the block rate on transactions the model itself wasn't confident
    # about).
    final_prob = np.clip(
        w["xgboost"] * xgb_prob
        + w["isolation_forest"] * iso_score
        + w["lof"] * lof_score
        + w["rules"] * rule_score,
        0.0, 1.0,
    )

    # Prevention still has two independent triggers, deliberately: a high
    # blended probability, OR a `severe` rule firing on its own (ledger
    # reconciliation failure / insufficient-funds execution / account
    # drain - see ml/rules.py). The second exists because those three
    # patterns are near-certain fraud even on transactions where XGBoost
    # and the anomaly detectors don't happen to agree - e.g. a brand new
    # account with no history for the unsupervised models to compare
    # against.
    blocked = (final_prob >= config.BLOCK_THRESHOLD) | rule_severe
    block_reason = np.where(
        rule_severe, ("rule_engine: " + rule_reasons.astype(str)).to_numpy(),
        np.where(blocked, "ensemble_probability_threshold", ""),
    )

    out = feat_df.copy()
    out["xgb_probability"] = xgb_prob
    out["isolation_forest_score"] = iso_score
    out["lof_score"] = lof_score
    out["rule_score"] = rule_score
    out["rule_reasons"] = rule_reasons.to_numpy()
    out["fraud_probability"] = final_prob
    out["flagged"] = (final_prob >= config.ALERT_THRESHOLD).astype(int)
    out["blocked"] = blocked
    out["block_reason"] = block_reason
    return out
