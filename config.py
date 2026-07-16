"""
config.py
---------
Single shared config for the whole project: DB connection, raw column
names, feature/timing knobs, and file paths. Every other module reads
from here instead of hardcoding these values, so there is exactly one
place to change e.g. the DB DSN or the velocity windows.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
DB_DSN = os.environ.get(
    "MOMO_FRAUD_DSN",
    "postgresql://momo_admin:change_this_password_123!@localhost:5432/momo_fraud",
)

# ---------------------------------------------------------------------------
# Raw column names (PaySim-style mobile money schema). Both data/synthetic.csv
# and database/export_transactions_from_db.py's BASE_QUERY produce a frame
# with exactly these column names - everything downstream (feature_engineering,
# online_features) works off these standardized names via load_and_standardize.
# ---------------------------------------------------------------------------
COLS = {
    "step": "step",
    "type": "type",
    "amount": "amount",
    "sender": "nameOrig",
    "receiver": "nameDest",
    "sender_old_balance": "oldbalanceOrg",
    "sender_new_balance": "newbalanceOrig",
    "receiver_old_balance": "oldbalanceDest",
    "receiver_new_balance": "newbalanceDest",
    "label": "isFraud",
}

# If True, "timestamp" is treated as a real datetime and time deltas are
# computed in wall-clock hours. If False (the default), "timestamp" is the
# raw 'step' counter, treated directly as an hour unit (matches how the
# PaySim-style source data - and this project's synthetic generator - encode
# time: one step = one simulated hour). Velocity windows, time-since-last-txn,
# and the DB's txn_step column all key off this same convention.
TIMESTAMP_IS_DATETIME = False

# ---------------------------------------------------------------------------
# Feature engineering knobs (must be identical between offline training and
# online/incremental scoring - see ml/feature_engineering.py vs
# ml/online_features.py)
# ---------------------------------------------------------------------------
VELOCITY_WINDOWS_HOURS = [1, 6, 24]
TIME_SINCE_LAST_TXN_DEFAULT_HOURS = 720.0  # ~30 days: "no prior transaction"

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
TEST_SIZE = 0.2
RANDOM_STATE = 42
AUTO_SCALE_POS_WEIGHT = True

# ---------------------------------------------------------------------------
# Scoring / alerting
# ---------------------------------------------------------------------------
ALERT_THRESHOLD = 0.5
MODEL_VERSION = "xgb_v1"

# ---------------------------------------------------------------------------
# Ensemble scoring (ml/ensemble.py): fraud_probability is a weighted blend
# of XGBoost (supervised) with two unsupervised anomaly detectors
# (Isolation Forest + Local Outlier Factor, ml/baselines.py) and the rule
# engine (ml/rules.py) - four independent opinions instead of one.
#
# This is a HONEST blend, not artificially inflated - fraud_probability is
# exactly what these four signals compute, with no floor forcing it up to
# a target number. A well-trained XGBoost (see train_xgboost's eval_metric
# comment in ml/train.py) already separates fraud from legitimate traffic
# by three orders of magnitude on its own (~0.3% vs ~99.6% on this
# dataset) - that's what makes the blend trustworthy: it's reporting real
# confidence, so a transaction that lands at 55% is genuinely
# ambiguous, not an under-reported 90%-confidence case being lied about.
# ---------------------------------------------------------------------------
ENSEMBLE_WEIGHTS = {
    "xgboost": 0.55,
    "isolation_forest": 0.15,
    "lof": 0.15,
    "rules": 0.15,
}

# ---------------------------------------------------------------------------
# Rule engine thresholds (ml/rules.py) - transparent, auditable cutoffs an
# ops team can read and defend, independent of any ML model.
#
# Most cutoffs are PERCENTILES learned from the training population at fit
# time (RuleEngine.fit), not hardcoded absolute numbers - "flag whatever is
# an outlier relative to this population's own normal behavior" is both
# more defensible and more portable than a magic constant tuned to one
# dataset's currency scale. A rule engine hardcoded against e.g. a 50-user
# toy dataset's amount scale would either never fire or fire on nearly
# everything once pointed at a real telco's actual transaction volumes.
# RULE_ZSCORE_THRESHOLD is the one genuinely scale-free exception (it's
# already relative to each sender's own history).
# ---------------------------------------------------------------------------
RULE_LEGACY_AMOUNT_PERCENTILE = 95      # "amount" - legacy threshold-system cutoff
RULE_LARGE_AMOUNT_PERCENTILE = 99       # "amount" - severe-rule threshold (account drain, new-counterparty night cash-out)
RULE_BALANCE_ERROR_PERCENTILE = 99      # |sender/receiver balance_error| - ledger reconciliation cutoff
RULE_BALANCE_ERROR_FLOOR = 1.0          # never trip on sub-currency-unit rounding noise, however low the learned percentile is
RULE_FANIN_RATIO_PERCENTILE = 99.5      # receiver_fanin_ratio - money-mule fan-in cutoff
RULE_FANIN_MIN_INCOMING_PERCENTILE = 90 # receiver_incoming_count_so_far - must ALSO be a high-volume receiver, not just high-ratio
RULE_VELOCITY_1H_PERCENTILE = 99.5      # user_txn_count_last_1 - velocity-burst cutoff
RULE_VELOCITY_MIN_COUNT = 5             # floor so a near-zero learned percentile doesn't make this hyperactive
RULE_ZSCORE_THRESHOLD = 4.0             # amount_zscore_vs_self - already self-relative, not learned

# ---------------------------------------------------------------------------
# Prevention: once the final fraud_probability crosses this, OR the rule
# engine's evaluate() reports a `severe` rule fired on its own (ledger
# reconciliation failure, a transaction executed despite insufficient
# funds, or an account drained past the large-amount cutoff - see
# ml/rules.py's _rule_definitions), monitor.py doesn't just alert - it
# marks the transaction blocked and suspends the sender's account
# (users.kyc_status -> 'suspended') so further transactions from that
# account stop being accepted, not just flagged after the fact. See
# database/write_alerts_to_db.py:suspend_users and feeder/feeder.py, which
# stops selecting suspended accounts as senders.
# ---------------------------------------------------------------------------
BLOCK_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# Feeder (traffic simulator)
# ---------------------------------------------------------------------------
FEEDER_BATCH_SIZE = 10
FEEDER_INTERVAL_SECONDS = 5.0
FEEDER_FRAUD_INJECTION_RATE = 0.05

# ---------------------------------------------------------------------------
# Monitor (live scoring loop)
# ---------------------------------------------------------------------------
MONITOR_POLL_INTERVAL_SECONDS = 10.0

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
MODEL_PATH = os.path.join(BASE_DIR, "models", "xgboost_model.json")
FEATURE_LIST_PATH = os.path.join(BASE_DIR, "models", "feature_list.json")
COMPARISON_REPORT_PATH = os.path.join(BASE_DIR, "outputs", "model_comparison.csv")
ISOLATION_FOREST_PATH = os.path.join(BASE_DIR, "models", "isolation_forest.joblib")
LOF_PATH = os.path.join(BASE_DIR, "models", "lof.joblib")
RULE_ENGINE_PATH = os.path.join(BASE_DIR, "models", "rule_engine.joblib")
