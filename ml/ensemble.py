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


# Human-readable phrasing for each named rule in rules.py's
# _rule_definitions, given the feature row that fired it - so the alert
# queue/detail view explains WHAT was unusual, in the same terms the rule
# itself evaluated, not just which rule's name matched.
_RULE_PHRASES = {
    "legacy_amount_cutoff": lambda r: (
        f"amount GHS {r.amount:,.2f} is above the large-transaction cutoff learned from this population"
    ),
    "balance_mismatch": lambda r: (
        f"ledger mismatch of GHS {max(abs(r.sender_balance_error), abs(r.receiver_balance_error)):,.2f} "
        "between the recorded balances and the transaction amount"
    ),
    "insufficient_funds_executed": lambda r: (
        "transaction went through even though the amount exceeded the sender's balance beforehand"
    ),
    "account_drained": lambda r: (
        f"sender's account was emptied to GHS 0 by this GHS {r.amount:,.2f} transaction"
    ),
    "extreme_amount_vs_self": lambda r: (
        f"amount is {r.amount_zscore_vs_self:.1f} standard deviations above this sender's own average "
        f"(GHS {r.amount:,.2f} vs their usual GHS {r.user_amount_cummean:,.2f})"
    ),
    "velocity_burst": lambda r: (
        f"{int(r.user_txn_count_last_1)} transactions from this sender in the last hour - well above their normal pace"
    ),
    "new_counterparty_large_night_cashout": lambda r: (
        "large cash-out to a brand-new counterparty, sent during night hours"
    ),
    "mule_fanin_pattern": lambda r: (
        f"receiver shows a money-mule fan-in pattern ({int(r.receiver_distinct_senders_so_far)} distinct senders "
        f"across {int(r.receiver_incoming_count_so_far)} incoming transactions)"
    ),
    "device_change_then_large_txn": lambda r: (
        "sender's device changed "
        + ("on this very transaction" if r.sender_hours_since_device_change < 1
           else f"{r.sender_hours_since_device_change:.1f}h ago")
        + f", immediately followed by a large GHS {r.amount:,.2f} {'cash-out' if r.is_cash_out_or_transfer else 'transfer'} "
        "- matches a SIM-swap / device-takeover pattern"
    ),
}


def _behavior_clauses(row, skip_amount_clause=False):
    """Clauses describing THIS transaction against the sender/receiver's
    own learned history (see profile_store.py/online_features.py) -
    included even when no named rule fired, so a flag is never explained
    purely as an opaque model percentage. skip_amount_clause avoids
    restating the sender's-average comparison when a rule phrase (e.g.
    extreme_amount_vs_self/legacy_amount_cutoff) already covered it."""
    clauses = []
    if skip_amount_clause:
        pass
    elif row.user_txn_count_so_far > 0:
        clauses.append(
            f"amount GHS {row.amount:,.2f} vs sender's usual GHS {row.user_amount_cummean:,.2f} "
            f"({row.amount_zscore_vs_self:+.1f}sigma over {int(row.user_txn_count_so_far)} prior transactions)"
        )
    else:
        clauses.append(f"sender's first observed transaction, amount GHS {row.amount:,.2f}")
    if row.user_txn_count_last_1 >= 3:
        clauses.append(f"{int(row.user_txn_count_last_1)} transactions from this sender in the last hour")
    if row.is_new_counterparty:
        clauses.append("first-ever transaction to this receiver")
    if row.sender_device_changed_this_txn:
        clauses.append("sent from a device never seen on this account before")
    if row.receiver_incoming_count_so_far >= 5 and row.receiver_fanin_ratio > 0.5:
        clauses.append(
            f"receiver has taken money from {int(row.receiver_distinct_senders_so_far)} different senders "
            f"across {int(row.receiver_incoming_count_so_far)} incoming transactions"
        )
    return clauses


def _build_explanation(row, fired_names, prob):
    """Builds the human-readable block_reason for one row: named-rule
    phrases first (most specific), then behavioral context against the
    sender/receiver's own history, deduped and capped so it stays
    readable in the UI."""
    clauses = [_RULE_PHRASES[name](row) for name in fired_names if name in _RULE_PHRASES]
    amount_already_covered = "extreme_amount_vs_self" in fired_names or "legacy_amount_cutoff" in fired_names
    for c in _behavior_clauses(row, skip_amount_clause=amount_already_covered):
        if c not in clauses:
            clauses.append(c)
    if not fired_names:
        clauses.insert(0, f"ensemble model estimated a {prob:.0%} fraud probability (no single rule fired)")
    return "; ".join(clauses[:4])


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
    flagged = final_prob >= config.ALERT_THRESHOLD

    # block_reason is populated for every FLAGGED-or-blocked row (not just
    # blocked ones) - see _build_explanation - so the dashboard's
    # transaction detail view always has something to show for "why".
    fired_lists = [[n.strip() for n in r.split(",") if n.strip()] for r in rule_reasons]
    block_reason = [
        _build_explanation(row, fired, prob) if (flagged[i] or blocked[i]) else ""
        for i, (row, fired, prob) in enumerate(zip(feat_df.itertuples(index=False), fired_lists, final_prob))
    ]

    out = feat_df.copy()
    out["xgb_probability"] = xgb_prob
    out["isolation_forest_score"] = iso_score
    out["lof_score"] = lof_score
    out["rule_score"] = rule_score
    out["rule_reasons"] = rule_reasons.to_numpy()
    out["fraud_probability"] = final_prob
    out["flagged"] = flagged.astype(int)
    out["blocked"] = blocked
    out["block_reason"] = block_reason
    return out
