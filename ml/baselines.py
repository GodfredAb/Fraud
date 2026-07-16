"""
baselines.py
------------
"Existing systems" to compare XGBoost against - the same held-out
transactions, the same metrics, so the comparison in train.py's report
means something:

  - Rule-Based: the full rule engine (ml/rules.py) - static thresholds
    representative of what a lot of mobile money operators run today.
    This is the SAME engine ensemble.py uses live, not a separate
    simplified stand-in - see rules.py's module docstring.
  - Logistic Regression: a standard, simple supervised baseline.
  - Random Forest: a comparable tree ensemble, to isolate what XGBoost
    specifically buys you over "just use trees".
  - Isolation Forest: unsupervised anomaly detection via recursive random
    partitioning - representative of a system that has to run before any
    confirmed fraud labels exist.
  - Local Outlier Factor: a SECOND unsupervised detector, deliberately a
    different family from Isolation Forest - LOF measures local density
    deviation (how isolated a point is relative to its k nearest
    neighbors) rather than Isolation Forest's global partitioning. The two
    catch different anomaly shapes, which is exactly why ensemble.py
    blends both rather than relying on one unsupervised opinion.

Every model exposes the same tiny interface so train.py can treat them
uniformly: .name, .fit(X, y=None), .predict_proba_fraud(X) -> array of
scores in [0, 1] (higher = more fraud-like), and optionally
.predict_flag(X) -> 0/1 array (falls back to thresholding predict_proba_fraud
at config.ALERT_THRESHOLD if not provided).
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

import config
from rules import RuleEngine  # noqa: F401 - re-exported for get_baseline_suite


class LogisticRegressionModel:
    name = "Logistic Regression"

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=config.RANDOM_STATE
        )

    def fit(self, X, y=None):
        Xs = self.scaler.fit_transform(X)
        self.model.fit(Xs, y)
        return self

    def predict_proba_fraud(self, X):
        Xs = self.scaler.transform(X)
        return self.model.predict_proba(Xs)[:, 1]


class RandomForestModel:
    name = "Random Forest"

    def __init__(self):
        self.model = RandomForestClassifier(
            n_estimators=200, max_depth=None, class_weight="balanced",
            random_state=config.RANDOM_STATE, n_jobs=-1,
        )

    def fit(self, X, y=None):
        self.model.fit(X, y)
        return self

    def predict_proba_fraud(self, X):
        return self.model.predict_proba(X)[:, 1]


class IsolationForestModel:
    """Unsupervised - never sees labels, even at fit time. Anomaly score is
    inverted and min-max scaled to [0, 1] so it's comparable to the
    supervised models' probabilities on the same PR-AUC/ROC-AUC metrics."""

    name = "Isolation Forest (unsupervised)"

    def __init__(self, contamination):
        # contamination = expected fraud rate; falls back to sklearn's
        # 'auto' if the training data has (almost) no positives to estimate from.
        self.contamination = contamination if 0 < contamination < 0.5 else "auto"
        self.model = IsolationForest(
            n_estimators=200, contamination=self.contamination,
            random_state=config.RANDOM_STATE, n_jobs=-1,
        )

    def fit(self, X, y=None):
        self.model.fit(X)
        return self

    def predict_proba_fraud(self, X):
        raw = -self.model.decision_function(X)  # higher = more anomalous
        lo, hi = raw.min(), raw.max()
        if hi - lo < 1e-12:
            return np.zeros(len(raw))
        return (raw - lo) / (hi - lo)

    def predict_flag(self, X):
        return (self.model.predict(X) == -1).astype(int)


class LocalOutlierFactorModel:
    """Second unsupervised model. novelty=True is required so
    .decision_function/.predict can be called on new data after fit - the
    default (novelty=False) only supports fit_predict on the training set
    itself, which is useless for scoring a held-out test set or live
    traffic."""

    name = "Local Outlier Factor (unsupervised)"

    def __init__(self, contamination, n_neighbors=20):
        self.contamination = contamination if 0 < contamination < 0.5 else "auto"
        self.model = LocalOutlierFactor(
            n_neighbors=n_neighbors, contamination=self.contamination,
            novelty=True, n_jobs=-1,
        )

    def fit(self, X, y=None):
        self.model.fit(X)
        return self

    def predict_proba_fraud(self, X):
        raw = -self.model.decision_function(X)  # higher = more anomalous
        lo, hi = raw.min(), raw.max()
        if hi - lo < 1e-12:
            return np.zeros(len(raw))
        return (raw - lo) / (hi - lo)

    def predict_flag(self, X):
        return (self.model.predict(X) == -1).astype(int)


def get_baseline_suite(train_fraud_rate: float):
    return {
        "rule_based": RuleEngine(),
        "logistic_regression": LogisticRegressionModel(),
        "random_forest": RandomForestModel(),
        "isolation_forest": IsolationForestModel(contamination=train_fraud_rate),
        "local_outlier_factor": LocalOutlierFactorModel(contamination=train_fraud_rate),
    }
