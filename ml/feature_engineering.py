"""
feature_engineering.py
-----------------------
Offline/batch feature computation, used for training (train.py) and for
building each user's historical baseline (database/init_profiles.py).

Two kinds of features:
  - Transaction-level (add_transaction_level_features): row-wise, no state
    needed - balance deltas/errors, log amount, night/hour flags, etc.
  - Behavioral/historical (the other 14 features - counts, running mean/std,
    velocity, counterparty novelty, etc.): these depend on everything that
    happened to a user *before* this transaction, computed causally.

For the behavioral half, build_feature_table reuses online_features.py's
compute_batch_features against the WHOLE history as one pass (starting from
empty profiles/pairs/history) rather than a second, independently-written
implementation. This is a deliberate design choice, not a shortcut: it's
what guarantees byte-for-byte agreement between what the model is trained
on and what the live monitor computes at inference time, since both paths
literally run the same causal update code - there is no risk of a "second
implementation" silently drifting from the first.
"""

import numpy as np
import pandas as pd

import config

NIGHT_HOURS = {0, 1, 2, 3, 4, 5}
CASH_OUT_TRANSFER_TYPES = {"CASH_OUT", "TRANSFER"}

# Static, ordered list of model input columns (excludes ids/timestamp/raw
# txn_type - txn_type is one-hot encoded separately, the same way at both
# train time (train.py) and score time (monitor.py), so the two stay in sync).
FEATURE_COLUMNS = [
    # --- transaction-level (11) -----------------------------------------
    "amount",
    "amount_log",
    "sender_balance_delta",
    "sender_balance_error",
    "receiver_balance_delta",
    "receiver_balance_error",
    "sender_emptied_account",
    "sender_insufficient_funds_flag",
    "is_cash_out_or_transfer",
    "hour_of_day",
    "is_night_txn",
    # --- behavioral / historical (14) -----------------------------------
    "user_txn_count_so_far",
    "user_amount_cummean",
    "user_amount_cumstd",
    "user_amount_cummax",
    "amount_zscore_vs_self",
    "time_since_last_txn",
    "user_txn_count_last_1",
    "user_txn_count_last_6",
    "user_txn_count_last_24",
    "user_distinct_receivers_so_far",
    "is_new_counterparty",
    "receiver_incoming_count_so_far",
    "receiver_distinct_senders_so_far",
    "receiver_fanin_ratio",
]


def load_and_standardize(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Renames raw source columns (config.COLS - either data/synthetic.csv's
    PaySim-style headers, or database/export_transactions_from_db.py's
    aliased query output) to the internal standard names every other module
    works with, and sorts by timestamp with a STABLE sort. pandas' default
    sort isn't stable, so tied timestamps (multiple transactions in the same
    'step') would otherwise get ordered differently between separate calls/
    pipelines - explicit kind="mergesort" keeps that deterministic."""
    c = config.COLS
    rename_map = {
        c["step"]: "step_raw",
        c["type"]: "txn_type",
        c["amount"]: "amount",
        c["sender"]: "sender_id",
        c["receiver"]: "receiver_id",
        c["sender_old_balance"]: "sender_balance_old",
        c["sender_new_balance"]: "sender_balance_new",
        c["receiver_old_balance"]: "receiver_balance_old",
        c["receiver_new_balance"]: "receiver_balance_new",
    }
    df = raw_df.rename(columns=rename_map).copy()

    if c["label"] and c["label"] in raw_df.columns:
        df["label"] = raw_df[c["label"]].astype(int)
    else:
        df["label"] = 0

    if config.TIMESTAMP_IS_DATETIME:
        df["timestamp"] = pd.to_datetime(df["step_raw"])
    else:
        df["timestamp"] = df["step_raw"].astype(float)

    if "txn_id" not in df.columns:
        df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        df["txn_id"] = np.arange(len(df))
    else:
        df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    for col in ("amount", "sender_balance_old", "sender_balance_new",
                "receiver_balance_old", "receiver_balance_new"):
        df[col] = df[col].astype(float)

    # sender_imei/receiver_imei: only present when raw_df comes from the DB
    # export (export_transactions_from_db.py's BASE_QUERY) - data/synthetic.csv's
    # plain PaySim-style shape has no device columns at all. Filled with None
    # so the SIM-swap/device-change feature in online_features.py degrades to
    # "no signal" rather than erroring on CSV-only (offline training) input.
    for col in ("sender_imei", "receiver_imei"):
        df[col] = raw_df[col] if col in raw_df.columns else None

    return df[[
        "txn_id", "timestamp", "sender_id", "receiver_id", "amount", "txn_type",
        "sender_balance_old", "sender_balance_new",
        "receiver_balance_old", "receiver_balance_new", "label",
        "sender_imei", "receiver_imei",
    ]]


def add_transaction_level_features(df: pd.DataFrame) -> pd.DataFrame:
    """Row-wise features - no cross-row state needed."""
    df = df.copy()

    df["amount_log"] = np.log1p(df["amount"])

    df["sender_balance_delta"] = df["sender_balance_new"] - df["sender_balance_old"]
    df["sender_balance_error"] = df["sender_balance_new"] - (df["sender_balance_old"] - df["amount"])
    df["receiver_balance_delta"] = df["receiver_balance_new"] - df["receiver_balance_old"]
    df["receiver_balance_error"] = df["receiver_balance_new"] - (df["receiver_balance_old"] + df["amount"])

    df["sender_emptied_account"] = (
        (df["sender_balance_old"] > 0) & (df["sender_balance_new"] == 0)
    ).astype(int)
    df["sender_insufficient_funds_flag"] = (df["amount"] > df["sender_balance_old"]).astype(int)
    df["is_cash_out_or_transfer"] = df["txn_type"].isin(CASH_OUT_TRANSFER_TYPES).astype(int)

    if config.TIMESTAMP_IS_DATETIME:
        df["hour_of_day"] = pd.to_datetime(df["timestamp"]).dt.hour
    else:
        df["hour_of_day"] = (df["timestamp"].astype(float) % 24).astype(int)
    df["is_night_txn"] = df["hour_of_day"].isin(NIGHT_HOURS).astype(int)

    return df


def build_feature_table(raw_path: str) -> pd.DataFrame:
    """Full offline pipeline used by train.py: read a CSV (either the
    original synthetic.csv or one exported from the DB), standardize it,
    and compute every FEATURE_COLUMNS value causally over the whole history
    in one pass (see module docstring for why this reuses online_features'
    incremental logic rather than a separately-written vectorized version)."""
    raw_df = pd.read_csv(raw_path)
    std_df = load_and_standardize(raw_df)

    from online_features import compute_batch_features  # deferred: avoids a
    # circular import (online_features imports load_and_standardize and
    # add_transaction_level_features from this module).
    feat_df, _ = compute_batch_features(raw_df, profiles={}, seen_pairs=set(), recent_history={})

    feat_df["label"] = std_df["label"].values
    return feat_df
